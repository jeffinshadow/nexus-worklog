"""Entrega 7: papéis acumuláveis, consentimento e atribuição de tarefas."""
import pytest

from app import db, mailer
from app.routers import assign as assign_mod
from conftest import Bearer, criar_chave, hist, texto, uid_de


@pytest.fixture
def enviados(monkeypatch):
    """E-mails de atribuição capturados (sem SMTP, sem thread)."""
    caixa = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(assign_mod, "_spawn", lambda to, mail: caixa.append((to, mail.subject, mail.text())))
    return caixa


def _papeis(admin, u, roles):
    r = admin.put(f"/admin/users/{uid_de(u)}/roles", {"roles": roles})
    assert r.status_code == 200, r.text
    return r


def test_papeis_iniciais_e_me(admin, usuario):
    assert sorted(admin.get("/auth/me").json()["roles"]) == ["admin", "user", "viewer"]
    me = usuario.get("/auth/me").json()
    assert me["roles"] == ["user"] and me["accepts_assignments_at"] is None and me["retro_days"] == 60


def test_tela_de_permissoes_e_protecoes(admin, usuario):
    lista = {u["email"]: u for u in admin.get("/admin/users").json()}
    assert lista[usuario.me["email"]]["roles"] == ["user"]
    assert usuario.get("/admin/users").status_code == 403
    _papeis(admin, usuario, ["user", "assigner", "viewer"])
    assert sorted(usuario.get("/auth/me").json()["roles"]) == ["assigner", "user", "viewer"]
    # O admin não tira o próprio admin; e nunca fica sem nenhum.
    r = admin.put(f"/admin/users/{uid_de(admin)}/roles", {"roles": ["user"]})
    assert r.status_code == 400
    assert admin.put(f"/admin/users/{uid_de(usuario)}/roles", {"roles": []}).status_code == 422
    assert admin.put(f"/admin/users/{uid_de(usuario)}/roles", {"roles": ["dono"]}).status_code == 422
    # Mudança fica no histórico de quem foi alterado.
    assert any(h["action"] == "user.roles" for h in hist(usuario))
    # users.role espelha admin (compatibilidade).
    _papeis(admin, usuario, ["admin"])
    assert db.query_one("SELECT role FROM users WHERE id = %s", (uid_de(usuario),))["role"] == "admin"


def test_visualizador_saiu_do_admin(admin, usuario, novo_usuario):
    uid = uid_de(usuario)
    so_admin = novo_usuario("chefe@example.com")
    _papeis(admin, so_admin, ["admin"])
    assert so_admin.get(f"/viewer/users/{uid}/board").status_code == 403
    assert so_admin.get("/viewer/export/apontamentos.csv").status_code == 403
    assert so_admin.get("/admin/users").status_code == 200
    # Visualizador sem admin: vê registros e relatórios, não mexe em contas.
    vis = novo_usuario("vis@example.com")
    _papeis(admin, vis, ["viewer"])
    assert vis.get(f"/viewer/users/{uid}/board").status_code == 200
    assert vis.get(f"/viewer/users/{uid}/dashboard").status_code == 200
    assert vis.get("/viewer/export/apontamentos.csv").status_code == 200
    assert vis.get("/admin/users").status_code == 403
    # Lista só quem tem registro próprio (vis não tem o papel Usuário).
    emails = [u["email"] for u in vis.get("/viewer/users").json()]
    assert usuario.me["email"] in emails and "vis@example.com" not in emails
    assert vis.get(f"/viewer/users/{uid_de(vis)}/board").status_code == 404
    # Por chave de API, nunca.
    assert Bearer(criar_chave(vis)["token"]).get(f"/viewer/users/{uid}/board").status_code == 403


def test_atribuir_exige_papel_e_consentimento(admin, usuario, novo_usuario, enviados):
    chefe = novo_usuario("chefe@example.com")
    alvo = uid_de(usuario)
    tarefa = {"user_id": alvo, "title": "Trocar o nobreak", "due_date": "2030-01-10", "priority": 1}
    assert chefe.post("/assign", tarefa).status_code == 403  # sem o papel
    _papeis(admin, chefe, ["user", "assigner"])
    r = chefe.post("/assign", tarefa)
    assert r.status_code == 403 and "aceitou" in r.json()["detail"]  # sem consentimento
    # Tela de consentimentos: admin e atribuidor veem; usuário comum não.
    assert usuario.get("/assign/people").status_code == 403
    pessoas = {p["email"]: p for p in chefe.get("/assign/people").json()}
    assert pessoas[usuario.me["email"]]["accepts"] is False
    assert usuario.put("/me/assignments", {"accept": True}).status_code == 200
    pessoas = {p["email"]: p for p in admin.get("/assign/people").json()}
    assert pessoas[usuario.me["email"]]["accepts"] and pessoas[usuario.me["email"]]["accepts_assignments_at"]
    r = chefe.post("/assign", tarefa)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert r.json()["emailed"] is True
    # E-mail para quem recebeu, com o título.
    assert len(enviados) == 1 and enviados[0][0] == usuario.me["email"] and "Trocar o nobreak" in enviados[0][1]
    # A tarefa é de quem recebeu, com "atribuída por".
    t = usuario.get(f"/worklog/{tid}").json()
    assert t["assigned_by_name"] and t["title"] == "Trocar o nobreak" and t["priority"] == 1
    board = usuario.get("/board").json()
    assert any(x["id"] == tid and x["assigned_by_name"] for x in board["in_progress"])
    assert chefe.get(f"/worklog/{tid}").status_code == 404  # quem atribuiu não edita
    # Quem atribuiu acompanha o status.
    usuario.post(f"/worklog/{tid}/finish")
    enviadas = chefe.get("/assign/sent").json()
    assert enviadas[0]["id"] == tid and enviadas[0]["status"] == "done" and enviadas[0]["completed_at"]
    # Histórico nas duas pontas; quem recebeu pode desfazer o recebimento.
    assert any(h["action"] == "assign.send" and "Trocar o nobreak" in h["summary"] for h in hist(chefe))
    rec = [h for h in hist(usuario, entity="worklog", entity_id=tid) if h["action"] == "worklog.assign"][0]
    assert "atribuída por" in rec["summary"]


def test_atribuir_regras(admin, usuario, novo_usuario, enviados):
    chefe = novo_usuario("chefe@example.com")
    _papeis(admin, chefe, ["user", "assigner"])
    chefe.put("/me/assignments", {"accept": True})
    assert chefe.post("/assign", {"user_id": uid_de(chefe), "title": "x"}).status_code == 400  # a si mesmo
    assert chefe.post("/assign", {"user_id": 99999, "title": "x"}).status_code == 404
    # Conta sem o papel Usuário não recebe.
    usuario.put("/me/assignments", {"accept": True})
    _papeis(admin, usuario, ["viewer"])
    assert chefe.post("/assign", {"user_id": uid_de(usuario), "title": "x"}).status_code == 404
    # Revogar o consentimento não apaga o que já foi recebido.
    _papeis(admin, usuario, ["user"])
    tid = chefe.post("/assign", {"user_id": uid_de(usuario), "title": "Fica"}).json()["id"]
    usuario.put("/me/assignments", {"accept": False})
    assert usuario.get(f"/worklog/{tid}").status_code == 200
    assert chefe.post("/assign", {"user_id": uid_de(usuario), "title": "y"}).status_code == 403


def test_atribuir_pelo_mcp(admin, usuario, novo_usuario, enviados):
    chefe = novo_usuario("chefe@example.com")
    ia = Bearer(criar_chave(chefe)["token"])
    nomes = [t["name"] for t in ia.rpc("tools/list").json()["result"]["tools"]]
    assert "assign_task" not in nomes  # sem o papel, nem aparece
    assert ia.rpc("tools/call", {"name": "assign_task", "arguments": {"to": "x", "title": "y"}}).json()["error"]
    _papeis(admin, chefe, ["user", "assigner"])
    usuario.put("/me/assignments", {"accept": True})
    nomes = [t["name"] for t in ia.rpc("tools/list").json()["result"]["tools"]]
    assert {"assign_task", "list_assignable", "list_assigned"} <= set(nomes)
    assert usuario.me["email"] in texto(ia.tool("list_assignable"))
    res = ia.tool("assign_task", to=usuario.me["email"], title="Revisar backup", priority="alta")
    assert not res["isError"], texto(res)
    assert "Atribuída a" in texto(res) and len(enviados) == 1
    res = ia.tool("assign_task", to="ninguem@example.com", title="x")
    assert res["isError"]
    assert "Revisar backup" in texto(ia.tool("list_assigned"))
    # Chave só de leitura não atribui.
    leitura = Bearer(criar_chave(chefe, nome="leitura", scope="read")["token"])
    assert leitura.post("/assign", {"user_id": uid_de(usuario), "title": "x"}).status_code == 403
    # Origem registrada como mcp no histórico de quem recebeu.
    rec = [h for h in hist(usuario) if h["action"] == "worklog.assign"][0]
    assert rec["actor"] == "mcp"


def test_consentimento_so_pelo_app(usuario):
    ia = Bearer(criar_chave(usuario)["token"])
    assert ia.c.put("/api/me/assignments", json={"accept": True}, headers=ia.h).status_code == 403
    assert usuario.put("/me/assignments", {"accept": True}).json()["accepts_assignments_at"]
    assert usuario.put("/me/assignments", {"accept": False}).json()["accepts_assignments_at"] is None
    acoes = [h["summary"] for h in hist(usuario) if h["action"] == "assignments.consent"]
    assert acoes == ["deixou de aceitar tarefas atribuídas", "passou a aceitar tarefas atribuídas"]
