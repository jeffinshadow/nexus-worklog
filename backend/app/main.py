import asyncio
import logging
import pathlib
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg import errors as pg_errors
from psycopg_pool import PoolTimeout
from pydantic import BaseModel, EmailStr, Field, TypeAdapter, ValidationError

from . import db, notify, roles
from .config import config
from .routers import (admin, assign, auth, board, branding, calendar, dashboard, export, history, mcp, me,
                      notifications, projects, recurring, reports, search, summary, templates, timer, tokens, viewer,
                      worklog)
from .deps import active_user
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
    if db.query_one("SELECT 1 FROM users WHERE email = %s", (email,)):
        return
    row = db.query_one(
        """INSERT INTO users (email, password_hash, role, must_change_password)
           VALUES (%s, %s, 'admin', true) RETURNING id""",
        (email, hash_password(config.ADMIN_INITIAL_PASSWORD)),
    )
    roles.grant(row["id"], ["user", "admin", "viewer"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    run_migrations()
    seed_admin()
    task = None
    if config.SMTP_HOST and config.MAIL_SCHEDULER:
        task = asyncio.create_task(notify.scheduler())
    yield
    if task:
        task.cancel()


app = FastAPI(
    title="Shadow Nexus Worklog",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.exception_handler(Busy)
@app.exception_handler(PoolTimeout)
@app.exception_handler(pg_errors.QueryCanceled)  # statement_timeout (db.py)
async def _busy(request: Request, exc: Exception):
    return JSONResponse({"detail": "servidor ocupado, tente de novo em instantes"}, status_code=503)


@app.get("/api/health")
def health():
    """Para o healthcheck do compose e monitoramento: app e banco respondendo."""
    db.query_one("SELECT 1 AS ok")
    return {"ok": True}


class ClientErrorIn(BaseModel):
    message: str = Field(max_length=300)
    where: str = Field(default="", max_length=200)


@app.post("/api/client-errors", status_code=204)
def client_error(data: ClientErrorIn, user=Depends(active_user)):
    """Erro de JavaScript do navegador vai para o log do backend (sem terceiros,
    sem banco). Só logado, poucos por pessoa; sem CSRF: só escreve no log."""
    if client_error_limiter.allow(f"ce:{user['user_id']}"):
        clean = lambda t: " ".join(t.split())[:300]  # noqa: E731 — uma linha por erro no log
        logging.getLogger("uvicorn.error").warning("erro no navegador (usuário %s) em %s: %s",
                                                   user["user_id"], clean(data.where), clean(data.message))

for module in (auth, recurring, worklog, board, dashboard, reports, admin, history, tokens, mcp, branding, projects,
               summary, search, export, calendar, notifications, me, timer, templates, viewer, assign):
    app.include_router(module.router)
app.include_router(worklog.items)  # /api/notes, /api/checklist, /api/time
