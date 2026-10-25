"""Gauntlet noturno R1: exclusão de conta (LGPD), saúde, erros do navegador e links diretos."""
from app import db, mailer
from app.routers import assign as assign_mod
from conftest import Bearer, criar_chave, hist, uid_de


def _conta(email):
    return db.query_one("SELECT id FROM users WHERE email = %s", (email,))


def test_admin_exclui_conta_com_confirmacao(admin, usuario):
    uid = uid_de(usuario)
    usuario.post("/worklog", {"title": "Dado da pessoa"})
    r = admin.post(f"/admin/users/{uid}/delete", {"confirm_email": "outro@example.com"})
    assert r.status_code == 400 and "e-mail" in r.json()["detail"]
    assert usuario.post(f"/admin/users/{uid}/delete", {"confirm_email": usuario.me["email"]}).status_code == 403
    r = admin.post(f"/admin/users/{uid}/delete", {"confirm_email": usuario.me["email"].upper()})
    assert r.status_code == 200 and r.json()["tasks"] == 1
    assert _conta(usuario.me["email"]) is None
    assert db.query_one("SELECT count(*)::int AS n FROM worklog_tasks WHERE user_id = %s", (uid,))["n"] == 0
    assert usuario.get("/board").status_code == 401  # sessão foi junto
    assert any(h["action"] == "user.delete" and usuario.me["email"] in h["summary"] for h in hist(admin))


def test_admin_nao_exclui_a_si_nem_o_ultimo_admin(admin, novo_usuario):
    eu = uid_de(admin)
    assert admin.post(f"/admin/users/{eu}/delete", {"confirm_email": admin.me["email"]}).status_code == 400
    outro = novo_usuario("outro.admin@example.com")
    admin.put(f"/admin/users/{uid_de(outro)}/roles", {"roles": ["user", "admin"]})
    # Com dois admins, um pode excluir o outro.
    assert admin.post(f"/admin/users/{uid_de(outro)}/delete", {"confirm_email": "outro.admin@example.com"}).status_code == 200


def test_pessoa_exclui_a_propria_conta(admin, usuario, novo_usuario, monkeypatch):
    # Tarefa que a pessoa atribuiu fica com quem recebeu.
    monkeypatch.setattr(mailer, "configured", lambda: False)
    alvo = novo_usuario("alvo@example.com")
    alvo.put("/me/assignments", {"accept": True})
    admin.put(f"/admin/users/{uid_de(usuario)}/roles", {"roles": ["user", "assigner"]})
    tid = usuario.post("/assign", {"user_id": uid_de(alvo), "title": "Fica com o alvo"}).json()["id"]
    assert usuario.post("/me/delete", {"password": "errada-123456"}).status_code == 400
    ia = Bearer(criar_chave(usuario)["token"])
    assert ia.post("/me/delete", {"password": "x"}).status_code == 403  # só pelo app
    r = usuario.post("/me/delete", {"password": "Senha-Do-Usuario-1"})
    assert r.status_code == 200
    assert _conta(usuario.me["email"]) is None
    t = alvo.get(f"/worklog/{tid}").json()
    assert t["title"] == "Fica com o alvo" and t["assigned_by"] is None


def test_ultimo_admin_nao_se_exclui(admin):
    r = admin.post("/me/delete", {"password": "Admin-Definitiva-Teste-1"})
    assert r.status_code == 400 and "único admin" in r.json()["detail"]


def test_health_e_erros_do_navegador(usuario, caplog):
    assert usuario.c.get("/api/health").json() == {"ok": True}
    assert usuario.post("/client-errors", {"message": "TypeError: x is undefined\nlinha 2", "where": "#/hoje"}).status_code == 204
    assert any("erro no navegador" in r.getMessage() and "linha 2" in r.getMessage() for r in caplog.records)
    for _ in range(15):
        usuario.post("/client-errors", {"message": "repete"})
    assert sum("repete" in r.getMessage() for r in caplog.records) <= 10  # limitado
    assert usuario.post("/client-errors", {"message": "x" * 400}).status_code == 422
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).post("/api/client-errors", json={"message": "x"}).status_code == 401


def test_links_diretos_para_a_tarefa(admin, usuario, novo_usuario, monkeypatch):
    enviados = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(assign_mod, "_spawn", lambda to, mail: enviados.append(mail.text()))
    chefe = novo_usuario("chefe@example.com")
    admin.put(f"/admin/users/{uid_de(chefe)}/roles", {"roles": ["user", "assigner"]})
    usuario.put("/me/assignments", {"accept": True})
    tid = chefe.post("/assign", {"user_id": uid_de(usuario), "title": "Link"}).json()["id"]
    assert f"#/tarefas?id={tid}" in enviados[0]
    t2 = usuario.post("/worklog", {"title": "Com prazo", "due_date": "2030-01-01"}).json()["id"]
    ics = usuario.c.get(usuario.post("/calendar", {}).json()["path"]).text
    assert f"#/tarefas?id={t2}" in ics.replace("\r\n ", "")


def test_contato_de_suporte(admin, usuario):
    assert admin.put("/admin/settings", {"retro_days": 60, "support_contact": "  ramal   2040 "}).status_code == 200
    assert usuario.get("/auth/me").json()["support_contact"] == "ramal 2040"
