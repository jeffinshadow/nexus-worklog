"""Papéis acumuláveis (sql/010): uma conta pode ter qualquer combinação.

  user      tem o próprio registro (Hoje, Tarefas, Rotinas...) e pode receber tarefas
  admin     contas, permissões e configurações gerais
  assigner  atribui tarefas a quem consentiu (pelo app ou por chave de API/MCP)
  viewer    vê os registros e tira relatórios de todos (só pelo app)

users.role espelha "admin" só por compatibilidade (rollback e código antigo).
"""
from . import db

ROLES = ("user", "admin", "assigner", "viewer")
LABELS = {"user": "Usuário", "admin": "Admin", "assigner": "Atribuidor de tarefas", "viewer": "Visualizador de tarefas"}

# Subconsulta para as leituras de sessão/chave (deps): papéis como lista.
ROLES_SQL = "ARRAY(SELECT r.role FROM user_roles r WHERE r.user_id = u.id ORDER BY r.role) AS roles"


def of(user_id: int) -> list[str]:
    return [r["role"] for r in db.query_all("SELECT role FROM user_roles WHERE user_id = %s ORDER BY role", (user_id,))]


def grant(user_id: int, roles) -> None:
    for role in roles:
        db.execute("INSERT INTO user_roles (user_id, role) VALUES (%s, %s) ON CONFLICT DO NOTHING", (user_id, role))
    _mirror(user_id)


def replace(user_id: int, roles) -> None:
    db.execute("DELETE FROM user_roles WHERE user_id = %s AND NOT (role = ANY(%s))", (user_id, list(roles)))
    grant(user_id, roles)


def _mirror(user_id: int) -> None:
    db.execute(
        """UPDATE users SET role = CASE WHEN EXISTS (SELECT 1 FROM user_roles WHERE user_id = %(u)s AND role = 'admin')
                                        THEN 'admin' ELSE 'user' END
            WHERE id = %(u)s""",
        {"u": user_id},
    )


def admins_count() -> int:
    return db.query_one("SELECT count(*)::int AS n FROM user_roles WHERE role = 'admin'")["n"]
