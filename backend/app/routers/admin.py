"""Admin: contas (convite, senha), permissões e configurações gerais.

Ver os registros e relatórios das pessoas saiu daqui: é do Visualizador de
tarefas (routers/viewer.py).
"""

import logging
import threading
import unicodedata
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException

from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from .. import audit, db, links, mailer, org, people, push, roles, teams
from ..deps import require_admin, require_admin_csrf
from ..schemas import (AdminProfileIn, AppSettingsIn, BlockUserIn, DeleteUserIn, InviteIn, OrgIn, ResetPasswordIn,
                       RolesIn)
from ..security import generate_temp_password, hash_password, revoke_access
from ..services import default_project

router = APIRouter(prefix="/api/admin", tags=["admin"])
log = logging.getLogger("uvicorn.error")


def _send_quiet(to: str, mail) -> None:
    try:
        mailer.send(to, mail.subject, mail.text(), mail.html())
    except Exception as e:  # noqa: BLE001 — a ação já foi feita; o e-mail é aviso
        log.warning("aviso por e-mail para %s falhou: %s", to, e)


def _spawn(to: str, mail) -> None:
    """Envio fora da requisição (o SMTP pode levar segundos), como na atribuição."""
    threading.Thread(target=_send_quiet, args=(to, mail), daemon=True).start()


def _ensure_user(user_id: int) -> dict:
    row = db.query_one("SELECT id, email FROM users WHERE id = %s", (user_id,))
    if not row:
        raise HTTPException(status_code=404, detail="usuário não encontrado")
    return row


def _sort_key(name: str) -> str:
    """Ordem alfabética sem acento e sem caixa (Álvaro junto de Alice)."""
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()


@router.get("/users")
def list_users(admin=Depends(require_admin)):
    """Contas em ordem de nome (o que a linha mostra), com o último acesso
    (`last_seen_at`: entrar ou usar o app; nulo = nunca entrou), a criação e
    quantas tarefas abertas cada uma tem (`open_tasks`, para transferir)."""
    rows = db.query_all(
        f"""SELECT u.id, u.email, u.role, u.created_at, u.accepts_assignments_at, u.invite_pending,
                   u.viewers_allowed, u.blocked_at, u.last_seen_at,
                   (SELECT count(*) FROM worklog_tasks w WHERE w.user_id = u.id AND w.status <> 'done')::int AS open_tasks,
                   -- convite pendente cujo link já venceu: o admin reenvia
                   (u.invite_pending AND NOT EXISTS (
                       SELECT 1 FROM auth_links l WHERE l.user_id = u.id AND l.kind = 'invite'
                          AND l.used_at IS NULL AND l.expires_at > now())) AS invite_expired,
                   {roles.ROLES_SQL},
                   -- equipes ativas (sql/043): coluna e filtro em Admin › Contas
                   COALESCE((SELECT json_agg(json_build_object('id', t.id, 'name', t.name) ORDER BY lower(t.name))
                               FROM teams t JOIN team_members m ON m.team_id = t.id
                              WHERE m.user_id = u.id AND t.archived_at IS NULL), '[]'::json) AS teams,
                   (u.id IS NOT DISTINCT FROM (SELECT s.master_user_id FROM app_settings s WHERE s.id = 1)) AS is_master
              FROM users u""")
    out = [{**r, **people.profile(r["id"])} for r in rows]
    out.sort(key=lambda r: (_sort_key(r["name"] or r["email"]), r["email"]))
    return out


@router.post("/users", status_code=201)
def invite_user(data: InviteIn, admin=Depends(require_admin_csrf)):
    """Cria a conta de um convidado, com o nome (vale até o primeiro acesso; no
    tour a pessoa confirma ou ajusta) e os papéis escolhidos ali (padrão: só
    Usuário; mudam depois em Papéis…).

    Com e-mail configurado: convite por link (vale 7 dias, uso único), mandado
    por e-mail e mostrado ao admin para copiar; a pessoa cria a própria senha.
    Sem e-mail: senha temporária (mostrada uma única vez ao admin), trocada no
    primeiro login, como no reset."""
    email = data.email.lower()
    if db.query_one("SELECT 1 FROM users WHERE email = %s", (email,)):
        raise HTTPException(status_code=409, detail="e-mail já cadastrado")
    by_link = mailer.configured()
    temp = generate_temp_password()
    nome = " ".join((data.display_name or "").split()) or None
    papeis = sorted(set(data.roles))
    from .equipes import check_teams, set_user_teams  # import tardio: equipes importa admin.role_notice
    equipes = check_teams(data.team_ids)
    db.execute(
        """INSERT INTO users (email, password_hash, role, must_change_password, invite_pending, display_name)
           VALUES (%s, %s, 'user', %s, %s, %s)""",
        # no convite por link a senha é aleatória e ninguém a vê: só o link entra
        (email, hash_password(generate_temp_password(32) if by_link else temp), not by_link, by_link, nome),
    )
    novo = db.query_one("SELECT id FROM users WHERE email = %s", (email,))
    roles.grant(novo["id"], papeis)
    if equipes:
        set_user_teams(novo["id"], equipes)
    nomes_eq = [t["name"] for t in teams.of_user(novo["id"])]
    audit.record({**admin, "actor": "admin"}, "user.invite", "user", novo["id"],
                 after={"email": email, "by": admin["email"], "link": by_link, "display_name": nome, "roles": papeis,
                        **({"teams": nomes_eq} if nomes_eq else {})},
                 user_id=novo["id"])
    if not by_link:
        return {"email": email, "temp_password": temp, "display_name": nome, "roles": papeis, "teams": nomes_eq}
    return {**_send_invite(novo["id"], email, admin), "display_name": nome, "roles": papeis, "teams": nomes_eq}


def _invite_mail(email: str, by_name: str, link: str):
    from ..notify import Mail  # import tardio: notify importa rotas
    m = Mail("Convite para o Nexus Worklog", f"{by_name} convidou você para o Nexus",
             "O Nexus guarda o seu dia de trabalho: rotinas, tarefas e o tempo de cada uma, com relatório pronto. "
             "Crie a sua senha pelo botão abaixo. O convite vale por 7 dias e funciona uma vez só.")
    m.blocks = [("A sua conta", [email])]
    if privacy := org.get()["privacy_url"]:  # Admin › Para empresas
        m.blocks.append(("Privacidade", [f"Política de privacidade desta instância: {privacy}"]))
    m.link, m.absolute, m.button = link, True, "Aceitar o convite"
    m.reason, m.settings_tab = "Você recebe este e-mail porque um administrador do Nexus criou uma conta para você.", None
    return m


def _send_invite(uid: int, email: str, admin: dict) -> dict:
    """Link novo (o anterior deixa de valer) e o e-mail. O admin sempre recebe o
    link: se o e-mail não chegar, ele manda por outro canal."""
    link = links.url("invite", links.issue(uid, "invite"))
    try:
        m = _invite_mail(email, people.profile(admin["user_id"])["name"], link)
        mailer.send(email, m.subject, m.text(), m.html())
        return {"email": email, "invite_url": link, "emailed": True}
    except mailer.MailError as e:
        log.warning("convite para %s não foi por e-mail: %s", email, e)
        return {"email": email, "invite_url": link, "emailed": False}


@router.post("/users/{user_id}/invite")
def resend_invite(user_id: int, admin=Depends(require_admin_csrf)):
    """Reenvia o convite de quem ainda não entrou (link novo, o velho para de valer)."""
    target = _ensure_user(user_id)
    if not db.query_one("SELECT 1 FROM users WHERE id = %s AND invite_pending", (user_id,)):
        raise HTTPException(status_code=400, detail="essa conta já aceitou o convite")
    if not mailer.configured():
        raise HTTPException(status_code=400, detail="e-mail não configurado no servidor: use Redefinir senha")
    audit.record({**admin, "actor": "admin"}, "user.invite_resend", "user", user_id,
                 after={"email": target["email"], "by": admin["email"]}, user_id=user_id)
    return _send_invite(user_id, target["email"], admin)


@router.post("/users/{user_id}/cancel-invite")
def cancel_invite(user_id: int, admin=Depends(require_admin_csrf)):
    """Desfaz um convite que ainda não foi aceito: a conta (sem dados, a pessoa
    nunca entrou) sai e o link deixa de valer. Sem digitar o e-mail."""
    target = _ensure_user(user_id)
    if not db.query_one("SELECT 1 FROM users WHERE id = %s AND invite_pending", (user_id,)):
        raise HTTPException(status_code=400, detail="essa conta já aceitou o convite: para tirar, use Excluir conta")
    # Conta pendente com tarefas (transferidas antes desta regra, ou por outro
    # caminho): cancelar apagaria tudo junto. Recusa e indica o caminho com transferência.
    n = db.query_one("SELECT count(*)::int AS n FROM worklog_tasks WHERE user_id = %s", (user_id,))["n"]
    if n:
        raise HTTPException(status_code=409, detail=(
            f"essa conta tem {'1 tarefa' if n == 1 else f'{n} tarefas'}: use Excluir conta e passe "
            f"{'a tarefa' if n == 1 else 'as tarefas'} para outra pessoa"))
    if not roles.delete_account(user_id):
        raise HTTPException(status_code=400, detail="o sistema precisa de pelo menos um admin")
    # O pedido de convite que gerou a conta volta a ficar pendente (não fica "convidado"
    # com o convite cancelado): o admin decide de novo. Só se não houver outro aberto.
    db.execute(
        """UPDATE invite_requests SET status = 'pending', decided_at = NULL, decided_by = NULL
            WHERE id = (SELECT id FROM invite_requests WHERE lower(email) = lower(%(e)s) AND status = 'invited'
                         ORDER BY decided_at DESC NULLS LAST, id DESC LIMIT 1)
              AND NOT EXISTS (SELECT 1 FROM invite_requests WHERE lower(email) = lower(%(e)s) AND status = 'pending')""",
        {"e": target["email"]})
    audit.record({**admin, "actor": "admin"}, "user.invite_cancel", "user", user_id,
                 before={"email": target["email"]})
    return {"ok": True, "email": target["email"]}


@router.post("/users/{user_id}/block")
def block_user(user_id: int, data: BlockUserIn | None = None, admin=Depends(require_admin_csrf)):
    """Corta o acesso agora, sem apagar nada (celular perdido, pessoa de férias
    ou que saiu): senha trocada por uma que ninguém sabe, sessões, chaves de
    API, calendário, notificações e passkeys desligados, links de e-mail sem
    valor e "Esqueci a senha" sem efeito. Redefinir senha libera de novo.
    `transfer_to`: as tarefas abertas passam para essa pessoa (papel Usuário)."""
    if user_id == admin["user_id"]:
        raise HTTPException(status_code=400, detail="você não pode bloquear a sua própria conta")
    target = _ensure_user(user_id)
    if teams.is_master(user_id):
        raise HTTPException(status_code=400, detail=MASTER_LOCKED)
    if db.query_one("SELECT 1 FROM users WHERE id = %s AND invite_pending", (user_id,)):
        raise HTTPException(status_code=400, detail="o convite ainda não foi aceito: use Cancelar convite")
    dest = _receiver(user_id, data.transfer_to if data else None)
    db.execute("""UPDATE users SET password_hash = %s, must_change_password = true, blocked_at = now()
                   WHERE id = %s""", (hash_password(generate_temp_password(32)), user_id))
    _cut_access(user_id)
    db.execute("UPDATE auth_links SET used_at = now() WHERE user_id = %s AND used_at IS NULL", (user_id,))
    audit.record({**admin, "actor": "admin"}, "user.block", "user", user_id,
                 after={"by": admin["email"], "email": target["email"]}, user_id=user_id)
    moved = transfer_open_tasks(target, dest, admin) if dest else None
    return {"ok": True, "email": target["email"], "transferred": moved}


# ------------------------------------------------ transferir tarefas abertas --

def _receiver(src_id: int, to_id: int | None) -> dict | None:
    """Quem recebe as tarefas abertas de quem sai: outra conta com o papel
    Usuário, acesso liberado e que já entrou (convite pendente não recebe, a
    mesma regra do Atribuir; não precisa ter aceitado tarefas atribuídas: é
    decisão da administração). Validado ANTES de bloquear ou excluir."""
    if to_id is None:
        return None
    if to_id == src_id:
        raise HTTPException(status_code=400, detail="escolha outra pessoa para receber as tarefas")
    row = db.query_one(
        """SELECT u.id, u.email FROM users u
            WHERE u.id = %s AND u.blocked_at IS NULL AND NOT u.invite_pending
              AND EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'user')""", (to_id,))
    if not row:
        raise HTTPException(status_code=400, detail="quem recebe as tarefas precisa ter o papel Usuário, o acesso liberado e já ter entrado no Nexus")
    return row


def _transfer_mail(titles: list[str], from_name: str, by_name: str):
    from ..notify import Mail  # import tardio: notify importa rotas
    n = len(titles)
    if n > 1:
        m = Mail(f"{n} tarefas passaram para você", f"{by_name} transferiu para você as tarefas abertas de {from_name}",
                 "Elas já estão nas suas tarefas no Nexus, com as anotações, o checklist e as fotos.")
    else:
        m = Mail(f"Uma tarefa passou para você: {titles[0]}", f"{by_name} transferiu para você uma tarefa de {from_name}",
                 "Ela já está nas suas tarefas no Nexus, com as anotações, o checklist e as fotos.")
    m.block("Tarefas", titles, True)
    m.reason = "Você recebe este e-mail porque quem administra o Nexus transferiu tarefas para você."
    m.settings_tab = None
    m.link = "/#/tarefas"
    return m


def transfer_open_tasks(src: dict, dest: dict, admin: dict) -> dict:
    """Passa as tarefas abertas (não concluídas) de `src` para `dest`, numa
    gravação só: a tarefa muda de dono com as anotações, o checklist e as
    fotos; entra no projeto padrão de quem recebe (os projetos são de cada
    um); o tempo já registrado fica no registro de quem saiu (é trabalho dele).
    Cada tarefa vai ao histórico de quem recebe (worklog.transfer), e quem
    recebe é avisado como numa atribuição (e-mail e notificação no aparelho)."""
    rows = db.query_all(
        """WITH t AS (SELECT id FROM worklog_tasks WHERE user_id = %(src)s AND status <> 'done' FOR UPDATE),
                x AS (DELETE FROM worklog_task_projects WHERE task_id IN (SELECT id FROM t)),
                tm AS (DELETE FROM task_timers WHERE task_id IN (SELECT id FROM t)),
                n AS (UPDATE task_notes SET user_id = %(dst)s, external_ref = NULL WHERE task_id IN (SELECT id FROM t)),
                c AS (UPDATE task_checklist SET user_id = %(dst)s WHERE task_id IN (SELECT id FROM t)),
                f AS (UPDATE photos SET user_id = %(dst)s, external_ref = NULL WHERE task_id IN (SELECT id FROM t)),
                w AS (UPDATE worklog_tasks SET user_id = %(dst)s, project_id = %(p)s, objective_id = NULL,
                                               exec_position = NULL, external_ref = NULL
                       WHERE id IN (SELECT id FROM t) RETURNING id, title)
           SELECT id, title FROM w ORDER BY id""",
        {"src": src["id"], "dst": dest["id"], "p": default_project(dest["id"])})
    from_name = people.profile(src["id"])["name"]
    to_name = people.profile(dest["id"])["name"]
    by_name = people.profile(admin["user_id"])["name"]
    ctx = {**admin, "actor": "admin"}
    for r in rows:
        snap = audit.worklog_snapshot(r["id"], dest["id"])
        audit.record(ctx, "worklog.transfer", "worklog", r["id"],
                     after={**snap, "by": by_name, "from": from_name}, user_id=dest["id"])
    out = {"count": len(rows), "to": to_name, "to_id": dest["id"], "emailed": False}
    if not rows:
        return out
    audit.record(ctx, "user.transfer_tasks", "user", src["id"],
                 after={"from": src["email"], "to": dest["email"], "count": len(rows), "by": admin["email"],
                        "tasks": [r["id"] for r in rows]})
    titles = [r["title"] for r in rows]
    if mailer.configured():
        _spawn(dest["email"], _transfer_mail(titles, from_name, by_name))
        out["emailed"] = True
    threading.Thread(target=_push_transfer, args=(dest["id"], rows, from_name), daemon=True).start()
    return out


def _push_transfer(uid: int, rows: list[dict], from_name: str) -> None:
    """Notificação no aparelho como a de uma tarefa atribuída (a mesma preferência)."""
    try:
        p = push.prefs(uid)
        if not p["assigned"]:
            return
        one = len(rows) == 1
        title = f"Tarefa de {from_name} passou para você" if one else f"{len(rows)} tarefas de {from_name} passaram para você"
        url = f"/#/tarefas?id={rows[0]['id']}" if one else "/#/tarefas"
        push.send(uid, push._msg(title, rows[0]["title"] if one else "Abra o Nexus para ver.", url,
                                 f"transferidas-{rows[0]['id']}", "atribuida", p["hide_content"],
                                 "Tarefas passaram para você"), urgency="high", ttl=24 * 3600)
    except Exception:  # noqa: BLE001 — a transferência já foi feita; a notificação é aviso
        log.exception("notificação da transferência falhou")


def _cut_access(user_id: int) -> None:
    """Encerra TODAS as sessões e corta o que não depende da senha: chaves de
    API, link do calendário e passkeys (entrar sem senha derrubaria o corte)."""
    db.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
    revoke_access(user_id)
    db.execute("DELETE FROM webauthn_credentials WHERE user_id = %s", (user_id,))


@router.put("/users/{user_id}/roles")
def set_roles(user_id: int, data: RolesIn, admin=Depends(require_admin_csrf)):
    """Papéis da conta. O admin não tira o próprio papel de admin (não se
    tranca para fora) e o sistema nunca fica sem nenhum admin."""
    target = _ensure_user(user_id)
    before = roles.of(user_id)
    novos = sorted(set(data.roles))
    if user_id == admin["user_id"] and "admin" not in novos:
        raise HTTPException(status_code=400, detail="você não pode tirar o seu próprio papel de admin")
    if "admin" not in novos and teams.is_master(user_id):
        raise HTTPException(status_code=400, detail=MASTER_LOCKED)
    if "admin" in before and "admin" not in novos and roles.admins_count() <= 1:
        raise HTTPException(status_code=400, detail="o sistema precisa de pelo menos um admin")
    roles.replace(user_id, novos)
    notified = False
    if set(before) != set(novos):
        audit.record({**admin, "actor": "admin"}, "user.roles", "user", user_id,
                     before={"roles": before}, after={"roles": novos, "by": admin["email"], "email": target["email"]},
                     user_id=user_id)
        if user_id != admin["user_id"]:
            notified = role_notice(user_id, target["email"], set(novos) - set(before), set(before) - set(novos), admin)
    return {"id": user_id, "roles": novos, "notified": notified}


MASTER_LOCKED = ("essa conta é a do admin master: só ela mesma passa o papel para outro admin "
                 "(Admin › Equipes › Transferir), e depois disso dá para mudar")

# O que cada papel muda para a pessoa (aviso no app e no e-mail; mesma ordem do Admin).
ROLE_GAIN = {
    "user": ("Usuário", "Você passa a ter o seu próprio registro: Hoje, Tarefas, Rotinas e relatórios."),
    "admin": ("Admin", "Você administra o Nexus: convites, contas, papéis e configurações gerais (Admin, no menu)."),
    "assigner": ("Manda tarefas", "Você pode mandar tarefas para quem aceitou receber e acompanhar o que mandou."),
    "viewer": ("Vê a equipe", "Você vê, sem editar, o registro da equipe na tela Equipe."),
    # Não é um papel de user_roles: o aviso da transferência do master (routers/equipes.py) usa o mesmo aviso único.
    "master": ("Admin master", "Você é o admin master: com “Vê a equipe” e “Manda tarefas” ligados, vê e atribui para "
                               "todos, com ou sem equipe; as suas visualizações ficam no log de admin."),
}


def role_notice(uid: int, email: str, added: set, removed: set, admin: dict, mail: bool = True) -> bool:
    """Guarda o aviso único (o app mostra no próximo acesso, até "Entendi") e,
    com e-mail configurado, avisa por e-mail. Ganhou e perdeu de novo antes de
    ver = nada a dizer. Convite ainda não aceito ou conta bloqueada: nada (o
    tour e a liberação já explicam). Devolve se houve aviso."""
    u = db.query_one("SELECT invite_pending, blocked_at, role_notice FROM users WHERE id = %s", (uid,))
    if not u or u["invite_pending"] or u["blocked_at"]:
        return False
    old = u["role_notice"] or {}
    old_add, old_rem = set(old.get("added", [])), set(old.get("removed", []))
    add = (old_add - removed) | (added - old_rem)    # ganhou e perdeu antes de ver: some dos dois lados
    rem = (old_rem - added) | (removed - old_add)
    notice = {"added": [k for k in ROLE_GAIN if k in add], "removed": [k for k in ROLE_GAIN if k in rem]}
    db.execute("UPDATE users SET role_notice = %s WHERE id = %s",
               (Jsonb(notice) if (add or rem) else None, uid))
    if mail and mailer.configured():
        _spawn(email, _roles_mail(added, removed, people.profile(admin["user_id"])["name"]))
    return True


def _roles_mail(added: set, removed: set, by_name: str):
    from ..notify import Mail
    ganhou = [ROLE_GAIN[k][0] for k in ROLE_GAIN if k in added]
    perdeu = [ROLE_GAIN[k][0] for k in ROLE_GAIN if k in removed]
    nomes = lambda xs: " e ".join(f"“{n}”" for n in xs)  # noqa: E731
    if ganhou:
        m = Mail(f"Novo papel no Nexus: {', '.join(ganhou)}", f"{by_name} deu a você o papel {nomes(ganhou)}",
                 "Os seus papéis no Nexus mudaram. Na próxima vez que abrir o app, ele mostra o que mudou.")
    else:
        m = Mail(f"Papel retirado no Nexus: {', '.join(perdeu)}", f"{by_name} tirou o seu papel {nomes(perdeu)}",
                 "Os seus papéis no Nexus mudaram. Na próxima vez que abrir o app, ele mostra o que mudou.")
    for k in ROLE_GAIN:
        if k in added:
            m.blocks.append((f"Novo: {ROLE_GAIN[k][0]}", [ROLE_GAIN[k][1]]))
    for k in ROLE_GAIN:
        if k in removed:
            m.blocks.append((f"Retirado: {ROLE_GAIN[k][0]}",
                             ["O que vinha com esse papel sai do menu. Os seus dados continuam guardados."]))
    m.reason, m.settings_tab = "Você recebe este e-mail porque quem administra o Nexus mudou os seus papéis.", None
    return m


@router.put("/users/{user_id}/profile")
def edit_profile(user_id: int, data: AdminProfileIn, admin=Depends(require_admin_csrf)):
    """Admin › pessoa › Editar nome e e-mail (o caminho para mudar quando a
    opção "Nome e e-mail definidos pela administração" está ligada; vale também
    com ela desligada, para corrigir um convite). Campo ausente = mantém.
    Trocar o e-mail avisa o endereço antigo e o novo (conta que já entrou). Fica
    no log de admin (histórico de quem alterou)."""
    target = db.query_one("SELECT id, email, display_name, invite_pending FROM users WHERE id = %s", (user_id,))
    if not target:
        raise HTTPException(status_code=404, detail="usuário não encontrado")
    sent = data.model_fields_set
    before = {"email": target["email"], "display_name": target["display_name"]}
    after = {}
    if "display_name" in sent:
        nome = " ".join((data.display_name or "").split()) or None
        if nome != target["display_name"]:
            db.execute("UPDATE users SET display_name = %s WHERE id = %s", (nome, user_id))
            after["display_name"] = nome
    new = data.email.lower() if "email" in sent and data.email else None
    if new and new != target["email"]:
        if db.query_one("SELECT 1 FROM users WHERE email = %s AND id <> %s", (new, user_id)):
            raise HTTPException(status_code=409, detail="esse e-mail já é de outra conta")
        try:
            db.execute("UPDATE users SET email = %s WHERE id = %s", (new, user_id))
        except UniqueViolation as e:
            raise HTTPException(status_code=409, detail="esse e-mail já é de outra conta") from e
        links.cancel(user_id, "email")  # um pedido de troca da própria pessoa deixa de valer
        links.cancel(user_id, "reset")  # link de nova senha mandado ao endereço antigo também
        after["email"] = new
        if not target["invite_pending"]:  # quem nunca entrou recebe o convite (reenviar), não um aviso
            from .auth import notify_email_change  # import tardio: auth importa outras rotas
            notify_email_change(target["email"], new, by_admin=True)
    if after:
        audit.record({**admin, "actor": "admin"}, "user.profile", "user", user_id, before=before,
                     after={**after, "by": admin["email"], "target": after.get("email", target["email"])})
    row = db.query_one("SELECT id, email FROM users WHERE id = %s", (user_id,))
    return {**row, **people.profile(user_id)}


@router.post("/users/{user_id}/delete")
def delete_user(user_id: int, data: DeleteUserIn, admin=Depends(require_admin_csrf)):
    """Exclui a conta e TODOS os dados dela (tarefas, rotinas, tempo, chaves,
    histórico: ON DELETE CASCADE). Sem volta: o admin confirma digitando o
    e-mail. Tarefas que essa pessoa atribuiu ficam com quem recebeu.
    `transfer_to`: antes de excluir, as tarefas abertas passam para essa pessoa."""
    if user_id == admin["user_id"]:
        raise HTTPException(status_code=400, detail="para a sua própria conta, use Configurações > Conta")
    target = _ensure_user(user_id)
    if data.confirm_email.strip().lower() != target["email"]:
        raise HTTPException(status_code=400, detail="confirme digitando o e-mail da conta")
    if teams.is_master(user_id):
        raise HTTPException(status_code=400, detail=MASTER_LOCKED)
    if "admin" in roles.of(user_id) and roles.admins_count() <= 1:
        raise HTTPException(status_code=400, detail="o sistema precisa de pelo menos um admin")
    dest = _receiver(user_id, data.transfer_to)
    moved = transfer_open_tasks(target, dest, admin) if dest else None
    counts = account_counts(user_id)
    if not roles.delete_account(user_id):
        raise HTTPException(status_code=400, detail="o sistema precisa de pelo menos um admin")
    # Fica no histórico de quem excluiu (o do excluído some junto com a conta).
    audit.record({**admin, "actor": "admin"}, "user.delete", "user", user_id,
                 before={"email": target["email"], **counts, **({"transferred": moved["count"]} if moved else {})})
    return {"ok": True, "email": target["email"], **counts, "transferred": moved}


def account_counts(user_id: int) -> dict:
    return db.query_one(
        """SELECT (SELECT count(*) FROM worklog_tasks WHERE user_id = %(u)s)::int AS tasks,
                  (SELECT count(*) FROM recurring_tasks WHERE user_id = %(u)s)::int AS routines,
                  (SELECT count(*) FROM time_entries WHERE user_id = %(u)s)::int AS time_entries""",
        {"u": user_id})


@router.get("/settings")
def get_settings(admin=Depends(require_admin)):
    return db.query_one("SELECT retro_days, support_contact, photo_quota_mb FROM app_settings WHERE id = 1")


@router.put("/settings")
def put_settings(data: AppSettingsIn, admin=Depends(require_admin_csrf)):
    before = get_settings(admin)
    contact = " ".join((data.support_contact or "").split()) or None
    db.execute("""UPDATE app_settings SET retro_days = %s, support_contact = %s, updated_at = now(),
                         photo_quota_mb = COALESCE(%s, photo_quota_mb) WHERE id = 1""",
               (data.retro_days, contact, data.photo_quota_mb))
    audit.record({**admin, "actor": "admin"}, "app.settings", "app_settings", 1,
                 before=before, after=data.model_dump())
    return get_settings(admin)


@router.get("/org")
def get_org(admin=Depends(require_admin)):
    """Para empresas e instituições: as opções globais (todas desligadas por padrão).
    `mail_configured`: sem e-mail, o pedido de convite nunca aparece (a opção só explica)."""
    o = org.get()
    return {"team_visibility": o["team_visibility"], "team_visibility_since": o["team_visibility_since"],
            "assign_receive": o["assign_receive"], "assign_receive_since": o["assign_receive_since"],
            "identity_managed": o["identity_managed"], "invite_request_on": o["invite_request_on"],
            "ticket_url": o["ticket_url"], "privacy_url": o["privacy_url"], "mail_configured": mailer.configured()}


@router.put("/org")
def put_org(data: OrgIn, admin=Depends(require_admin_csrf)):
    """Liga/desliga cada opção (campo ausente = mantém). Cada mudança fica no
    log de admin (quem e quando). Visibilidade e receber tarefas: as escolhas
    de cada pessoa ficam guardadas; voltar para "Cada pessoa escolhe" as devolve."""
    before = org.get()
    ctx = {**admin, "actor": "admin"}
    if data.team_visibility is not None and data.team_visibility != before["team_visibility"]:
        db.execute("""UPDATE app_settings SET team_visibility = %s, updated_at = now(),
                             team_visibility_since = CASE WHEN %s = 'managers' THEN now() ELSE team_visibility_since END
                       WHERE id = 1""", (data.team_visibility, data.team_visibility))
        # Quem mudou já sabe: o aviso único da mudança não aparece para o próprio admin.
        db.execute("UPDATE users SET visibility_notice_at = now() WHERE id = %s", (admin["user_id"],))
        audit.record(ctx, "app.team_visibility", "app_settings", 1, before={"team_visibility": before["team_visibility"]},
                     after={"team_visibility": data.team_visibility, "by": admin["email"]})
    if data.assign_receive is not None and data.assign_receive != before["assign_receive"]:
        db.execute("""UPDATE app_settings SET assign_receive = %s, updated_at = now(),
                             assign_receive_since = CASE WHEN %s = 'all' THEN now() ELSE assign_receive_since END
                       WHERE id = 1""", (data.assign_receive, data.assign_receive))
        db.execute("UPDATE users SET assign_notice_at = now() WHERE id = %s", (admin["user_id"],))
        audit.record(ctx, "app.assign_receive", "app_settings", 1, before={"assign_receive": before["assign_receive"]},
                     after={"assign_receive": data.assign_receive, "by": admin["email"]})
    for key in ("identity_managed", "invite_request_on"):
        val = getattr(data, key)
        if val is not None and val != before[key]:
            db.execute(f"UPDATE app_settings SET {key} = %s, updated_at = now() WHERE id = 1", (val,))
            audit.record(ctx, f"app.{key}", "app_settings", 1, before={key: before[key]},
                         after={key: val, "by": admin["email"]})
    # Endereços (chamados; política de privacidade): valem para todos; enviado vazio ou null = tira.
    for key in ("ticket_url", "privacy_url"):
        if key in data.model_fields_set:
            url = (getattr(data, key) or "").strip() or None
            if url != before[key]:
                db.execute(f"UPDATE app_settings SET {key} = %s, updated_at = now() WHERE id = 1", (url,))
                audit.record(ctx, f"app.{key}", "app_settings", 1, before={key: before[key]},
                             after={key: url, "by": admin["email"]})
    return get_org(admin)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, data: ResetPasswordIn | None = None, admin=Depends(require_admin_csrf)):
    """Redefine a senha de outra conta (e libera uma conta bloqueada). A senha
    atual deixa de valer, e as sessões, chaves de API, calendário e passkeys
    do alvo são cortados. Duas formas:

    - `temp` (padrão): senha temporária mostrada uma única vez ao admin; a
      pessoa troca no próximo login.
    - `link` (só com e-mail configurado): o link de nova senha do "Esqueci a
      senha" vai para o e-mail da pessoa (vale 24 horas, uso único); o admin
      também recebe o link, para mandar por outro canal se o e-mail falhar.

    Para a própria conta, use a troca normal."""
    if user_id == admin["user_id"]:
        raise HTTPException(status_code=400, detail="use a troca de senha da sua própria conta")
    target = _ensure_user(user_id)
    method = data.method if data else "temp"
    if method == "link" and not mailer.configured():
        raise HTTPException(status_code=400, detail="e-mail não configurado no servidor: use a senha temporária")
    was_blocked = bool(db.query_one("SELECT 1 FROM users WHERE id = %s AND blocked_at IS NOT NULL", (user_id,)))

    temp = generate_temp_password()
    # Pelo link, a senha vira uma que ninguém sabe até a pessoa criar a dela.
    secret = generate_temp_password(32) if method == "link" else temp
    # Também libera uma conta bloqueada (blocked_at volta a vazio).
    db.execute(
        """UPDATE users SET password_hash = %s, must_change_password = %s, invite_pending = false,
                            blocked_at = NULL WHERE id = %s""",
        (hash_password(secret), method == "temp", user_id),
    )
    # Conta comprometida ou pessoa que saiu: ela só volta com a senha temporária (ou o link).
    _cut_access(user_id)
    audit.record({**admin, "actor": "admin"}, "user.reset_password", "password", user_id,
                 after={"by": admin["email"], "method": method, **({"unblocked": True} if was_blocked else {})},
                 user_id=user_id)
    if method == "temp":
        return {"email": target["email"], "temp_password": temp, "method": "temp"}
    link = links.url("reset", links.issue(user_id, "reset", ttl=ADMIN_RESET_TTL))
    try:
        m = _admin_reset_mail(target["email"], people.profile(admin["user_id"])["name"], link, was_blocked)
        mailer.send(target["email"], m.subject, m.text(), m.html())
        emailed = True
    except mailer.MailError as e:
        log.warning("link de nova senha para a conta %s não foi por e-mail: %s", user_id, e)
        emailed = False
    return {"email": target["email"], "reset_url": link, "emailed": emailed, "method": "link"}


ADMIN_RESET_TTL = timedelta(hours=24)  # o "Esqueci a senha" vale 1 hora; o mandado pelo admin, um dia


def _admin_reset_mail(email: str, by_name: str, link: str, unblocked: bool):
    from ..notify import Mail
    m = Mail("Crie uma senha nova para o Nexus",
             "O seu acesso foi liberado" if unblocked else "A sua senha do Nexus foi redefinida",
             f"{by_name}, que administra o Nexus, {'liberou o seu acesso' if unblocked else 'redefiniu a sua senha'}. "
             "Crie uma senha nova pelo botão abaixo. O link vale por 24 horas e funciona uma vez só.")
    m.blocks = [("A sua conta", [email]),
                ("A senha antiga não vale mais", ["Os aparelhos conectados saíram da conta; entre de novo com a senha nova."])]
    m.link, m.absolute, m.button = link, True, "Criar uma senha nova"
    m.reason, m.settings_tab = "Você recebe este e-mail porque um administrador do Nexus redefiniu a sua senha.", None
    return m
