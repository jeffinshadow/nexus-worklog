"""Quem pode ser visto por quem acompanha a equipe (papel viewer).

UM lugar só decide: as rotas do visualizador (routers/viewer.py: lista, quadro,
mês, PDF, painel da Equipe), as horas da equipe em CSV, as fotos e a foto de
perfil chamam visible_sql()/can_see(). A regra: o papel Usuário (só quem tem
registro próprio) e
  - o aceite da própria pessoa (users.viewers_allowed, em Configurações > Conta), OU
  - a instância em "Visível para quem gerencia" (app_settings.team_visibility =
    'managers', Admin › Para empresas e instituições; sql/036).
As escolhas individuais nunca são apagadas: voltar para "Cada pessoa escolhe"
devolve o que cada um tinha marcado. A flag vai numa subconsulta: uma leitura
só, sempre consistente com o banco, e vale para tudo de uma vez.
"""
from . import db


def visible_sql(alias: str = "u") -> str:
    """Condição SQL (para um WHERE/SELECT) sobre a linha `alias` de users:
    verdadeira para quem quem acompanha a equipe pode ver."""
    return (f"(EXISTS (SELECT 1 FROM user_roles vr WHERE vr.user_id = {alias}.id AND vr.role = 'user')"
            f" AND ({alias}.viewers_allowed OR EXISTS (SELECT 1 FROM app_settings vs"
            f" WHERE vs.id = 1 AND vs.team_visibility = 'managers')))")


# Conta em uso (já entrou e segue com acesso): convite pendente ou conta
# bloqueada não têm o que mostrar nas listas e no painel da Equipe.
ACTIVE_SQL = "(NOT {a}.invite_pending AND {a}.blocked_at IS NULL)"


def active_sql(alias: str = "u") -> str:
    return ACTIVE_SQL.format(a=alias)


def can_see(user_id: int) -> bool:
    return bool(db.query_one(f"SELECT 1 FROM users u WHERE u.id = %s AND {visible_sql('u')}", (user_id,)))
