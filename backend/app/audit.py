"""Histórico de ações: quem alterou o quê, de onde, com antes/depois.

Toda rota que altera dados chama `record` com o contexto de autenticação
(`deps._authenticate`), que traz a origem: web (app), api (chave) ou mcp (IA
pelo servidor MCP), e o nome da chave quando houver. O antes/depois em JSON
alimenta a tela de histórico e o "desfazer" (routers/history.py).
"""
from datetime import date, datetime

from psycopg.types.json import Jsonb

from . import db


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def record(ctx: dict, action: str, entity: str, entity_id, before=None, after=None,
           user_id: int | None = None) -> None:
    db.execute(
        """
        INSERT INTO audit_log (user_id, actor, token_id, token_name, action,
                               entity, entity_id, before, after)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            user_id or ctx["user_id"],
            ctx.get("actor", "web"),
            ctx.get("token_id"),
            ctx.get("token_name"),
            action,
            entity,
            entity_id,
            Jsonb(_jsonable(before)) if before is not None else None,
            Jsonb(_jsonable(after)) if after is not None else None,
        ),
    )


# Snapshots usados no antes/depois (e restaurados pelo desfazer).
_WORKLOG_COLS = ("id, title, description, status, due_date, created_at, completed_at, "
                 "project_id, priority, ticket, after_hours, external_ref, assigned_by, assigned_at, "
                 "blocked_reason, blocked_at")
_RECURRING_COLS = ("id, label, position, active, created_at, deactivated_at, "
                   "freq, weekdays, month_day, interval_days")


def worklog_snapshot(task_id: int, user_id: int):
    return db.query_one(
        f"SELECT {_WORKLOG_COLS} FROM worklog_tasks WHERE id = %s AND user_id = %s",
        (task_id, user_id),
    )


def recurring_snapshot(task_id: int, user_id: int):
    return db.query_one(
        f"SELECT {_RECURRING_COLS} FROM recurring_tasks WHERE id = %s AND user_id = %s",
        (task_id, user_id),
    )
