"""Auditoria, pacote p01: admin inicial, limitador de tentativas, Retry-After,
push ao sair, "Esqueci a senha" (tempo e conta bloqueada), senhas triviais e
dias úteis."""
import re

import pytest

import app.routers.auth as auth_mod
from app import db, mailer, main, security
from app.security import RateLimiter, weak_password
from conftest import ADMIN_EMAIL, ADMIN_PW_INICIAL, SENHA_PADRAO, Api, uid_de


@pytest.fixture(autouse=True)
def _limite_da_passkey_zerado():
    security.passkey_options_limiter._hits.clear()  # o conftest ainda não conhece este limitador
    yield


class _Agora:
    """threading.Thread que roda na hora (o trabalho em segundo plano vira síncrono)."""

    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@pytest.fixture
def caixa(monkeypatch):
    enviados = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None: enviados.append((to, subject, text)))
    monkeypatch.setattr(auth_mod.threading, "Thread", _Agora)
    return enviados


def _entrar(email, senha):
    return Api().post("/auth/login", {"email": email, "password": senha})


# ------------------------------------------------------------ admin inicial --

def test_seed_admin_nao_recria_com_admin_existente(admin):
    # O admin trocou o próprio e-mail: o do .env não existe mais, mas há um admin.
    db.execute("UPDATE users SET email = 'dona@example.com' WHERE email = %s", (ADMIN_EMAIL,))
    main.seed_admin()
    assert not db.query_one("SELECT 1 FROM users WHERE email = %s", (ADMIN_EMAIL,))
    assert db.query_one("SELECT count(*)::int AS n FROM users")["n"] == 1
    assert _entrar(ADMIN_EMAIL, ADMIN_PW_INICIAL).status_code == 401


def test_seed_admin_cria_quando_nao_ha_admin():
    db.execute("TRUNCATE users RESTART IDENTITY CASCADE")
    main.seed_admin()
    u = db.query_one("SELECT id, role, must_change_password FROM users WHERE email = %s", (ADMIN_EMAIL,))
    assert u["role"] == "admin" and u["must_change_password"]
    main.seed_admin()  # de novo: nada muda
    assert db.query_one("SELECT count(*)::int AS n FROM users")["n"] == 1


# ---------------------------------------------------------------- limitador --

def test_limitador_cheio_deixa_passar_chave_nova_e_mantem_a_bloqueada():
    lim = RateLimiter(max_hits=2, window_seconds=60)
    lim._PRUNE_AT = 3
    assert lim.allow("a") and lim.allow("a") and not lim.allow("a")  # "a" estourou
    assert lim.allow("b") and lim.allow("c")                         # cheio (3 chaves vivas)
    assert lim.allow("nova")                                          # cheio não recusa quem chega
    assert lim.blocked("a") and not lim.allow("a")                    # o bloqueio continua
    assert "b" not in lim._hits and "c" not in lim._hits              # as que não estouraram saíram
    for i in range(50):                                               # e segue aceitando chaves novas
        assert lim.allow(f"k{i}")
    assert lim.blocked("a") and len(lim._hits) <= 4


def test_onze_logins_certos_do_mesmo_ip_passam(usuario):
    for _ in range(11):
        assert _entrar(usuario.me["email"], SENHA_PADRAO).status_code == 200


def test_dez_falhas_do_mesmo_ip_bloqueiam_e_o_retry_after_diz_quanto_falta(usuario, monkeypatch):
    for i in range(10):  # e-mails diferentes: quem estoura é a chave do IP
        assert _entrar(f"ninguem{i}@example.com", "senha-errada-123").status_code == 401
    r = _entrar(usuario.me["email"], SENHA_PADRAO)
    assert r.status_code == 429
    assert 290 <= int(r.headers["Retry-After"]) <= 300
    assert r.json()["detail"] == "Muitas tentativas. Espere 5 minutos."
    # 200 s depois faltam uns 100 s: o cabeçalho e a frase acompanham.
    agora = security.time.monotonic()
    monkeypatch.setattr(security.time, "monotonic", lambda: agora + 200)
    r = _entrar(usuario.me["email"], SENHA_PADRAO)
    assert r.status_code == 429 and 90 <= int(r.headers["Retry-After"]) <= 100
    assert r.json()["detail"] == "Muitas tentativas. Espere 2 minutos."
    monkeypatch.setattr(security.time, "monotonic", lambda: agora + 301)
    assert _entrar(usuario.me["email"], SENHA_PADRAO).status_code == 200


def test_tetos_por_email_nao_mudaram(usuario):
    assert (security.login_limiter.max, security.login_limiter.window) == (10, 300)
    assert (security.login_email_limiter.max, security.login_email_limiter.window) == (100, 300)
    email = usuario.me["email"]
    for _ in range(10):
        assert _entrar(email, "senha-errada-123").status_code == 401
    assert _entrar(email, SENHA_PADRAO).status_code == 429  # e-mail+IP (e IP) estourados


def test_abrir_a_tela_de_login_nao_gasta_o_limite_do_login(usuario):
    a = Api()
    for _ in range(30):
        assert a.post("/auth/passkeys/login/options").status_code == 200
    assert _entrar(usuario.me["email"], SENHA_PADRAO).status_code == 200
    for _ in range(30):
        assert a.post("/auth/passkeys/login/options").status_code == 200
    r = a.post("/auth/passkeys/login/options")  # o limite próprio: 60 em 5 min
    assert r.status_code == 429 and 1 <= int(r.headers["Retry-After"]) <= 300
    assert _entrar(usuario.me["email"], SENHA_PADRAO).status_code == 200


def test_passkey_errada_conta_como_falha_do_ip(usuario):
    a = Api()
    for _ in range(10):
        o = a.post("/auth/passkeys/login/options").json()
        r = a.post("/auth/passkeys/login", {"challenge_id": o["challenge_id"], "credential": {"id": "AAAA", "rawId": "AAAA"}})
        assert r.status_code == 401
    o = a.post("/auth/passkeys/login/options").json()
    r = a.post("/auth/passkeys/login", {"challenge_id": o["challenge_id"], "credential": {"id": "AAAA", "rawId": "AAAA"}})
    assert r.status_code == 429 and "Retry-After" in r.headers


# ------------------------------------------------------------- push ao sair --

def _inscrever(uid, nome):
    db.execute("INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, label) VALUES (%s, %s, 'p', 'a', %s)",
               (uid, "https://fcm.googleapis.com/fcm/send/" + nome, nome))


def _inscricoes(uid):
    return sorted(r["label"] for r in db.query_all("SELECT label FROM push_subscriptions WHERE user_id = %s", (uid,)))


def test_sair_dos_outros_aparelhos_apaga_as_inscricoes_push(usuario, admin):
    uid = uid_de(usuario)
    _inscrever(uid, "celular-perdido")
    _inscrever(uid, "este")
    _inscrever(uid_de(admin), "do-admin")
    r = usuario.post("/auth/logout-others")
    assert r.status_code == 200, r.text
    assert _inscricoes(uid) == [] and _inscricoes(uid_de(admin)) == ["do-admin"]


def test_sair_apaga_a_inscricao_do_aparelho_quando_o_endpoint_vem(usuario, admin):
    uid = uid_de(usuario)
    _inscrever(uid, "este")
    _inscrever(uid, "outro")
    _inscrever(uid_de(admin), "do-admin")
    # endpoint de outra conta não apaga nada dela
    outro = Api()
    outro.login(usuario.me["email"], SENHA_PADRAO)
    r = outro.post("/auth/logout", {"endpoint": "https://fcm.googleapis.com/fcm/send/do-admin"})
    assert r.status_code == 200 and _inscricoes(uid_de(admin)) == ["do-admin"] and _inscricoes(uid) == ["este", "outro"]
    r = usuario.post("/auth/logout", {"endpoint": "https://fcm.googleapis.com/fcm/send/este"})
    assert r.status_code == 200, r.text
    assert _inscricoes(uid) == ["outro"]
    assert usuario.get("/auth/me").status_code == 401


def test_sair_sem_corpo_continua_valendo(usuario):
    _inscrever(uid_de(usuario), "este")
    uid = uid_de(usuario)
    assert usuario.post("/auth/logout").status_code == 200
    assert usuario.get("/auth/me").status_code == 401 and _inscricoes(uid) == ["este"]


# ---------------------------------------------------------- esqueci a senha --

def test_forgot_de_conta_bloqueada_manda_o_aviso_e_responde_igual(admin, usuario, caixa):
    email = usuario.me["email"]
    assert admin.post(f"/admin/users/{uid_de(usuario)}/block").status_code == 200
    caixa.clear()
    r = Api().post("/auth/forgot", {"email": email})
    assert r.status_code == 200 and r.json() == Api().post("/auth/forgot", {"email": "ninguem@example.com"}).json() == {"ok": True}
    assert len(caixa) == 1
    para, assunto, texto = caixa[0]
    assert para == email and "bloqueado" in assunto
    assert "Seu acesso ao Nexus está bloqueado por quem administra. Para voltar a entrar, peça que libere o acesso." in texto
    assert "#senha=" not in texto
    assert not db.query_one("SELECT 1 FROM auth_links WHERE kind = 'reset' AND used_at IS NULL")
    # mesmos limites: 3 por hora por e-mail
    assert Api().post("/auth/forgot", {"email": email}).status_code == 200
    assert Api().post("/auth/forgot", {"email": email}).status_code == 200
    assert Api().post("/auth/forgot", {"email": email}).status_code == 429


def test_forgot_responde_antes_de_consultar_a_conta(usuario, monkeypatch):
    enviados, fila = [], []

    class Depois:
        def __init__(self, target, args=(), daemon=None):
            self.target, self.args = target, args

        def start(self):
            fila.append(self)

    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None: enviados.append((to, subject, text)))
    monkeypatch.setattr(auth_mod.threading, "Thread", Depois)
    assert Api().post("/auth/forgot", {"email": usuario.me["email"]}).json() == {"ok": True}
    assert Api().post("/auth/forgot", {"email": "ninguem@example.com"}).json() == {"ok": True}
    # A resposta saiu e nada foi feito ainda: link, histórico e e-mail ficam para a thread, nos dois casos.
    assert len(fila) == 2 and not enviados and not db.query_one("SELECT 1 FROM auth_links WHERE kind = 'reset'")
    for t in fila:
        t.start = None
        t.target(*t.args)
    assert len(enviados) == 1 and enviados[0][0] == usuario.me["email"] and "#senha=" in enviados[0][2]
    assert db.query_one("SELECT 1 FROM audit_log WHERE action = 'password.forgot'")


# ---------------------------------------------------------- senhas triviais --

TRIVIAIS = ["1234567890", "0000000000", "aaaaaaaaaa", "9876543210", "0123456789012", "1212121212", "123123123123",
            "nexusnexus", "NexusNexusNexus"]


def test_weak_password():
    for s in TRIVIAIS:
        assert weak_password(s, "ana@example.com"), s
    assert weak_password("Ana.Souza@Example.com", "ana.souza@example.com")
    for s in [SENHA_PADRAO, "3141592653", "1357924680", "nexus-worklog", "aaaaaaaaab", "outra@example.com", "2026202620261"]:
        assert not weak_password(s, "ana@example.com"), s


def test_troca_de_senha_recusa_trivial(usuario):
    email = usuario.me["email"]
    for nova in TRIVIAIS[:3] + ["nexusnexus", email, email.upper()]:
        r = usuario.post("/auth/change-password", {"current_password": SENHA_PADRAO, "new_password": nova})
        assert r.status_code == 400 and r.json()["detail"] == "Essa senha é fácil de adivinhar.", (nova, r.text)
    security.login_limiter._hits.clear()
    assert _entrar(email, SENHA_PADRAO).status_code == 200  # a senha não mudou
    r = usuario.post("/auth/change-password", {"current_password": SENHA_PADRAO, "new_password": "Outra-Senha-Boa-2"})
    assert r.status_code == 200, r.text


def test_convite_recusa_trivial_sem_gastar_o_link(admin, caixa):
    r = admin.post("/admin/users", {"email": "nova@example.com"})
    token = r.json()["invite_url"].split("#convite=")[1]
    for senha in ["1234567890", "aaaaaaaaaa", "nova@example.com", "nexusnexus"]:
        r = Api().post("/auth/invite/accept", {"token": token, "password": senha})
        assert r.status_code == 400 and r.json()["detail"] == "Essa senha é fácil de adivinhar.", (senha, r.text)
    assert Api().post("/auth/invite/accept", {"token": token, "password": SENHA_PADRAO}).status_code == 200


def test_redefinicao_recusa_trivial_sem_gastar_o_link(usuario, caixa):
    email = usuario.me["email"]
    assert Api().post("/auth/forgot", {"email": email}).status_code == 200
    token = re.search(r"#senha=([\w-]+)", caixa[-1][2]).group(1)
    for senha in ["0000000000", "zzzzzzzzzzzz", email, "nexusnexusnexus"]:
        r = Api().post("/auth/reset", {"token": token, "password": senha})
        assert r.status_code == 400 and r.json()["detail"] == "Essa senha é fácil de adivinhar.", (senha, r.text)
    assert Api().post("/auth/reset", {"token": token, "password": "Senha-Nova-Do-Link-3"}).status_code == 200
    assert _entrar(email, "Senha-Nova-Do-Link-3").status_code == 200


# --------------------------------------------------------------- dias úteis --

def test_dias_uteis_le_o_valor_do_banco_e_nao_repete_o_trabalho(usuario):
    uid = uid_de(usuario)
    atual = usuario.me["work_days"]
    novo = 126 if atual != 126 else 62
    assert usuario.post("/auth/settings", {"work_days": novo}).json() == {"ok": True, "work_days": novo}
    n = db.query_one("SELECT count(*)::int AS n FROM audit_log WHERE action = 'settings.update' AND user_id = %s", (uid,))["n"]
    assert n == 1
    # Mesmo pedido de novo (duplo clique): nada a fazer, nenhuma linha nova no histórico.
    assert usuario.post("/auth/settings", {"work_days": novo}).json() == {"ok": True, "work_days": novo}
    assert db.query_one("SELECT count(*)::int AS n FROM audit_log WHERE action = 'settings.update' AND user_id = %s", (uid,))["n"] == n
    assert db.query_one("SELECT work_days FROM users WHERE id = %s", (uid,))["work_days"] == novo
