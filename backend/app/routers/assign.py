"""Atribuição de tarefas: o Atribuidor manda uma tarefa para quem pode receber
(quem consentiu ou, com "Todos recebem de quem atribui", todo Usuário: a regra
mora em assignable.py; com equipes, só quem compartilha equipe com quem
atribui, ou o admin master com o papel "Manda tarefas" ligado).

A tarefa nasce na conta de quem recebe (ele é o dono: edita, conclui, exclui)
com "atribuída por". Quem atribuiu acompanha o status em "Tarefas que
atribuí" e, enquanto ela está "a fazer" e sem nada registrado, ainda pode
corrigir título, prazo e prioridade (só os que quem recebeu não mudou) ou
cancelar o envio (engano; só se ela não mexeu em nada). Depois disso é só de
quem recebeu. Excluída ou cancelada, a linha continua na lista com o
que aconteceu (vem do histórico, 60 dias). Cada atribuição manda um e-mail.
Pelo app ou por chave de API/MCP (escopo de escrita), só com o papel.

Devolver (quem recebeu, POST /api/worklog/{id}/return): a tarefa sai da conta
dela como uma exclusão (lápide worklog.delete, com o motivo; desfazível no
Histórico) e ninguém fica com ela até quem atribuiu decidir. Quem atribuiu
ganha "assign.returned" no próprio histórico (e-mail e push com o motivo) e vê
a linha "devolvida" em Tarefas que atribuí e em "Precisa de atenção", até
atribuir de novo (`from_return`, a mesma pessoa ou outra, com os campos
ajustáveis) ou encerrar (POST /api/assign/{id}/close).
"""
import logging
import threading
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import assignable, audit, db, mailer, people, push, teams
from ..deps import active_user_csrf, require_assigner, require_assigner_csrf, require_people_list
from ..labels import PRIO_PT
from ..schemas import AssignEditIn, AssignIn, ReturnIn
from ..security import token_hash
from ..services import app_today, app_tz, default_project

router = APIRouter(prefix="/api/assign", tags=["assign"])
# Devolver é de quem recebeu (a tarefa é dela): fica junto das rotas da tarefa.
received = APIRouter(prefix="/api/worklog", tags=["assign"])
log = logging.getLogger("uvicorn.error")


@router.get("/people")
def list_people(team: Annotated[str | None, Query(max_length=20)] = None, user=Depends(require_people_list)):
    """Contas com registro próprio e se podem receber tarefas agora (`accepts`,
    a regra de assignable.py) e desde quando aceitaram (`accepts_assignments_at`;
    com "Todos recebem de quem atribui" fica a escolha guardada da pessoa).
    Conta com acesso bloqueado não recebe (`blocked`: a tela diz por quê).
    `everyone`: a instância está em "Todos recebem". A foto só de quem pode
    receber (a mesma regra de GET /api/me/avatar/{id}); o admin vê todas.

    Quem não é admin (o papel Manda tarefas) vê com nome e e-mail só quem pode
    receber (e a própria conta). Quem não pode receber vem só como
    `{"accepts": false, "everyone": …}`, sem id, e-mail nem bloqueio: conta
    para "as outras N ainda não aceitam", sem expor quem disse não. Com equipes
    (sql/043), quem está fora do escopo de quem atribui nem entra na conta
    (o admin continua vendo todos, com `accepts` pela regra dele).

    `teams`: as equipes que a pessoa compartilha com quem pede (o master com o
    papel: todas as dela), para agrupar o Atribuir; `team` filtra por uma
    (o mesmo seletor da Equipe, teams.filter_sql)."""
    uid = user["user_id"]
    # Admin só pelo app (como deps.require_people_list): a chave de API de um admin
    # que também atribui vê o que o papel "Manda tarefas" vê, não todas as contas.
    is_admin = "admin" in (user.get("roles") or []) and user.get("actor") == "web"
    master = teams.selector(uid, "assigner")["master"]
    cut = teams.filter_sql("u", uid, "assigner", team) if "assigner" in (user.get("roles") or []) else "TRUE"
    scope = "TRUE" if is_admin else assignable.scope_sql("u", uid)
    names = teams.names_sql("u.id") if master else teams.shared_names_sql(uid, "u.id")
    rows = db.query_all(
        f"""SELECT u.id, u.email, u.accepts_assignments_at, u.blocked_at IS NOT NULL AS blocked,
                   u.invite_pending AS pending,
                   {assignable.receive_sql('u', uid)} AS accepts, {names} AS teams,
                   {teams.company_sql('u.id')} AS company
             FROM users u
            WHERE EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'user')
              AND ({scope} OR u.id = %s) AND {cut}
            ORDER BY NOT {assignable.receive_sql('u', uid)}, nx_fold(u.email)""", (uid,))
    # Uma leitura para a lista toda (eram três consultas por pessoa: "todos recebem", equipe e perfil).
    todos = assignable.everyone()
    perfis = people.profiles(r["id"] for r in rows)
    out = []
    for r in rows:
        everyone = r.pop("company") and todos  # o mesmo que assignable.everyone_for(r["id"])
        pending = r.pop("pending")
        if not is_admin and not r["accepts"] and r["id"] != uid:
            if r["blocked"] or pending:
                continue  # bloqueada ou convite sem aceitar: não é "ainda não aceita", nem entra na conta
            out.append({"accepts": False, "everyone": everyone})
            continue
        p = dict(perfis[r["id"]])
        if not r["accepts"] and not is_admin:
            p["avatar"] = None
        out.append({**r, **p, "everyone": everyone})
    return out


@router.get("/teams")
def assign_teams(user=Depends(require_assigner)):
    """O seletor de equipe do Atribuir: as equipes de quem atribui (o master com
    "Manda tarefas" ligado: todas, mais "Sem equipe"). `on`: a instância tem equipes."""
    return teams.selector(user["user_id"], "assigner")


def _mail_reason(to_id: int) -> str:
    if assignable.everyone_for(to_id):
        return ("Você recebe este e-mail porque, nesta instância do Nexus, todos recebem tarefas "
                "de quem atribui (definido pela administração).")
    return "Você recebe este e-mail porque aceitou receber tarefas atribuídas (Configurações > Conta)."


def _assignment_mail(task: dict, by_name: str, to_id: int):
    from ..notify import Mail  # import tardio: notify importa rotas
    m = Mail(f"Nova tarefa para você: {task['title']}", f"{by_name} atribuiu uma tarefa a você",
             "Ela já está nas suas tarefas no Nexus.")
    m.reason = _mail_reason(to_id)
    m.settings_tab = "conta"
    m.link = f"/#/tarefas?id={task['id']}"
    itens = [task["title"]]
    if task.get("description"):
        itens.append(task["description"])
    if task.get("due_date"):
        itens.append(f"Prazo: {task['due_date'].strftime('%d/%m/%Y')}")
    if task.get("priority") != 2:
        itens.append(f"Prioridade {PRIO_PT[task['priority']]}")
    if task.get("ticket"):
        itens.append(f"Chamado {task['ticket']}")
    m.blocks = [("Tarefa", itens)]
    return m


def _send(to: str, mail) -> None:
    try:
        mailer.send(to, mail.subject, mail.text(), mail.html())
    except Exception as e:  # noqa: BLE001 — a tarefa já foi atribuída; o e-mail é aviso
        # Sem o e-mail em claro no log: o mesmo resumo com que se procura a conta, se precisar.
        log.warning("e-mail de atribuição para %s falhou: %s", token_hash(to)[:12], e)


def _spawn(to: str, mail) -> None:
    """Envio fora da requisição (o SMTP pode levar segundos)."""
    threading.Thread(target=_send, args=(to, mail), daemon=True).start()


@router.post("", status_code=201)
def assign(data: AssignIn, user=Depends(require_assigner_csrf)):
    if data.user_id == user["user_id"]:
        raise HTTPException(status_code=400, detail="para você mesmo, crie a tarefa normalmente")
    target = db.query_one(
        f"""SELECT u.id, u.email, {assignable.receive_sql('u', user['user_id'])} AS accepts FROM users u
            WHERE u.id = %s AND u.blocked_at IS NULL AND EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'user')""",
        (data.user_id,),
    )
    if not target or not assignable.in_scope(user["user_id"], target["id"]):
        # Fora das equipes de quem atribui: como quem não existe (sem revelar a conta).
        raise HTTPException(status_code=404, detail="usuário não encontrado")
    if not target["accepts"]:
        raise HTTPException(status_code=403, detail="essa pessoa não aceitou receber tarefas atribuídas")
    by_name = people.profile(user["user_id"])["name"]
    to_name = people.profile(target["id"])["name"]
    # A tarefa e as duas linhas do histórico (a de quem recebe e a de quem atribuiu, que
    # é de onde sai "Tarefas que atribuí") vão juntas; os avisos saem depois de gravar.
    with db.transaction():
        _limit(user["user_id"], target["id"])
        if data.from_return is not None:
            _lock_open_return(user["user_id"], data.from_return, 409, RESOLVED_MSG)
        row = db.query_one(
            """INSERT INTO worklog_tasks (user_id, title, description, due_date, priority, ticket, after_hours,
                                          assigned_by, assigned_at, project_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), %s) RETURNING id""",
            (target["id"], data.title, data.description, data.due_date, data.priority, data.ticket,
             data.after_hours, user["user_id"], default_project(target["id"])),  # o projeto padrão de quem recebe
        )
        tid = row["id"]
        snap = audit.worklog_snapshot(tid, target["id"])
        audit.record(user, "worklog.assign", "worklog", tid, after={**snap, "by": by_name}, user_id=target["id"])
        audit.record(user, "assign.send", "assignment", tid,
                     after={"title": data.title, "to": to_name, "to_email": target["email"], "to_id": target["id"],
                            **({"from_return": data.from_return} if data.from_return is not None else {})})
    emailed = mailer.configured()
    if emailed:
        _spawn(target["email"], _assignment_mail({**snap, "due_date": data.due_date}, by_name, target["id"]))
    threading.Thread(target=push.notify_assigned, args=(target["id"], {"id": tid, "title": data.title}, by_name), daemon=True).start()
    return {"id": tid, "to": to_name, "emailed": emailed}


# Freio por par (quem atribui, quem recebe): cada atribuição cria tarefa na conta de
# outra pessoa e manda e-mail e push. Por destinatário, não um teto global: uma
# conta-robô de integração precisa importar filas para várias pessoas. Vale para
# app, chave de API e MCP (todos passam por assign()). Conta no histórico de quem
# atribui (assign.send), que já guarda o destinatário: sobrevive a reinício do
# backend. Atribuição cancelada (a tarefa saiu da conta de quem recebeu) não conta.
ASSIGN_MAX, ASSIGN_WINDOW = 20, 600


def _limit(by: int, to: int) -> None:
    """Dentro da transação do envio: a trava por remetente (solta ao gravar) põe em
    fila os envios simultâneos da mesma pessoa, e cada um conta os que já gravaram."""
    db.query_one("SELECT pg_advisory_xact_lock(hashtext('assign.limit'), %s::int)", (by,))
    row = db.query_one(
        """SELECT count(*)::int AS n, min(created_at) AS first, now() AS now FROM (
               SELECT a.created_at FROM audit_log a
                WHERE a.user_id = %s AND a.action = 'assign.send' AND (a.after->>'to_id')::bigint = %s
                  AND a.created_at > now() - make_interval(secs => %s)
                  AND NOT (EXISTS (SELECT 1 FROM audit_log c
                                    WHERE c.user_id = a.user_id AND c.entity = 'assignment'
                                      AND c.entity_id = a.entity_id AND c.action = 'assign.cancel')
                           AND NOT EXISTS (SELECT 1 FROM worklog_tasks w WHERE w.id = a.entity_id))
                ORDER BY a.created_at DESC LIMIT %s) x""", (by, to, ASSIGN_WINDOW, ASSIGN_MAX))
    if row["n"] >= ASSIGN_MAX:
        wait = max(1, ASSIGN_WINDOW - int((row["now"] - row["first"]).total_seconds()))
        raise HTTPException(
            status_code=429, headers={"Retry-After": str(wait)},
            detail=f"muitas tarefas para a mesma pessoa em pouco tempo (até {ASSIGN_MAX} a cada "
                   f"{ASSIGN_WINDOW // 60} minutos); tente de novo em alguns minutos")


def notify_assigner(task_id: int) -> None:
    """Tarefa atribuída acabou de ser concluída: avisa quem atribuiu, uma vez só
    (assigner_notified_at). Sem SMTP, só marca. Quem atribuiu também vê na lista."""
    row = db.query_one(
        """UPDATE worklog_tasks SET assigner_notified_at = now()
            WHERE id = %s AND status = 'done' AND assigned_by IS NOT NULL AND assigner_notified_at IS NULL
        RETURNING title, user_id, assigned_by, completed_at""",
        (task_id,),
    )
    if not row or not mailer.configured():
        return
    to = db.query_one("SELECT email FROM users WHERE id = %s", (row["assigned_by"],))
    if not to:
        return
    from ..notify import Mail
    quem = people.profile(row["user_id"])["name"]
    m = Mail(f"Concluída: {row['title']}", f"{quem} concluiu a tarefa que você atribuiu",
             "Ela aparece como concluída em Equipe, em Tarefas que atribuí, no Nexus.")
    m.reason = "Você recebe este e-mail porque atribuiu esta tarefa pelo Nexus (um aviso por tarefa)."
    m.settings_tab = None
    m.link = "/#/equipe"
    m.blocks = [("Tarefa", [row["title"], f"Concluída em {row['completed_at'].astimezone(app_tz()).strftime('%d/%m/%Y %H:%M')}"])]
    _spawn(to["email"], m)


@router.get("/sent")
def sent(user=Depends(require_assigner)):
    """Tarefas que esta pessoa atribuiu, com o status atual (as mais recentes).
    `editable`: ainda dá para corrigir (o que quem recebeu não mudou; falso se
    ela deixou de receber tarefas atribuídas); `cancelable`: ainda dá para
    cancelar (vale mesmo sem `editable`). As que saíram da conta de
    quem recebeu continuam aqui (status "removed", com `ended`)."""
    # Fora das equipes de quem atribuiu (`same_team` falso) a linha vem sem `description`
    # nem `blocked_reason`; conta de destino excluída: "conta excluída", sem e-mail nem
    # motivo da devolução (em _removed). Fica em comentário: a docstring vai para o openapi.
    # `open`: "a fazer", sem nada registrado e no alcance (o que o cancelar exige). Alterar
    # pede também a regra do PATCH: a pessoa ainda recebe, ou a conta está bloqueada.
    scope = assignable.scope_sql('u', int(user['user_id']))
    rows = db.query_all(
        f"""SELECT w.id, w.title, w.description, w.status, w.due_date, w.assigned_at, w.completed_at, w.priority, w.blocked_reason,
                   w.user_id AS to_id, u.email AS to_email,
                   (w.status = 'todo' AND NOT EXISTS ({_STARTED.format(t="w.id")}) AND {scope}) AS open,
                   (u.blocked_at IS NOT NULL OR {assignable.consent_sql('u')}) AS receives,
                   {scope} AS same_team
              FROM worklog_tasks w JOIN users u ON u.id = w.user_id
             WHERE w.assigned_by = %s
             ORDER BY w.assigned_at DESC NULLS LAST, w.id DESC
             LIMIT 200""",
        (user["user_id"],),
    )
    today = app_today()
    nomes = people.profiles(r["to_id"] for r in rows)
    for r in rows:
        # Cancelar só enquanto quem recebeu não mexeu em nada (Alterar ainda vale
        # para os campos que ela não mudou). Quem desligou o aceite: só cancelar.
        aberta, recebe = r.pop("open"), r.pop("receives")
        r["editable"] = bool(aberta and recebe)
        r["cancelable"] = bool(aberta and not _touched(r["id"], r["to_id"]))
        if not r["same_team"]:
            # Fora do alcance de quem atribuiu: a linha fica (o que ela mandou), sem o
            # que quem recebeu escreve hoje na tarefa.
            r["description"] = r["blocked_reason"] = None
        r["to_name"] = nomes[r.pop("to_id")]["name"]
        r["late"] = bool(r["due_date"] and r["status"] != "done" and r["due_date"] < today)
        r["ended"] = None
    rows += _removed(user["user_id"])
    rows.sort(key=lambda r: (r["assigned_at"] is not None, r["assigned_at"] or 0, r["id"]), reverse=True)
    return rows[:200]


# Quem recebeu já registrou algo na tarefa: tempo, anotação, checklist, foto, cronômetro.
_STARTED = """SELECT 1 FROM time_entries WHERE task_id = {t} UNION ALL
              SELECT 1 FROM task_notes WHERE task_id = {t} UNION ALL
              SELECT 1 FROM task_checklist WHERE task_id = {t} UNION ALL
              SELECT 1 FROM task_timers WHERE task_id = {t} UNION ALL
              SELECT 1 FROM photos WHERE task_id = {t} AND deleted_at IS NULL"""


def _removed(uid: int) -> list[dict]:
    """Atribuições (histórico de quem atribuiu, 60 dias) cuja tarefa não existe
    mais, com o que houve: excluída no histórico de quem recebeu, cancelada ou
    devolvida (com o motivo e, se já resolvida, atribuída de novo ou encerrada)
    no de quem atribuiu. Sem registro (desfez o recebimento, conta excluída):
    "removed" sem data."""
    rows = db.query_all(
        """SELECT a.entity_id AS id,
                  -- o título mais recente: o da saída, o da última alteração, o do envio
                  COALESCE(f.title, (SELECT u.after->>'title' FROM audit_log u
                                      WHERE u.user_id = a.user_id AND u.entity = 'assignment' AND u.entity_id = a.entity_id
                                        AND u.action = 'assign.update' ORDER BY u.id DESC LIMIT 1),
                           a.after->>'title') AS title,
                  a.after->>'to' AS to_name,
                  a.after->>'to_email' AS to_email,
                  EXISTS (SELECT 1 FROM users x
                           WHERE x.id = COALESCE((a.after->>'to_id')::bigint,
                                                 (SELECT y.id FROM users y WHERE y.email = a.after->>'to_email'))) AS to_exists,
                  a.created_at AS assigned_at, f.action AS end_action, f.at AS ended_at,
                  f.snap AS end_snap, z.action AS res_action, z.at AS res_at, z.to_name AS res_to, z.to_exists AS res_to_exists
             FROM audit_log a
             LEFT JOIN LATERAL (
                  SELECT d.action, d.created_at AS at, d.id, d.before->>'title' AS title, NULL::jsonb AS snap FROM audit_log d
                   WHERE d.user_id = COALESCE((a.after->>'to_id')::bigint,
                                              (SELECT x.id FROM users x WHERE x.email = a.after->>'to_email'))
                     AND d.entity = 'worklog' AND d.entity_id = a.entity_id AND d.action = 'worklog.delete'
                  UNION ALL
                  SELECT d.action, d.created_at, d.id, d.before->>'title', NULL FROM audit_log d
                   WHERE d.user_id = a.user_id AND d.entity = 'assignment' AND d.entity_id = a.entity_id
                     AND d.action = 'assign.cancel'
                  UNION ALL  -- a devolução (gravada logo depois da lápide de quem recebeu)
                  SELECT d.action, d.created_at, d.id, d.after->>'title', d.after FROM audit_log d
                   WHERE d.user_id = a.user_id AND d.entity = 'assignment' AND d.entity_id = a.entity_id
                     AND d.action = 'assign.returned'
                  ORDER BY id DESC LIMIT 1) f ON true
             LEFT JOIN LATERAL (
                  SELECT r.action, r.created_at AS at, r.after->>'to' AS to_name,
                         EXISTS (SELECT 1 FROM users x
                                  WHERE x.id = COALESCE((r.after->>'to_id')::bigint,
                                                        (SELECT y.id FROM users y WHERE y.email = r.after->>'to_email'))) AS to_exists
                    FROM audit_log r
                   WHERE f.action = 'assign.returned' AND r.user_id = a.user_id AND r.id > f.id
                     AND ((r.entity = 'assignment' AND r.entity_id = a.entity_id AND r.action = 'assign.close')
                          OR (r.action = 'assign.send' AND r.after->>'from_return' = a.entity_id::text))
                   ORDER BY r.id DESC LIMIT 1) z ON true
            WHERE a.user_id = %s AND a.action = 'assign.send' AND a.created_at > now() - interval '60 days'
              AND NOT EXISTS (SELECT 1 FROM worklog_tasks w WHERE w.id = a.entity_id)
            ORDER BY a.id DESC LIMIT 100""",
        (uid,),
    )
    kinds = {"worklog.delete": "deleted", "assign.cancel": "canceled", "assign.returned": "returned"}
    out = []
    for r in rows:
        snap, kind = r.pop("end_snap") or {}, kinds.get(r.pop("end_action"), "removed")
        res_action, res_at, res_to = r.pop("res_action"), r.pop("res_at"), r.pop("res_to")
        if not r.pop("res_to_exists"):
            res_to = GONE  # quem recebeu a reatribuição saiu da instância: sem o nome, como em to_name
        ended = {"kind": kind, "at": r.pop("ended_at")}
        gone = not r.pop("to_exists")
        if gone:
            # A conta de destino não existe mais: a linha fica (é o histórico de quem
            # atribuiu), sem nome, e-mail nem o motivo que a pessoa escreveu.
            r["to_name"], r["to_email"] = GONE, None
        if kind == "returned":
            ended["reason"] = None if gone else snap.get("reason")
            ended["resolved"] = None if not res_action else (
                {"kind": "closed", "at": res_at} if res_action == "assign.close"
                else {"kind": "reassigned", "at": res_at, "to": res_to})
            # Para "Atribuir de novo": os campos como a tarefa saiu (quem atribuiu ajusta no diálogo).
            ended["prefill"] = {k: snap.get(k) for k in ("title", "description", "due_date", "priority", "ticket", "after_hours")}
        out.append({**r, "status": "removed", "description": None, "due_date": None, "completed_at": None, "priority": 2,
                    "blocked_reason": None, "late": False, "editable": False, "cancelable": False, "ended": ended})
    return out


GONE = "conta excluída"
RESOLVED_MSG = "essa devolução já foi resolvida (atribuída de novo ou encerrada)"

# Devolução ainda sem decisão de quem atribuiu: a tarefa não voltou (desfazer
# de quem recebeu), não saiu de novo da conta dela e não foi atribuída de novo
# nem encerrada.
_OPEN_RETURNS = """
    SELECT a.id AS hist_id, a.entity_id AS id, a.after->>'title' AS title,
           CASE WHEN tu.id IS NULL THEN 'conta excluída' ELSE a.after->>'to' END AS to_name,
           (a.after->>'to_id')::bigint AS to_id,
           CASE WHEN tu.id IS NULL THEN NULL ELSE a.after->>'reason' END AS reason, a.created_at AS at
      FROM audit_log a LEFT JOIN users tu ON tu.id = (a.after->>'to_id')::bigint
     WHERE a.user_id = %(u)s AND a.action = 'assign.returned' AND a.created_at > now() - interval '60 days'
       AND NOT EXISTS (SELECT 1 FROM worklog_tasks w WHERE w.id = a.entity_id)
       AND NOT EXISTS (SELECT 1 FROM audit_log d WHERE d.user_id = (a.after->>'to_id')::bigint AND d.entity = 'worklog'
                         AND d.entity_id = a.entity_id AND d.action = 'worklog.delete' AND d.id > a.id)
       AND NOT EXISTS (SELECT 1 FROM audit_log r WHERE r.user_id = a.user_id AND r.id > a.id
                         AND ((r.entity = 'assignment' AND r.entity_id = a.entity_id AND r.action = 'assign.close')
                              OR (r.action = 'assign.send' AND r.after->>'from_return' = a.entity_id::text)))"""


def open_returns(uid: int) -> list[dict]:
    """Devoluções que esperam quem atribuiu (a mais recente antes)."""
    return db.query_all(_OPEN_RETURNS + " ORDER BY a.id DESC LIMIT 50", {"u": uid})


def _lock_open_return(uid: int, task_id: int, status: int, detail: str) -> dict:
    """Dentro da transação de quem decide a devolução (atribuir de novo ou
    encerrar): trava a linha assign.returned e confere de novo. Duas decisões
    ao mesmo tempo: a segunda espera a primeira gravar e encontra a devolução
    já resolvida."""
    r = next((x for x in open_returns(uid) if x["id"] == task_id), None)
    if r:
        db.query_one("SELECT 1 FROM audit_log WHERE id = %s FOR UPDATE", (r["hist_id"],))
        r = next((x for x in open_returns(uid) if x["id"] == task_id), None)
    if not r:
        raise HTTPException(status_code=status, detail=detail)
    return r


def return_resolved(task_id: int, assigner_id: int, since_id: int) -> bool:
    """Quem atribuiu já decidiu (atribuiu de novo ou encerrou) depois da devolução since_id?"""
    return bool(db.query_one(
        """SELECT 1 FROM audit_log r WHERE r.user_id = %(a)s AND r.id > %(s)s
              AND ((r.entity = 'assignment' AND r.entity_id = %(t)s AND r.action = 'assign.close')
                   OR (r.action = 'assign.send' AND r.after->>'from_return' = %(t)s::text)) LIMIT 1""",
        {"a": assigner_id, "s": since_id, "t": task_id}))


def _own_sent(task_id: int, uid: int) -> dict:
    """A tarefa que esta pessoa atribuiu, se ainda dá para mexer: "a fazer" e
    sem nada registrado por quem recebeu. Depois disso é só de quem recebeu."""
    row = db.query_one(
        """SELECT w.id, w.user_id, w.status, w.title, u.email, u.blocked_at IS NOT NULL AS blocked
             FROM worklog_tasks w JOIN users u ON u.id = w.user_id
            WHERE w.id = %s AND w.assigned_by = %s""", (task_id, uid))
    if not row:
        raise HTTPException(status_code=404, detail="tarefa não encontrada")
    if row["status"] != "todo" or db.query_one(_STARTED.format(t="%(t)s") + " LIMIT 1", {"t": task_id}):
        raise HTTPException(status_code=409, detail=STARTED_MSG)
    return row


STARTED_MSG = "a pessoa já começou esta tarefa e agora só ela pode alterá-la; combine direto com quem recebeu"

# O que quem recebeu pode mudar na tarefa (comparado com o que chegou a ela).
_OWN_FIELDS = ("title", "description", "due_date", "priority", "project_id", "extra_project_ids", "objective_id",
               "ticket", "after_hours")
_FIELD_PT = {"title": "o título", "description": "a descrição", "due_date": "o prazo", "priority": "a prioridade"}


def _touched(task_id: int, to_id: int) -> list[str]:
    """Campos que quem recebeu mudou na tarefa (as edições dela que não foram
    desfeitas; as de quem atribuiu ficam em worklog.assign_update)."""
    rows = db.query_all(
        """SELECT before, after FROM audit_log
            WHERE user_id = %s AND entity = 'worklog' AND entity_id = %s
              AND action = 'worklog.update' AND undone_at IS NULL""", (to_id, task_id))
    return [k for k in _OWN_FIELDS
            if any(k in (r["before"] or {}) and k in (r["after"] or {}) and r["before"][k] != r["after"][k] for r in rows)]


def _change_mail(title: str, by_name: str, verb: str, lines: list[str], link: str, to_id: int):
    from ..notify import Mail  # import tardio: notify importa rotas
    m = Mail(f"Tarefa {verb[:-2].lower()}ada: {title}", f"{by_name} {verb.lower()} uma tarefa que tinha atribuído a você",
             "Era uma das suas tarefas a fazer no Nexus.")
    m.reason = _mail_reason(to_id)
    m.settings_tab = "conta"
    m.link = link
    m.blocks = [("Tarefa", lines)]
    return m


NOT_RECEIVING_MSG = ("essa pessoa não recebe mais tarefas atribuídas: a tarefa continua com ela, "
                     "mas você não pode mais alterá-la (ainda pode cancelar)")
OUT_OF_TEAM_MSG = ("vocês não estão mais na mesma equipe: a tarefa continua na sua lista, "
                   "mas só quem recebeu pode mudá-la agora")


@router.patch("/{task_id}")
def update_sent(task_id: int, data: AssignEditIn, user=Depends(require_assigner_csrf)):
    """Corrige título, descrição, prazo ou prioridade de uma tarefa atribuída que ainda não
    começou. Só o que de fato muda; campo que quem recebeu já mudou não é
    regravado por cima (409, nada muda)."""
    row = _own_sent(task_id, user["user_id"])
    if not assignable.in_scope(user["user_id"], row["user_id"]):
        # Atribuição antiga entre quem não compartilha mais equipe: fica no
        # histórico de quem mandou (Tarefas que atribuí), mas não se altera.
        raise HTTPException(status_code=403, detail=OUT_OF_TEAM_MSG)
    if not row["blocked"] and not assignable.can_receive(user["user_id"], row["user_id"]):
        # A mesma regra do envio: quem desligou o aceite não tem a tarefa reescrita.
        # Cancelar continua valendo (só o escopo). Conta bloqueada pelo admin segue
        # como antes: dá para corrigir, sem e-mail (ninguém lê).
        raise HTTPException(status_code=403, detail=NOT_RECEIVING_MSG)
    with db.transaction():
        after, by_name, desc_changed = _update_sent(task_id, data, row, user)
    if mailer.configured() and not row["blocked"]:  # conta bloqueada: ninguém lê
        lines = [after["title"]]
        if desc_changed:
            lines.append(after["description"] or "(sem descrição)")
        if after["due_date"]:
            lines.append(f"Prazo: {after['due_date'].strftime('%d/%m/%Y')}")
        lines.append(f"Prioridade {PRIO_PT[after['priority']]}")
        _spawn(row["email"], _change_mail(after["title"], by_name, "Alterou", lines, f"/#/tarefas?id={task_id}", row["user_id"]))
    return {"id": task_id, "title": after["title"], "description": after["description"], "due_date": after["due_date"],
            "priority": after["priority"]}


def _update_sent(task_id: int, data: AssignEditIn, row: dict, user: dict):
    """A gravação de update_sent (a tarefa e as duas linhas do histórico), dentro da transação de quem chama."""
    before = audit.worklog_snapshot(task_id, row["user_id"])
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None or k in ("due_date", "description")}
    changes = {k: v for k, v in changes.items() if audit._jsonable(v) != audit._jsonable(before[k])}
    if not changes:
        raise HTTPException(status_code=400, detail="nada para mudar")
    mexidos = [k for k in _touched(task_id, row["user_id"]) if k in changes]
    if mexidos:
        quem = people.profile(row["user_id"])["name"]
        raise HTTPException(status_code=409, detail=(
            f"{quem} já mudou {' e '.join(_FIELD_PT[k] for k in mexidos)} desde que recebeu; "
            "nada foi alterado. Combine com ela ou mude só o resto"))
    sets = ", ".join(f"{k} = %({k})s" for k in changes)  # chaves fixas do schema
    # Só se ninguém mudou esses campos entre a leitura e a gravação.
    same = " AND ".join(f"{k} IS NOT DISTINCT FROM %(old_{k})s" for k in changes)
    if not db.execute(f"""UPDATE worklog_tasks SET {sets}
                           WHERE id = %(id)s AND assigned_by = %(by)s AND status = 'todo' AND {same}""",
                      {**changes, **{f"old_{k}": before[k] for k in changes}, "id": task_id, "by": user["user_id"]}):
        raise HTTPException(status_code=409, detail=STARTED_MSG)
    after = audit.worklog_snapshot(task_id, row["user_id"])
    by_name = people.profile(user["user_id"])["name"]
    # No histórico de quem recebe (pode desfazer: a tarefa é dela) e no de quem atribuiu.
    audit.record(user, "worklog.assign_update", "worklog", task_id, before=before, after={**after, "by": by_name},
                 user_id=row["user_id"])
    audit.record(user, "assign.update", "assignment", task_id,
                 before={k: before[k] for k in ("title", "description", "due_date", "priority")},
                 after={"title": after["title"], "description": after["description"], "due_date": after["due_date"],
                        "priority": after["priority"], "to": people.profile(row["user_id"])["name"]})
    return after, by_name, "description" in changes


@router.post("/{task_id}/cancel")
def cancel_sent(task_id: int, user=Depends(require_assigner_csrf)):
    """Cancela uma atribuição feita por engano: a tarefa (ainda não começada e
    sem nada mudado por quem recebeu) sai da conta dela, que é avisada por
    e-mail. No histórico dela fica a exclusão (worklog.delete, desfazível)."""
    row = _own_sent(task_id, user["user_id"])
    if not assignable.in_scope(user["user_id"], row["user_id"]):
        raise HTTPException(status_code=403, detail=OUT_OF_TEAM_MSG)
    # A exclusão e as duas linhas do histórico vão juntas; o e-mail sai depois de gravar.
    with db.transaction():
        before = audit.worklog_snapshot(task_id, row["user_id"])
        if _touched(task_id, row["user_id"]):
            raise HTTPException(status_code=409, detail=(
                "a pessoa já mexeu nesta tarefa: cancelar apagaria o que ela escreveu. "
                "Combine com ela (ela pode excluir) ou use Alterar"))
        p = {"id": task_id, "by": user["user_id"], **{f"old_{k}": before[k] for k in
                                                         ("title", "description", "due_date", "priority", "project_id")}}
        # Tudo de novo na mesma gravação: nada registrado e nada mudado desde a leitura.
        if not db.execute(
                f"""DELETE FROM worklog_tasks
                     WHERE id = %(id)s AND assigned_by = %(by)s AND status = 'todo'
                       AND NOT EXISTS ({_STARTED.format(t="%(id)s")})
                       AND title IS NOT DISTINCT FROM %(old_title)s AND description IS NOT DISTINCT FROM %(old_description)s
                       AND due_date IS NOT DISTINCT FROM %(old_due_date)s AND priority = %(old_priority)s
                       AND project_id IS NOT DISTINCT FROM %(old_project_id)s""", p):
            raise HTTPException(status_code=409, detail=STARTED_MSG)
        by_name = people.profile(user["user_id"])["name"]
        # Lápide comum (*.delete) para o feed/webhook de quem recebeu, com quem cancelou.
        audit.record(user, "worklog.delete", "worklog", task_id,
                     before={**before, "by": by_name, "canceled_by": by_name, "children": {}},
                     user_id=row["user_id"])
        audit.record(user, "assign.cancel", "assignment", task_id,
                     before={"title": row["title"], "to": people.profile(row["user_id"])["name"]})
    if mailer.configured() and not row["blocked"]:
        _spawn(row["email"], _change_mail(row["title"], by_name, "Cancelou", [row["title"], "A tarefa saiu da sua lista; não precisa fazer nada."], "/#/tarefas", row["user_id"]))
    return {"ok": True}

@router.post("/{task_id}/close")
def close_return(task_id: int, user=Depends(require_assigner_csrf)):
    """Encerra uma tarefa devolvida sem atribuir de novo: sai de "Precisa de
    atenção" e fica na lista como "devolvida · encerrada"."""
    with db.transaction():
        r = _lock_open_return(user["user_id"], task_id, 404, "não há devolução em aberto com esse número")
        audit.record(user, "assign.close", "assignment", task_id,
                     before={"title": r["title"], "to": r["to_name"], "reason": r["reason"]})
    return {"ok": True}


# ------------------------------------------------------------ devolver --

def _return_mail(title: str, quem: str, reason: str):
    from ..notify import Mail  # import tardio: notify importa rotas
    m = Mail(f"Devolvida: {title}", f"{quem} devolveu a tarefa que você atribuiu",
             f"Ela saiu das tarefas de {quem}. Em Equipe, em Tarefas que atribuí, você atribui de novo "
             "(à mesma pessoa ou a outra) ou encerra.")
    m.reason = "Você recebe este e-mail porque atribuiu esta tarefa pelo Nexus."
    m.settings_tab = None
    m.link = "/#/equipe"
    m.blocks = [("Tarefa", [title]), ("Motivo", [reason])]
    return m


def _push_return(uid: int, tid: int, title: str, quem: str, reason: str) -> None:
    try:
        p = push.prefs(uid)
        if p["assigned"]:
            push.send(uid, push._msg(f"Devolvida por {quem}", f"{title}: {reason}", "/#/equipe", f"devolvida-{tid}",
                                     "devolvida", p["hide_content"], "Tarefa devolvida"), ttl=24 * 3600)
    except Exception:  # noqa: BLE001 — aviso; a devolução já foi gravada
        log.exception("push de devolução da tarefa %s falhou", tid)


def _undo_return_mail(title: str, quem: str):
    from ..notify import Mail  # import tardio: notify importa rotas
    m = Mail(f"Voltou atrás: {title}", f"{quem} desfez a devolução da tarefa que você atribuiu",
             f"A tarefa voltou para as tarefas de {quem}, como antes da devolução. Não precisa atribuir de novo.")
    m.reason = "Você recebe este e-mail porque atribuiu esta tarefa pelo Nexus."
    m.settings_tab = None
    m.link = "/#/equipe"
    m.blocks = [("Tarefa", [title])]
    return m


def notify_return_undone(assigner_id: int, task_id: int, title: str, uid: int) -> None:
    """Quem devolveu desfez (Histórico): quem atribuiu recebeu o e-mail "Devolvida"
    e ficaria achando que a tarefa está sem dono. Avisa pelo mesmo caminho."""
    assigner = db.query_one("SELECT id, email FROM users WHERE id = %s AND blocked_at IS NULL", (assigner_id,))
    if not assigner:
        return
    quem = people.profile(uid)["name"]
    if mailer.configured():
        _spawn(assigner["email"], _undo_return_mail(title, quem))

    def _push():
        try:
            p = push.prefs(assigner["id"])
            if p["assigned"]:
                push.send(assigner["id"], push._msg(f"{quem} voltou atrás", f"{title}: a tarefa voltou para {quem}",
                                                    "/#/equipe", f"devolvida-{task_id}", "devolvida", p["hide_content"],
                                                    "Devolução desfeita"), ttl=24 * 3600)
        except Exception:  # noqa: BLE001 — aviso; o desfazer já foi gravado
            log.exception("push do desfazer da devolução %s falhou", task_id)
    threading.Thread(target=_push, daemon=True).start()


@received.post("/{task_id}/return")
def return_task(task_id: int, data: ReturnIn, user=Depends(active_user_csrf)):
    """Quem recebeu devolve a tarefa atribuída, com o motivo (até 120). Ela sai
    das tarefas dela como uma exclusão (desfazível no Histórico enquanto quem
    atribuiu não decidir) e quem atribuiu é avisado (e-mail, push, Hoje, Equipe)."""
    uid = user["user_id"]
    before = audit.worklog_snapshot(task_id, uid)
    if not before:
        raise HTTPException(status_code=404, detail="tarefa não encontrada (pode ter sido excluída)")
    if not before["assigned_by"] or before["assigned_by"] == uid:
        raise HTTPException(status_code=400, detail="só dá para devolver uma tarefa que alguém atribuiu a você")
    if before["status"] == "done":
        raise HTTPException(status_code=409, detail="a tarefa já está concluída; para devolver, reabra antes")
    assigner = db.query_one("SELECT id, email, blocked_at IS NOT NULL AS blocked FROM users WHERE id = %s",
                            (before["assigned_by"],))
    quem = people.profile(uid)["name"]
    by_name = people.profile(assigner["id"])["name"] if assigner else "quem atribuiu"
    from .worklog import stop_timer_of  # import tardio: worklog importa este módulo
    # Tudo ou nada: parar o cronômetro, guardar os filhos, apagar e gravar as duas
    # linhas do histórico. Uma falha no meio deixa a tarefa como estava (antes, a
    # tarefa sumia sem lápide). E-mail e push só depois de gravar.
    with db.transaction():
        # Trava a tarefa: nada entra nela (tempo, anotação) entre a leitura e a exclusão.
        if not db.query_one("SELECT 1 FROM worklog_tasks WHERE id = %s AND user_id = %s AND status <> 'done' FOR UPDATE",
                            (task_id, uid)):
            raise HTTPException(status_code=409, detail="a tarefa mudou enquanto você devolvia")
        # Tarefa transferida pelo admin guarda horas de quem a tinha: a exclusão em
        # cascata as apagaria (e o desfazer as devolveria na conta errada).
        if db.query_one("SELECT 1 FROM time_entries WHERE task_id = %s AND user_id <> %s LIMIT 1", (task_id, uid)):
            raise HTTPException(status_code=409, detail=FOREIGN_TIME_MSG)
        # Cronômetro rodando nela: para e aponta antes (o tempo entra na lápide e volta com o desfazer).
        stop_timer_of(user, task_id)
        # Anotações, checklist e tempo saem junto (como na exclusão): ficam na lápide para o desfazer.
        before["children"] = {
            "notes": db.query_all("SELECT id, body, actor, token_name, created_at, external_ref FROM task_notes WHERE task_id = %s", (task_id,)),
            "checklist": db.query_all("SELECT id, label, done, position FROM task_checklist WHERE task_id = %s", (task_id,)),
            # user_id: de quem é cada apontamento (o desfazer devolve a quem apontou).
            "time": db.query_all("SELECT id, user_id, minutes, day, note, actor, token_name, created_at, external_ref, started_at, ended_at"
                                  " FROM time_entries WHERE task_id = %s", (task_id,)),
        }
        if not db.execute("DELETE FROM worklog_tasks WHERE id = %s AND user_id = %s AND status <> 'done'", (task_id, uid)):
            raise HTTPException(status_code=409, detail="a tarefa mudou enquanto você devolvia")
        # Lápide comum (*.delete) para o feed/webhook de quem recebeu, com o motivo.
        audit.record(user, "worklog.delete", "worklog", task_id,
                     before={**before, "returned_to": by_name, "return_reason": data.reason})
        if assigner:
            audit.record(user, "assign.returned", "assignment", task_id, user_id=assigner["id"], after={
                **{k: before[k] for k in ("title", "description", "due_date", "priority", "ticket", "after_hours")},
                "to": quem, "to_id": uid, "reason": data.reason})
    if assigner and not assigner["blocked"]:
        if mailer.configured():
            _spawn(assigner["email"], _return_mail(before["title"], quem, data.reason))
        threading.Thread(target=_push_return, args=(assigner["id"], task_id, before["title"], quem, data.reason),
                         daemon=True).start()
    return {"ok": True, "to": by_name}


FOREIGN_TIME_MSG = "esta tarefa guarda horas de quem a passou para você; conclua em vez de devolver"


# ------------------------------------------------- aviso do Hoje (E7) --

NEWS_FIRST_DAYS = 7  # sem aviso visto ainda: o que chegou nos últimos 7 dias


def news(uid: int) -> dict | None:
    """Das que esta pessoa atribuiu, desde o último aviso visto: quantas foram
    concluídas e quantas devolvidas (ainda sem decisão). Só retorno, nada de
    atraso de terceiros."""
    row = db.query_one(
        f"""WITH s AS (SELECT COALESCE(assign_news_seen_at, now() - make_interval(days => %(d)s)) AS since
                         FROM users WHERE id = %(u)s)
            SELECT s.since,
                   (SELECT count(*)::int FROM worklog_tasks w
                     WHERE w.assigned_by = %(u)s AND w.status = 'done' AND w.assigner_notified_at > s.since) AS done,
                   (SELECT count(*)::int FROM ({_OPEN_RETURNS} AND a.created_at > s.since) x) AS returned
              FROM s""", {"u": uid, "d": NEWS_FIRST_DAYS})
    if not row or not (row["done"] or row["returned"]):
        return None
    return row


@router.post("/news/seen")
def news_seen(user=Depends(require_assigner_csrf)):
    """O aviso do Hoje foi visto ("Entendi", "Ver" ou o X): o próximo conta daqui."""
    db.execute("UPDATE users SET assign_news_seen_at = now() WHERE id = %s", (user["user_id"],))
    return {"ok": True}
