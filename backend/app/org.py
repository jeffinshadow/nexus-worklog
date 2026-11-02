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

Equipes (sql/043): "Para empresas" vale só para quem está em alguma equipe
(teams.company_applies). Sem equipe, a visibilidade gerenciada, "Todos recebem",
nome/e-mail pela administração e o endereço de chamados da instância NÃO se
aplicam à pessoa (volta a escolha dela, com os valores guardados). Instância sem
nenhuma equipe = vale para todos, como antes. Exceções globais (com ou sem
equipe): "Solicitar convite" na tela de login e a política de privacidade.

O tour do primeiro acesso é obrigatório para toda conta nova (decisão do dono,
01/11): deixou de ser opção. A coluna app_settings.tour_required fica no banco
(sem uso); contas que já existiam têm tour_first_access=false e nunca são forçadas.
"""
from fastapi import HTTPException

from . import db, teams

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


def identity_managed(user_id: int) -> bool:
    """Nome e e-mail desta pessoa são definidos pela administração (opção ligada e ela em equipe)."""
    return bool(get()["identity_managed"]) and teams.company_applies(user_id)


def ensure_identity_editable(user_id: int) -> None:
    """Nome/e-mail pela própria pessoa: 403 com o motivo quando a administração define."""
    if identity_managed(user_id):
        raise HTTPException(status_code=403, detail=IDENTITY_LOCKED)


def effective(user_id: int) -> dict:
    """As opções de "Para empresas" que valem para esta pessoa (sem equipe, com
    equipes na instância: nenhuma; o pedido de convite e a privacidade são globais)."""
    o = get()
    if teams.company_applies(user_id):
        return o
    return {**o, "team_visibility": "self", "assign_receive": "self", "identity_managed": False, "ticket_url": None}


def for_user(user_id: int) -> dict:
    """O que a sessão precisa saber (GET /auth/me): as opções e o que vale para esta pessoa."""
    o = effective(user_id)
    u = db.query_one("""SELECT tour_done_at, tour_first_access, visibility_notice_at, assign_notice_at, created_at, ticket_url,
                               EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = users.id AND r.role = 'user') AS is_user
                          FROM users WHERE id = %s""", (user_id,)) or {}
    managed = o["team_visibility"] == "managers"
    # Entrou numa equipe depois da mudança (sql/043): o aviso vale a partir da entrada.
    joined = teams.joined_at(user_id) if teams.any_active() else None
    since = max(x for x in (o["team_visibility_since"], joined) if x) if (o["team_visibility_since"] or joined) else None
    notice = bool(managed and u.get("is_user") and since
                  and (u.get("visibility_notice_at") is None or u["visibility_notice_at"] < since))
    a_since = max(x for x in (o["assign_receive_since"], joined) if x) if (o["assign_receive_since"] or joined) else None
    a_notice = bool(o["assign_receive"] == "all" and u.get("is_user") and a_since
                    and (u.get("assign_notice_at") is None or u["assign_notice_at"] < a_since))
    pending = db.query_one(
        """SELECT new_email FROM auth_links WHERE user_id = %s AND kind = 'email'
              AND used_at IS NULL AND expires_at > now() ORDER BY id DESC LIMIT 1""", (user_id,))
    return {
        # O que vale para ESTA pessoa (sem equipe, com equipes na instância: tudo "self").
        "org": {"team_visibility": o["team_visibility"], "assign_receive": o["assign_receive"],
                "identity_managed": o["identity_managed"]},
        # Equipes (sql/043): as da pessoa (só leitura na Conta), se a instância
        # tem equipes e se ela é o admin master.
        "teams": [t["name"] for t in teams.of_user(user_id)],
        "teams_on": teams.any_active(),
        "is_master": teams.is_master(user_id),
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
