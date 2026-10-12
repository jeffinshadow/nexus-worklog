"""Fixtures da suíte. Roda contra um Postgres real e descartável
(docker-compose.test.yml); cada teste começa com o banco zerado."""
import os

import pytest
from fastapi.testclient import TestClient

from app import db, main, security
from app.main import app

ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PW_INICIAL = os.environ["ADMIN_INITIAL_PASSWORD"]
ADMIN_PW = "Admin-Definitiva-Teste-1"
SENHA_PADRAO = "Senha-Do-Usuario-1"

TABELAS = ["app_branding", "audit_log", "api_tokens", "notification_log", "notification_prefs", "calendar_feeds",
           "time_entries", "task_checklist", "task_notes",
           "recurring_completions", "recurring_tasks", "projects",
           "worklog_tasks", "sessions", "users"]


@pytest.fixture(scope="session", autouse=True)
def _app():
    # Abre o pool, aplica as migrations e semeia o admin (lifespan real).
    with TestClient(app):
        yield


@pytest.fixture(autouse=True)
def _banco_limpo():
    existentes = {r["tablename"] for r in db.query_all(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    alvo = [t for t in TABELAS if t in existentes]
    db.execute(f"TRUNCATE {', '.join(alvo)} RESTART IDENTITY CASCADE")
    if "app_branding" in existentes:
        db.execute("INSERT INTO app_branding (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    main.seed_admin()
    for limiter in (security.login_limiter, security.login_email_limiter,
                    security.pdf_limiter):
        limiter._hits.clear()
    yield


class Api:
    """Cliente de teste com cookie de sessão e CSRF, como o frontend."""

    def __init__(self):
        self.c = TestClient(app, base_url="http://testserver")
        self.csrf = None
        self.me = None

    def login(self, email, senha):
        r = self.c.post("/api/auth/login", json={"email": email, "password": senha})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf_token"]
        self.me = r.json()
        return r

    def _h(self, extra=None):
        h = {"X-CSRF-Token": self.csrf} if self.csrf else {}
        h.update(extra or {})
        return h

    def get(self, path, **kw):
        return self.c.get("/api" + path, **kw)

    def post(self, path, json=None, headers=None):
        return self.c.post("/api" + path, json=json, headers=self._h(headers))

    def patch(self, path, json=None, headers=None):
        return self.c.patch("/api" + path, json=json, headers=self._h(headers))

    def delete(self, path, headers=None):
        return self.c.delete("/api" + path, headers=self._h(headers))


@pytest.fixture
def admin():
    a = Api()
    a.login(ADMIN_EMAIL, ADMIN_PW_INICIAL)
    r = a.post("/auth/change-password", {"current_password": ADMIN_PW_INICIAL, "new_password": ADMIN_PW})
    assert r.status_code == 200, r.text
    a.login(ADMIN_EMAIL, ADMIN_PW)
    return a


@pytest.fixture
def novo_usuario(admin):
    """Fábrica: convida pelo admin, faz o 1º login e troca a senha."""
    def _criar(email="colega@example.com", senha=SENHA_PADRAO):
        r = admin.post("/admin/users", {"email": email})
        assert r.status_code == 201, r.text
        u = Api()
        u.login(email, r.json()["temp_password"])
        r = u.post("/auth/change-password", {"current_password": r.json()["temp_password"], "new_password": senha})
        assert r.status_code == 200, r.text
        u.login(email, senha)
        return u
    return _criar


@pytest.fixture
def usuario(novo_usuario):
    return novo_usuario()


def recuar_criacao(task_id, dias):
    """Faz uma recorrente 'existir' há N dias (para testar retroativo e vigência)."""
    db.execute(
        "UPDATE recurring_tasks SET created_at = now() - make_interval(days => %s) WHERE id = %s",
        (dias, task_id),
    )


class Bearer:
    """Cliente autenticado por chave de API (como uma IA ou automação)."""

    def __init__(self, token):
        self.c = TestClient(app, base_url="http://testserver")
        self.h = {"Authorization": f"Bearer {token}"}

    def get(self, path, **kw):
        return self.c.get("/api" + path, headers=self.h, **kw)

    def post(self, path, json=None):
        return self.c.post("/api" + path, json=json, headers=self.h)

    def patch(self, path, json=None):
        return self.c.patch("/api" + path, json=json, headers=self.h)

    def delete(self, path):
        return self.c.delete("/api" + path, headers=self.h)

    def rpc(self, method, params=None, rid=1, headers=None):
        body = {"jsonrpc": "2.0", "method": method}
        if rid is not None:
            body["id"] = rid
        if params is not None:
            body["params"] = params
        return self.c.post("/mcp", json=body, headers={**self.h, **(headers or {})})

    def tool(self, name, **args):
        r = self.rpc("tools/call", {"name": name, "arguments": args})
        assert r.status_code == 200, r.text
        return r.json()["result"]


def criar_chave(api, nome="IA de teste", scope="write", dias=90):
    r = api.post("/tokens", {"name": nome, "scope": scope, "expires_in_days": dias})
    assert r.status_code == 201, r.text
    return r.json()


# ---- ajudantes comuns dos testes
def dia_hoje(u):
    """O "hoje" do servidor (fuso da app), não o da máquina de teste."""
    from datetime import date
    return date.fromisoformat(u.get("/board").json()["today"])


def hist(u, **kw):
    q = "&".join(f"{k}={v}" for k, v in kw.items())
    return u.get(f"/history?{q}").json()


def texto(res):
    """Texto da resposta de uma ferramenta MCP."""
    return res["content"][0]["text"]


def uid_de(u):
    return db.query_one("SELECT id FROM users WHERE email = %s", (u.me["email"],))["id"]
