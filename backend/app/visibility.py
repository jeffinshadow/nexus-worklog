"""Quem pode ser visto por quem acompanha a equipe (papel viewer).

UM lugar só decide: as rotas do visualizador (routers/viewer.py: lista, quadro,
mês, PDF, painel da Equipe e "Precisa de atenção"), as horas da equipe em CSV,
as fotos, a foto de perfil e a transparência da Conta chamam
visible_sql()/can_see(). A regra, para quem vê (`viewer`): o papel Usuário (só
quem tem registro próprio) e
  - o aceite da própria pessoa (users.viewers_allowed, em Configurações > Conta), OU
  - a instância em "Visível para quem gerencia" (app_settings.team_visibility =
    'managers', Admin › Para empresas e instituições; sql/036), e só para quem
    está em alguma equipe (sql/043: sem equipe, "Para empresas" não vale para a
    pessoa e volta a escolha dela);
  - E o escopo de equipe (sql/043, teams.py): com equipes na instância, só quem
    compartilha pelo menos uma equipe com quem vê; o admin master com o papel
    "Vê a equipe" ligado vê todos. Sem nenhuma equipe ativa, tudo como antes.
As escolhas individuais nunca são apagadas: voltar para "Cada pessoa escolhe"
(ou sair da última equipe) devolve o que cada um tinha marcado. As flags vão em
subconsultas: uma leitura só, sempre consistente com o banco.
"""
from . import db, teams


def consent_sql(alias: str = "u") -> str:
    """A parte que não depende de quem vê: papel Usuário e (aceite ou Para empresas)."""
    return (f"(EXISTS (SELECT 1 FROM user_roles vr WHERE vr.user_id = {alias}.id AND vr.role = 'user')"
            f" AND ({alias}.viewers_allowed OR (EXISTS (SELECT 1 FROM app_settings vs"
            f" WHERE vs.id = 1 AND vs.team_visibility = 'managers') AND {teams.company_sql(alias + '.id')})))")


def scope_sql(alias: str, viewer) -> str:
    """Só o escopo de equipe entre quem vê e a linha `alias`."""
    return teams.scope_sql(viewer, f"{alias}.id", "viewer")


def visible_sql(alias: str, viewer) -> str:
    """Condição SQL (para um WHERE/SELECT) sobre a linha `alias` de users:
    verdadeira para quem `viewer` (id inteiro ou expressão SQL) pode ver."""
    return f"({consent_sql(alias)} AND {scope_sql(alias, viewer)})"


# Conta em uso (já entrou e segue com acesso): convite pendente ou conta
# bloqueada não têm o que mostrar nas listas e no painel da Equipe.
ACTIVE_SQL = "(NOT {a}.invite_pending AND {a}.blocked_at IS NULL)"


def active_sql(alias: str = "u") -> str:
    return ACTIVE_SQL.format(a=alias)


def can_see(viewer_id: int, user_id: int) -> bool:
    return bool(db.query_one(f"SELECT 1 FROM users u WHERE u.id = %s AND {visible_sql('u', int(viewer_id))}",
                             (user_id,)))


def log_master_view(viewer: dict, user_id: int | None, what: str, people: int = 0) -> None:
    """As visualizações do admin master de registros de outras pessoas vão para o
    log de admin (o histórico dele, ator "admin"): uma linha por pessoa e por
    tipo (quadro, mês, PDF, projetos) a cada dia, sem inundar. user_id=None = da
    equipe toda (painel, horas em CSV), com quantas pessoas entraram."""
    if user_id == viewer["user_id"] or not teams.is_master(viewer["user_id"]):
        return
    if user_id is None and not people:
        return
    from . import audit  # import tardio (audit importa só o db, mas fica igual aos routers)
    if db.query_one(
            """SELECT 1 FROM audit_log WHERE user_id = %s AND action = 'master.view'
                  AND entity_id IS NOT DISTINCT FROM %s AND after->>'what' = %s
                  AND created_at > date_trunc('day', now())""",
            (viewer["user_id"], user_id, what)):
        return
    if user_id is None:
        audit.record({**viewer, "actor": "admin"}, "master.view", "team", None, after={"what": what, "people": people})
        return
    target = db.query_one("SELECT email FROM users WHERE id = %s", (user_id,))
    audit.record({**viewer, "actor": "admin"}, "master.view", "user", user_id,
                 after={"what": what, "email": target["email"] if target else None})
