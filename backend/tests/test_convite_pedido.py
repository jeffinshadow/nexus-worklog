"""Pedido de convite pela tela de login: só com e-mail, sem revelar contas,
um aberto por e-mail, armadilha para robôs, admin convida ou recusa; e o tema."""
from app import db, mailer, push
from conftest import Api


def _corpo(**kw):
    return {"name": "Ana Souza", "email": "ana@empresa.com.br", "source": "colega",
            "reason": "Quero registrar o suporte da filial e tirar o relatório do mês.", **kw}


def test_sem_email_configurado_nao_existe(monkeypatch):
    monkeypatch.setattr(mailer, "configured", lambda: False)
    assert Api().post("/auth/invite-request", _corpo()).status_code == 404
    assert Api().get("/auth/options").json()["invite_request"] is False


def test_pedido_chega_ao_admin_e_ele_convida(monkeypatch, admin):
    monkeypatch.setattr(mailer, "configured", lambda: True)
    enviados, notificados = [], []
    monkeypatch.setattr(mailer, "send", lambda to, subj, *a, **k: enviados.append((to, subj)))
    monkeypatch.setattr(push, "send", lambda uid, msg, **k: notificados.append((uid, msg["title"])) or 1)
    import app.routers.invite_requests as ir
    monkeypatch.setattr(ir.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda self: target()})())
    assert Api().get("/auth/options").json()["invite_request"] is True
    assert Api().post("/auth/invite-request", _corpo()).status_code == 202
    assert any(s.startswith("Pedido de convite") for _, s in enviados)          # admin avisado por e-mail
    assert any(to == "ana@empresa.com.br" for to, _ in enviados)               # quem pediu recebe a confirmação
    assert notificados and notificados[0][1] == "Pedido de convite"
    lista = admin.get("/admin/invite-requests").json()
    assert lista[0]["name"] == "Ana Souza" and lista[0]["status"] == "pending"
    # pedir de novo com o mesmo e-mail: mesma resposta, nenhum pedido novo
    assert Api().post("/auth/invite-request", _corpo(name="Ana")).status_code == 202
    assert len([r for r in admin.get("/admin/invite-requests").json() if r["status"] == "pending"]) == 1
    r = admin.post(f"/admin/invite-requests/{lista[0]['id']}/invite")
    assert r.status_code == 200, r.text
    assert "invite_url" in r.json()
    u = db.query_one("SELECT display_name, invite_pending FROM users WHERE email = 'ana@empresa.com.br'")
    assert u["display_name"] == "Ana Souza" and u["invite_pending"]
    assert admin.post(f"/admin/invite-requests/{lista[0]['id']}/invite").status_code == 404  # já decidido


def test_conta_existente_e_robo_nao_viram_pedido(monkeypatch, admin, usuario):
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda *a, **k: None)
    assert Api().post("/auth/invite-request", _corpo(email=usuario.me["email"])).status_code == 202
    assert Api().post("/auth/invite-request", _corpo(email="bot@spam.example", website="http://x")).status_code == 202
    assert admin.get("/admin/invite-requests").json() == []


def test_recusar_e_so_admin_ve(monkeypatch, admin, usuario):
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda *a, **k: None)
    Api().post("/auth/invite-request", _corpo())
    rid = db.query_one("SELECT id FROM invite_requests")["id"]
    assert usuario.get("/admin/invite-requests").status_code == 403
    assert admin.post(f"/admin/invite-requests/{rid}/decline").status_code == 200
    assert db.query_one("SELECT status FROM invite_requests WHERE id = %s", (rid,))["status"] == "declined"


def test_limite_por_email(monkeypatch):
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda *a, **k: None)
    codes = [Api().post("/auth/invite-request", _corpo(email="mesmo@x.com.br")).status_code for _ in range(3)]
    assert codes[-1] == 429


def test_tema_da_conta(usuario):
    assert usuario.get("/auth/me").json()["theme"] == "auto"
    assert usuario.put("/me/theme", {"theme": "light"}).status_code == 200
    assert usuario.get("/auth/me").json()["theme"] == "light"
    assert usuario.put("/me/theme", {"theme": "rosa"}).status_code == 422
