import logging
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import EmailStr, TypeAdapter, ValidationError

from . import db
from .config import config
from .routers import admin, auth, board, dashboard, recurring, reports, worklog
from .security import hash_password

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
    db.execute(
        """INSERT INTO users (email, password_hash, role, must_change_password)
           VALUES (%s, %s, 'admin', true)""",
        (email, hash_password(config.ADMIN_INITIAL_PASSWORD)),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    run_migrations()
    seed_admin()
    yield


app = FastAPI(
    title="Shadow Nexus Worklog",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

for module in (auth, recurring, worklog, board, dashboard, reports, admin):
    app.include_router(module.router)
