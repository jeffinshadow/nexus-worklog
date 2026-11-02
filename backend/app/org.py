"""Admin › "Para empresas e instituições": opções globais da instância, todas
desligadas por padrão (o padrão é o organizador pessoal). sql/036.

  team_visibility   'self' (cada pessoa escolhe) | 'managers' (visível para quem gerencia; visibility.py)
  identity_managed  nome e e-mail definidos pela administração (a Conta só mostra)
  tour_required     tour obrigatório no primeiro acesso (sem "Pular" até concluir)
"""
from fastapi import HTTPException

from . import db

DEFAULTS = {"team_visibility": "self", "identity_managed": False, "tour_required": False}

IDENTITY_LOCKED = "Nesta instância do Nexus, nome e e-mail são definidos pela administração. Para mudar, fale com quem administra."
VISIBILITY_LOCKED = ("Nesta instância do Nexus, quem gerencia a equipe vê as tarefas de todos "
                     "(definido pela administração).")


def get() -> dict:
    r = db.query_one("""SELECT team_visibility, team_visibility_since, identity_managed, tour_required
                          FROM app_settings WHERE id = 1""")
    return {**DEFAULTS, "team_visibility_since": None, **(r or {})}


def identity_managed() -> bool:
    return bool(get()["identity_managed"])


def ensure_identity_editable() -> None:
    """Nome/e-mail pela própria pessoa: 403 com o motivo quando a administração define."""
    if identity_managed():
        raise HTTPException(status_code=403, detail=IDENTITY_LOCKED)


def for_user(user_id: int) -> dict:
    """O que a sessão precisa saber (GET /auth/me): as opções e o que vale para esta pessoa."""
    o = get()
    u = db.query_one("""SELECT tour_done_at, tour_first_access, visibility_notice_at, created_at,
                               EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = users.id AND r.role = 'user') AS is_user
                          FROM users WHERE id = %s""", (user_id,)) or {}
    managed = o["team_visibility"] == "managers"
    since = o["team_visibility_since"]
    notice = bool(managed and u.get("is_user") and since
                  and (u.get("visibility_notice_at") is None or u["visibility_notice_at"] < since))
    pending = db.query_one(
        """SELECT new_email FROM auth_links WHERE user_id = %s AND kind = 'email'
              AND used_at IS NULL AND expires_at > now() ORDER BY id DESC LIMIT 1""", (user_id,))
    return {
        "org": {"team_visibility": o["team_visibility"], "identity_managed": o["identity_managed"],
                "tour_required": o["tour_required"]},
        # Primeiro acesso com o tour obrigatório: sem "Pular" até concluir.
        "tour_required": bool(o["tour_required"] and u.get("tour_first_access") and u.get("tour_done_at") is None),
        # Aviso único (com "Entendi") para quem já usava quando a visibilidade foi ligada.
        "visibility_notice": notice,
        "email_pending": pending["new_email"] if pending else None,
    }
