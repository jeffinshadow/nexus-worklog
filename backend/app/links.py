"""Links de uso único mandados por e-mail: convite (7 dias), recuperação de
senha (1 hora) e confirmação do e-mail novo (24 horas; guarda o endereço novo). O token vai só no link (no #, fora dos logs do servidor); o
banco guarda o hash. Um link novo do mesmo tipo invalida os anteriores."""
from datetime import datetime, timedelta, timezone

from . import db
from .config import config
from .security import new_token, token_hash

TTL = {"invite": timedelta(days=7), "reset": timedelta(hours=1), "email": timedelta(hours=24)}
HASH_KEY = {"invite": "convite", "reset": "senha", "email": "email"}  # /login#convite=... / #senha=... / #email=...


def issue(user_id: int, kind: str, new_email: str | None = None, ttl: timedelta | None = None) -> str:
    """ttl: outra validade (o link de nova senha mandado pelo admin vale 24 horas)."""
    db.execute("UPDATE auth_links SET used_at = now() WHERE user_id = %s AND kind = %s AND used_at IS NULL",
               (user_id, kind))
    token = new_token()
    db.execute("INSERT INTO auth_links (user_id, kind, token_hash, expires_at, new_email) VALUES (%s, %s, %s, %s, %s)",
               (user_id, kind, token_hash(token), datetime.now(timezone.utc) + (ttl or TTL[kind]), new_email))
    return token


def cancel(user_id: int, kind: str) -> bool:
    """Invalida o link aberto deste tipo (ex.: desistiu de trocar o e-mail)."""
    return bool(db.execute("UPDATE auth_links SET used_at = now() WHERE user_id = %s AND kind = %s AND used_at IS NULL",
                           (user_id, kind)))


def url(kind: str, token: str) -> str:
    return f"{config.APP_URL}/login#{HASH_KEY[kind]}={token}"


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


def consume_email(token: str) -> dict | None:
    """Gasta o link de confirmação de e-mail: {user_id, new_email} ou None."""
    return db.query_one(
        """UPDATE auth_links SET used_at = now()
            WHERE token_hash = %s AND kind = 'email' AND used_at IS NULL AND expires_at > now()
        RETURNING user_id, new_email""", (token_hash(token or ""),))
