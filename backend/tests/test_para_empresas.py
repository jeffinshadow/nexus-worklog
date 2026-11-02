"""Admin › "Para empresas e instituições" (sql/036): visibilidade definida pelo
admin, nome e e-mail (pela pessoa com confirmação, ou só pelo admin), convite
com nome e papéis. O tour do primeiro acesso é obrigatório para toda conta
nova (deixou de ser opção em 01/11)."""
import base64
import os
import re
from datetime import datetime, timedelta, timezone

import pytest

from app import db, mailer, visibility
from app.routers import auth as auth_mod
from conftest import Api, Bearer, SENHA_PADRAO, criar_chave, hist, uid_de


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


def _token(texto, chave):
    return re.search(chave + r"=([\w-]+)", texto).group(1)


def _org(admin, **kw):
    r = admin.put("/admin/org", kw)
    assert r.status_code == 200, r.text
    return r.json()


def _papeis(admin, u, roles):
    assert admin.put(f"/admin/users/{uid_de(u)}/roles", {"roles": roles}).status_code == 200


def _foto():
    webp = lambda n: b"RIFF" + (n + 4).to_bytes(4, "little") + b"WEBPVP8 " + os.urandom(n)  # noqa: E731
    return {"image": base64.b64encode(webp(300)).decode(), "thumb": base64.b64encode(webp(80)).decode(),
            "width": 1600, "height": 1200}


def _admin_log(admin, action):
    return [r for r in db.query_all("SELECT action, actor, before, after FROM audit_log WHERE action = %s ORDER BY id",
                                    (action,))]


# ------------------------------------------------------------- padrão: tudo desligado --

def test_tudo_desligado_por_padrao(admin, usuario):
    assert admin.get("/admin/org").json() == {"team_visibility": "self", "team_visibility_since": None,
                                              "assign_receive": "self", "assign_receive_since": None,
                                              "identity_managed": False, "invite_request_off": False,
                                              "ticket_url": None, "mail_configured": False}
    me = usuario.get("/auth/me").json()
    assert me["org"] == {"team_visibility": "self", "assign_receive": "self", "identity_managed": False}
    assert me["visibility_notice"] is False and me["assign_notice"] is False and me["email_pending"] is None
    # Só o admin mexe nas opções.
    assert usuario.get("/admin/org").status_code == 403
    assert usuario.put("/admin/org", {"identity_managed": True}).status_code == 403


# ---------------------------------------------------------------- visibilidade da equipe --

def test_visivel_para_quem_gerencia_e_volta_ao_que_cada_um_escolheu(admin, novo_usuario):
    a = novo_usuario("ana@example.com")
    b = novo_usuario("bia@example.com")
    vis = novo_usuario("vis@example.com")
    _papeis(admin, vis, ["viewer"])
    a.put("/me/viewers", {"accept": True})  # Ana aceitou; Bia não
    ua, ub = uid_de(a), uid_de(b)
    tid = b.post("/worklog", {"title": "Trocar nobreak"}).json()["id"]
    b.post(f"/worklog/{tid}/time", {"minutes": 30})
    foto = b.post(f"/worklog/{tid}/photos", _foto()).json()["id"]
    lista = lambda: {u["email"] for u in vis.get("/viewer/users").json()}  # noqa: E731
    csv = lambda: {l.split(";")[-1] for l in vis.get("/viewer/export/apontamentos.csv").content.decode("utf-8-sig").splitlines()[1:]}  # noqa: E731

    # Cada pessoa escolhe (padrão): Bia não aparece em nada.
    assert lista() == {"ana@example.com"}
    assert vis.get(f"/viewer/users/{ub}/board").status_code == 404
    assert vis.get(f"/photos/{foto}").status_code == 404
    assert "bia@example.com" not in csv()
    assert visibility.can_see(ua) and not visibility.can_see(ub)

    # Visível para quem gerencia: todos com o papel Usuário, sem mexer no aceite guardado.
    out = _org(admin, team_visibility="managers")
    assert out["team_visibility"] == "managers" and out["team_visibility_since"]
    assert {"ana@example.com", "bia@example.com"} <= lista()
    assert vis.get(f"/viewer/users/{ub}/board").status_code == 200
    assert vis.get(f"/viewer/users/{ub}/dashboard").status_code == 200
    assert vis.get(f"/photos/{foto}").status_code == 200
    assert vis.get(f"/me/avatar/{ub}").status_code == 404  # sem foto, mas não por falta de permissão
    assert "bia@example.com" in csv()
    assert visibility.can_see(ub)
    team = vis.get("/viewer/team").json()  # painel da Equipe: o mesmo ponto único
    assert "bia@example.com" in {p.get("email") for p in team["people"]} or ub in {p.get("id") for p in team["people"]}
    # Quem não tem o papel continua sem ver.
    assert a.get(f"/viewer/users/{ub}/board").status_code == 403
    assert db.query_one("SELECT viewers_allowed FROM users WHERE id = %s", (ub,))["viewers_allowed"] is False

    # Volta para "Cada pessoa escolhe": cada um com o que tinha escolhido.
    _org(admin, team_visibility="self")
    assert lista() == {"ana@example.com"}
    assert vis.get(f"/viewer/users/{ub}/board").status_code == 404
    assert vis.get(f"/photos/{foto}").status_code == 404
    assert vis.get(f"/viewer/users/{ua}/board").status_code == 200
    assert ub not in {p.get("id") for p in vis.get("/viewer/team").json()["people"]}


def test_aceite_bloqueado_com_mensagem_clara(admin, usuario):
    usuario.put("/me/viewers", {"accept": True})
    _org(admin, team_visibility="managers")
    me = usuario.get("/auth/me").json()
    assert me["org"]["team_visibility"] == "managers"
    r = usuario.put("/me/viewers", {"accept": False})
    assert r.status_code == 409
    assert "definido pela administração" in r.json()["detail"] and "guardada" in r.json()["detail"]
    assert usuario.get("/auth/me").json()["viewers_allowed"] is True  # nada mudou
    _org(admin, team_visibility="self")
    assert usuario.put("/me/viewers", {"accept": False}).status_code == 200


def test_api_e_mcp_seguem_o_mesmo_filtro(admin, usuario):
    _org(admin, team_visibility="managers")
    uid = uid_de(usuario)
    chave = Bearer(criar_chave(admin)["token"])  # admin semeado tem o papel viewer
    # O visualizador é só pelo app: chave de API não alcança o registro de ninguém, nem com a flag.
    assert chave.get(f"/viewer/users/{uid}/board").status_code == 403
    assert chave.get("/viewer/users").status_code == 403
    # MCP: as ferramentas só trabalham no registro da própria chave.
    nomes = {t["name"] for t in chave.rpc("tools/list").json()["result"]["tools"]}
    assert not any("viewer" in n for n in nomes)
    usuario.post("/worklog", {"title": "Tarefa da colega"})
    assert "Tarefa da colega" not in str(chave.tool("list_tasks"))
    assert "Tarefa da colega" not in str(chave.tool("search", query="colega"))


def test_aviso_unico_para_quem_ja_usa(admin, usuario):
    assert usuario.get("/auth/me").json()["visibility_notice"] is False
    _org(admin, team_visibility="managers")
    assert usuario.get("/auth/me").json()["visibility_notice"] is True
    assert usuario.put("/me/visibility-notice").json() == {"visibility_notice": False}
    assert usuario.get("/auth/me").json()["visibility_notice"] is False
    # Desligar e ligar de novo: avisa de novo (uma vez).
    _org(admin, team_visibility="self")
    assert usuario.get("/auth/me").json()["visibility_notice"] is False
    db.execute("UPDATE app_settings SET team_visibility_since = now() + interval '1 second'")
    _org(admin, team_visibility="managers")
    assert usuario.get("/auth/me").json()["visibility_notice"] is True
    # Passar pelo tour conta como visto.
    usuario.put("/me/tour", {"done": True})
    assert usuario.get("/auth/me").json()["visibility_notice"] is False


def test_admin_nao_recebe_o_aviso_da_propria_mudanca(admin, usuario):
    """R6 admin A5: quem liga a opção já sabe; o aviso único vai só para os outros."""
    db.execute("INSERT INTO user_roles (user_id, role) SELECT id, 'user' FROM users WHERE email = %s ON CONFLICT DO NOTHING",
               (admin.get("/auth/me").json()["email"],))
    _org(admin, team_visibility="managers", assign_receive="all")
    me = admin.get("/auth/me").json()
    assert me["visibility_notice"] is False and me["assign_notice"] is False
    outro = usuario.get("/auth/me").json()
    assert outro["visibility_notice"] is True and outro["assign_notice"] is True


def test_log_de_admin_das_opcoes(admin):
    _org(admin, team_visibility="managers")
    _org(admin, team_visibility="managers")  # sem mudança: não registra
    _org(admin, identity_managed=True)
    _org(admin, team_visibility="self")
    rows = _admin_log(admin, "app.team_visibility")
    assert [r["after"]["team_visibility"] for r in rows] == ["managers", "self"]
    assert all(r["actor"] == "admin" and r["after"]["by"] == admin.me["email"] for r in rows)
    assert len(_admin_log(admin, "app.identity_managed")) == 1
    textos = [h["summary"] for h in hist(admin) if h["action"] == "app.team_visibility"]
    assert any("Visível para quem gerencia" in t for t in textos)
    assert any("Cada pessoa escolhe" in t for t in textos)


# ----------------------------------------------------------------------- nome e e-mail --

def test_troca_do_proprio_email_com_confirmacao(usuario, caixa):
    antigo = usuario.me["email"]
    assert usuario.post("/me/email", {"new_email": "novo@example.com", "password": "errada"}).status_code == 400
    assert usuario.post("/me/email", {"new_email": antigo, "password": SENHA_PADRAO}).status_code == 400
    r = usuario.post("/me/email", {"new_email": "Novo@Example.com", "password": SENHA_PADRAO})
    assert r.status_code == 200, r.text
    assert r.json() == {"email_pending": "novo@example.com"}
    assert caixa[-1][0] == "novo@example.com" and "#email=" in caixa[-1][2]
    token = _token(caixa[-1][2], "email")
    # Só troca depois de confirmar.
    me = usuario.get("/auth/me").json()
    assert me["email"] == antigo and me["email_pending"] == "novo@example.com"
    r = Api().post("/auth/email/confirm", {"token": token})  # outro aparelho, sem sessão
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "novo@example.com"
    assert usuario.get("/auth/me").json()["email"] == "novo@example.com"
    assert usuario.get("/auth/me").json()["email_pending"] is None
    # Aviso ao endereço antigo; uso único.
    assert caixa[-1][0] == antigo and "novo@example.com" in caixa[-1][2]
    assert Api().post("/auth/email/confirm", {"token": token}).status_code == 400
    Api().login("novo@example.com", SENHA_PADRAO)
    acoes = [r["action"] for r in db.query_all("SELECT action FROM audit_log WHERE action LIKE 'email.%%' ORDER BY id")]
    assert acoes == ["email.change_request", "email.change"]


def test_email_unico_e_link_vencido(novo_usuario, caixa):
    a = novo_usuario("ana@example.com")
    novo_usuario("bia@example.com")
    assert a.post("/me/email", {"new_email": "bia@example.com", "password": SENHA_PADRAO}).status_code == 409
    a.post("/me/email", {"new_email": "ana2@example.com", "password": SENHA_PADRAO})
    token = _token(caixa[-1][2], "email")
    db.execute("UPDATE auth_links SET expires_at = now() - interval '1 minute' WHERE kind = 'email'")
    assert Api().post("/auth/email/confirm", {"token": token}).status_code == 400
    assert a.get("/auth/me").json()["email"] == "ana@example.com"
    # Pedido novo invalida o anterior; desistir também.
    a.post("/me/email", {"new_email": "ana3@example.com", "password": SENHA_PADRAO})
    t1 = _token(caixa[-1][2], "email")
    a.post("/me/email", {"new_email": "ana4@example.com", "password": SENHA_PADRAO})
    t2 = _token(caixa[-1][2], "email")
    assert Api().post("/auth/email/confirm", {"token": t1}).status_code == 400
    assert a.delete("/me/email").json() == {"email_pending": None}
    assert Api().post("/auth/email/confirm", {"token": t2}).status_code == 400
    # Alguém pegou o endereço entre o pedido e a confirmação: 409, nada muda.
    a.post("/me/email", {"new_email": "carla@example.com", "password": SENHA_PADRAO})
    t3 = _token(caixa[-1][2], "email")
    novo_usuario("carla@example.com")
    assert Api().post("/auth/email/confirm", {"token": t3}).status_code == 409
    assert a.get("/auth/me").json()["email"] == "ana@example.com"


def test_troca_de_email_sem_servidor_de_email(usuario):
    r = usuario.post("/me/email", {"new_email": "novo@example.com", "password": SENHA_PADRAO})
    assert r.status_code == 400 and "administra" in r.json()["detail"]


def test_nome_e_email_definidos_pela_administracao(admin, usuario, caixa):
    assert usuario.put("/me/profile", {"display_name": "Eu Mesma"}).status_code == 200
    usuario.post("/me/email", {"new_email": "pedido@example.com", "password": SENHA_PADRAO})
    token = _token(caixa[-1][2], "email")
    _org(admin, identity_managed=True)
    assert usuario.get("/auth/me").json()["org"]["identity_managed"] is True
    r = usuario.put("/me/profile", {"display_name": "Outro"})
    assert r.status_code == 403 and "definidos pela administração" in r.json()["detail"]
    assert usuario.post("/me/email", {"new_email": "x@example.com", "password": SENHA_PADRAO}).status_code == 403
    # Pedido feito antes de ligar não passa depois.
    assert Api().post("/auth/email/confirm", {"token": token}).status_code == 403
    assert usuario.get("/auth/me").json()["display_name"] == "Eu Mesma"


def test_admin_edita_nome_e_email(admin, usuario, caixa):
    _org(admin, identity_managed=True)
    uid, antigo = uid_de(usuario), usuario.me["email"]
    n = len(caixa)
    r = admin.put(f"/admin/users/{uid}/profile", {"display_name": "  Maria   Souza ", "email": "maria@example.com"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "maria@example.com" and r.json()["display_name"] == "Maria Souza"
    # Avisa o endereço antigo e o novo.
    assert {c[0] for c in caixa[n:]} == {antigo, "maria@example.com"}
    Api().login("maria@example.com", SENHA_PADRAO)
    # E-mail de outra conta: 409. Só o nome: o e-mail fica.
    assert admin.put(f"/admin/users/{uid}/profile", {"email": admin.me["email"]}).status_code == 409
    assert admin.put(f"/admin/users/{uid}/profile", {"display_name": "Maria S."}).json()["email"] == "maria@example.com"
    # Só admin.
    assert usuario.put(f"/admin/users/{uid}/profile", {"display_name": "Eu"}).status_code == 403
    log = _admin_log(admin, "user.profile")
    assert len(log) == 2 and log[0]["actor"] == "admin"
    assert log[0]["before"]["email"] == antigo and log[0]["after"]["email"] == "maria@example.com"
    assert log[1]["after"]["display_name"] == "Maria S."


# ------------------------------------------------------------- convite com nome e papéis --

def test_convite_com_nome_e_papel(admin, caixa):
    r = admin.post("/admin/users", {"email": "gestora@example.com", "display_name": " Gestora  Lima ",
                                    "roles": ["user", "viewer"]})
    assert r.status_code == 201, r.text
    assert r.json()["display_name"] == "Gestora Lima" and r.json()["roles"] == ["user", "viewer"]
    token = _token(r.json()["invite_url"], "convite")
    info = Api().get(f"/auth/link?kind=invite&token={token}").json()
    assert info["display_name"] == "Gestora Lima" and info["name_locked"] is False
    pend = next(u for u in admin.get("/admin/users").json() if u["email"] == "gestora@example.com")
    assert pend["name"] == "Gestora Lima" and sorted(pend["roles"]) == ["user", "viewer"]
    anon = Api()
    me = anon.post("/auth/invite/accept", {"token": token, "password": "Senha-Da-Gestora-1"}).json()
    assert me["display_name"] == "Gestora Lima" and sorted(me["roles"]) == ["user", "viewer"]
    assert me["tour_required"] is True  # conta nova: tour obrigatório no primeiro acesso
    # Os papéis continuam mudando depois.
    uid = me["id"]
    assert admin.put(f"/admin/users/{uid}/roles", {"roles": ["user"]}).status_code == 200
    # Sem papel nenhum, não.
    assert admin.post("/admin/users", {"email": "x@example.com", "roles": []}).status_code == 422
    assert admin.post("/admin/users", {"email": "y@example.com", "roles": ["dono"]}).status_code == 422


def test_convite_sem_nome_continua_como_antes(admin):
    r = admin.post("/admin/users", {"email": "simples@example.com"})
    assert r.status_code == 201 and r.json()["roles"] == ["user"] and r.json()["display_name"] is None


def test_convite_com_nome_travado_pela_administracao(admin, caixa):
    _org(admin, identity_managed=True)
    r = admin.post("/admin/users", {"email": "func@example.com", "display_name": "Funcionário Um"})
    token = _token(r.json()["invite_url"], "convite")
    assert Api().get(f"/auth/link?kind=invite&token={token}").json()["name_locked"] is True
    me = Api().post("/auth/invite/accept", {"token": token, "password": "Senha-Do-Func-1", "display_name": "Apelido"}).json()
    assert me["display_name"] == "Funcionário Um"


# --------------------------------------------------------------------- tour obrigatório --

def test_tour_obrigatorio_sempre_no_primeiro_acesso(admin, usuario, caixa):
    # Conta que já existia: tour_first_access vem da migração (falso p/ quem já usa) e nunca é forçada.
    db.execute("UPDATE users SET tour_first_access = false WHERE id = %s", (uid_de(usuario),))
    assert usuario.get("/auth/me").json()["tour_required"] is False
    # Conta nova: obrigatório até concluir, sem opção nenhuma ligada.
    r = admin.post("/admin/users", {"email": "nova@example.com", "display_name": "Nova"})
    nova = Api()
    me = nova.post("/auth/invite/accept", {"token": _token(r.json()["invite_url"], "convite"), "password": "Senha-Da-Nova-1"}).json()
    nova.csrf = me["csrf_token"]
    assert me["tour_required"] is True and me["tour_done_at"] is None
    out = nova.put("/me/tour", {"done": True}).json()
    assert out["tour_done_at"] and out["tour_required"] is False
    # Rever pela Ajuda (done=false) não volta a obrigar.
    nova.put("/me/tour", {"done": False})
    me = nova.get("/auth/me").json()
    assert me["tour_done_at"] is None and me["tour_required"] is False
    # A opção saiu do Admin: mandar o campo antigo não muda nada.
    assert admin.put("/admin/org", {"tour_required": False}).status_code == 200
    r = admin.post("/admin/users", {"email": "outra@example.com"})
    outra = Api()
    me = outra.post("/auth/invite/accept", {"token": _token(r.json()["invite_url"], "convite"), "password": "Senha-Da-Outra-1"}).json()
    assert me["tour_required"] is True
    assert "tour_required" not in admin.get("/admin/org").json()


def test_migracao_nao_obriga_quem_ja_usa():
    """Rodar a 036 de novo não muda ninguém que já concluiu ou já usava."""
    from app import main
    db.execute("""INSERT INTO users (email, password_hash, role, tour_done_at, tour_first_access)
                  VALUES ('antiga@example.com', 'x', 'user', now(), false)""")
    db.execute("""INSERT INTO users (email, password_hash, role, invite_pending)
                  VALUES ('pendente@example.com', 'x', 'user', true)""")
    db.execute_script((main.SQL_DIR / "036_para_empresas.sql").read_text(encoding="utf-8"))
    rows = {r["email"]: r for r in db.query_all("SELECT email, tour_first_access, tour_done_at FROM users")}
    assert rows["antiga@example.com"]["tour_first_access"] is False and rows["antiga@example.com"]["tour_done_at"]
    assert rows["pendente@example.com"]["tour_first_access"] is True


def test_convite_a_partir_do_pedido_com_nome_e_papel(monkeypatch, admin, caixa):
    import app.routers.invite_requests as ir
    monkeypatch.setattr(ir.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda self: target()})())
    monkeypatch.setattr(ir.push, "send", lambda *a, **k: 0)
    corpo = {"name": "Carla Dias", "email": "carla@empresa.com.br", "source": "colega",
             "reason": "Quero registrar o suporte da filial e tirar o relatório do mês."}
    assert Api().post("/auth/invite-request", corpo).status_code == 202
    rid = admin.get("/admin/invite-requests").json()[0]["id"]
    r = admin.post(f"/admin/invite-requests/{rid}/invite", {"display_name": "Carla D. Souza", "roles": ["user", "assigner"]})
    assert r.status_code == 200, r.text
    assert r.json()["display_name"] == "Carla D. Souza" and r.json()["roles"] == ["assigner", "user"]
    u = db.query_one("SELECT id, display_name FROM users WHERE email = 'carla@empresa.com.br'")
    assert u["display_name"] == "Carla D. Souza"
    papeis = sorted(x["role"] for x in db.query_all("SELECT role FROM user_roles WHERE user_id = %s", (u["id"],)))
    assert papeis == ["assigner", "user"]
