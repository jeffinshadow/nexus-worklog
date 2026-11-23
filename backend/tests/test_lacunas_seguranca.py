"""Checagens de segurança que a suíte deixava desligar sem falhar (auditoria, testes-qualidade #2).
Cada teste passa no código certo e falha com a checagem correspondente desligada (prova por mutação)."""
import re

from app import db
from tests.conftest import SENHA_PADRAO, Api, uid_de


def test_sessao_vencida_responde_401_e_some(usuario):
    assert usuario.get("/board").status_code == 200
    db.execute("UPDATE sessions SET expires_at = now() - interval '1 second' WHERE user_id = %s", (uid_de(usuario),))
    n = db.query_one("SELECT count(*)::int AS n FROM sessions WHERE user_id = %s", (uid_de(usuario),))["n"]
    r = usuario.get("/board")
    assert r.status_code == 401 and "expirada" in r.text
    # A sessão vencida usada some do banco (as outras saem na faxina do login).
    assert db.query_one("SELECT count(*)::int AS n FROM sessions WHERE user_id = %s", (uid_de(usuario),))["n"] == n - 1


def test_conta_bloqueada_nao_entra_nem_com_a_senha_certa(usuario):
    """A segunda tranca do bloqueio (auth.py): mesmo que a senha fosse conhecida, o login responde 403."""
    db.execute("UPDATE users SET blocked_at = now() WHERE id = %s", (uid_de(usuario),))
    r = Api().c.post("/api/auth/login", json={"email": "colega@example.com", "password": SENHA_PADRAO})
    assert r.status_code == 403 and "bloqueado" in r.text
    assert "set-cookie" not in r.headers


def test_trocar_senha_exige_a_senha_atual_e_tem_limite(usuario):
    r = usuario.post("/auth/change-password", {"current_password": "Errada-Mesmo-123", "new_password": "Outra-Senha-Nova-1"})
    assert r.status_code == 400 and "senha atual incorreta" in r.text
    assert Api().c.post("/api/auth/login", json={"email": "colega@example.com", "password": "Outra-Senha-Nova-1"}).status_code == 401
    # Sessão roubada não testa senhas à vontade: depois de 10 tentativas, 429 (mesmo com a senha certa).
    for _ in range(9):
        usuario.post("/auth/change-password", {"current_password": "Errada-Mesmo-123", "new_password": "Outra-Senha-Nova-1"})
    r = usuario.post("/auth/change-password", {"current_password": SENHA_PADRAO, "new_password": "Outra-Senha-Nova-1"})
    assert r.status_code == 429


def test_aparelho_de_outra_pessoa_nao_e_removido(usuario, novo_usuario):
    outro = novo_usuario("outro@example.com")
    db.execute("""INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, label)
                  VALUES (%s, 'https://fcm.googleapis.com/fcm/send/x', 'p', 'a', 'Chrome')""", (uid_de(usuario),))
    did = db.query_one("SELECT id FROM push_subscriptions")["id"]
    assert outro.delete(f"/push/devices/{did}").status_code == 404
    assert db.query_one("SELECT 1 FROM push_subscriptions WHERE id = %s", (did,))
    assert usuario.delete(f"/push/devices/{did}").status_code == 200


def test_passkey_de_outra_pessoa_nao_e_removida(usuario, novo_usuario):
    outro = novo_usuario("outro@example.com")
    db.execute("""INSERT INTO webauthn_credentials (user_id, credential_id, public_key, sign_count, name)
                  VALUES (%s, %s, %s, 0, 'Celular')""", (uid_de(usuario), b"cred-1", b"pk"))
    pid = db.query_one("SELECT id FROM webauthn_credentials")["id"]
    assert outro.delete(f"/auth/passkeys/{pid}").status_code == 404
    assert db.query_one("SELECT 1 FROM webauthn_credentials WHERE id = %s", (pid,))


def _link(caixa, chave):
    return re.search(chave + r"=([\w-]+)", caixa[-1][2]).group(1)


def test_link_de_senha_vencido_ou_usado_nao_vale(usuario, caixa):
    anon = Api()
    assert anon.post("/auth/forgot", {"email": "colega@example.com"}).status_code == 200
    tok = _link(caixa, "senha")
    db.execute("UPDATE auth_links SET expires_at = now() - interval '1 second' WHERE kind = 'reset'")
    assert anon.post("/auth/link", {"kind": "reset", "token": tok}).status_code == 404
    assert anon.post("/auth/reset", {"token": tok, "password": "Senha-Pelo-Link-1"}).status_code == 400
    db.execute("UPDATE auth_links SET expires_at = now() + interval '1 hour' WHERE kind = 'reset'")
    assert anon.post("/auth/reset", {"token": tok, "password": "Senha-Pelo-Link-1"}).status_code == 200
    # Uso único: o mesmo link não troca a senha de novo.
    assert Api().post("/auth/reset", {"token": tok, "password": "Senha-Pelo-Link-2"}).status_code == 400
    assert Api().c.post("/api/auth/login", json={"email": "colega@example.com", "password": "Senha-Pelo-Link-2"}).status_code == 401


def test_convite_vencido_nao_cria_senha(admin, caixa):
    assert admin.post("/admin/users", {"email": "nova@example.com"}).status_code == 201
    tok = _link(caixa, "convite")
    db.execute("UPDATE auth_links SET expires_at = now() - interval '1 second' WHERE kind = 'invite'")
    assert Api().post("/auth/invite/accept", {"token": tok, "password": "Senha-Do-Convite-1"}).status_code == 400
    assert db.query_one("SELECT invite_pending FROM users WHERE email = 'nova@example.com'")["invite_pending"]


def test_links_tem_limite_de_tentativas_por_ip(admin):
    anon = Api()
    for _ in range(30):
        assert anon.post("/auth/reset", {"token": "x" * 43, "password": "Senha-Pelo-Link-1"}).status_code == 400
    r = anon.post("/auth/reset", {"token": "x" * 43, "password": "Senha-Pelo-Link-1"})
    assert r.status_code == 429 and r.headers["Retry-After"]
    assert anon.post("/auth/invite/accept", {"token": "x" * 43, "password": "Senha-Pelo-Link-1"}).status_code == 429


def test_sair_mata_a_sessao_no_servidor(usuario):
    """Cookie copiado antes do logout não vale depois (o logout apaga a sessão no banco, não só o cookie)."""
    from app.config import config
    roubado = usuario.c.cookies.get(config.SESSION_COOKIE)
    assert usuario.post("/auth/logout").status_code == 200
    ladrao = Api()
    ladrao.c.cookies.set(config.SESSION_COOKIE, roubado)
    assert ladrao.get("/auth/me").status_code == 401


def test_cookie_de_sessao_e_httponly_e_samesite_strict(usuario):
    r = Api().c.post("/api/auth/login", json={"email": "colega@example.com", "password": SENHA_PADRAO})
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc and "path=/" in sc
