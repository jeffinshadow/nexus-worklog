"""Quem pode receber tarefas de quem tem o papel "Manda tarefas" (assigner).

UM lugar só decide: a lista de quem aceita (GET /api/assign/people, que o
diálogo Atribuir da Equipe e o MCP list_assignable usam), o envio (POST
/api/assign e o MCP assign_task), a correção de uma tarefa enviada (PATCH
/api/assign/{id}), a foto de perfil vista por quem atribui e a transparência
da Conta chamam receive_sql()/can_receive(). A regra, para quem atribui (`by`):
o papel Usuário, conta sem bloqueio e
  - o aceite da própria pessoa (users.accepts_assignments_at, em Configurações > Conta), OU
  - a instância em "Todos recebem de quem atribui" (app_settings.assign_receive =
    'all', Admin › Para empresas e instituições; sql/041), para quem já entrou
    (convite ainda não aceito não recebe: a pessoa nem viu o Nexus) e está em
    alguma equipe (sql/043: sem equipe, "Para empresas" não vale para a pessoa);
  - E o escopo de equipe (sql/043, teams.py): com equipes na instância, só quem
    compartilha pelo menos uma equipe com quem atribui; o admin master com o
    papel "Manda tarefas" ligado atribui para todos. Sem equipes, como antes.
As escolhas individuais nunca são apagadas: voltar para "Cada pessoa escolhe"
devolve o que cada um tinha marcado (o mesmo desenho de visibility.py).
"""
from . import db, teams

ALL_SQL = "EXISTS (SELECT 1 FROM app_settings rs WHERE rs.id = 1 AND rs.assign_receive = 'all')"


def consent_sql(alias: str = "u") -> str:
    """A parte que não depende de quem atribui: papel, sem bloqueio e (aceite ou Para empresas)."""
    return (f"(EXISTS (SELECT 1 FROM user_roles rr WHERE rr.user_id = {alias}.id AND rr.role = 'user')"
            f" AND {alias}.blocked_at IS NULL"
            f" AND ({alias}.accepts_assignments_at IS NOT NULL"
            f" OR ({ALL_SQL} AND NOT {alias}.invite_pending AND {teams.company_sql(alias + '.id')})))")


def scope_sql(alias: str, by) -> str:
    """Só o escopo de equipe entre quem atribui e a linha `alias`."""
    return teams.scope_sql(by, f"{alias}.id", "assigner")


def receive_sql(alias: str, by) -> str:
    """Condição SQL sobre a linha `alias` de users: verdadeira para quem pode
    receber agora tarefas de `by` (id inteiro ou expressão SQL)."""
    return f"({consent_sql(alias)} AND {scope_sql(alias, by)})"


def can_receive(by: int, user_id: int) -> bool:
    return bool(db.query_one(f"SELECT 1 FROM users u WHERE u.id = %s AND {receive_sql('u', int(by))}", (user_id,)))


def in_scope(by: int, user_id: int) -> bool:
    return bool(db.query_one(f"SELECT 1 FROM users u WHERE u.id = %s AND {scope_sql('u', int(by))}", (user_id,)))


def everyone() -> bool:
    """A instância está em "Todos recebem de quem atribui"?"""
    return bool(db.query_one(f"SELECT 1 WHERE {ALL_SQL}"))


def everyone_for(user_id: int) -> bool:
    """"Todos recebem" vale para esta pessoa (instância ligada e ela em alguma equipe)?"""
    return everyone() and teams.company_applies(user_id)
