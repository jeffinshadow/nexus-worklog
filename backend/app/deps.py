import ipaddress
import hmac
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response

from . import db
from .config import config
from .roles import ROLES_SQL
from .security import token_hash, token_limiter


def client_ip(request: Request) -> str:
    """IP do cliente para rate limit e logs.

    O nginx SEMPRE sobrescreve X-Client-IP: com o CF-Connecting-IP (posto pela
    borda da Cloudflare, que o cliente nao controla) ou, sem Cloudflare, com o
    endereco da conexao. Nao usamos X-Forwarded-For: o primeiro valor dele vem
    do proprio cliente e pode ser forjado para escapar do rate limit.
    """
    real = (request.headers.get("x-client-ip") or "").strip()
    ip = real or (request.client.host if request.client else "unknown")
    # IPv6: um cliente costuma ter um /64 inteiro; agrupa para o limite valer.
    if ":" in ip:
        try:
            return str(ipaddress.ip_network(f"{ip}/64", strict=False))
        except ValueError:
            pass
    return ip


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
    """Valida o cookie de sessao e devolve sessao + usuario. Levanta 401 se
    invalida/expirada."""
    token = request.cookies.get(config.SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="não autenticado")

    row = db.query_one(
        """
        SELECT s.id AS sid, s.csrf_token, s.expires_at,
               u.id AS user_id, u.email, u.role, u.must_change_password,
               u.work_days, """ + ROLES_SQL + """
          FROM sessions s
          JOIN users u ON u.id = s.user_id
         WHERE s.token_hash = %s
        """,
        (token_hash(token),),
    )
    if not row:
        raise HTTPException(status_code=401, detail="sessão inválida")

    now = datetime.now(timezone.utc)
    # Prazo fixo (SESSION_TTL_DAYS, o mesmo do cookie): sem renovação, o login
    # é pedido de novo ao vencer.
    if row["expires_at"] <= now:
        db.execute("DELETE FROM sessions WHERE id = %s", (row["sid"],))
        raise HTTPException(status_code=401, detail="sessão expirada")
    return row


def _load_token(raw: str) -> dict:
    """Valida uma chave de API (Authorization: Bearer nxs_...)."""
    row = db.query_one(
        """
        SELECT t.id AS token_id, t.name AS token_name, t.scope, t.last_used_at,
               u.id AS user_id, u.email, u.role, u.must_change_password,
               u.work_days, """ + ROLES_SQL + """
          FROM api_tokens t
          JOIN users u ON u.id = t.user_id
         WHERE t.token_hash = %s
           AND t.revoked_at IS NULL
           AND (t.expires_at IS NULL OR t.expires_at > now())
        """,
        (token_hash(raw),),
    )
    if not row:
        raise HTTPException(
            status_code=401,
            detail="chave de API inválida, revogada ou vencida",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not token_limiter.allow(f"tok:{row['user_id']}"):  # por pessoa: 20 chaves não multiplicam o limite
        raise HTTPException(status_code=429, detail="muitas requisições com esta chave, aguarde um minuto")
    now = datetime.now(timezone.utc)
    # "Último uso" com resolução de 1 minuto: evita uma escrita por requisição.
    if row["last_used_at"] is None or now - row["last_used_at"] > timedelta(minutes=1):
        db.execute("UPDATE api_tokens SET last_used_at = %s WHERE id = %s", (now, row["token_id"]))
    row.update(actor="api", csrf_token=None, sid=None)
    return row


def _authenticate(request: Request) -> dict:
    """Contexto de autenticação único: cookie de sessão (web) ou chave de API.

    O dicionário devolvido carrega o usuário e QUEM está agindo (actor web/api,
    token_id/token_name e scope); o histórico usa isso para registrar a origem.
    """
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        return _load_token(auth[7:].strip())
    session = _load_session(request)
    session.update(actor="web", token_id=None, token_name=None, scope="write")
    return session


def _check_csrf(request: Request, session: dict) -> None:
    # Chave de API dispensa CSRF: o ataque de CSRF depende do cookie que o
    # navegador manda sozinho; um header Authorization não é enviado por
    # outro site (o app não habilita CORS).
    if session.get("actor") != "web":
        return
    sent = request.headers.get("X-CSRF-Token")
    if not sent or not hmac.compare_digest(sent, session["csrf_token"]):
        raise HTTPException(status_code=403, detail="token CSRF inválido")


# ---- Dependencies -----------------------------------------------------------
# Ponto unico de decisao de autenticacao/autorizacao. Rotas usam estas deps;
# nenhuma checagem de permissao fica espalhada nos handlers.


def _require_write(session: dict) -> None:
    if session.get("scope") != "write":
        raise HTTPException(status_code=403, detail="esta chave de API é só de leitura")


def _require_web(session: dict) -> None:
    if session.get("actor") != "web":
        raise HTTPException(status_code=403, detail="disponível só pelo app, não por chave de API")


def current_user(request: Request) -> dict:
    """Sessao ou chave valida. Permite usuario com must_change_password (para
    /me e troca de senha)."""
    return _authenticate(request)


def web_user_csrf(request: Request) -> dict:
    """Só sessão do app (nunca chave de API) + CSRF: logout, troca de senha."""
    session = _authenticate(request)
    _require_web(session)
    _check_csrf(request, session)
    return session


def active_user(request: Request) -> dict:
    """Sessao (ou chave) valida e senha ja definida. Rotas de leitura de dados."""
    session = _authenticate(request)
    if session["must_change_password"]:
        raise HTTPException(status_code=403, detail="troca de senha obrigatória")
    return session


def active_user_csrf(request: Request) -> dict:
    """Escrita de dados: sessão + CSRF, ou chave de API com escopo de escrita."""
    session = active_user(request)
    _check_csrf(request, session)
    _require_write(session)
    return session


def web_active(request: Request) -> dict:
    """Só sessão do app: telas que não fazem sentido por chave (ex.: chaves)."""
    session = active_user(request)
    _require_web(session)
    return session


def web_active_csrf(request: Request) -> dict:
    session = web_active(request)
    _check_csrf(request, session)
    return session


def _require_role(session: dict, role: str, detail: str) -> None:
    if role not in (session.get("roles") or []):
        raise HTTPException(status_code=403, detail=detail)


def require_admin(request: Request) -> dict:
    """Autorizacao de admin verificada SEMPRE no backend. Chave de API nunca
    acessa o admin, mesmo a de um admin."""
    session = active_user(request)
    _require_web(session)
    _require_role(session, "admin", "acesso restrito ao admin")
    return session


def require_admin_csrf(request: Request) -> dict:
    """Admin + CSRF: para mutacoes em /api/admin/*."""
    session = require_admin(request)
    _check_csrf(request, session)
    return session


def require_viewer(request: Request) -> dict:
    """Visualizador de tarefas: registros e relatórios de todos. Só pelo app."""
    session = active_user(request)
    _require_web(session)
    _require_role(session, "viewer", "acesso restrito ao visualizador de tarefas")
    return session


def require_assigner(request: Request) -> dict:
    """Atribuidor de tarefas: pelo app ou por chave de API (leitura)."""
    session = active_user(request)
    _require_role(session, "assigner", "acesso restrito ao atribuidor de tarefas")
    return session


def require_assigner_csrf(request: Request) -> dict:
    """Atribuir: sessão + CSRF, ou chave de API com escopo de escrita."""
    session = require_assigner(request)
    _check_csrf(request, session)
    _require_write(session)
    return session


def require_people_list(request: Request) -> dict:
    """Quem consentiu em receber tarefas: Admin ou Atribuidor."""
    session = active_user(request)
    roles = session.get("roles") or []
    if "assigner" in roles or ("admin" in roles and session.get("actor") == "web"):  # admin só pelo app
        return session
    raise HTTPException(status_code=403, detail="acesso restrito ao admin ou ao atribuidor de tarefas")
