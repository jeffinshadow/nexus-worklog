"""Histórico de ações do próprio usuário e "desfazer".

Desfazer só vale para a alteração MAIS RECENTE de cada item (tarefa,
recorrente, configuração): desfazer uma alteração antiga por cima de mudanças
posteriores apagaria trabalho sem aviso. O próprio desfazer fica registrado
(ação "undo") e não pode ser desfeito de novo.
"""
from datetime import date, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .. import audit, db
from ..paging import clamp, put_total, OFFSET_MAX
from . import photos
from ..labels import dur
from ..services import RETRO_DAYS, app_today, app_tz, board_day_range, set_extra_projects
from .recurring import active_order, refresh_after_from, renumber
from .worklog import check_day_total
from ..deps import active_user, active_user_csrf

router = APIRouter(prefix="/api/history", tags=["history"])

UNDOABLE = {
    "worklog.create", "worklog.assign", "worklog.update", "worklog.finish", "worklog.delete",
    "worklog.assign_update",
    "recurring.create", "recurring.update", "recurring.deactivate", "recurring.toggle", "recurring.replace",
    "recurring.pause", "recurring.resume", "recurring.order",
    "note.create", "note.update", "note.delete", "time.update", "checklist.create", "checklist.update", "checklist.delete",
    "time.create", "time.delete", "project.create", "project.update", "project.delete",
    "renewal.create", "renewal.update", "renewal.renew", "renewal.delete",
    "objective.create", "objective.update", "objective.delete", "objective.order",
    "photo.create", "photo.delete",
}

ACTION_LABELS = {
    "worklog.create": "criou a tarefa",
    "photo.create": "adicionou uma foto",
    "photo.delete": "excluiu uma foto",
    "worklog.update": "editou a tarefa",
    "worklog.finish": "concluiu a tarefa",
    "worklog.delete": "excluiu a tarefa",
    "worklog.assign": "recebeu a tarefa",
    "assign.send": "atribuiu a tarefa",
    "assign.update": "alterou a tarefa atribuída",
    "assign.cancel": "cancelou a tarefa atribuída",
    "assign.returned": "teve devolvida a tarefa que atribuiu",
    "assign.close": "encerrou a tarefa devolvida",
    "worklog.assign_update": "teve alterada por quem atribuiu a tarefa",
    "worklog.assign_cancel": "teve cancelada por quem atribuiu a tarefa",
    "user.block": "bloqueou o acesso",
    "user.invite_cancel": "cancelou o convite",
    "assignments.consent": "alterou o aceite de tarefas atribuídas",
    "viewers.consent": "alterou quem vê a equipe pode ver seu registro",
    "user.roles": "alterou as permissões",
    "user.delete": "excluiu a conta",
    "renewal.create": "cadastrou o vencimento",
    "renewal.update": "editou o vencimento",
    "renewal.renew": "renovou",
    "renewal.delete": "excluiu o vencimento",
    "app.settings": "alterou as configurações gerais",
    "app.team_visibility": "alterou a visibilidade da equipe",
    "app.assign_receive": "alterou quem recebe tarefas atribuídas",
    "app.identity_managed": "alterou quem define nome e e-mail",
    "app.tour_required": "alterou o tour obrigatório",
    "app.invite_request_off": "alterou o pedido de convite na tela de login",
    "app.invite_request_on": "alterou o pedido de convite na tela de login",
    "app.privacy_url": "alterou o endereço da política de privacidade",
    "app.ticket_url": "alterou o endereço do sistema de chamados da instância",
    "worklog.transfer": "recebeu a tarefa transferida",
    "user.transfer_tasks": "transferiu as tarefas abertas",
    "email.change_request": "pediu para trocar o e-mail da conta",
    "email.change": "trocou o e-mail da conta",
    "user.profile": "alterou nome e e-mail de uma conta",
    "team.create": "criou a equipe",
    "team.update": "renomeou a equipe",
    "team.archive": "arquivou a equipe",
    "team.unarchive": "desarquivou a equipe",
    "team.delete": "excluiu a equipe",
    "team.members": "mudou os membros da equipe",
    "user.teams": "mudou as equipes de uma conta",
    "master.view": "viu, como admin master, o registro de",
    "master.transfer_code": "pediu o código para transferir o papel de admin master",
    "master.transfer_fail": "errou o código da transferência do papel de admin master",
    "master.transfer": "transferiu o papel de admin master",
    "master.received": "recebeu o papel de admin master",
    "recurring.create": "criou a rotina",
    "recurring.update": "editou a rotina",
    "recurring.deactivate": "excluiu a rotina",
    "recurring.toggle": "marcou a rotina",
    "recurring.replace": "trocou a agenda da rotina",
    "recurring.pause": "pausou a rotina",
    "recurring.resume": "retomou a rotina",
    "recurring.order": "mudou a ordem das rotinas",
    "settings.update": "alterou os dias úteis",
    "notifications.update": "alterou os avisos por e-mail",
    "profile.update": "alterou o nome de exibição",
    "profile.avatar": "trocou a foto de perfil",
    "profile.avatar_reset": "removeu a foto de perfil",
    "assistant.update": "alterou o assistente",
    "tickets.update": "alterou o endereço dos chamados",
    "default_project.update": "alterou o projeto padrão",
    "objective.create": "criou o objetivo",
    "objective.update": "editou o objetivo",
    "objective.delete": "excluiu o objetivo",
    "objective.order": "reordenou os objetivos de",
    "timer.start": "iniciou o cronômetro em",
    "timer.discard": "descartou o cronômetro de",
    "template.create": "criou o modelo",
    "template.update": "editou o modelo",
    "template.delete": "excluiu o modelo",
    "calendar.create": "criou o link do calendário",
    "calendar.revoke": "revogou o link do calendário",
    "note.create": "anotou na tarefa",
    "note.update": "editou uma anotação da tarefa",
    "note.delete": "excluiu uma anotação da tarefa",
    "checklist.create": "adicionou o item",
    "checklist.update": "editou o item",
    "checklist.delete": "removeu o item",
    "time.create": "apontou tempo em",
    "time.update": "corrigiu um apontamento de",
    "time.delete": "excluiu um apontamento de",
    "project.create": "criou o projeto",
    "project.update": "editou o projeto",
    "project.delete": "excluiu o projeto",
    "token.create": "criou a chave de API",
    "token.revoke": "revogou a chave de API",
    "token.renew": "renovou a validade da chave de API",
    "webhook.create": "criou o webhook para",
    "webhook.enable": "religou o webhook para",
    "webhook.update": "editou o webhook para",
    "webhook.delete": "excluiu o webhook para",
    "user.invite": "criou a conta (convite)",
    "user.reset_password": "redefiniu a senha",
    "user.invite_resend": "reenviou o convite",
    "user.invite_accept": "aceitou o convite e criou a senha",
    "password.forgot": "pediu o link para redefinir a senha",
    "sessions.logout_others": "saiu dos outros aparelhos",
    "password.reset_link": "redefiniu a senha pelo link do e-mail",
    "branding.update": "alterou os textos da identidade visual",
    "branding.logo": "enviou um novo logo",
    "branding.logo_reset": "restaurou o logo padrão",
    "undo": "desfez uma ação",
}


def _label(row) -> str:
    snap = row["after"] or row["before"] or {}
    name = snap.get("title") or snap.get("label") or snap.get("name") or ""
    if row["action"] == "undo":
        # O que foi desfeito: a ação original (after.action) e o nome do item.
        base = ACTION_LABELS.get((row["after"] or {}).get("action") or "")
        if not base or base == ACTION_LABELS["undo"]:
            return "desfez uma ação"
        b = row["before"] or {}  # o estado que a ação original tinha deixado (o "after" dela)
        item = b.get("title") or b.get("label") or b.get("name") or ""
        return f"desfez: {base} “{item}”" if item else f"desfez: {base}"
    if row["action"].startswith("checklist."):
        item = snap.get("label") or ""
        if row["action"] == "checklist.update" and row["after"] and row["before"]:
            if row["after"].get("done") != row["before"].get("done"):
                verbo = "concluiu o item" if row["after"].get("done") else "reabriu o item"
                return f"{verbo} “{item}” em “{snap.get('title', '')}”"
        return f"{ACTION_LABELS[row['action']]} “{item}” em “{snap.get('title', '')}”"
    if row["action"] in ("time.create", "time.delete"):
        return f"{ACTION_LABELS[row['action']]} “{snap.get('title', '')}” ({dur(snap.get('minutes'))})"
    if row["action"] == "time.update" and row["before"] and row["after"]:
        de, para = row["before"].get("minutes"), row["after"].get("minutes")
        quanto = f"{dur(de)} → {dur(para)}" if de != para else dur(para)
        return f"{ACTION_LABELS['time.update']} “{snap.get('title', '')}” ({quanto})"
    if row["action"] == "worklog.delete" and snap.get("return_reason"):
        return f"devolveu a tarefa “{name}” a {snap.get('returned_to') or 'quem atribuiu'}: «{snap['return_reason']}»"
    if row["action"] == "assign.returned":
        return f"{snap.get('to', '')} devolveu a tarefa “{name}”: «{snap.get('reason', '')}»"
    if row["action"] == "assign.close":
        return f"encerrou a tarefa “{name}”, devolvida por {snap.get('to', '')}"
    if row["action"] == "worklog.delete" and snap.get("canceled_by"):
        return f"{snap['canceled_by']} cancelou a tarefa “{name}”, que tinha atribuído a você"
    if row["action"] == "worklog.assign" and snap.get("by"):
        return f"recebeu a tarefa “{name}”, atribuída por {snap['by']}"
    if row["action"] == "user.delete" and row["before"]:
        return f"excluiu a conta {row['before'].get('email', '')} e todos os dados dela"
    if row["action"] == "assign.send":
        return f"atribuiu a tarefa “{name}” a {snap.get('to', '')}"
    if row["action"] in ("assign.update", "assign.cancel"):
        verbo = "alterou" if row["action"] == "assign.update" else "cancelou"
        return f"{verbo} a tarefa “{name}”, atribuída a {snap.get('to', '')}"
    if row["action"] in ("worklog.assign_update", "worklog.assign_cancel"):
        verbo = "alterou" if row["action"] == "worklog.assign_update" else "cancelou"
        return f"{snap.get('by') or 'quem atribuiu'} {verbo} a tarefa “{name}”, que tinha atribuído a você"
    if row["action"] in ("user.block", "user.invite_cancel"):
        email = (row["after"] or row["before"] or {}).get("email", "")
        return f"{ACTION_LABELS[row['action']]} de {email}" if row["action"] == "user.block" else f"cancelou o convite de {email}"
    if row["action"] == "assignments.consent" and row["after"]:
        return "passou a aceitar tarefas atribuídas" if row["after"].get("accept") else "deixou de aceitar tarefas atribuídas"
    if row["action"] == "viewers.consent" and row["after"]:
        return ("passou a permitir que quem vê a equipe veja seu registro" if row["after"].get("accept")
                else "deixou de permitir que quem vê a equipe veja seu registro")
    if row["action"] == "app.team_visibility" and row["after"]:
        return ("ligou “Visível para quem gerencia”: quem tem o papel Vê a equipe vê o registro de todos"
                if row["after"].get("team_visibility") == "managers"
                else "voltou para “Cada pessoa escolhe” quem vê o registro")
    if row["action"] == "app.assign_receive" and row["after"]:
        return ("ligou “Todos recebem de quem atribui”: todo Usuário recebe tarefas de quem tem o papel Manda tarefas"
                if row["after"].get("assign_receive") == "all"
                else "voltou para “Cada pessoa escolhe” quem recebe tarefas atribuídas")
    if row["action"] == "app.identity_managed" and row["after"]:
        return ("ligou “Nome e e-mail definidos pela administração”" if row["after"].get("identity_managed")
                else "desligou “Nome e e-mail definidos pela administração”")
    if row["action"] == "app.tour_required" and row["after"]:
        return ("ligou o tour obrigatório no primeiro acesso" if row["after"].get("tour_required")
                else "desligou o tour obrigatório no primeiro acesso")
    if row["action"] == "app.invite_request_off" and row["after"]:
        return ("tirou o “Solicitar convite” da tela de login" if row["after"].get("invite_request_off")
                else "voltou a oferecer o “Solicitar convite” na tela de login")
    if row["action"] == "app.invite_request_on" and row["after"]:
        return ("passou a oferecer o “Solicitar convite” na tela de login" if row["after"].get("invite_request_on")
                else "tirou o “Solicitar convite” da tela de login")
    if row["action"] == "worklog.transfer" and row["after"]:
        return f"recebeu a tarefa “{name}”, que era de {snap.get('from', '')} (transferida por {snap.get('by', '')})"
    if row["action"] == "user.transfer_tasks" and row["after"]:
        n = row["after"].get("count", 0)
        s_ = "s" if n != 1 else ""
        return f"transferiu {n} tarefa{s_} aberta{s_} de {row['after'].get('from', '')} para {row['after'].get('to', '')}"
    if row["action"] in ("email.change_request", "email.change") and row["after"]:
        return f"{ACTION_LABELS[row['action']]} para {row['after'].get('email', '')}"
    if row["action"] == "user.profile":
        b, a = row["before"] or {}, row["after"] or {}
        quem = a.get("target") or b.get("email") or ""
        partes = []
        if "email" in a and a["email"] != b.get("email"):
            partes.append(f"e-mail para {a['email']}")
        if "display_name" in a and a["display_name"] != b.get("display_name"):
            partes.append(f"nome para “{a['display_name']}”" if a["display_name"] else "nome (volta ao do e-mail)")
        return f"alterou {' e '.join(partes) or 'o perfil'} da conta {quem}"
    if row["action"].startswith("team.") or row["action"] == "user.teams":
        a, b = row["after"] or {}, row["before"] or {}
        if row["action"] == "team.update":
            return f"renomeou a equipe “{b.get('name', '')}” para “{a.get('name', '')}”"
        if row["action"] == "team.members":
            return (f"mudou os membros da equipe “{a.get('name', '')}” "
                    f"(+{a.get('added', 0)}, -{a.get('removed', 0)})")
        if row["action"] == "user.teams":
            return f"mudou as equipes de {a.get('email', '')} ({', '.join(a.get('teams') or []) or 'sem equipe'})"
        return f"{ACTION_LABELS[row['action']]} “{a.get('name') or b.get('name', '')}”"
    if row["action"].startswith("master.") and row["after"]:
        a = row["after"]
        if row["action"] == "master.view":
            o_que = {"quadro": "o quadro", "mês": "o mês", "pdf": "o relatório em PDF", "projetos": "os projetos",
                     "horas": "as horas da equipe (CSV)", "painel": "o painel da Equipe"}.get(a.get("what"), a.get("what"))
            if a.get("email"):
                return f"viu, como admin master, {o_que} de {a['email']}"
            return f"viu, como admin master, {o_que} ({a.get('people', 0)} pessoas)"
        if row["action"] in ("master.transfer", "master.transfer_code"):
            return f"{ACTION_LABELS[row['action']]} para {a.get('to_email') or a.get('to', '')}"
        if row["action"] == "master.received":
            return f"recebeu de {a.get('from_email') or a.get('from', '')} o papel de admin master"
    if row["action"] == "user.roles" and row["after"]:
        from ..roles import LABELS
        papeis = ", ".join(LABELS.get(r, r) for r in row["after"].get("roles", [])) or "nenhum"
        return f"alterou as permissões ({papeis})"
    text = ACTION_LABELS.get(row["action"], row["action"])
    if (row["action"] == "worklog.update" and (row["before"] or {}).get("status") == "done"
            and (row["after"] or {}).get("status") not in (None, "done")):
        text = "reabriu a tarefa"
    if row["action"] == "recurring.pause" and (row["after"] or {}).get("pause"):
        fim = str(row["after"]["pause"]["end_d"])  # AAAA-MM-DD
        text = f"pausou até {fim[8:10]}/{fim[5:7]} a rotina"
    if row["action"] == "recurring.toggle" and row["after"]:
        text = ("marcou" if row["after"]["done"] else "desmarcou") + " a rotina"
        if row["after"]["done"] and row["before"] and row["before"].get("done") and row["after"].get("note") != row["before"].get("note"):
            text = "anotou a evidência da rotina" if row["after"].get("note") else "excluiu a evidência da rotina"
        dia = str(row["after"]["day"])  # AAAA-MM-DD; fora das aspas, que são do nome
        return f"{text} “{name}” em {dia[8:10]}/{dia[5:7]}" if name else f"{text} em {dia[8:10]}/{dia[5:7]}"
    return f"{text} “{name}”" if name else text


def _latest_ids(user_id: int) -> set[int]:
    """Última ação (não desfeita, não-undo) de cada item."""
    rows = db.query_all(
        """
        SELECT DISTINCT ON (entity, entity_id) id
          FROM audit_log
         WHERE user_id = %s AND action <> 'undo' AND undone_at IS NULL
         ORDER BY entity, entity_id, id DESC
        """,
        (user_id,),
    )
    return {r["id"] for r in rows}


def _with_names(user_id: int, rows: list) -> list:
    # Para toggles, o snapshot só tem dia/feito: busca o rótulo da recorrente.
    ids = {r["entity_id"] for r in rows if r["action"] == "recurring.toggle"}
    labels = {}
    if ids:
        for r in db.query_all(
            "SELECT id, label FROM recurring_tasks WHERE user_id = %s AND id = ANY(%s)",
            (user_id, list(ids)),
        ):
            labels[r["id"]] = r["label"]
    for r in rows:
        if r["action"] == "recurring.toggle" and r["after"] is not None:
            r["after"] = {**r["after"], "label": labels.get(r["entity_id"], "")}
    return rows


# O feed esconde os eventos dos últimos segundos: duas gravações simultâneas
# podem terminar fora da ordem dos ids, e o cursor (after) pularia a mais lenta.
FEED_LAG_SECONDS = 2


def feed_item(r: dict) -> dict:
    """Um evento do feed de mudanças (também o corpo dos webhooks)."""
    snap = r["after"] or r["before"] or {}
    item = {"id": r["id"], "at": r["created_at"], "action": r["action"], "entity": r["entity"],
            "entity_id": r["entity_id"], "actor": r["actor"], "token_name": r["token_name"]}
    if isinstance(snap, dict) and snap.get("external_ref"):
        item["external_ref"] = snap["external_ref"]
    return item


def feed(uid: int, after: int, limit: int) -> list:
    """Eventos da pessoa depois do id `after`, do mais antigo ao mais novo.
    Exclusão = lápide (action *.delete). Cursor anterior ao que o histórico
    ainda guarda (180 dias) → 410: o integrador precisa recomeçar do zero."""
    if after > 0:
        oldest = db.query_one("SELECT min(id) AS m FROM audit_log")["m"]
        if oldest is not None and after < oldest - 1:
            raise HTTPException(status_code=410, detail="cursor anterior ao histórico guardado (180 dias); recomece com after=0")
    rows = db.query_all(
        """SELECT id, created_at, actor, token_name, action, entity, entity_id, before, after
             FROM audit_log
            WHERE user_id = %s AND id > %s AND created_at <= now() - make_interval(secs => %s)
            ORDER BY id LIMIT %s""",
        (uid, after, FEED_LAG_SECONDS, limit),
    )
    return [feed_item(r) for r in rows]


@router.get("")
def list_history(
    limit: int = Query(default=50, ge=1, le=200),
    entity: Optional[str] = None,
    entity_id: Optional[int] = None,
    after: Annotated[Optional[int], Query(ge=0)] = None,  # Annotated: None também quando o MCP chama direto
    offset: Annotated[int, Query(ge=0, le=OFFSET_MAX, description="Pula as N ações mais recentes (páginas); o total vem em X-Total-Count")] = 0,
    token_id: Annotated[Optional[int], Query(ge=1, description="Só o que esta chave de API fez (\"o que esta chave fez\")")] = None,
    response: Response = None,
    user=Depends(active_user),
):
    limit = clamp(limit, 1, 200, 50)  # também quando chamada pelo MCP (sem validação de Query)
    offset = clamp(offset, 0, OFFSET_MAX, 0)
    if after is not None:  # feed de mudanças, para sincronizar (docs/API.md); sem offset nem total
        return feed(user["user_id"], after, limit)
    # Os avisos de agenda do sistema (followup.due...) são só do feed e dos webhooks.
    cond, params = ["user_id = %s", "actor <> 'system'"], [user["user_id"]]
    if token_id is not None:
        cond.append("token_id = %s")
        params.append(token_id)
    if entity:
        cond.append("entity = %s")
        params.append(entity)
    if entity_id is not None:
        cond.append("entity_id = %s")
        params.append(entity_id)
    where = " AND ".join(cond)
    put_total(response, db.query_one(f"SELECT count(*)::int AS n FROM audit_log WHERE {where}", tuple(params))["n"])
    rows = db.query_all(
        f"""
        SELECT id, created_at, actor, token_name, action, entity, entity_id,
               before, after, undone_at
          FROM audit_log
         WHERE {where}
         ORDER BY id DESC
         LIMIT %s OFFSET %s
        """,
        (*params, limit, offset),
    )
    rows = _with_names(user["user_id"], rows)
    latest = _latest_ids(user["user_id"])
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "created_at": r["created_at"],
            "actor": r["actor"],
            "token_name": r["token_name"],
            "action": r["action"],
            "entity": r["entity"],
            "entity_id": r["entity_id"],
            "summary": _label(r),
            "undone": r["undone_at"] is not None,
            "can_undo": r["action"] in UNDOABLE and r["undone_at"] is None and r["id"] in latest,
        })
    return out


def _icone(name):
    """Ícone do projeto no banco: a pasta (padrão) e registros antigos sem ícone ficam NULL."""
    return None if name in (None, "pasta") else name


def _projeto_existente(uid: int, project_id):
    """Ao desfazer, o projeto antigo pode ter sido excluído: volta sem projeto."""
    if project_id is None:
        return None
    ok = db.query_one("SELECT 1 FROM projects WHERE id = %s AND user_id = %s", (project_id, uid))
    return project_id if ok else None


def _ref_livre(uid: int, ref):
    """A chave externa volta com a tarefa, se ninguém a usou nesse meio-tempo."""
    if not ref:
        return None
    return None if db.query_one("SELECT 1 FROM worklog_tasks WHERE user_id = %s AND external_ref = %s", (uid, ref)) else ref


def _ref_livre_em(tabela: str, uid: int, ref):
    """Idem para projetos e objetivos."""
    if not ref:
        return None
    return None if db.query_one(f"SELECT 1 FROM {tabela} WHERE user_id = %s AND external_ref = %s", (uid, ref)) else ref


def _usuario_existente(user_id):
    if user_id is None:
        return None
    return user_id if db.query_one("SELECT 1 FROM users WHERE id = %s", (user_id,)) else None


def _objetivo_valido(uid: int, objective_id, project_id):
    """Ao desfazer, o objetivo pode ter sido excluído (ou a tarefa estar noutro projeto)."""
    if objective_id is None:
        return None
    ok = db.query_one("SELECT 1 FROM project_objectives WHERE id = %s AND user_id = %s AND project_id IS NOT DISTINCT FROM %s",
                      (objective_id, uid, project_id))
    return objective_id if ok else None


def _restore_worklog(uid: int, snap: dict) -> None:
    db.execute(
        """UPDATE worklog_tasks
              SET title = %s, description = %s, status = %s, due_date = %s, completed_at = %s,
                  project_id = %s, priority = %s, ticket = %s, after_hours = %s,
                  blocked_reason = %s, blocked_at = %s, follow_up_on = %s, resolution = %s
            WHERE id = %s AND user_id = %s""",
        (snap["title"], snap["description"], snap["status"], snap["due_date"],
         snap["completed_at"], _projeto_existente(uid, snap.get("project_id")),
         snap.get("priority") or 2, snap.get("ticket"), bool(snap.get("after_hours")),
         snap.get("blocked_reason"), snap.get("blocked_at"), snap.get("follow_up_on"), snap.get("resolution"), snap["id"], uid),
    )
    if "remind_at" in snap:  # registros de antes do lembrete não têm o campo (não apagam o atual)
        db.execute("""UPDATE worklog_tasks SET remind_at = %s, remind_snoozed_until = NULL, remind_seen_at = NULL
                       WHERE id = %s AND user_id = %s AND remind_at IS DISTINCT FROM %s::timestamptz""",
                   (snap["remind_at"], snap["id"], uid, snap["remind_at"]))
    if "extra_project_ids" in snap:  # registros de antes dos projetos extras não têm a lista
        set_extra_projects(uid, snap["id"], snap["extra_project_ids"])
    if "objective_id" in snap:  # idem para os objetivos
        proj = db.query_one("SELECT project_id FROM worklog_tasks WHERE id = %s", (snap["id"],))["project_id"]
        db.execute("UPDATE worklog_tasks SET objective_id = %s, exec_position = %s WHERE id = %s AND user_id = %s",
                   (_objetivo_valido(uid, snap["objective_id"], proj), snap.get("exec_position"), snap["id"], uid))


def _restore_recurring(uid: int, snap: dict) -> None:
    db.execute(
        """UPDATE recurring_tasks
              SET label = %s, position = %s, active = %s, created_at = %s, deactivated_at = %s,
                  freq = %s, weekdays = %s, month_day = %s, interval_days = %s, require_note = %s, remind_at = %s
            WHERE id = %s AND user_id = %s""",
        (snap["label"], snap["position"], snap["active"], snap["created_at"],
         snap["deactivated_at"], snap.get("freq") or "daily", snap.get("weekdays"),
         snap.get("month_day"), snap.get("interval_days"), bool(snap.get("require_note")), snap.get("remind_at"), snap["id"], uid),
    )
    if "steps" in snap:  # registros de antes dos passos não têm o campo
        db.execute("UPDATE recurring_tasks SET steps = %s WHERE id = %s AND user_id = %s", (snap["steps"], snap["id"], uid))


def _need_task(uid: int, task_id: int) -> None:
    if not audit.worklog_snapshot(task_id, uid):
        raise HTTPException(status_code=409, detail="a tarefa não existe mais")


def _gone() -> HTTPException:
    return HTTPException(status_code=409, detail="o item não existe mais")


# Reinserção dos filhos de uma tarefa (desfazer exclusão), com o id original.
def _put_objective(uid: int, o: dict) -> None:
    """Recria o objetivo (mesmo id) e devolve a ele as tarefas que ainda estão no
    projeto sem objetivo, na ordem que tinham."""
    db.execute(
        """INSERT INTO project_objectives (id, user_id, project_id, title, description, due_date, position, created_at,
                                          external_ref)
           OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
        (o["id"], uid, o["project_id"], o["title"], o.get("description"), o.get("due_date"), o.get("position") or 0,
         o.get("created_at"), _ref_livre_em("project_objectives", uid, o.get("external_ref"))))
    for t in o.get("tasks") or []:
        db.execute("""UPDATE worklog_tasks SET objective_id = %s, exec_position = %s
                       WHERE id = %s AND user_id = %s AND project_id = %s AND objective_id IS NULL""",
                   (o["id"], t.get("exec_position"), t["id"], uid, o["project_id"]))


def _put_note(uid: int, task_id: int, n: dict) -> None:
    """A chave externa volta junto (se ninguém a usou nesse meio-tempo): o reenvio não duplica."""
    db.execute("""INSERT INTO task_notes (id, task_id, user_id, body, actor, token_name, created_at, external_ref)
                  OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
               (n["id"], task_id, uid, n["body"], n["actor"], n["token_name"], n["created_at"],
                _ref_livre_em("task_notes", uid, n.get("external_ref"))))


def _put_item(uid: int, task_id: int, c: dict) -> None:
    db.execute("""INSERT INTO task_checklist (id, task_id, user_id, label, done, position)
                  OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s, %s)""",
               (c["id"], task_id, uid, c["label"], c["done"], c["position"]))


def _put_time(uid: int, task_id: int, e: dict) -> None:
    db.execute("""INSERT INTO time_entries (id, task_id, user_id, minutes, day, note, actor, token_name, created_at,
                                            external_ref, started_at, ended_at)
                  OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
               (e["id"], task_id, uid, e["minutes"], e["day"], e["note"], e["actor"], e["token_name"], e["created_at"],
                _ref_livre_em("time_entries", uid, e.get("external_ref")), e.get("started_at"), e.get("ended_at")))


def _current_routine(uid: int, rid: int) -> int:
    """A rotina que substituiu `rid` (trocas de agenda em sequência), ou ela mesma."""
    for _ in range(50):
        nxt = db.query_one(
            """SELECT a.entity_id FROM audit_log a JOIN recurring_tasks r ON r.id = a.entity_id AND r.user_id = a.user_id
                WHERE a.user_id = %s AND a.action = 'recurring.replace' AND a.undone_at IS NULL
                  AND (a.after->>'replaced')::bigint = %s
                ORDER BY a.id DESC LIMIT 1""", (uid, rid))
        if not nxt:
            return rid
        rid = nxt["entity_id"]
    return rid


def _set_pause_today(rid: int, end_d) -> None:
    """Deixa a rotina `rid` pausada de hoje até `end_d` (None ou passado: sem pausa hoje)."""
    today = app_today()
    cur = db.query_one("""SELECT id, start_d FROM recurring_pauses WHERE recurring_id = %s AND start_d <= %s AND end_d >= %s
                          ORDER BY id DESC LIMIT 1""", (rid, today, today))
    if end_d is not None and end_d >= today:
        if cur:
            db.execute("UPDATE recurring_pauses SET end_d = %s WHERE id = %s", (end_d, cur["id"]))
        else:
            db.execute("INSERT INTO recurring_pauses (recurring_id, start_d, end_d) VALUES (%s, %s, %s)", (rid, today, end_d))
    elif cur:
        if cur["start_d"] < today:
            db.execute("UPDATE recurring_pauses SET end_d = %s WHERE id = %s", (today - timedelta(days=1), cur["id"]))
        else:
            db.execute("DELETE FROM recurring_pauses WHERE id = %s", (cur["id"],))


@router.post("/{history_id}/undo")
def undo(history_id: int, user=Depends(active_user_csrf)):
    uid = user["user_id"]
    row = db.query_one(
        "SELECT * FROM audit_log WHERE id = %s AND user_id = %s", (history_id, uid)
    )
    if not row:
        raise HTTPException(status_code=404, detail="essa ação não está mais no histórico")
    if row["action"] not in UNDOABLE:
        raise HTTPException(status_code=400, detail="esta ação não pode ser desfeita")
    if row["undone_at"] is not None:
        raise HTTPException(status_code=409, detail="esta ação já foi desfeita")
    if history_id not in _latest_ids(uid):
        raise HTTPException(status_code=409, detail="houve alterações depois desta; desfaça as mais recentes primeiro")

    a, before, after, eid = row["action"], row["before"], row["after"], row["entity_id"]
    if a in ("worklog.create", "worklog.assign"):
        # Itens copiados pelo Duplicar (ainda desmarcados) não são trabalho da pessoa.
        copied = [int(i) for i in (after or {}).get("copied_checklist") or []]
        if db.query_one(
            """SELECT 1 FROM task_notes WHERE task_id = %(t)s UNION ALL
               SELECT 1 FROM task_checklist WHERE task_id = %(t)s AND (done OR NOT id = ANY(%(c)s::bigint[])) UNION ALL
               SELECT 1 FROM time_entries WHERE task_id = %(t)s UNION ALL
               SELECT 1 FROM photos WHERE task_id = %(t)s AND deleted_at IS NULL LIMIT 1""", {"t": eid, "c": copied}):
            raise HTTPException(status_code=409, detail="a tarefa já tem anotações, checklist, tempo ou fotos; para tirá-la, exclua pela tela")
        db.execute("DELETE FROM worklog_tasks WHERE id = %s AND user_id = %s", (eid, uid))
    elif a in ("worklog.update", "worklog.finish", "worklog.assign_update"):
        _need_task(uid, eid)
        _restore_worklog(uid, before)
    elif a == "worklog.delete":
        if audit.worklog_snapshot(eid, uid) or db.query_one("SELECT 1 FROM worklog_tasks WHERE id = %s", (eid,)):
            raise HTTPException(status_code=409, detail="a tarefa já existe")
        # Devolvida: volta enquanto quem atribuiu não decidiu (atribuir de novo ou encerrar).
        if before.get("return_reason") and before.get("assigned_by"):
            from .assign import return_resolved
            if return_resolved(eid, before["assigned_by"], history_id):
                raise HTTPException(status_code=409, detail=(
                    "quem atribuiu já resolveu a devolução (atribuiu de novo ou encerrou); combine direto com essa pessoa"))
        kids = before.get("children") or {}
        por_dia: dict[str, int] = {}
        for e in kids.get("time", []):
            por_dia[str(e["day"])] = por_dia.get(str(e["day"]), 0) + e["minutes"]
        for day, minutes in por_dia.items():  # tudo ou nada: confere antes de gravar
            check_day_total(uid, day, minutes, status=409)
        db.execute(
            """INSERT INTO worklog_tasks (id, user_id, title, description, status, due_date,
                                          created_at, completed_at, project_id, priority, ticket, after_hours,
                                          external_ref, assigned_by, assigned_at,
                                          blocked_reason, blocked_at, assigner_notified_at, follow_up_on, resolution)
               OVERRIDING SYSTEM VALUE
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (eid, uid, before["title"], before["description"], before["status"],
             before["due_date"], before["created_at"], before["completed_at"],
             _projeto_existente(uid, before.get("project_id")), before.get("priority") or 2,
             before.get("ticket"), bool(before.get("after_hours")), _ref_livre(uid, before.get("external_ref")),
             _usuario_existente(before.get("assigned_by")), before.get("assigned_at"),
             before.get("blocked_reason"), before.get("blocked_at"), before.get("assigner_notified_at"),
             before.get("follow_up_on"), before.get("resolution")),
        )
        set_extra_projects(uid, eid, before.get("extra_project_ids"))
        if before.get("remind_at"):
            db.execute("UPDATE worklog_tasks SET remind_at = %s WHERE id = %s", (before["remind_at"], eid))
        if before.get("objective_id"):
            proj = _projeto_existente(uid, before.get("project_id"))
            db.execute("UPDATE worklog_tasks SET objective_id = %s, exec_position = %s WHERE id = %s",
                       (_objetivo_valido(uid, before["objective_id"], proj), before.get("exec_position"), eid))
        for n in kids.get("notes", []):
            _put_note(uid, eid, n)
        for c in kids.get("checklist", []):
            _put_item(uid, eid, c)
        for e in kids.get("time", []):
            _put_time(uid, eid, e)
        if before.get("return_reason") and before.get("assigned_by"):
            from .assign import notify_return_undone
            notify_return_undone(before["assigned_by"], eid, before["title"], uid)
    elif a == "recurring.create":
        if not db.query_one("SELECT 1 FROM recurring_tasks WHERE id = %s AND user_id = %s AND active", (eid, uid)):
            raise HTTPException(status_code=409, detail="a rotina já foi encerrada")
        has_done = db.query_one("SELECT 1 FROM recurring_completions WHERE task_id = %s LIMIT 1", (eid,))
        if has_done:
            db.execute(
                """UPDATE recurring_tasks SET active = false,
                          deactivated_at = COALESCE(deactivated_at, now())
                    WHERE id = %s AND user_id = %s""", (eid, uid))
        else:
            db.execute("DELETE FROM recurring_tasks WHERE id = %s AND user_id = %s", (eid, uid))
    elif a == "recurring.update":
        _restore_recurring(uid, before)
    elif a == "recurring.deactivate":
        if (app_today() - row["created_at"].astimezone(app_tz()).date()).days > RETRO_DAYS:  # dias parados viraram faltas
            raise HTTPException(status_code=409, detail="essa remoção já saiu da janela de 7 dias; crie a rotina de novo")
        _restore_recurring(uid, before)
    elif a == "recurring.replace":
        # Tira a nova (devolvendo TODAS as marcações dela, com a evidência) e reativa a
        # antiga como era. Na mesma janela da remoção: depois, os dias viraram faltas.
        if (app_today() - row["created_at"].astimezone(app_tz()).date()).days > RETRO_DAYS:
            raise HTTPException(status_code=409, detail="essa troca já saiu da janela de 7 dias; ajuste a agenda de novo")
        db.execute("UPDATE recurring_completions SET task_id = %s WHERE task_id = %s AND user_id = %s",
                   (after["replaced"], eid, uid))
        db.execute("UPDATE photos SET recurring_id = %s WHERE recurring_id = %s AND user_id = %s",
                   (after["replaced"], eid, uid))  # senão o CASCADE da exclusão apagaria as fotos
        db.execute("DELETE FROM recurring_tasks WHERE id = %s AND user_id = %s", (eid, uid))
        _restore_recurring(uid, before)
    elif a in ("recurring.pause", "recurring.resume"):
        # Volta o período como era (pausa nova: some). Na janela da remoção:
        # depois disso os dias da pausa já viraram números fechados.
        if (app_today() - row["created_at"].astimezone(app_tz()).date()).days > RETRO_DAYS:
            raise HTTPException(status_code=409, detail="essa mudança já saiu da janela de 7 dias; pause ou retome de novo")
        if before.get("pause"):
            db.execute("UPDATE recurring_pauses SET end_d = %s WHERE id = %s AND recurring_id = %s",
                       (before["pause"]["end_d"], before["pause"]["id"], eid))
        else:
            # Pausa nova: desfeita no próprio dia, some; depois disso, age como "retomar"
            # (termina ontem), para os dias já passados (talvez num mês fechado) não virarem falta.
            p = db.query_one("SELECT start_d FROM recurring_pauses WHERE id = %s AND recurring_id = %s",
                             (after["pause"]["id"], eid))
            if p and p["start_d"] < app_today():
                db.execute("UPDATE recurring_pauses SET end_d = LEAST(end_d, %s) WHERE id = %s AND recurring_id = %s",
                           (app_today() - timedelta(days=1), after["pause"]["id"], eid))
            else:
                db.execute("DELETE FROM recurring_pauses WHERE id = %s AND recurring_id = %s", (after["pause"]["id"], eid))
        # A agenda mudou depois (a pausa foi copiada para a rotina nova): vale para a atual.
        if (atual := _current_routine(uid, eid)) != eid:
            _set_pause_today(atual, date.fromisoformat(str(before["pause"]["end_d"])) if before.get("pause") else None)
    elif a == "recurring.toggle":
        day = date.fromisoformat(before["day"])
        min_day, today = board_day_range(app_today())
        if not (min_day <= day <= today):  # mesma janela da marcação (7 dias)
            raise HTTPException(status_code=409, detail="essa marcação já saiu da janela de edição (7 dias)")
        if before["done"]:
            db.execute(
                """INSERT INTO recurring_completions (task_id, user_id, completed_date, note)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (task_id, completed_date) DO UPDATE SET note = EXCLUDED.note""",
                (eid, uid, day, before.get("note")))
        else:
            db.execute(
                "DELETE FROM recurring_completions WHERE task_id = %s AND user_id = %s AND completed_date = %s",
                (eid, uid, day))
        refresh_after_from(uid, eid)
    elif a == "photo.create":
        if not photos.soft_delete(uid, eid):
            raise _gone()
    elif a == "photo.delete":
        if before.get("task_id"):
            _need_task(uid, before["task_id"])
        if not photos.restore(uid, eid):
            raise _gone()
    elif a == "note.create":
        if not db.execute("DELETE FROM task_notes WHERE id = %s AND user_id = %s", (eid, uid)):
            raise _gone()
    elif a == "note.update":
        if not db.execute("UPDATE task_notes SET body = %s WHERE id = %s AND user_id = %s", (before["body"], eid, uid)):
            raise _gone()
    elif a == "time.update":
        if not db.query_one("SELECT 1 FROM time_entries WHERE id = %s AND user_id = %s", (eid, uid)):
            raise _gone()
        mesmo_dia = str(before["day"]) == str(after["day"])
        volta = before["minutes"] - (after["minutes"] if mesmo_dia else 0)
        if volta > 0:
            check_day_total(uid, before["day"], volta, status=409)
        db.execute("UPDATE time_entries SET minutes = %s, day = %s, note = %s WHERE id = %s AND user_id = %s",
                   (before["minutes"], before["day"], before.get("note"), eid, uid))
    elif a == "note.delete":
        _need_task(uid, before["task_id"])
        _put_note(uid, before["task_id"], {**before, "id": eid})
    elif a == "checklist.create":
        if not db.execute("DELETE FROM task_checklist WHERE id = %s AND user_id = %s", (eid, uid)):
            raise _gone()
    elif a == "checklist.update":
        if not db.execute("UPDATE task_checklist SET label = %s, done = %s WHERE id = %s AND user_id = %s",
                          (before["label"], before["done"], eid, uid)):
            raise _gone()
    elif a == "checklist.delete":
        _need_task(uid, before["task_id"])
        _put_item(uid, before["task_id"], {**before, "id": eid})
    elif a == "time.create":
        if not db.execute("DELETE FROM time_entries WHERE id = %s AND user_id = %s", (eid, uid)):
            raise _gone()
    elif a == "time.delete":
        _need_task(uid, before["task_id"])
        check_day_total(uid, before["day"], before["minutes"], status=409)
        _put_time(uid, before["task_id"], {**before, "id": eid})
    elif a == "renewal.create":
        if not db.execute("DELETE FROM renewals WHERE id = %s AND user_id = %s", (eid, uid)):
            raise _gone()
    elif a in ("renewal.update", "renewal.renew"):
        if not db.execute(
                """UPDATE renewals SET label = %s, expires_on = %s, warn_days = %s, project_id = %s, note = %s,
                                       renew_months = %s
                    WHERE id = %s AND user_id = %s""",
                (before["label"], before["expires_on"], before["warn_days"],
                 _projeto_existente(uid, before.get("project_id")), before.get("note"), before.get("renew_months"), eid, uid)):
            raise _gone()
    elif a == "renewal.delete":
        db.execute(
            """INSERT INTO renewals (id, user_id, label, expires_on, warn_days, project_id, note, renew_months)
               OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (eid, uid, before["label"], before["expires_on"], before["warn_days"],
             _projeto_existente(uid, before.get("project_id")), before.get("note"), before.get("renew_months")))
    elif a == "objective.create":
        # As tarefas que entraram nele depois voltam para "Sem objetivo" (o FK cuida).
        db.execute("DELETE FROM project_objectives WHERE id = %s AND user_id = %s", (eid, uid))
    elif a == "objective.update":
        if not db.execute("""UPDATE project_objectives SET title = %s, description = %s, due_date = %s, updated_at = now()
                              WHERE id = %s AND user_id = %s""",
                          (before["title"], before["description"], before["due_date"], eid, uid)):
            raise HTTPException(status_code=409, detail="o objetivo não existe mais")
    elif a == "recurring.order":
        # A ordem anterior volta; rotina criada (ou trocada de agenda) depois fica no fim, na ordem atual.
        atual = active_order(uid)
        antes = [i for i in before["ids"] if i in atual]
        renumber(uid, antes + [i for i in atual if i not in antes])
    elif a == "objective.order":
        # A ordem anterior volta; objetivo criado depois fica no fim, na ordem atual.
        atual = [r["id"] for r in db.query_all(
            "SELECT id FROM project_objectives WHERE user_id = %s AND project_id = %s ORDER BY position, id", (uid, eid))]
        antes = [i for i in before["ids"] if i in atual]
        for i, oid in enumerate(antes + [i for i in atual if i not in antes]):
            db.execute("UPDATE project_objectives SET position = %s WHERE id = %s AND user_id = %s", (i, oid, uid))
    elif a == "objective.delete":
        if not db.query_one("SELECT 1 FROM projects WHERE id = %s AND user_id = %s", (before["project_id"], uid)):
            raise HTTPException(status_code=409, detail="o projeto do objetivo não existe mais")
        _put_objective(uid, before)
    elif a == "project.create":
        # Com tarefas no projeto, arquiva em vez de apagar (não tira de ninguém).
        if db.query_one("SELECT 1 FROM worklog_tasks WHERE project_id = %s LIMIT 1", (eid,)) or \
                db.query_one("SELECT 1 FROM worklog_task_projects WHERE project_id = %s LIMIT 1", (eid,)):
            db.execute("UPDATE projects SET archived = true WHERE id = %s AND user_id = %s", (eid, uid))
        else:
            db.execute("DELETE FROM projects WHERE id = %s AND user_id = %s", (eid, uid))
    elif a == "project.update":
        if db.query_one("SELECT 1 FROM projects WHERE user_id = %s AND name = %s AND id <> %s", (uid, before["name"], eid)):
            raise HTTPException(status_code=409, detail="já existe um projeto com esse nome")
        db.execute("""UPDATE projects SET name = %s, color = %s, icon = %s, description = %s, archived = %s
                       WHERE id = %s AND user_id = %s""",
                   (before["name"], before["color"], _icone(before.get("icon")), before.get("description"),
                    before["archived"], eid, uid))
    elif a == "project.delete":
        if db.query_one("SELECT 1 FROM projects WHERE user_id = %s AND name = %s", (uid, before["name"])):
            raise HTTPException(status_code=409, detail="já existe um projeto com esse nome")
        db.execute(
            """INSERT INTO projects (id, user_id, name, color, icon, description, archived, external_ref)
               OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (eid, uid, before["name"], before["color"], _icone(before.get("icon")), before.get("description"), before["archived"],
             _ref_livre_em("projects", uid, before.get("external_ref"))))
        # As tarefas que estavam nele voltam (se ninguém as pôs em outro projeto).
        db.execute("UPDATE worklog_tasks SET project_id = %s WHERE user_id = %s AND project_id IS NULL AND id = ANY(%s)",
                   (eid, uid, before.get("task_ids") or []))
        # As que tinham outro projeto (um extra virou o principal) voltam como eram,
        # se o principal não mudou depois; e onde ele era extra, volta a ser.
        for t in before.get("promoted") or []:
            if db.query_one("SELECT 1 FROM worklog_tasks WHERE id = %s AND user_id = %s AND project_id = %s",
                            (t["id"], uid, t["project_id"])):
                db.execute("UPDATE worklog_tasks SET project_id = %s WHERE id = %s", (eid, t["id"]))
                db.execute("INSERT INTO worklog_task_projects (task_id, project_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                           (t["id"], t["project_id"]))
        db.execute(
            """INSERT INTO worklog_task_projects (task_id, project_id)
               SELECT w.id, %s FROM worklog_tasks w
                WHERE w.user_id = %s AND w.id = ANY(%s) AND w.project_id IS NOT NULL AND w.project_id <> %s
               ON CONFLICT DO NOTHING""",
            (eid, uid, before.get("extra_task_ids") or [], eid))
        for o in before.get("objectives") or []:  # os objetivos voltam, com as tarefas deles
            _put_objective(uid, o)

    db.execute("UPDATE audit_log SET undone_at = now() WHERE id = %s", (history_id,))
    audit.record(user, "undo", row["entity"], eid, before=after, after={"undid": history_id, "action": a})
    return {"ok": True, "undid": history_id, "action": a}
