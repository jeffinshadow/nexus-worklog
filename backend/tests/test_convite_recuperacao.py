"""Convite por link e recuperação de senha por e-mail; semanas anteriores do resumo."""
import re

import pytest

from app import db, mailer
from app.routers import auth as auth_mod
from conftest import ADMIN_EMAIL, ADMIN_PW, Api, SENHA_PADRAO, uid_de

SENHA_NOVA = "Senha-Nova-Do-Link-1"


class _Agora:
    """threading.Thread que roda na hora (o envio em segundo plano vira síncrono)."""

    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@pytest.fixture
def caixa(monkeypatch):
    """E-mail configurado; o que seria enviado fica na lista (para, assunto, texto)."""
    enviados = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None: enviados.append((to, subject, text)))
    monkeypatch.setattr(auth_mod.threading, "Thread", _Agora)
    return enviados


def _token(texto, chave):
    return re.search(chave + r"=([\w-]+)", texto).group(1)


# ------------------------------------------------------------------ convite --

def test_convite_por_link(admin, caixa):
    r = admin.post("/admin/users", {"email": "nova@example.com"})
    assert r.status_code == 201, r.text
    res = r.json()
    assert res["emailed"] and "temp_password" not in res and "#convite=" in res["invite_url"]
    assert caixa[0][0] == "nova@example.com" and "#convite=" in caixa[0][2]
    token = _token(res["invite_url"], "convite")
    pend = next(u for u in admin.get("/admin/users").json() if u["email"] == "nova@example.com")
    assert pend["invite_pending"]

    anon = Api()
    assert anon.get(f"/auth/link?kind=invite&token={token}").json()["email"] == "nova@example.com"
    assert anon.get(f"/auth/link?kind=reset&token={token}").status_code == 404  # outro tipo não vale
    assert anon.post("/auth/invite/accept", {"token": token, "password": "curta"}).status_code == 422
    r = anon.post("/auth/invite/accept", {"token": token, "password": SENHA_NOVA, "display_name": "  Nova   Pessoa "})
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["email"] == "nova@example.com" and me["display_name"] == "Nova Pessoa" and not me["must_change_password"]
    assert anon.get("/auth/me").status_code == 200  # já entrou
    # Uso único; depois, entra com a senha criada.
    assert Api().post("/auth/invite/accept", {"token": token, "password": SENHA_NOVA}).status_code == 400
    Api().login("nova@example.com", SENHA_NOVA)
    pend = next(u for u in admin.get("/admin/users").json() if u["email"] == "nova@example.com")
    assert not pend["invite_pending"]


def test_reenviar_convite_invalida_o_anterior(admin, caixa):
    res = admin.post("/admin/users", {"email": "nova@example.com"}).json()
    velho = _token(res["invite_url"], "convite")
    uid = db.query_one("SELECT id FROM users WHERE email = 'nova@example.com'")["id"]
    novo = admin.post(f"/admin/users/{uid}/invite").json()
    assert novo["emailed"] and len(caixa) == 2
    assert Api().get(f"/auth/link?kind=invite&token={velho}").status_code == 404
    assert Api().get(f"/auth/link?kind=invite&token={_token(novo['invite_url'], 'convite')}").status_code == 200
    # Quem já aceitou não recebe outro.
    Api().post("/auth/invite/accept", {"token": _token(novo["invite_url"], "convite"), "password": SENHA_NOVA})
    assert admin.post(f"/admin/users/{uid}/invite").status_code == 400


def test_convite_vencido_e_faxina(admin, caixa):
    admin.post("/admin/users", {"email": "nova@example.com"})
    conta = lambda: next(u for u in admin.get("/admin/users").json() if u["email"] == "nova@example.com")
    assert conta()["invite_pending"] and not conta()["invite_expired"]
    db.execute("UPDATE auth_links SET expires_at = now() - interval '1 minute', created_at = now() - interval '40 days'")
    assert conta()["invite_expired"]
    Api().login(ADMIN_EMAIL, ADMIN_PW)  # o login faz a faxina dos links velhos
    assert db.query_one("SELECT count(*) AS n FROM auth_links")["n"] == 0
    uid = conta()["id"]
    assert admin.post(f"/admin/users/{uid}/invite").json()["emailed"]  # reenviar volta a valer
    assert not conta()["invite_expired"]


def test_convite_sem_email_continua_com_senha_temporaria(admin):
    res = admin.post("/admin/users", {"email": "nova@example.com"}).json()
    assert res["temp_password"] and "invite_url" not in res
    assert Api().login("nova@example.com", res["temp_password"]).json()["must_change_password"]


def test_convite_e_falha_de_envio(admin, monkeypatch):
    monkeypatch.setattr(mailer, "configured", lambda: True)

    def falha(*a, **k):
        raise mailer.MailError("falha no envio: teste")
    monkeypatch.setattr(mailer, "send", falha)
    res = admin.post("/admin/users", {"email": "nova@example.com"}).json()
    assert res["emailed"] is False and "#convite=" in res["invite_url"]  # o admin manda por outro canal


# ------------------------------------------------------------- recuperação --

def test_options_mostra_se_ha_email(monkeypatch):
    assert Api().get("/auth/options").json() == {"email": False, "invite_request": False}
    monkeypatch.setattr(mailer, "configured", lambda: True)
    assert Api().get("/auth/options").json() == {"email": True, "invite_request": True}


def test_esqueci_a_senha(usuario, caixa):
    email = usuario.me["email"]
    anon = Api()
    assert anon.post("/auth/forgot", {"email": "ninguem@example.com"}).json() == {"ok": True}  # mesma resposta
    assert caixa == []
    assert anon.post("/auth/forgot", {"email": email.upper()}).json() == {"ok": True}
    assert caixa[0][0] == email and "#senha=" in caixa[0][2]
    token = _token(caixa[0][2], "senha")
    assert anon.get(f"/auth/link?kind=reset&token={token}").json()["email"] == email
    r = anon.post("/auth/reset", {"token": token, "password": SENHA_NOVA})
    assert r.status_code == 200 and r.json()["email"] == email
    assert usuario.get("/auth/me").status_code == 401  # a sessão antiga caiu
    assert anon.post("/auth/reset", {"token": token, "password": SENHA_NOVA}).status_code == 400  # uso único
    assert Api().c.post("/api/auth/login", json={"email": email, "password": SENHA_PADRAO}).status_code == 401
    Api().login(email, SENHA_NOVA)


def test_esqueci_a_senha_limites(usuario, caixa, monkeypatch):
    for _ in range(3):
        assert Api().post("/auth/forgot", {"email": usuario.me["email"]}).status_code == 200
    assert Api().post("/auth/forgot", {"email": usuario.me["email"]}).status_code == 429
    # Só o último link vale.
    assert Api().get(f"/auth/link?kind=reset&token={_token(caixa[0][2], 'senha')}").status_code == 404
    assert Api().get(f"/auth/link?kind=reset&token={_token(caixa[-1][2], 'senha')}").status_code == 200


def test_esqueci_a_senha_sem_email():
    assert Api().post("/auth/forgot", {"email": ADMIN_EMAIL}).status_code == 400


def test_link_vencido(usuario, caixa):
    Api().post("/auth/forgot", {"email": usuario.me["email"]})
    db.execute("UPDATE auth_links SET expires_at = now() - interval '1 minute'")
    token = _token(caixa[0][2], "senha")
    assert Api().get(f"/auth/link?kind=reset&token={token}").status_code == 404
    assert Api().post("/auth/reset", {"token": token, "password": SENHA_NOVA}).status_code == 400


# ------------------------------------------------------- semanas passadas --

def test_semanas_anteriores(usuario):
    tid = usuario.post("/worklog", {"title": "Feita há duas semanas", "status": "done"}).json()["id"]
    db.execute("""UPDATE worklog_tasks SET created_at = now() - interval '14 days', completed_at = now() - interval '14 days'
                   WHERE id = %s""", (tid,))
    db.execute("UPDATE users SET created_at = now() - interval '60 days' WHERE id = %s", (uid_de(usuario),))
    atual = usuario.get("/summary/week").json()
    assert atual["back"] == 0 and atual["week"] == usuario.get("/summary").json()["week"]
    assert atual["oldest"] >= 8
    duas = usuario.get("/summary/week?back=2").json()["week"]
    assert duas["pontual_done"] == 1 and duas["deliveries"][0]["title"] == "Feita há duas semanas"
    assert (duas["end"] and duas["start"])
    uma = usuario.get("/summary/week?back=1").json()["week"]
    assert uma["previous"]["pontual_done"] == 1 and uma["pontual_done"] == 0
    assert usuario.get("/summary/week?back=999").status_code == 422


def test_mcp_semana_passada(usuario):
    from conftest import Bearer, criar_chave, texto
    tid = usuario.post("/worklog", {"title": "Feita há uma semana", "status": "done"}).json()["id"]
    db.execute("""UPDATE worklog_tasks SET created_at = now() - interval '7 days', completed_at = now() - interval '7 days'
                   WHERE id = %s""", (tid,))
    b = Bearer(criar_chave(usuario)["token"])
    r = b.tool("get_week", weeks_ago=1)
    assert not r["isError"] and "Feita há uma semana" in texto(r) and "semana anterior" in texto(r)
    assert b.tool("get_week", weeks_ago=-1)["isError"]
    assert "Não há registros" in texto(b.tool("get_week", weeks_ago=50))
