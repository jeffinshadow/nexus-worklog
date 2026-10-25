"""Admin: contas (convite, senha), permissões e configurações gerais.

Ver os registros e relatórios das pessoas saiu daqui: é do Visualizador de
tarefas (routers/viewer.py).
"""
from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db, people, roles
from ..deps import require_admin, require_admin_csrf
from ..schemas import AppSettingsIn, DeleteUserIn, InviteIn, RolesIn
from ..security import generate_temp_password, hash_password, revoke_access

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _ensure_user(user_id: int) -> dict:
    row = db.query_one("SELECT id, email FROM users WHERE id = %s", (user_id,))
    if not row:
        raise HTTPException(status_code=404, detail="usuario nao encontrado")
    return row


@router.get("/users")
def list_users(admin=Depends(require_admin)):
    rows = db.query_all(
        f"""SELECT u.id, u.email, u.role, u.created_at, u.accepts_assignments_at, {roles.ROLES_SQL}
              FROM users u ORDER BY lower(u.email)""")
    return [{**r, **people.profile(r["id"])} for r in rows]


@router.post("/users", status_code=201)
def invite_user(data: InviteIn, admin=Depends(require_admin_csrf)):
    """Cria a conta de um convidado com senha temporaria (mostrada uma unica vez
    ao admin). O convidado troca a senha no primeiro login, como no reset.
    Nasce com o papel Usuário; os outros se dão em Permissões."""
    email = data.email.lower()
    if db.query_one("SELECT 1 FROM users WHERE email = %s", (email,)):
        raise HTTPException(status_code=409, detail="email ja cadastrado")
    temp = generate_temp_password()
    db.execute(
        """INSERT INTO users (email, password_hash, role, must_change_password)
           VALUES (%s, %s, 'user', true)""",
        (email, hash_password(temp)),
    )
    novo = db.query_one("SELECT id FROM users WHERE email = %s", (email,))
    roles.grant(novo["id"], ["user"])
    audit.record({**admin, "actor": "admin"}, "user.invite", "user", novo["id"],
                 after={"email": email, "by": admin["email"]}, user_id=novo["id"])
    return {"email": email, "temp_password": temp}


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
        "UPDATE users SET password_hash = %s, must_change_password = true WHERE id = %s",
        (hash_password(temp), user_id),
    )
    # Encerra TODAS as sessoes do alvo e corta os acessos que nao dependem da
    # senha (conta comprometida ou pessoa que saiu): chaves de API e o link
    # do calendario. Ele so volta com a senha temporaria.
    db.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
    revoke_access(user_id)
    audit.record({**admin, "actor": "admin"}, "user.reset_password", "password", user_id,
                 after={"by": admin["email"]}, user_id=user_id)
    return {"email": target["email"], "temp_password": temp}
