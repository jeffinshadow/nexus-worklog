"""Chaves de API pessoais (para IA e automações agirem em nome do usuário).

Só pelo app (sessão): uma chave não cria nem revoga chaves. O valor completo
aparece uma única vez, na criação; o banco guarda só o HMAC (security.token_hash).
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db
from ..deps import web_active, web_active_csrf
from ..schemas import TokenIn, TokenRenewIn
from ..security import new_api_token, token_hash

router = APIRouter(prefix="/api/tokens", tags=["tokens"])

MAX_ACTIVE = 20


@router.get("")
def list_tokens(user=Depends(web_active)):
    return db.query_all(
        """
        SELECT id, name, prefix, scope, created_at, expires_at, last_used_at, revoked_at,
               (revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())) AS active
          FROM api_tokens
         WHERE user_id = %s
         ORDER BY revoked_at IS NOT NULL, created_at DESC
        """,
        (user["user_id"],),
    )


def _active_count(uid: int) -> int:
    return db.query_one(
        """SELECT count(*) AS n FROM api_tokens
            WHERE user_id = %s AND revoked_at IS NULL
              AND (expires_at IS NULL OR expires_at > now())""",
        (uid,),
    )["n"]


@router.post("", status_code=201)
def create_token(data: TokenIn, user=Depends(web_active_csrf)):
    if _active_count(user["user_id"]) >= MAX_ACTIVE:
        raise HTTPException(status_code=409, detail=f"limite de {MAX_ACTIVE} chaves ativas; revogue alguma")
    raw, prefix = new_api_token()
    expires = (datetime.now(timezone.utc) + timedelta(days=data.expires_in_days)
               if data.expires_in_days else None)
    row = db.query_one(
        """
        INSERT INTO api_tokens (user_id, name, prefix, token_hash, scope, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id, name, prefix, scope, created_at, expires_at
        """,
        (user["user_id"], data.name.strip(), prefix, token_hash(raw), data.scope, expires),
    )
    audit.record(user, "token.create", "token", row["id"],
                 after={"name": row["name"], "scope": row["scope"], "expires_at": expires})
    # Única vez em que a chave completa sai do servidor.
    return {**row, "token": raw}


@router.delete("/{token_id}")
def revoke_token(token_id: int, user=Depends(web_active_csrf)):
    row = db.query_one(
        """UPDATE api_tokens SET revoked_at = now()
            WHERE id = %s AND user_id = %s AND revoked_at IS NULL
        RETURNING id, name""",
        (token_id, user["user_id"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="não encontrado")
    audit.record(user, "token.revoke", "token", token_id, after={"name": row["name"]})
    return {"ok": True}


@router.post("/{token_id}/renew")
def renew_token(token_id: int, data: TokenRenewIn, user=Depends(web_active_csrf)):
    """Nova validade (a partir de agora) para uma chave vencida ou perto de
    vencer: a IA segue com a mesma chave, sem reconfigurar. Revogada não volta."""
    uid = user["user_id"]
    cur = db.query_one(
        """SELECT id, name, expires_at, (expires_at IS NOT NULL AND expires_at <= now()) AS expired
             FROM api_tokens WHERE id = %s AND user_id = %s AND revoked_at IS NULL""",
        (token_id, uid),
    )
    if not cur:
        raise HTTPException(status_code=404, detail="não encontrada (uma chave revogada não volta; crie outra)")
    if cur["expired"] and _active_count(uid) >= MAX_ACTIVE:
        raise HTTPException(status_code=409, detail=f"limite de {MAX_ACTIVE} chaves ativas; revogue alguma")
    expires = (datetime.now(timezone.utc) + timedelta(days=data.expires_in_days)
               if data.expires_in_days else None)
    row = db.query_one(
        """UPDATE api_tokens SET expires_at = %s WHERE id = %s
        RETURNING id, name, prefix, scope, created_at, expires_at, last_used_at, revoked_at, true AS active""",
        (expires, token_id),
    )
    audit.record(user, "token.renew", "token", token_id,
                 before={"name": cur["name"], "expires_at": cur["expires_at"]},
                 after={"name": cur["name"], "expires_at": expires})
    return row
