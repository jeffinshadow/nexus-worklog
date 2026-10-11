import hmac
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response

from . import db
from .config import config
from .security import token_hash


def client_ip(request: Request) -> str:
    """IP do cliente para rate limit e logs.

    O nginx SEMPRE sobrescreve X-Client-IP: com o CF-Connecting-IP (posto pela
    borda da Cloudflare, que o cliente nao controla) ou, sem Cloudflare, com o
    endereco da conexao. Nao usamos X-Forwarded-For: o primeiro valor dele vem
    do proprio cliente e pode ser forjado para escapar do rate limit.
    """
    real = request.headers.get("x-client-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=config.SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="strict",
        path="/",
        max_age=config.SESSION_TTL_DAYS * 86400,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(config.SESSION_COOKIE, path="/")


def _load_session(request: Request) -> dict:
    """Valida o cookie de sessao, renova a expiracao (sliding) e devolve
    sessao + usuario. Levanta 401 se invalida/expirada."""
    token = request.cookies.get(config.SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="nao autenticado")

    row = db.query_one(
        """
        SELECT s.id AS sid, s.csrf_token, s.expires_at,
               u.id AS user_id, u.email, u.role, u.must_change_password
          FROM sessions s
          JOIN users u ON u.id = s.user_id
         WHERE s.token_hash = %s
        """,
        (token_hash(token),),
    )
    if not row:
        raise HTTPException(status_code=401, detail="sessao invalida")

    now = datetime.now(timezone.utc)
    if row["expires_at"] <= now:
        db.execute("DELETE FROM sessions WHERE id = %s", (row["sid"],))
        raise HTTPException(status_code=401, detail="sessao expirada")

    # Renovacao deslizante.
    new_exp = now + timedelta(days=config.SESSION_TTL_DAYS)
    db.execute("UPDATE sessions SET expires_at = %s WHERE id = %s", (new_exp, row["sid"]))
    return row


def _check_csrf(request: Request, session: dict) -> None:
    sent = request.headers.get("X-CSRF-Token")
    if not sent or not hmac.compare_digest(sent, session["csrf_token"]):
        raise HTTPException(status_code=403, detail="token CSRF invalido")


# ---- Dependencies -----------------------------------------------------------
# Ponto unico de decisao de autenticacao/autorizacao. Rotas usam estas deps;
# nenhuma checagem de permissao fica espalhada nos handlers.


def current_user(request: Request) -> dict:
    """Sessao valida. Permite usuario com must_change_password (para /me e
    troca de senha)."""
    return _load_session(request)


def current_user_csrf(request: Request) -> dict:
    session = _load_session(request)
    _check_csrf(request, session)
    return session


def active_user(request: Request) -> dict:
    """Sessao valida e senha ja definida. Usada em todas as rotas de dados."""
    session = _load_session(request)
    if session["must_change_password"]:
        raise HTTPException(status_code=403, detail="troca de senha obrigatoria")
    return session


def active_user_csrf(request: Request) -> dict:
    session = active_user(request)
    _check_csrf(request, session)
    return session


def require_admin(request: Request) -> dict:
    """Autorizacao de admin verificada SEMPRE no backend."""
    session = active_user(request)
    if session["role"] != "admin":
        raise HTTPException(status_code=403, detail="acesso restrito ao admin")
    return session


def require_admin_csrf(request: Request) -> dict:
    """Admin + CSRF: para mutacoes em /api/admin/*."""
    session = require_admin(request)
    _check_csrf(request, session)
    return session


def effective_user_id(session: dict, as_user: int | None) -> int:
    """Resolve o user_id alvo de uma consulta. Unico caminho para acessar
    dados de outro usuario, e so para admin."""
    if as_user is None or as_user == session["user_id"]:
        return session["user_id"]
    if session["role"] == "admin":
        return as_user
    raise HTTPException(status_code=403, detail="acesso negado")
