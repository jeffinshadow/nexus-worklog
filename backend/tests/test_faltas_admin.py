"""Pequenas faltas do Admin (sql/037): último acesso e ordem por nome nas
Contas, link de nova senha mandado pelo admin, pedido de convite que o admin
desliga (e origens genéricas), transferir as tarefas abertas de quem sai e o
aviso de papel ganho ou retirado."""
import re
from datetime import datetime, timedelta, timezone

import pytest

from app import db, mailer
from app.routers import auth as auth_mod
from conftest import ligar_pedido_convite, Api, SENHA_PADRAO, hist, uid_de


class _Agora:
    """threading.Thread que roda na hora (o envio em segundo plano vira síncrono)."""

    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@pytest.fixture
def caixa(monkeypatch):
    enviados = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None, **kw: enviados.append((to, subject, text)))
    monkeypatch.setattr(auth_mod.threading, "Thread", _Agora)
    return enviados


def _conta(admin, email):
    return next(u for u in admin.get("/admin/users").json() if u["email"] == email)


# --------------------------------------------------------------- último acesso e ordem --

def test_contas_com_ultimo_acesso_criacao_e_ordem_por_nome(admin, novo_usuario):
    novo_usuario("zeca@example.com")
    b = novo_usuario("bruno@example.com")
    db.execute("UPDATE users SET display_name = 'Álvaro Zeca' WHERE email = 'zeca@example.com'")
    convite = admin.post("/admin/users", {"email": "carla@example.com", "display_name": "Carla"})
    assert convite.status_code == 201
    lista = admin.get("/admin/users").json()
    nomes = [u["name"] for u in lista]
    assert nomes == sorted(nomes, key=lambda n: n.replace("Á", "A").casefold())  # sem acento, sem caixa
    assert nomes.index("Álvaro Zeca") < nomes.index("Carla")
    bruno = _conta(admin, "bruno@example.com")
    assert bruno["last_seen_at"] and bruno["created_at"] and bruno["open_tasks"] == 0
    assert _conta(admin, "carla@example.com")["last_seen_at"] is None  # nunca entrou
    b.post("/worklog", {"title": "Aberta"})
    assert _conta(admin, "bruno@example.com")["open_tasks"] == 1


def test_ultimo_acesso_grava_no_maximo_a_cada_5_minutos(usuario):
    uid = uid_de(usuario)
    velho = datetime.now(timezone.utc) - timedelta(hours=3)
    db.execute("UPDATE users SET last_seen_at = %s WHERE id = %s", (velho, uid))
    usuario.get("/auth/me")
    agora = db.query_one("SELECT last_seen_at FROM users WHERE id = %s", (uid,))["last_seen_at"]
    assert agora > velho + timedelta(hours=2)
    recente = datetime.now(timezone.utc) - timedelta(minutes=2)
    db.execute("UPDATE users SET last_seen_at = %s WHERE id = %s", (recente, uid))
    usuario.get("/auth/me")
    assert db.query_one("SELECT last_seen_at FROM users WHERE id = %s", (uid,))["last_seen_at"] == recente


def test_lista_de_contas_so_para_admin(usuario):
    assert usuario.get("/admin/users").status_code == 403


# ------------------------------------------------------------ redefinir senha por link --

def test_link_de_nova_senha_exige_email(admin, usuario):
    r = admin.post(f"/admin/users/{uid_de(usuario)}/reset-password", {"method": "link"})
    assert r.status_code == 400 and "senha temporária" in r.json()["detail"]


def test_admin_manda_link_de_nova_senha(admin, usuario, caixa):
    uid = uid_de(usuario)
    r = admin.post(f"/admin/users/{uid}/reset-password", {"method": "link"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["method"] == "link" and out["emailed"] is True and "temp_password" not in out
    para, assunto, corpo = caixa[-1]
    assert para == usuario.me["email"] and "senha nova" in assunto.lower() and "24 horas" in corpo
    token = re.search(r"senha=([\w-]+)", corpo).group(1)
    # Vale 24 horas (o "Esqueci a senha" vale 1).
    exp = db.query_one("SELECT expires_at FROM auth_links WHERE user_id = %s AND kind = 'reset' AND used_at IS NULL", (uid,))
    assert exp["expires_at"] > datetime.now(timezone.utc) + timedelta(hours=23)
    # A senha antiga já não vale e a sessão aberta caiu.
    assert usuario.get("/auth/me").status_code == 401
    assert Api().c.post("/api/auth/login", json={"email": usuario.me["email"], "password": SENHA_PADRAO}).status_code == 401
    me = Api().post("/auth/reset", {"token": token, "password": "Senha-Nova-Pelo-Link-1"}).json()
    assert me["email"] == usuario.me["email"] and me["must_change_password"] is False
    log = db.query_one("SELECT after FROM audit_log WHERE action = 'user.reset_password' ORDER BY id DESC LIMIT 1")
    assert log["after"]["method"] == "link"


def test_liberar_acesso_por_link(admin, usuario, caixa):
    uid = uid_de(usuario)
    assert admin.post(f"/admin/users/{uid}/block").status_code == 200
    r = admin.post(f"/admin/users/{uid}/reset-password", {"method": "link"}).json()
    assert "liberado" in caixa[-1][1].lower() or "liberou" in caixa[-1][2]
    assert db.query_one("SELECT blocked_at FROM users WHERE id = %s", (uid,))["blocked_at"] is None
    token = r["reset_url"].split("#senha=")[1]
    assert Api().post("/auth/reset", {"token": token, "password": "Senha-Nova-Pelo-Link-2"}).status_code == 200


def test_senha_temporaria_continua_padrao(admin, usuario, caixa):
    r = admin.post(f"/admin/users/{uid_de(usuario)}/reset-password").json()
    assert r["method"] == "temp" and r["temp_password"]
    assert not any("senha nova" in s.lower() for _, s, _ in caixa)  # nada por e-mail


# ------------------------------------------------------------------ pedido de convite --

def _pedido(**kw):
    return {"name": "Ana Souza", "email": "ana@empresa.com.br", "source": "empresa",
            "reason": "Quero registrar o suporte da filial.", **kw}


def test_pedido_de_convite_e_opt_in(admin, caixa):
    # Desligado por padrão (decisão D1, sql/042): nem a tela oferece nem a rota aceita.
    assert Api().get("/auth/options").json() == {"email": True, "invite_request": False, "privacy_url": None}
    assert admin.get("/admin/org").json()["invite_request_on"] is False
    assert Api().post("/auth/invite-request", _pedido()).status_code == 404
    assert not db.query_one("SELECT 1 FROM invite_requests")
    org = admin.put("/admin/org", {"invite_request_on": True}).json()
    assert org["invite_request_on"] is True and org["mail_configured"] is True
    assert Api().get("/auth/options").json()["invite_request"] is True
    assert Api().post("/auth/invite-request", _pedido()).status_code == 202
    admin.put("/admin/org", {"invite_request_on": False})
    assert Api().post("/auth/invite-request", _pedido(email="outra@x.com")).status_code == 404
    rows = db.query_all("SELECT after FROM audit_log WHERE action = 'app.invite_request_on' ORDER BY id")
    assert [r["after"]["invite_request_on"] for r in rows] == [True, False]
    textos = [h["summary"] for h in hist(admin) if h["action"] == "app.invite_request_on"]
    assert any("passou a oferecer" in t for t in textos) and any("tirou" in t for t in textos)


def test_origens_genericas(admin, caixa):
    ligar_pedido_convite()
    for i, origem in enumerate(("colega", "empresa", "internet", "outro")):
        assert Api().post("/auth/invite-request", _pedido(email=f"p{i}@x.com", source=origem)).status_code == 202
    for antiga in ("site", "github"):  # não oferecidas mais
        assert Api().post("/auth/invite-request", _pedido(email=f"{antiga}@x.com", source=antiga)).status_code == 422
    # Pedido antigo guardado continua aparecendo.
    db.execute("INSERT INTO invite_requests (name, email, source, reason) VALUES ('Velho', 'v@x.com', 'github', 'antigo')")
    assert any(r["source"] == "github" for r in admin.get("/admin/invite-requests").json())


# --------------------------------------------------------- transferir tarefas abertas --

def _com_tarefas(u):
    a = u.post("/worklog", {"title": "Chamado aberto"}).json()
    u.post(f"/worklog/{a['id']}/notes", {"body": "Falta trocar o cabo"})
    u.post(f"/worklog/{a['id']}/checklist", {"label": "Testar a rede"})
    u.post(f"/worklog/{a['id']}/time", {"minutes": 30})
    b = u.post("/worklog", {"title": "Concluída antes"}).json()
    db.execute("UPDATE worklog_tasks SET status = 'done', completed_at = now() WHERE id = %s", (b["id"],))
    return a["id"], b["id"]


def test_bloquear_transferindo_tarefas_abertas(admin, novo_usuario, caixa):
    sai = novo_usuario("sai@example.com")
    fica = novo_usuario("fica@example.com")
    aberta, feita = _com_tarefas(sai)
    sid, fid = uid_de(sai), uid_de(fica)
    caixa.clear()
    r = admin.post(f"/admin/users/{sid}/block", {"transfer_to": fid})
    assert r.status_code == 200, r.text
    t = r.json()["transferred"]
    assert t["count"] == 1 and t["to_id"] == fid and t["emailed"] is True
    assert db.query_one("SELECT user_id FROM worklog_tasks WHERE id = %s", (aberta,))["user_id"] == fid
    assert db.query_one("SELECT user_id FROM worklog_tasks WHERE id = %s", (feita,))["user_id"] == sid  # concluída fica
    # Anotações e checklist vão junto; o tempo fica no registro de quem saiu.
    assert db.query_one("SELECT user_id FROM task_notes WHERE task_id = %s", (aberta,))["user_id"] == fid
    assert db.query_one("SELECT user_id FROM task_checklist WHERE task_id = %s", (aberta,))["user_id"] == fid
    assert db.query_one("SELECT user_id FROM time_entries WHERE task_id = %s", (aberta,))["user_id"] == sid
    # Quem recebe vê a tarefa, o histórico e o e-mail.
    assert fica.get(f"/worklog/{aberta}").status_code == 200
    h = [x for x in hist(fica) if x["action"] == "worklog.transfer"]
    assert h and "Chamado aberto" in h[0]["summary"] and not h[0]["can_undo"]
    assert any(to == "fica@example.com" and "Chamado aberto" in subj for to, subj, _ in caixa)
    assert any(x["action"] == "user.transfer_tasks" for x in hist(admin))


def test_transferir_valida_quem_recebe_antes_de_bloquear(admin, novo_usuario):
    sai = novo_usuario("sai@example.com")
    so_admin = novo_usuario("gestor@example.com")
    sid = uid_de(sai)
    admin.put(f"/admin/users/{uid_de(so_admin)}/roles", {"roles": ["admin"]})
    for destino in (sid, uid_de(so_admin), 999999):
        r = admin.post(f"/admin/users/{sid}/block", {"transfer_to": destino})
        assert r.status_code == 400, destino
    assert db.query_one("SELECT blocked_at FROM users WHERE id = %s", (sid,))["blocked_at"] is None
    # Sem transferir, como antes (as tarefas ficam na conta).
    sai.post("/worklog", {"title": "Fica aqui"})
    r = admin.post(f"/admin/users/{sid}/block")
    assert r.status_code == 200 and r.json()["transferred"] is None
    assert db.query_one("SELECT count(*)::int AS n FROM worklog_tasks WHERE user_id = %s", (sid,))["n"] == 1


def test_excluir_transferindo_tarefas_abertas(admin, novo_usuario):
    sai = novo_usuario("sai@example.com")
    fica = novo_usuario("fica@example.com")
    aberta, feita = _com_tarefas(sai)
    r = admin.post(f"/admin/users/{uid_de(sai)}/delete", {"confirm_email": "sai@example.com", "transfer_to": uid_de(fica)})
    assert r.status_code == 200, r.text
    assert r.json()["transferred"]["count"] == 1
    row = db.query_one("SELECT user_id, title FROM worklog_tasks WHERE id = %s", (aberta,))
    assert row["user_id"] == uid_de(fica)
    assert db.query_one("SELECT body FROM task_notes WHERE task_id = %s", (aberta,))["body"] == "Falta trocar o cabo"
    assert not db.query_one("SELECT 1 FROM worklog_tasks WHERE id = %s", (feita,))  # o resto saiu com a conta
    log = db.query_one("SELECT before FROM audit_log WHERE action = 'user.delete' ORDER BY id DESC LIMIT 1")
    assert log["before"]["transferred"] == 1


def test_transferir_nao_quebra_projeto_nem_referencia_externa(admin, novo_usuario):
    sai = novo_usuario("sai@example.com")
    fica = novo_usuario("fica@example.com")
    p = sai.post("/projects", {"name": "Filial"}).json()
    t = sai.post("/worklog", {"title": "Com projeto", "project_id": p["id"], "external_ref": "ext-1"}).json()
    fica.post("/worklog", {"title": "Mesma ref", "external_ref": "ext-1"})
    assert admin.post(f"/admin/users/{uid_de(sai)}/block", {"transfer_to": uid_de(fica)}).status_code == 200
    row = db.query_one("SELECT project_id, external_ref FROM worklog_tasks WHERE id = %s", (t["id"],))
    assert row["project_id"] is None and row["external_ref"] is None  # sem o projeto padrão de quem recebe


# ------------------------------------------------------------------- aviso de papel --

def test_aviso_de_papel_ganho(admin, usuario, caixa):
    uid = uid_de(usuario)
    caixa.clear()
    r = admin.put(f"/admin/users/{uid}/roles", {"roles": ["user", "assigner"]})
    assert r.json()["notified"] is True
    me = usuario.get("/auth/me").json()
    assert me["role_notice"] == {"added": ["assigner"], "removed": []}
    assert any(to == usuario.me["email"] and "Manda tarefas" in subj for to, subj, _ in caixa)
    assert usuario.put("/me/role-notice").json() == {"role_notice": None}
    assert usuario.get("/auth/me").json()["role_notice"] is None


def test_aviso_de_papel_retirado_e_idas_e_vindas(admin, usuario):
    uid = uid_de(usuario)
    admin.put(f"/admin/users/{uid}/roles", {"roles": ["user", "viewer"]})
    admin.put(f"/admin/users/{uid}/roles", {"roles": ["user"]})  # tirou antes de a pessoa ver
    assert usuario.get("/auth/me").json()["role_notice"] is None  # nada a dizer
    admin.put(f"/admin/users/{uid}/roles", {"roles": ["user", "assigner"]})
    usuario.put("/me/role-notice")
    admin.put(f"/admin/users/{uid}/roles", {"roles": ["user"]})
    assert usuario.get("/auth/me").json()["role_notice"] == {"added": [], "removed": ["assigner"]}


def test_sem_aviso_para_convite_pendente_nem_para_si(admin, caixa):
    r = admin.post("/admin/users", {"email": "pend@example.com"})
    uid = db.query_one("SELECT id FROM users WHERE email = 'pend@example.com'")["id"]
    caixa.clear()
    assert admin.put(f"/admin/users/{uid}/roles", {"roles": ["user", "viewer"]}).json()["notified"] is False
    assert db.query_one("SELECT role_notice FROM users WHERE id = %s", (uid,))["role_notice"] is None
    assert not caixa
    assert r.status_code == 201
    me = uid_de(admin)
    assert admin.put(f"/admin/users/{me}/roles", {"roles": ["admin", "user"]}).json()["notified"] is False


# ------------------------------------------------- endereço do sistema de chamados --

def test_endereco_de_chamados_pessoal_quando_o_global_esta_vazio(admin, novo_usuario):
    a = novo_usuario("ana@example.com")
    b = novo_usuario("bia@example.com")
    assert admin.get("/admin/org").json()["ticket_url"] is None  # padrão: vazio
    assert a.put("/me/tickets", {"ticket_url": "https://glpi.ana/{id}"}).status_code == 200
    me_a, me_b = a.get("/auth/me").json(), b.get("/auth/me").json()
    assert me_a["ticket_url"] == "https://glpi.ana/{id}" and me_a["ticket_url_managed"] is False
    assert me_b["ticket_url"] is None and me_b["ticket_url_managed"] is False


def test_endereco_global_trava_e_volta_ao_pessoal(admin, novo_usuario):
    a = novo_usuario("ana@example.com")
    b = novo_usuario("bia@example.com")
    a.put("/me/tickets", {"ticket_url": "https://glpi.ana/{id}"})
    url = "https://os.empresa.com.br/os/{id}"
    assert a.put("/admin/org", {"ticket_url": url}).status_code == 403  # só o admin
    assert admin.put("/admin/org", {"ticket_url": "javascript:alert(1)"}).status_code == 422
    assert admin.put("/admin/org", {"ticket_url": url}).json()["ticket_url"] == url
    for u in (a, b, admin):
        me = u.get("/auth/me").json()
        assert me["ticket_url"] == url and me["ticket_url_managed"] is True
    # Travado: a pessoa não muda o dela (409 com o motivo).
    r = b.put("/me/tickets", {"ticket_url": "https://glpi.bia/{id}"})
    assert r.status_code == 409 and "administração" in r.json()["detail"]
    # O export JSON traz o que vale.
    assert a.get("/export/tudo.json").json()["profile"]["ticket_url"] == url
    # Campo ausente mantém; o log de admin registra.
    assert admin.put("/admin/org", {"identity_managed": False}).json()["ticket_url"] == url
    log = db.query_all("SELECT before, after FROM audit_log WHERE action = 'app.ticket_url'")
    assert len(log) == 1 and log[0]["after"]["ticket_url"] == url and log[0]["before"]["ticket_url"] is None
    assert any(h["action"] == "app.ticket_url" for h in hist(admin))
    # Esvaziou: cada um volta ao seu (guardado).
    assert admin.put("/admin/org", {"ticket_url": ""}).json()["ticket_url"] is None
    me_a, me_b = a.get("/auth/me").json(), b.get("/auth/me").json()
    assert me_a["ticket_url"] == "https://glpi.ana/{id}" and me_a["ticket_url_managed"] is False
    assert me_b["ticket_url"] is None
    assert b.put("/me/tickets", {"ticket_url": "https://glpi.bia/{id}"}).status_code == 200


def test_migracao_nao_semeia_o_global():
    from app import main
    db.execute("INSERT INTO users (email, password_hash, role, ticket_url) VALUES ('u1@x.com', 'x', 'user', 'https://a/{id}')")
    db.execute_script((main.SQL_DIR / "037_faltas_admin.sql").read_text(encoding="utf-8"))
    assert db.query_one("SELECT ticket_url FROM app_settings WHERE id = 1")["ticket_url"] is None
