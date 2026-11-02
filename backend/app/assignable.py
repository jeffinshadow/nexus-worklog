"""Quem pode receber tarefas de quem tem o papel "Manda tarefas" (assigner).

UM lugar só decide: a lista de quem aceita (GET /api/assign/people, que o
diálogo Atribuir da Equipe e o MCP list_assignable usam), o envio (POST
/api/assign e o MCP assign_task) e a foto de perfil vista por quem atribui
chamam receive_sql()/can_receive(). A regra: o papel Usuário, conta sem
bloqueio e
  - o aceite da própria pessoa (users.accepts_assignments_at, em Configurações > Conta), OU
  - a instância em "Todos recebem de quem atribui" (app_settings.assign_receive =
    'all', Admin › Para empresas e instituições; sql/041), para quem já entrou
    (convite ainda não aceito não recebe: a pessoa nem viu o Nexus).
As escolhas individuais nunca são apagadas: voltar para "Cada pessoa escolhe"
devolve o que cada um tinha marcado (o mesmo desenho de visibility.py).
"""
from . import db

ALL_SQL = "EXISTS (SELECT 1 FROM app_settings rs WHERE rs.id = 1 AND rs.assign_receive = 'all')"


def receive_sql(alias: str = "u") -> str:
    """Condição SQL sobre a linha `alias` de users: verdadeira para quem pode
    receber tarefas atribuídas agora."""
    return (f"(EXISTS (SELECT 1 FROM user_roles rr WHERE rr.user_id = {alias}.id AND rr.role = 'user')"
            f" AND {alias}.blocked_at IS NULL"
            f" AND ({alias}.accepts_assignments_at IS NOT NULL OR ({ALL_SQL} AND NOT {alias}.invite_pending)))")


def can_receive(user_id: int) -> bool:
    return bool(db.query_one(f"SELECT 1 FROM users u WHERE u.id = %s AND {receive_sql('u')}", (user_id,)))


def everyone() -> bool:
    """A instância está em "Todos recebem de quem atribui"?"""
    return bool(db.query_one(f"SELECT 1 WHERE {ALL_SQL}"))
