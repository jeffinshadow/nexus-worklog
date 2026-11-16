"""Gauntlet loop, rodada 1: pontos frágeis achados na leitura do código.

Exportação de quem teve tarefas transferidas, textos só com espaços, MCP com
params fora do formato, passkey de conta bloqueada, rotina excluída duas vezes,
convite repetido e os rótulos que faltavam no Histórico."""
import json

import pytest
from psycopg.errors import UniqueViolation

from app import db
from conftest import Api, Bearer, SENHA_PADRAO, criar_chave, hist, uid_de
from test_passkeys import _cadastrar, _entrar


def test_exportar_tudo_depois_de_ter_tarefas_transferidas(admin, novo_usuario):
    """O tempo apontado fica com quem apontou; a tarefa vai para outra pessoa.
    A exportação de quem saiu (e voltou) quebrava ao procurar essa tarefa."""
    sai = novo_usuario("sai@example.com")
    fica = novo_usuario("fica@example.com")
    t = sai.post("/worklog", {"title": "Chamado aberto"}).json()
    assert sai.post(f"/worklog/{t['id']}/time", {"minutes": 30}).status_code == 201
    propria = sai.post("/worklog", {"title": "Fica comigo", "status": "done"}).json()
    sai.post(f"/worklog/{propria['id']}/time", {"minutes": 15})
    sid = uid_de(sai)
    assert admin.post(f"/admin/users/{sid}/block", {"transfer_to": uid_de(fica)}).status_code == 200
    temp = admin.post(f"/admin/users/{sid}/reset-password").json()["temp_password"]  # libera o acesso
    volta = Api()
    volta.login("sai@example.com", temp)
    assert volta.post("/auth/change-password", {"current_password": temp, "new_password": SENHA_PADRAO + "2"}).status_code == 200
    volta.login("sai@example.com", SENHA_PADRAO + "2")

    r = volta.get("/export/tudo.json")
    assert r.status_code == 200, r.text
    dados = json.loads(r.content)
    assert [x["title"] for x in dados["tasks"]] == ["Fica comigo"]
    assert [e["minutes"] for e in dados["tasks"][0]["time"]] == [15]
    fora = dados["time_on_transferred_tasks"]
    assert len(fora) == 1 and fora[0]["minutes"] == 30 and fora[0]["task_title"] == "Chamado aberto"
    # Quem nunca teve tarefa transferida recebe a lista vazia.
    assert json.loads(fica.get("/export/tudo.json").content)["time_on_transferred_tasks"] == []


def test_texto_so_com_espacos_e_recusado_e_pontas_saem(usuario):
    assert usuario.post("/worklog", {"title": "   "}).status_code == 422
    t = usuario.post("/worklog", {"title": "  Trocar o switch  "}).json()
    assert usuario.get(f"/worklog/{t['id']}").json()["title"] == "Trocar o switch"
    assert usuario.patch(f"/worklog/{t['id']}", {"title": " \t "}).status_code == 422
    assert usuario.get(f"/worklog/{t['id']}").json()["title"] == "Trocar o switch"
    # Anotação e item em branco davam erro 500 (o banco recusa texto vazio).
    assert usuario.post(f"/worklog/{t['id']}/notes", {"body": "   "}).status_code == 422
    assert usuario.post(f"/worklog/{t['id']}/checklist", {"label": "  "}).status_code == 422
    item = usuario.post(f"/worklog/{t['id']}/checklist", {"label": " Testar "}).json()
    assert item["label"] == "Testar"
    assert usuario.patch(f"/checklist/{item['id']}", {"label": "   "}).status_code == 422
    assert usuario.post("/recurring", {"label": "   "}).status_code == 422
    r = usuario.post("/recurring", {"label": "  Conferir backup "})
    assert r.status_code == 201, r.text
    assert usuario.get("/board").json()["recurring"][0]["label"] == "Conferir backup"


def test_mcp_params_fora_do_formato_vira_erro_do_protocolo(usuario):
    ia = Bearer(criar_chave(usuario)["token"])
    for params in ([1, 2], "texto", 7):
        r = ia.rpc("tools/call", params)
        assert r.status_code == 200, r.text
        assert r.json()["error"]["code"] == -32602
    r = ia.rpc("tools/call", {"name": ["get_today"], "arguments": {}})
    assert r.status_code == 200 and r.json()["error"]["code"] == -32602
    r = ia.rpc("prompts/get", {"name": {"a": 1}})
    assert r.status_code == 200 and r.json()["error"]["code"] == -32602
    # O caminho normal segue igual.
    assert "isError" in ia.tool("get_today") and not ia.tool("get_today")["isError"]


def test_passkey_que_sobrou_em_conta_bloqueada_nao_entra(usuario):
    aut = _cadastrar(usuario)
    db.execute("UPDATE users SET blocked_at = now() WHERE id = %s", (uid_de(usuario),))
    _, r = _entrar(aut)
    assert r.status_code == 403 and "bloqueado" in r.json()["detail"]
    db.execute("UPDATE users SET blocked_at = NULL WHERE id = %s", (uid_de(usuario),))
    assert _entrar(aut)[1].status_code == 200


def test_excluir_rotina_duas_vezes_grava_uma_vez(usuario):
    rid = usuario.post("/recurring", {"label": "Ronda"}).json()["id"]
    assert usuario.delete(f"/recurring/{rid}").status_code == 200
    antes = db.query_one("SELECT deactivated_at FROM recurring_tasks WHERE id = %s", (rid,))["deactivated_at"]
    assert usuario.delete(f"/recurring/{rid}").status_code == 200  # clique repetido: sem erro
    assert db.query_one("SELECT deactivated_at FROM recurring_tasks WHERE id = %s", (rid,))["deactivated_at"] == antes
    assert sum(1 for h in hist(usuario, entity="recurring", entity_id=rid) if h["action"] == "recurring.deactivate") == 1
    assert usuario.delete("/recurring/999999").status_code == 404


def test_convite_repetido_responde_409(admin):
    assert admin.post("/admin/users", {"email": "nova@example.com"}).status_code == 201
    assert admin.post("/admin/users", {"email": "NOVA@example.com"}).status_code == 409


def test_historico_nomeia_passkey(usuario):
    _cadastrar(usuario, nome="Celular")
    linha = next(h for h in hist(usuario, entity="passkey") if h["action"] == "passkey.add")
    assert linha["summary"] == "cadastrou a passkey “Celular”"


# ------------------------------------------------------------- transações --

def test_transacao_desfaz_tudo_e_erro_tratado_nao_a_derruba(usuario):
    uid = uid_de(usuario)
    novo = "INSERT INTO projects (user_id, name) VALUES (%s, %s)"
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.execute(novo, (uid, "A"))
            assert db.query_one("SELECT 1 FROM projects WHERE user_id = %s", (uid,))  # a própria transação enxerga
            raise RuntimeError("falha no meio")
    assert not db.query_one("SELECT 1 FROM projects WHERE user_id = %s", (uid,))
    with db.transaction():
        db.execute(novo, (uid, "A"))
        with pytest.raises(UniqueViolation):  # erro tratado: só o comando volta atrás
            db.execute(novo, (uid, "A"))
        with db.transaction():  # uma dentro da outra é a mesma
            db.execute(novo, (uid, "B"))
    nomes = [r["name"] for r in db.query_all("SELECT name FROM projects WHERE user_id = %s ORDER BY name", (uid,))]
    assert nomes == ["A", "B"]


def test_desfazer_exclusao_e_tudo_ou_nada(usuario, monkeypatch):
    """Uma falha no meio do desfazer não deixa a tarefa de volta pela metade."""
    from app.routers import history as hmod
    t = usuario.post("/worklog", {"title": "Com anotação"}).json()
    usuario.post(f"/worklog/{t['id']}/notes", {"body": "trocar o cabo"})
    usuario.post(f"/worklog/{t['id']}/checklist", {"label": "testar"})
    assert usuario.delete(f"/worklog/{t['id']}").status_code == 200
    hid = hist(usuario, entity="worklog", entity_id=t["id"])[0]["id"]

    def quebra(*a, **k):
        raise RuntimeError("falha no meio")
    monkeypatch.setattr(hmod, "_put_item", quebra)
    with pytest.raises(RuntimeError):
        usuario.post(f"/history/{hid}/undo")
    assert not db.query_one("SELECT 1 FROM worklog_tasks WHERE id = %s", (t["id"],))
    assert not db.query_one("SELECT 1 FROM task_notes WHERE task_id = %s", (t["id"],))
    assert hist(usuario, entity="worklog", entity_id=t["id"])[0]["can_undo"]

    monkeypatch.undo()
    assert usuario.post(f"/history/{hid}/undo").status_code == 200
    volta = usuario.get(f"/worklog/{t['id']}").json()
    assert [n["body"] for n in volta["notes"]] == ["trocar o cabo"] and [c["label"] for c in volta["checklist"]] == ["testar"]
    assert usuario.post(f"/history/{hid}/undo").status_code == 409  # já desfeita


def test_excluir_projeto_e_tudo_ou_nada(usuario, monkeypatch):
    from app import audit
    p = usuario.post("/projects", {"name": "Filial"}).json()
    q = usuario.post("/projects", {"name": "Matriz"}).json()
    t = usuario.post("/worklog", {"title": "Em dois", "project_id": p["id"], "extra_project_ids": [q["id"]]}).json()
    o = usuario.post(f"/projects/{p['id']}/objectives", {"title": "Trocar switches"}).json()
    real = audit.record

    def quebra(ctx, action, *a, **k):
        if action == "project.delete":
            raise RuntimeError("falha no fim")
        return real(ctx, action, *a, **k)
    monkeypatch.setattr(audit, "record", quebra)
    with pytest.raises(RuntimeError):
        usuario.delete(f"/projects/{p['id']}")
    # Nada mudou: o projeto, o objetivo e o principal da tarefa seguem como estavam.
    assert db.query_one("SELECT 1 FROM projects WHERE id = %s", (p["id"],))
    assert db.query_one("SELECT 1 FROM project_objectives WHERE id = %s", (o["id"],))
    assert db.query_one("SELECT project_id FROM worklog_tasks WHERE id = %s", (t["id"],))["project_id"] == p["id"]
    monkeypatch.undo()
    assert usuario.delete(f"/projects/{p['id']}").status_code == 200
    assert db.query_one("SELECT project_id FROM worklog_tasks WHERE id = %s", (t["id"],))["project_id"] == q["id"]


def test_ordens_num_comando_so(usuario):
    ids = [usuario.post("/recurring", {"label": n}).json()["id"] for n in ("A", "B", "C")]
    assert usuario.post("/recurring/order", {"ids": [ids[2], ids[0], ids[1]]}).status_code == 200
    assert [r["label"] for r in usuario.get("/board").json()["recurring"]] == ["C", "A", "B"]
    p = usuario.post("/projects", {"name": "Obra"}).json()
    obj = [usuario.post(f"/projects/{p['id']}/objectives", {"title": n}).json()["id"] for n in ("1", "2", "3")]
    assert usuario.post(f"/projects/{p['id']}/objectives/order", {"ids": [obj[1], obj[2], obj[0]]}).status_code == 200
    pos = db.query_all("SELECT title, position FROM project_objectives WHERE project_id = %s ORDER BY position", (p["id"],))
    assert [(r["title"], r["position"]) for r in pos] == [("2", 0), ("3", 1), ("1", 2)]
    # Excluir o objetivo manda as tarefas dele para o fim de "Sem objetivo", na ordem que tinham.
    a = usuario.post("/worklog", {"title": "a", "project_id": p["id"], "objective_id": obj[0]}).json()
    b = usuario.post("/worklog", {"title": "b", "project_id": p["id"], "objective_id": obj[0]}).json()
    solta = usuario.post("/worklog", {"title": "solta", "project_id": p["id"]}).json()
    assert usuario.delete(f"/objectives/{obj[0]}").json()["tasks"] == 2
    ordem = db.query_all(
        "SELECT title FROM worklog_tasks WHERE project_id = %s AND objective_id IS NULL ORDER BY exec_position", (p["id"],))
    assert [r["title"] for r in ordem] == ["solta", "a", "b"] and {a["id"], b["id"], solta["id"]}


# ------------------------------------------------- lista por período e projeto --

def test_listar_por_periodo_filtra_o_projeto_no_banco(usuario):
    hoje = usuario.get("/board").json()["today"]
    p = usuario.post("/projects", {"name": "Filial"}).json()
    q = usuario.post("/projects", {"name": "Matriz"}).json()
    usuario.post("/worklog", {"title": "principal", "project_id": p["id"]})
    usuario.post("/worklog", {"title": "extra", "project_id": q["id"], "extra_project_ids": [p["id"]]})
    usuario.post("/worklog", {"title": "outro", "project_id": q["id"]})
    usuario.post("/worklog", {"title": "sem projeto", "project_id": None})
    r = usuario.get(f"/worklog?from={hoje}&to={hoje}&project={p['id']}")
    assert r.status_code == 200 and r.headers["X-Total-Count"] == "2"
    assert sorted(t["title"] for t in r.json()) == ["extra", "principal"]
    # Paginado já filtrado: a segunda página traz a que faltava, não uma de outro projeto.
    um = usuario.get(f"/worklog?from={hoje}&to={hoje}&project={p['id']}&limit=1&offset=1")
    assert len(um.json()) == 1 and um.json()[0]["title"] in ("extra", "principal")
    # Sem o filtro, tudo; o período continua valendo pelos dias inteiros (fuso da app).
    assert usuario.get(f"/worklog?from={hoje}&to={hoje}").headers["X-Total-Count"] == "4"
    assert usuario.get("/worklog?to=2020-01-01").json() == []
    # Pela IA, o mesmo filtro (com paginação no banco).
    ia = Bearer(criar_chave(usuario)["token"])
    txt = ia.tool("list_tasks", **{"from": hoje, "to": hoje, "project": "Filial"})["content"][0]["text"]
    assert "principal" in txt and "extra" in txt and "outro" not in txt and "sem projeto" not in txt
