"""Quem pode ser visto por quem acompanha a equipe (papel viewer).

UM lugar só decide: as rotas do visualizador (routers/viewer.py: lista, quadro,
mês, PDF, painel da Equipe), as horas da equipe em CSV, as fotos e a foto de
perfil chamam visible_sql()/can_see(). Hoje a regra é o aceite da própria
pessoa (users.viewers_allowed, em Configurações > Conta) e o papel Usuário (só
quem tem registro próprio). Uma opção da instância que torne todos visíveis
entra AQUI, e vale para tudo de uma vez.
"""
from . import db


def visible_sql(alias: str = "u") -> str:
    """Condição SQL (para um WHERE/SELECT) sobre a linha `alias` de users:
    verdadeira para quem quem acompanha a equipe pode ver."""
    return (f"({alias}.viewers_allowed AND EXISTS (SELECT 1 FROM user_roles vr"
            f" WHERE vr.user_id = {alias}.id AND vr.role = 'user'))")


# Conta em uso (já entrou e segue com acesso): convite pendente ou conta
# bloqueada não têm o que mostrar nas listas e no painel da Equipe.
ACTIVE_SQL = "(NOT {a}.invite_pending AND {a}.blocked_at IS NULL)"


def active_sql(alias: str = "u") -> str:
    return ACTIVE_SQL.format(a=alias)


def can_see(user_id: int) -> bool:
    return bool(db.query_one(f"SELECT 1 FROM users u WHERE u.id = %s AND {visible_sql('u')}", (user_id,)))
