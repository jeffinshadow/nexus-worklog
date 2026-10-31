"""Admin: contas (convite, senha), permissões e configurações gerais.

Ver os registros e relatórios das pessoas saiu daqui: é do Visualizador de
tarefas (routers/viewer.py).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db, links, mailer, people, roles
from ..deps import require_admin, require_admin_csrf
from ..schemas import AppSettingsIn, DeleteUserIn, InviteIn, RolesIn
from ..security import generate_temp_password, hash_password, revoke_access

router = APIRouter(prefix="/api/admin", tags=["admin"])
log = logging.getLogger("uvicorn.error")


def _ensure_user(user_id: int) -> dict:
    row = db.query_one("SELECT id, email FROM users WHERE id = %s", (user_id,))
    if not row:
        raise HTTPException(status_code=404, detail="usuário não encontrado")
    return row


@router.get("/users")
def list_users(admin=Depends(require_admin)):
    rows = db.query_all(
        f"""SELECT u.id, u.email, u.role, u.created_at, u.accepts_assignments_at, u.invite_pending,
                   -- convite pendente cujo link já venceu: o admin reenvia
                   (u.invite_pending AND NOT EXISTS (
                       SELECT 1 FROM auth_links l WHERE l.user_id = u.id AND l.kind = 'invite'
                          AND l.used_at IS NULL AND l.expires_at > now())) AS invite_expired,
                   {roles.ROLES_SQL}
              FROM users u ORDER BY lower(u.email)""")
    return [{**r, **people.profile(r["id"])} for r in rows]


@router.post("/users", status_code=201)
def invite_user(data: InviteIn, admin=Depends(require_admin_csrf)):
    """Cria a conta de um convidado. Nasce com o papel Usuário; os outros se
    dão em Permissões.

    Com e-mail configurado: convite por link (vale 7 dias, uso único), mandado
    por e-mail e mostrado ao admin para copiar; a pessoa cria a própria senha.
    Sem e-mail: senha temporária (mostrada uma única vez ao admin), trocada no
    primeiro login, como no reset."""
    email = data.email.lower()
    if db.query_one("SELECT 1 FROM users WHERE email = %s", (email,)):
        raise HTTPException(status_code=409, detail="e-mail já cadastrado")
    by_link = mailer.configured()
    temp = generate_temp_password()
    db.execute(
        """INSERT INTO users (email, password_hash, role, must_change_password, invite_pending)
           VALUES (%s, %s, 'user', %s, %s)""",
        # no convite por link a senha é aleatória e ninguém a vê: só o link entra
        (email, hash_password(generate_temp_password(32) if by_link else temp), not by_link, by_link),
    )
    novo = db.query_one("SELECT id FROM users WHERE email = %s", (email,))
    roles.grant(novo["id"], ["user"])
    audit.record({**admin, "actor": "admin"}, "user.invite", "user", novo["id"],
                 after={"email": email, "by": admin["email"], "link": by_link}, user_id=novo["id"])
    if not by_link:
        return {"email": email, "temp_password": temp}
    return _send_invite(novo["id"], email, admin)


def _invite_mail(email: str, by_name: str, link: str):
    from ..notify import Mail  # import tardio: notify importa rotas
    m = Mail("Convite para o Nexus Worklog", f"{by_name} convidou você para o Nexus",
             "O Nexus guarda o seu dia de trabalho: rotinas, tarefas e o tempo de cada uma, com relatório pronto. "
             "Crie a sua senha pelo botão abaixo. O convite vale por 7 dias e funciona uma vez só.")
    m.blocks = [("A sua conta", [email])]
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


@router.put("/users/{user_id}/roles")
def set_roles(user_id: int, data: RolesIn, admin=Depends(require_admin_csrf)):
    """Papéis da conta. O admin não tira o próprio papel de admin (não se
    tranca para fora) e o sistema nunca fica sem nenhum admin."""
    target = _ensure_user(user_id)
    before = roles.of(user_id)
    novos = sorted(set(data.roles))
    if user_id == admin["user_id"] and "admin" not in novos:
        raise HTTPException(status_code=400, detail="você não pode tirar o seu próprio papel de admin")
    if "admin" in before and "admin" not in novos and roles.admins_count() <= 1:
        raise HTTPException(status_code=400, detail="o sistema precisa de pelo menos um admin")
    roles.replace(user_id, novos)
    if set(before) != set(novos):
        audit.record({**admin, "actor": "admin"}, "user.roles", "user", user_id,
                     before={"roles": before}, after={"roles": novos, "by": admin["email"], "email": target["email"]},
                     user_id=user_id)
    return {"id": user_id, "roles": novos}


@router.post("/users/{user_id}/delete")
def delete_user(user_id: int, data: DeleteUserIn, admin=Depends(require_admin_csrf)):
    """Exclui a conta e TODOS os dados dela (tarefas, rotinas, tempo, chaves,
    histórico: ON DELETE CASCADE). Sem volta: o admin confirma digitando o
    e-mail. Tarefas que essa pessoa atribuiu ficam com quem recebeu."""
    if user_id == admin["user_id"]:
        raise HTTPException(status_code=400, detail="para a sua própria conta, use Configurações > Conta")
    target = _ensure_user(user_id)
    if data.confirm_email.strip().lower() != target["email"]:
        raise HTTPException(status_code=400, detail="confirme digitando o e-mail da conta")
    if "admin" in roles.of(user_id) and roles.admins_count() <= 1:
        raise HTTPException(status_code=400, detail="o sistema precisa de pelo menos um admin")
    counts = account_counts(user_id)
    if not roles.delete_account(user_id):
        raise HTTPException(status_code=400, detail="o sistema precisa de pelo menos um admin")
    # Fica no histórico de quem excluiu (o do excluído some junto com a conta).
    audit.record({**admin, "actor": "admin"}, "user.delete", "user", user_id,
                 before={"email": target["email"], **counts})
    return {"ok": True, "email": target["email"], **counts}


def account_counts(user_id: int) -> dict:
    return db.query_one(
        """SELECT (SELECT count(*) FROM worklog_tasks WHERE user_id = %(u)s)::int AS tasks,
                  (SELECT count(*) FROM recurring_tasks WHERE user_id = %(u)s)::int AS routines,
                  (SELECT count(*) FROM time_entries WHERE user_id = %(u)s)::int AS time_entries""",
        {"u": user_id})


@router.get("/settings")
def get_settings(admin=Depends(require_admin)):
    return db.query_one("SELECT retro_days, support_contact FROM app_settings WHERE id = 1")


@router.put("/settings")
def put_settings(data: AppSettingsIn, admin=Depends(require_admin_csrf)):
    before = get_settings(admin)
    contact = " ".join((data.support_contact or "").split()) or None
    db.execute("UPDATE app_settings SET retro_days = %s, support_contact = %s, updated_at = now() WHERE id = 1",
               (data.retro_days, contact))
    audit.record({**admin, "actor": "admin"}, "app.settings", "app_settings", 1,
                 before=before, after=data.model_dump())
    return get_settings(admin)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, admin=Depends(require_admin_csrf)):
    """Redefine a senha de um usuario para uma temporaria gerada (mostrada uma
    unica vez ao admin). Forca troca no proximo login e encerra as sessoes do
    alvo. Sem envolvimento de e-mail. Para a propria conta, use a troca normal."""
    if user_id == admin["user_id"]:
        raise HTTPException(status_code=400, detail="use a troca de senha da sua propria conta")
    target = _ensure_user(user_id)

    temp = generate_temp_password()
    db.execute(
        "UPDATE users SET password_hash = %s, must_change_password = true, invite_pending = false WHERE id = %s",
        (hash_password(temp), user_id),
    )
    # Encerra TODAS as sessoes do alvo e corta os acessos que nao dependem da
    # senha (conta comprometida ou pessoa que saiu): chaves de API e o link
    # do calendario. Ele so volta com a senha temporaria.
    db.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
    revoke_access(user_id)
    # As passkeys também: entrar sem senha numa conta que o admin bloqueou derrubaria o reset.
    db.execute("DELETE FROM webauthn_credentials WHERE user_id = %s", (user_id,))
    audit.record({**admin, "actor": "admin"}, "user.reset_password", "password", user_id,
                 after={"by": admin["email"]}, user_id=user_id)
    return {"email": target["email"], "temp_password": temp}
