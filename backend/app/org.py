"""Admin › "Para empresas e instituições": opções globais da instância, todas
desligadas por padrão (o padrão é o organizador pessoal). sql/036.

  team_visibility   'self' (cada pessoa escolhe) | 'managers' (visível para quem gerencia; visibility.py)
  assign_receive    'self' (cada pessoa escolhe) | 'all' (todos recebem de quem atribui; assignable.py, sql/041)
  identity_managed  nome e e-mail definidos pela administração (a Conta só mostra)
  invite_request_on  oferece "Solicitar convite" na tela de login (opt-in, sql/042; a
                    antiga invite_request_off, sql/037, ficou sem uso)
  privacy_url       endereço da política de privacidade (login, Conta, convite; sql/042)
  ticket_url        endereço do sistema de chamados da instância ({id} = o número; sql/037);
                    vazio = cada pessoa usa o seu (users.ticket_url)

O tour do primeiro acesso é obrigatório para toda conta nova (decisão do dono,
01/11): deixou de ser opção. A coluna app_settings.tour_required fica no banco
(sem uso); contas que já existiam têm tour_first_access=false e nunca são forçadas.
"""
from fastapi import HTTPException

from . import db

DEFAULTS = {"team_visibility": "self", "assign_receive": "self", "identity_managed": False, "invite_request_on": False,
            "ticket_url": None, "privacy_url": None}

IDENTITY_LOCKED = "Nesta instância do Nexus, nome e e-mail são definidos pela administração. Para mudar, fale com quem administra."
VISIBILITY_LOCKED = ("Nesta instância do Nexus, quem gerencia a equipe vê as tarefas de todos "
                     "(definido pela administração).")
ASSIGN_LOCKED = ("Nesta instância do Nexus, todos recebem tarefas de quem atribui "
                 "(definido pela administração).")


def get() -> dict:
    r = db.query_one("""SELECT team_visibility, team_visibility_since, assign_receive, assign_receive_since,
                               identity_managed, invite_request_on, ticket_url, privacy_url
                          FROM app_settings WHERE id = 1""")
    return {**DEFAULTS, "team_visibility_since": None, "assign_receive_since": None, **(r or {})}


def identity_managed() -> bool:
    return bool(get()["identity_managed"])


def ensure_identity_editable() -> None:
    """Nome/e-mail pela própria pessoa: 403 com o motivo quando a administração define."""
    if identity_managed():
        raise HTTPException(status_code=403, detail=IDENTITY_LOCKED)


def for_user(user_id: int) -> dict:
    """O que a sessão precisa saber (GET /auth/me): as opções e o que vale para esta pessoa."""
    o = get()
    u = db.query_one("""SELECT tour_done_at, tour_first_access, visibility_notice_at, assign_notice_at, created_at, ticket_url,
                               EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = users.id AND r.role = 'user') AS is_user
                          FROM users WHERE id = %s""", (user_id,)) or {}
    managed = o["team_visibility"] == "managers"
    since = o["team_visibility_since"]
    notice = bool(managed and u.get("is_user") and since
                  and (u.get("visibility_notice_at") is None or u["visibility_notice_at"] < since))
    a_since = o["assign_receive_since"]
    a_notice = bool(o["assign_receive"] == "all" and u.get("is_user") and a_since
                    and (u.get("assign_notice_at") is None or u["assign_notice_at"] < a_since))
    pending = db.query_one(
        """SELECT new_email FROM auth_links WHERE user_id = %s AND kind = 'email'
              AND used_at IS NULL AND expires_at > now() ORDER BY id DESC LIMIT 1""", (user_id,))
    return {
        "org": {"team_visibility": o["team_visibility"], "assign_receive": o["assign_receive"],
                "identity_managed": o["identity_managed"]},
        # Primeiro acesso de conta nova: o tour é obrigatório (sem "Pular" até concluir).
        "tour_required": bool(u.get("tour_first_access") and u.get("tour_done_at") is None),
        # Aviso único (com "Entendi") para quem já usava quando a visibilidade foi ligada.
        "visibility_notice": notice,
        # Aviso único para quem já usava quando "Todos recebem de quem atribui" foi ligado.
        "assign_notice": a_notice,
        "email_pending": pending["new_email"] if pending else None,
        # Endereço do sistema de chamados: o da instância (Admin › Para empresas), se
        # houver, vale para todos (a Conta mostra travado); senão, o da pessoa.
        "ticket_url": o["ticket_url"] or u.get("ticket_url"),
        "ticket_url_managed": bool(o["ticket_url"]),
        "privacy_url": o["privacy_url"],  # link na Conta (nulo = a instância não definiu)
    }
