"""Links de uso único mandados por e-mail: convite (7 dias) e recuperação de
senha (1 hora). O token vai só no link (no #, fora dos logs do servidor); o
banco guarda o hash. Um link novo do mesmo tipo invalida os anteriores."""
from datetime import datetime, timedelta, timezone

from . import db
from .config import config
from .security import new_token, token_hash

TTL = {"invite": timedelta(days=7), "reset": timedelta(hours=1)}
HASH_KEY = {"invite": "convite", "reset": "senha"}  # login.html#convite=... / #senha=...


def issue(user_id: int, kind: str) -> str:
    db.execute("UPDATE auth_links SET used_at = now() WHERE user_id = %s AND kind = %s AND used_at IS NULL",
               (user_id, kind))
    token = new_token()
    db.execute("INSERT INTO auth_links (user_id, kind, token_hash, expires_at) VALUES (%s, %s, %s, %s)",
               (user_id, kind, token_hash(token), datetime.now(timezone.utc) + TTL[kind]))
    return token


def url(kind: str, token: str) -> str:
    return f"{config.APP_URL}/login.html#{HASH_KEY[kind]}={token}"


def peek(token: str, kind: str):
    """A conta do link, se ele ainda vale (sem gastar)."""
    return db.query_one(
        """SELECT u.id, u.email, u.display_name FROM auth_links l JOIN users u ON u.id = l.user_id
            WHERE l.token_hash = %s AND l.kind = %s AND l.used_at IS NULL AND l.expires_at > now()""",
        (token_hash(token or ""), kind))


def consume(token: str, kind: str) -> int | None:
    """Gasta o link (uma vez só, mesmo com dois cliques ao mesmo tempo)."""
    row = db.query_one(
        """UPDATE auth_links SET used_at = now()
            WHERE token_hash = %s AND kind = %s AND used_at IS NULL AND expires_at > now()
        RETURNING user_id""", (token_hash(token or ""), kind))
    return row["user_id"] if row else None
