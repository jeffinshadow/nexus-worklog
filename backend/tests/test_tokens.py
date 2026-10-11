from app import db
from conftest import Bearer, criar_chave


def test_chave_aparece_uma_vez_e_banco_guarda_so_hash(usuario):
    k = criar_chave(usuario)
    assert k["token"].startswith("nxs_") and len(k["token"]) > 40
    lista = usuario.get("/tokens").json()
    assert "token" not in lista[0] and lista[0]["prefix"] == k["token"][:10]
    assert not db.query_one("SELECT 1 FROM api_tokens WHERE token_hash = %s", (k["token"],))


def test_chave_escrita_usa_api_sem_csrf(usuario):
    b = Bearer(criar_chave(usuario)["token"])
    assert b.post("/worklog", {"title": "Pela IA"}).status_code == 201
    assert any(t["title"] == "Pela IA" for t in usuario.get("/board").json()["in_progress"])


def test_chave_leitura_nao_altera(usuario):
    b = Bearer(criar_chave(usuario, scope="read")["token"])
    assert b.get("/board").status_code == 200
    assert b.post("/worklog", {"title": "x"}).status_code == 403


def test_chave_nao_acessa_admin_nem_gerencia_chaves_nem_senha(admin):
    b = Bearer(criar_chave(admin)["token"])
    assert b.get("/admin/users").status_code == 403
    assert b.get("/tokens").status_code == 403
    assert b.post("/tokens", {"name": "outra"}).status_code == 403
    assert b.post("/auth/change-password", {"current_password": "x", "new_password": "y" * 12}).status_code == 403


def test_revogada_e_vencida_param_de_funcionar(usuario):
    k = criar_chave(usuario)
    b = Bearer(k["token"])
    assert b.get("/board").status_code == 200
    assert usuario.delete(f"/tokens/{k['id']}").status_code == 200
    assert b.get("/board").status_code == 401
    k2 = criar_chave(usuario, nome="vence")
    db.execute("UPDATE api_tokens SET expires_at = now() - interval '1 minute' WHERE id = %s", (k2["id"],))
    assert Bearer(k2["token"]).get("/board").status_code == 401


def test_chave_invalida_e_de_outro_usuario(usuario, novo_usuario):
    assert Bearer("nxs_inventada").get("/board").status_code == 401
    k = criar_chave(usuario)
    outro = novo_usuario("outro@example.com")
    assert outro.delete(f"/tokens/{k['id']}").status_code == 404


def test_ultimo_uso_registrado(usuario):
    k = criar_chave(usuario)
    Bearer(k["token"]).get("/board")
    assert usuario.get("/tokens").json()[0]["last_used_at"] is not None
