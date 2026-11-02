"""Equipes e admin master (sql/043, pedido do dono 02/11): escopo por equipe
em "Vê a equipe" e "Manda tarefas" (app, API, MCP, CSV, PDF, painel e
"Precisa de atenção"), várias equipes, sem equipe = ninguém (exceto o master
com os papéis), instância sem equipes = como antes, "Para empresas" só para
quem está em equipe (com as exceções globais), transferência do master com
senha + código por e-mail, convite com equipe e o pentest focado."""
import re
from datetime import date

import pytest

from app import db, mailer, teams
from app.routers import admin as admin_mod
from app.routers import assign as assign_mod
from app.routers import equipes as equipes_mod
from conftest import ADMIN_PW, Bearer, SENHA_PADRAO, criar_chave, ligar_pedido_convite, texto, uid_de


class _Agora:
    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@pytest.fixture
def caixa(monkeypatch):
    """E-mails capturados (sem SMTP, sem thread)."""
    enviados = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None, **kw: enviados.append((to, subject, text)))
    monkeypatch.setattr(equipes_mod.threading, "Thread", _Agora)
    monkeypatch.setattr(admin_mod.threading, "Thread", _Agora)
    monkeypatch.setattr(assign_mod, "_spawn", lambda to, mail: enviados.append((to, mail.subject, mail.text())))
    return enviados


def _papeis(admin, u, roles):
    r = admin.put(f"/admin/users/{uid_de(u)}/roles", {"roles": roles})
    assert r.status_code == 200, r.text


def _equipe(admin, nome, *membros):
    r = admin.post("/admin/teams", {"name": nome, "member_ids": [uid_de(m) for m in membros]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _org(admin, **kw):
    r = admin.put("/admin/org", kw)
    assert r.status_code == 200, r.text


def _lista(vis, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    r = vis.get("/viewer/users" + (f"?{qs}" if qs else ""))
    assert r.status_code == 200, r.text
    return {u["email"] for u in r.json()} - {vis.me["email"]}


def _csv(vis, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    linhas = vis.get("/viewer/export/apontamentos.csv" + (f"?{qs}" if qs else "")).content.decode("utf-8-sig").splitlines()[1:]
    return {l.split(";")[-1] for l in linhas}


def _aceita(chefe):
    return {p["email"] for p in chefe.get("/assign/people").json() if p["accepts"] and p.get("id") != uid_de(chefe)}


@pytest.fixture
def cena(admin, novo_usuario, caixa):
    """Chefe (vê e atribui), Ana e Bia (aceitam ser vistas e receber), com um apontamento cada."""
    chefe = novo_usuario("chefe@example.com")
    ana = novo_usuario("ana@example.com")
    bia = novo_usuario("bia@example.com")
    _papeis(admin, chefe, ["user", "viewer", "assigner"])
    for p in (ana, bia):
        p.put("/me/viewers", {"accept": True})
        p.put("/me/assignments", {"accept": True})
        tid = p.post("/worklog", {"title": f"Tarefa de {p.me['email']}"}).json()["id"]
        assert p.post(f"/worklog/{tid}/time", {"minutes": 30}).status_code in (200, 201)
    return chefe, ana, bia


# ------------------------------------------------------- sem equipes = como antes --

def test_instancia_sem_equipes_funciona_como_antes(admin, cena):
    chefe, ana, bia = cena
    assert _lista(chefe) == {"ana@example.com", "bia@example.com"}
    assert {"ana@example.com", "bia@example.com"} <= _aceita(chefe)
    assert {"ana@example.com", "bia@example.com"} <= _csv(chefe)
    me = ana.get("/auth/me").json()
    assert me["teams"] == [] and me["teams_on"] is False
    assert chefe.get("/viewer/teams").json() == {"on": False, "master": False, "teams": [], "none": False}
    # Equipe só arquivada também não liga o escopo.
    tid = _equipe(admin, "Campo", chefe, ana)
    assert admin.patch(f"/admin/teams/{tid}", {"archived": True}).status_code == 200
    assert _lista(chefe) == {"ana@example.com", "bia@example.com"}


# ------------------------------------------------------------ escopo por equipe --

def test_escopo_por_equipe_em_tudo(admin, cena):
    chefe, ana, bia = cena
    ub = uid_de(bia)
    _equipe(admin, "Campo", chefe, ana)
    _equipe(admin, "Escritório", bia)
    # Vê a equipe: lista, quadro, mês, PDF, CSV, painel.
    assert _lista(chefe) == {"ana@example.com"}
    assert chefe.get(f"/viewer/users/{ub}/board").status_code == 404
    assert chefe.get(f"/viewer/users/{ub}/dashboard").status_code == 404
    assert chefe.get(f"/viewer/users/{ub}/reports/export").status_code == 404
    assert chefe.get(f"/viewer/users/{uid_de(ana)}/board").status_code == 200
    assert _csv(chefe) == {"ana@example.com"}
    painel = chefe.get("/viewer/team").json()
    assert {p["email"] for p in painel["people"]} == {"ana@example.com"}
    assert painel["hidden_count"] == 0  # quem está fora da equipe nem entra na conta
    assert painel["teams"]["on"] is True and [t["name"] for t in painel["teams"]["teams"]] == ["Campo"]
    # Manda tarefas: lista, envio e MCP.
    assert _aceita(chefe) == {"ana@example.com"}
    assert "bia@example.com" not in str(chefe.get("/assign/people").json())
    assert chefe.post("/assign", {"user_id": ub, "title": "Fora"}).status_code == 404
    assert chefe.post("/assign", {"user_id": uid_de(ana), "title": "Dentro"}).status_code == 201
    ia = Bearer(criar_chave(chefe)["token"])
    lista = texto(ia.tool("list_assignable"))
    assert "ana@example.com" in lista and "bia@example.com" not in lista
    assert ia.tool("assign_task", to="bia@example.com", title="Pelo MCP").get("isError")
    # Foto de perfil segue a mesma regra (404 como "sem foto").
    assert chefe.get(f"/me/avatar/{ub}").status_code == 404


def test_varias_equipes_e_seletor(admin, cena, novo_usuario):
    chefe, ana, bia = cena
    cid = _equipe(admin, "Campo", chefe, ana)
    eid = _equipe(admin, "Escritório", chefe, bia)
    outra = _equipe(admin, "Outra", bia)
    assert _lista(chefe) == {"ana@example.com", "bia@example.com"}
    assert _lista(chefe, team=cid) == {"ana@example.com"}
    assert _lista(chefe, team=eid) == {"bia@example.com"}
    assert _csv(chefe, team=eid) == {"bia@example.com"}
    assert {p["email"] for p in chefe.get(f"/viewer/team?team={cid}").json()["people"]} == {"ana@example.com"}
    # Equipe que não é dele, e "Sem equipe" (só o master): 404.
    assert chefe.get(f"/viewer/users?team={outra}").status_code == 404
    assert chefe.get("/viewer/users?team=none").status_code == 404
    assert chefe.get("/viewer/users?team=abc").status_code == 400
    # Atribuir: agrupa pelas equipes em comum.
    grupos = {p["email"]: p["teams"] for p in chefe.get("/assign/people").json() if p.get("email")}
    assert grupos["ana@example.com"] == ["Campo"] and grupos["bia@example.com"] == ["Escritório"]
    assert {p["email"] for p in chefe.get(f"/assign/people?team={cid}").json() if p.get("accepts") and p.get("email") != "chefe@example.com"} == {"ana@example.com"}


def test_sem_equipe_ninguem_ve_exceto_master_com_papeis(admin, cena):
    chefe, ana, bia = cena
    ub = uid_de(bia)
    _equipe(admin, "Campo", chefe, ana)  # Bia sem equipe
    assert "bia@example.com" not in _lista(chefe)
    # O master (admin semeado, com "Vê a equipe") vê todos, com ou sem equipe, e pode recortar "Sem equipe".
    assert admin.me["id"] == teams.master_id()
    assert {"ana@example.com", "bia@example.com"} <= _lista(admin)
    assert _lista(admin, team="none") >= {"bia@example.com"} and "ana@example.com" not in _lista(admin, team="none")
    sel = admin.get("/viewer/teams").json()
    assert sel["master"] is True and sel["none"] is True
    assert admin.get(f"/viewer/users/{ub}/board").status_code == 200
    # As visualizações dele vão para o log de admin (uma por pessoa/tipo/dia).
    admin.get(f"/viewer/users/{ub}/board")
    logs = db.query_all("SELECT actor, entity_id, after FROM audit_log WHERE action = 'master.view' AND entity_id = %s", (ub,))
    assert len(logs) == 1 and logs[0]["actor"] == "admin" and logs[0]["after"]["what"] == "quadro"
    admin.get("/viewer/team")
    assert db.query_one("SELECT 1 FROM audit_log WHERE action = 'master.view' AND entity = 'team'")
    # Manda tarefas: só com o papel ligado (desligado = nada).
    assert admin.get("/assign/teams").status_code == 403
    r = admin.put("/admin/master/roles", {"assigner": True})
    assert r.status_code == 200 and r.json()["assigner"] is True
    assert admin.post("/assign", {"user_id": ub, "title": "Do master"}).status_code == 201
    # Master sem os papéis não vê (nem a tela).
    admin.put("/admin/master/roles", {"viewer": False, "assigner": False})
    assert admin.get("/viewer/users").status_code == 403
    assert admin.get(f"/viewer/users/{ub}/board").status_code == 403
    assert admin.post("/assign", {"user_id": ub, "title": "X"}).status_code == 403


def test_master_sem_papeis_e_outro_admin_nao_tem_poder_de_master(admin, cena, novo_usuario):
    chefe, ana, bia = cena
    _equipe(admin, "Campo", chefe, ana)
    outro = novo_usuario("outro@example.com")
    _papeis(admin, outro, ["user", "admin", "viewer", "assigner"])
    assert _lista(outro) == set()  # admin comum sem equipe: ninguém
    assert outro.put("/admin/master/roles", {"viewer": True}).status_code == 403
    assert outro.post("/admin/master/transfer", {"to_user_id": uid_de(outro), "password": SENHA_PADRAO}).status_code == 403


def test_atribuicao_antiga_fora_da_equipe_fica_mas_nao_muda(admin, cena):
    chefe, ana, bia = cena
    tid = chefe.post("/assign", {"user_id": uid_de(ana), "title": "Antes das equipes"}).json()["id"]
    _equipe(admin, "Campo", chefe)
    _equipe(admin, "Escritório", ana)
    linha = next(r for r in chefe.get("/assign/sent").json() if r["id"] == tid)
    assert linha["editable"] is False and linha["cancelable"] is False and linha["same_team"] is False
    r = chefe.patch(f"/assign/{tid}", {"title": "Mudou"})
    assert r.status_code == 403 and "mesma equipe" in r.json()["detail"]
    assert chefe.post(f"/assign/{tid}/cancel").status_code == 403
    assert chefe.post("/assign", {"user_id": uid_de(ana), "title": "Nova"}).status_code == 404


def test_precisa_de_atencao_respeita_o_escopo(admin, cena):
    chefe, ana, bia = cena
    tb = bia.post("/worklog", {"title": "Vence já", "due_date": date.today().isoformat()}).json()["id"]
    ta = ana.post("/worklog", {"title": "Vence também", "due_date": date.today().isoformat()}).json()["id"]
    _equipe(admin, "Campo", chefe, ana)
    ids = {a["task_id"] for a in chefe.get("/viewer/team").json()["attention"]}
    assert ta in ids and tb not in ids


# ------------------------------------------------------- Para empresas e equipes --

def test_para_empresas_so_para_quem_esta_em_equipe(admin, novo_usuario, caixa):
    chefe = novo_usuario("chefe@example.com")
    ana = novo_usuario("ana@example.com")
    bia = novo_usuario("bia@example.com")
    _papeis(admin, chefe, ["user", "viewer", "assigner"])
    _org(admin, team_visibility="managers", assign_receive="all", identity_managed=True,
         ticket_url="https://chamados.example.com/{id}")
    tid = _equipe(admin, "Campo", chefe, ana)
    # Ana (na equipe): visível e recebe sem aceite; bloqueios na Conta.
    assert _lista(chefe) == {"ana@example.com"}
    assert _aceita(chefe) == {"ana@example.com"}
    me_a = ana.get("/auth/me").json()
    assert me_a["org"] == {"team_visibility": "managers", "assign_receive": "all", "identity_managed": True}
    assert me_a["ticket_url_managed"] is True and me_a["teams"] == ["Campo"]
    assert ana.put("/me/viewers", {"accept": False}).status_code == 409
    assert ana.put("/me/profile", {"display_name": "Ana"}).status_code == 403
    # Bia (sem equipe): escolha pessoal, nada bloqueado.
    me_b = bia.get("/auth/me").json()
    assert me_b["org"] == {"team_visibility": "self", "assign_receive": "self", "identity_managed": False}
    assert me_b["ticket_url_managed"] is False and me_b["visibility_notice"] is False and me_b["assign_notice"] is False
    assert bia.put("/me/viewers", {"accept": True}).status_code == 200
    assert bia.put("/me/profile", {"display_name": "Bia"}).status_code == 200
    assert bia.put("/me/tickets", {"ticket_url": "https://meu.example.com/{id}"}).status_code == 200
    # Ana sai da última equipe: volta ao pessoal, com os valores guardados (nunca aceitou).
    assert admin.put(f"/admin/users/{uid_de(ana)}/teams", {"team_ids": []}).status_code == 200
    me_a = ana.get("/auth/me").json()
    assert me_a["org"]["team_visibility"] == "self" and me_a["teams"] == []
    assert ana.put("/me/viewers", {"accept": False}).status_code == 200
    # Entrar numa equipe depois da mudança mostra o aviso único de novo.
    assert admin.put(f"/admin/users/{uid_de(bia)}/teams", {"team_ids": [tid]}).status_code == 200
    me_b = bia.get("/auth/me").json()
    assert me_b["visibility_notice"] is True and me_b["assign_notice"] is True


def test_excecoes_globais_valem_sem_equipe(admin, novo_usuario, caixa):
    bia = novo_usuario("bia@example.com")
    chefe = novo_usuario("chefe@example.com")
    _equipe(admin, "Campo", chefe)
    ligar_pedido_convite()
    _org(admin, privacy_url="https://example.com/privacidade")
    opts = bia.get("/auth/options").json()
    assert opts["invite_request"] is True and opts["privacy_url"] == "https://example.com/privacidade"
    assert bia.get("/auth/me").json()["privacy_url"] == "https://example.com/privacidade"


def test_conta_mostra_equipes_e_quem_ve(admin, cena, novo_usuario):
    chefe, ana, bia = cena
    _equipe(admin, "Campo", chefe, ana)
    assert ana.get("/auth/me").json()["teams"] == ["Campo"]
    quem = {p["name"]: p for p in ana.get("/me/visibility").json()}
    assert quem["Chefe"]["sees"] is True and "viewer" in quem["Chefe"]["roles"] and quem["Chefe"]["assigns"] is True
    quem_b = {p["name"]: p for p in bia.get("/me/visibility").json()}
    assert "Chefe" not in quem_b  # fora da equipe: não alcança
    assert any("admin" in p["roles"] for p in quem_b.values())  # o admin aparece (concede papéis)


# ------------------------------------------------------------ cadastro (admin) --

def test_cadastro_de_equipes_e_log(admin, cena):
    chefe, ana, bia = cena
    tid = _equipe(admin, "Campo", chefe)
    assert admin.post("/admin/teams", {"name": "  campo "}).status_code == 409
    r = admin.patch(f"/admin/teams/{tid}", {"name": "Campo Norte", "member_ids": [uid_de(chefe), uid_de(ana)]})
    assert r.status_code == 200 and {m["email"] for m in r.json()["members"]} == {"chefe@example.com", "ana@example.com"}
    users = {u["email"]: u for u in admin.get("/admin/users").json()}
    assert [t["name"] for t in users["ana@example.com"]["teams"]] == ["Campo Norte"]
    assert users[admin.me["email"]]["is_master"] is True and users["ana@example.com"]["is_master"] is False
    assert admin.delete(f"/admin/teams/{tid}").status_code == 200
    assert admin.get("/admin/teams").json() == []
    acoes = [r["action"] for r in db.query_all("SELECT action FROM audit_log WHERE action LIKE 'team.%%' ORDER BY id")]
    assert acoes == ["team.create", "team.update", "team.members", "team.delete"]
    resumo = [h["summary"] for h in admin.get("/history").json() if h["action"].startswith("team.")]
    assert any("Campo Norte" in s for s in resumo)


def test_convite_com_equipe(admin, caixa):
    tid = admin.post("/admin/teams", {"name": "Campo"}).json()["id"]
    r = admin.post("/admin/users", {"email": "nova@example.com", "team_ids": [tid]})
    assert r.status_code == 201 and r.json()["teams"] == ["Campo"]
    uid = db.query_one("SELECT id FROM users WHERE email = 'nova@example.com'")["id"]
    assert [t["name"] for t in teams.of_user(uid)] == ["Campo"]
    assert admin.post("/admin/users", {"email": "x@example.com", "team_ids": [999]}).status_code == 400
    assert not db.query_one("SELECT 1 FROM users WHERE email = 'x@example.com'")
    # A partir de um pedido de convite.
    ligar_pedido_convite()
    from conftest import Api
    anon = Api()
    assert anon.post("/auth/invite-request", {"email": "pedido@example.com", "name": "Pedro",
                                                 "source": "colega", "reason": "Quero usar"}).status_code == 202
    rid = next(r["id"] for r in admin.get("/admin/invite-requests").json() if r["email"] == "pedido@example.com" and r["status"] == "pending")
    r = admin.post(f"/admin/invite-requests/{rid}/invite", {"team_ids": [tid]})
    assert r.status_code == 201 or r.status_code == 200, r.text
    assert r.json()["teams"] == ["Campo"]


# ------------------------------------------------------------- transferir master --

def _codigo(caixa):
    return re.search(r"\b(\d{6})\b", caixa[-1][1]).group(1)


def test_transferir_master(admin, novo_usuario, caixa):
    novo = novo_usuario("novo@example.com")
    _papeis(admin, novo, ["user", "admin"])
    un = uid_de(novo)
    assert admin.post("/admin/master/transfer", {"to_user_id": un, "password": "errada"}).json()["detail"] == "senha incorreta"
    assert admin.post("/admin/master/transfer", {"to_user_id": admin.me["id"], "password": ADMIN_PW}).status_code == 400
    caixa.clear()
    r = admin.post("/admin/master/transfer", {"to_user_id": un, "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    assert caixa[-1][0] == admin.me["email"]
    code = _codigo(caixa)
    errado = "000000" if code != "000000" else "111111"
    r = admin.post("/admin/master/transfer/confirm", {"code": errado})
    assert r.status_code == 400 and "4 tentativas" in r.json()["detail"]
    assert teams.master_id() == admin.me["id"]
    r = admin.post("/admin/master/transfer/confirm", {"code": f" {code} "})
    assert r.status_code == 200, r.text
    assert teams.master_id() == un
    # Reusar o código: não vale.
    assert novo.post("/admin/master/transfer/confirm", {"code": code}).status_code == 400
    assert admin.post("/admin/master/transfer/confirm", {"code": code}).status_code == 403  # não é mais master
    # Quem recebe é avisado (no app e por e-mail) e fica no log de admin.
    me = novo.get("/auth/me").json()
    assert me["is_master"] is True and "master" in me["role_notice"]["added"]
    assert any(to == "novo@example.com" and "admin master" in subj for to, subj, _ in caixa)
    acoes = {r["action"] for r in db.query_all("SELECT action FROM audit_log WHERE action LIKE 'master.%%'")}
    assert {"master.transfer_code", "master.transfer_fail", "master.transfer", "master.received"} <= acoes
    # O antigo master pode perder o admin agora; o novo, não (só ele passa adiante).
    assert novo.put(f"/admin/users/{admin.me['id']}/roles", {"roles": ["user"]}).status_code == 200
    assert novo.put(f"/admin/users/{un}/roles", {"roles": ["user"]}).status_code == 400


def test_codigo_vencido_e_limite_de_tentativas(admin, novo_usuario, caixa):
    novo = novo_usuario("novo@example.com")
    _papeis(admin, novo, ["user", "admin"])
    un = uid_de(novo)
    admin.post("/admin/master/transfer", {"to_user_id": un, "password": ADMIN_PW})
    code = _codigo(caixa)
    db.execute("UPDATE auth_links SET expires_at = now() - interval '1 second' WHERE kind = 'master'")
    assert "vencido" in admin.post("/admin/master/transfer/confirm", {"code": code}).json()["detail"]
    admin.post("/admin/master/transfer", {"to_user_id": un, "password": ADMIN_PW})
    code = _codigo(caixa)
    errado = "000000" if code != "000000" else "111111"
    for _ in range(4):
        assert admin.post("/admin/master/transfer/confirm", {"code": errado}).status_code == 400
    assert admin.post("/admin/master/transfer/confirm", {"code": errado}).status_code == 429
    assert admin.post("/admin/master/transfer/confirm", {"code": code}).status_code == 400  # morreu
    assert teams.master_id() == admin.me["id"]
    assert admin.post("/admin/master/transfer/confirm", {"code": "12345"}).status_code == 422


def test_transferir_sem_email_configurado(admin, novo_usuario):
    novo = novo_usuario("novo@example.com")
    _papeis(admin, novo, ["user", "admin"])
    r = admin.post("/admin/master/transfer", {"to_user_id": uid_de(novo), "password": ADMIN_PW})
    assert r.status_code == 409 and "e-mail" in r.json()["detail"]


def test_para_quem_nao_e_admin_nao_transfere(admin, novo_usuario, caixa):
    novo = novo_usuario("novo@example.com")
    assert admin.post("/admin/master/transfer", {"to_user_id": uid_de(novo), "password": ADMIN_PW}).status_code == 400


# ------------------------------------------------------------- pentest focado --

def test_pentest_idor_e_escalada(admin, cena, novo_usuario):
    chefe, ana, bia = cena
    ua, ub = uid_de(ana), uid_de(bia)
    _equipe(admin, "Campo", chefe, ana)
    eid = _equipe(admin, "Escritório", bia)
    # Não-admin não mexe em equipes nem no master.
    for r in (chefe.get("/admin/teams"), chefe.post("/admin/teams", {"name": "Minha"}),
              chefe.put(f"/admin/users/{uid_de(chefe)}/teams", {"team_ids": [eid]}),
              chefe.patch(f"/admin/teams/{eid}", {"member_ids": [uid_de(chefe)]}),
              chefe.get("/admin/master"), chefe.put("/admin/master/roles", {"viewer": True}),
              chefe.post("/admin/master/transfer", {"to_user_id": uid_de(chefe), "password": SENHA_PADRAO})):
        assert r.status_code == 403
    # IDOR entre equipes: id de outra equipe no recorte, ids diretos.
    assert chefe.get(f"/viewer/team?team={eid}").status_code == 404
    assert chefe.get(f"/viewer/export/apontamentos.csv?team={eid}").status_code == 404
    assert chefe.get(f"/viewer/users/{ub}/projects").status_code == 404
    assert chefe.get(f"/assign/people?team={eid}").status_code == 404
    # Escalada para master: nenhuma rota além da transferência grava o master.
    outro = novo_usuario("outro@example.com")
    _papeis(admin, outro, ["user", "admin"])
    assert outro.post(f"/admin/users/{admin.me['id']}/block").status_code == 400
    assert outro.put(f"/admin/users/{admin.me['id']}/roles", {"roles": ["user"]}).status_code == 400
    assert outro.post(f"/admin/users/{admin.me['id']}/delete", {"confirm_email": admin.me["email"]}).status_code == 400
    r = admin.post("/me/delete", {"password": ADMIN_PW})
    assert r.status_code == 400 and "admin master" in r.json()["detail"]  # há outro admin, mas ele é o master
    assert teams.master_id() == admin.me["id"]
    # Chave de API nunca alcança o admin (nem o master).
    chave = Bearer(criar_chave(admin)["token"])
    assert chave.get("/admin/master").status_code == 403
    assert chave.post("/admin/master/transfer", {"to_user_id": uid_de(outro), "password": ADMIN_PW}).status_code == 403
    assert ua  # (usado acima pela cena)


def test_master_sempre_existe(admin):
    db.execute("UPDATE app_settings SET master_user_id = NULL")
    teams.ensure_master()
    assert teams.master_id() == admin.me["id"]
