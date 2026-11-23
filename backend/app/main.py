import asyncio
import json
import logging
import pathlib
from contextlib import asynccontextmanager

import psycopg
from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from psycopg import errors as pg_errors
from psycopg_pool import PoolTimeout
from pydantic import BaseModel, EmailStr, Field, TypeAdapter, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db, notify, roles, teams
from .config import config
from .version import VERSION
from .routers import (admin, assign, equipes, auth, board, branding, calendar, dashboard, export, history, mcp, me, packs,
                      invite_requests, notifications, objectives, passkeys, photos, projects, push, recurring, renewals, reports, review, search, summary, templates, timer,
                      saude, tokens, viewer, webhooks, worklog)
from .deps import web_active
from .security import Busy, client_error_limiter, hash_password

SQL_DIR = pathlib.Path(__file__).resolve().parent.parent / "sql"


def run_migrations() -> None:
    for path in sorted(SQL_DIR.glob("*.sql")):
        db.execute_script(path.read_text(encoding="utf-8"))


def seed_admin() -> None:
    if not config.ADMIN_EMAIL or not config.ADMIN_INITIAL_PASSWORD:
        return
    email = config.ADMIN_EMAIL.lower()
    try:
        # O login valida o e-mail; um endereco que nao passa aqui (ex.: dominio
        # reservado como .test ou .local) criaria um admin que nunca entra.
        TypeAdapter(EmailStr).validate_python(email)
    except ValidationError:
        logging.getLogger("uvicorn.error").error(
            "ADMIN_EMAIL invalido (%s): o login recusaria esse endereco. Admin NAO criado.", email
        )
        return
    # Só na instalação nova: havendo QUALQUER conta admin, não cria outra. Antes bastava o e-mail do
    # .env não existir (admin trocou o próprio e-mail, conta excluída) para nascer um admin novo com a
    # senha inicial do .env, que costuma ficar lá esquecida.
    if roles.admins_count() or db.query_one("SELECT 1 FROM users WHERE role = 'admin' OR email = %s", (email,)):
        teams.ensure_master()
        return
    row = db.query_one(
        """INSERT INTO users (email, password_hash, role, must_change_password)
           VALUES (%s, %s, 'admin', true) RETURNING id""",
        (email, hash_password(config.ADMIN_INITIAL_PASSWORD)),
    )
    roles.grant(row["id"], ["user", "admin", "viewer"])
    teams.ensure_master()  # o primeiro admin é o master (sql/043)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    run_migrations()
    seed_admin()
    task = None
    if config.MAIL_SCHEDULER:  # e-mails (se houver SMTP) e notificações dos aparelhos
        task = asyncio.create_task(notify.scheduler())
    yield
    if task:
        task.cancel()


app = FastAPI(
    title="Nexus Worklog",
    version=VERSION,
    description="API REST do Nexus Worklog. Referência, erros e exemplos: docs/API.md.",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


# Retry-After em todo 429/503: a automação espera em vez de repetir em rajada.
# Um minuto cobre as janelas curtas; as longas (login, convite) recusam de novo.
RETRY_AFTER = {429: "60", 503: "5"}


@app.exception_handler(Busy)
@app.exception_handler(PoolTimeout)
@app.exception_handler(pg_errors.QueryCanceled)  # statement_timeout (db.py)
@app.exception_handler(pg_errors.DeadlockDetected)  # duas transações (db.transaction) em círculo: nada foi gravado
async def _busy(request: Request, exc: Exception):
    return JSONResponse({"detail": "servidor ocupado, tente de novo em instantes"}, status_code=503,
                        headers={"Retry-After": RETRY_AFTER[503]})


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code in RETRY_AFTER and "Retry-After" not in (exc.headers or {}):
        exc.headers = {**(exc.headers or {}), "Retry-After": RETRY_AFTER[exc.status_code]}
    return await http_exception_handler(request, exc)


# NUL (\u0000), substituto solto (\ud800) ou número fora da faixa da coluna: o banco recusa e
# isso é erro do pedido, não do servidor. Com 500 a fila offline do celular repetia para sempre;
# com 4xx o item vai para "Não deu para aplicar". A mensagem é genérica porque o DataError cobre
# os dois casos (texto e número).
BAD_DATA = "o texto tem um caractere inválido ou um valor fora do limite"


@app.exception_handler(psycopg.DataError)
@app.exception_handler(UnicodeEncodeError)
async def _bad_data(request: Request, exc: Exception):
    # Uma linha no log (sem o valor): se for defeito nosso e não do pedido, dá para achar.
    logging.getLogger("uvicorn.error").warning("dado recusado em %s %s: %s", request.method, request.url.path,
                                               exc.__class__.__name__)
    return JSONResponse({"detail": BAD_DATA}, status_code=400)


@app.exception_handler(RequestValidationError)
async def _invalid(request: Request, exc: RequestValidationError):
    """O 422 de sempre; só não estoura (500) quando o valor recusado, que volta em `input`,
    traz um substituto solto: ele sai como "?"."""
    body = json.dumps({"detail": jsonable_encoder(exc.errors())}, ensure_ascii=False, separators=(",", ":"))
    return Response(body.encode("utf-8", "replace"), status_code=422, media_type="application/json")


class NoStore:
    """Cache-Control: no-store em toda resposta de /api/ que não trouxer o seu: os dados da
    pessoa não ficam no cache do navegador nem de um proxy no caminho. Fotos, avatar e logo
    já mandam o próprio Cache-Control e seguem com ele."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)

        async def wrapped(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                if not any(k.lower() == b"cache-control" for k, _ in headers):
                    message = {**message, "headers": headers + [(b"cache-control", b"no-store")]}
            await send(message)
        await self.app(scope, receive, wrapped)


app.add_middleware(NoStore)


@app.get("/api/health")
def health():
    """Para o healthcheck do compose e monitoramento: app e banco respondendo."""
    db.query_one("SELECT 1 AS ok")
    return {"ok": True}


class ClientErrorIn(BaseModel):
    message: str = Field(max_length=300)
    where: str = Field(default="", max_length=200)


@app.post("/api/client-errors", status_code=204)
def client_error(data: ClientErrorIn, user=Depends(web_active)):
    """Erro de JavaScript do navegador vai para o log do backend (sem terceiros,
    sem banco). Só sessão do app (chave de API não), poucos por pessoa; sem CSRF: só escreve no log."""
    if client_error_limiter.allow(f"ce:{user['user_id']}"):
        clean = lambda t: " ".join(t.split())[:300]  # noqa: E731 — uma linha por erro no log
        logging.getLogger("uvicorn.error").warning("erro no navegador (usuário %s) em %s: %s",
                                                   user["user_id"], clean(data.where), clean(data.message))

for module in (auth, recurring, worklog, board, dashboard, reports, admin, history, tokens, mcp, branding, projects,
               summary, search, photos, export, calendar, notifications, me, timer, templates, viewer, assign, renewals,
               objectives, push, passkeys, invite_requests, webhooks, review, packs, saude, equipes):
    app.include_router(module.router)
app.include_router(worklog.items)  # /api/notes, /api/checklist, /api/time
app.include_router(assign.received)  # /api/worklog/{id}/return (quem recebeu devolve)

# docs/openapi.json com a chave Bearer, as rotas só do app e os cabeçalhos (openapi_doc.py).
from . import openapi_doc  # noqa: E402

openapi_doc.install(app)
