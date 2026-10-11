from app import db
from conftest import Bearer, criar_chave, texto


def test_handshake_e_versao(usuario):
    b = Bearer(criar_chave(usuario)["token"])
    r = b.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                             "clientInfo": {"name": "teste", "version": "1"}})
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["protocolVersion"] == "2025-06-18" and "tools" in res["capabilities"]
    assert b.rpc("notifications/initialized", rid=None).status_code == 202
    assert b.rpc("ping").json()["result"] == {}
    assert b.rpc("initialize", {"protocolVersion": "1999-01-01"}).json()["result"]["protocolVersion"] == "2025-11-25"


def test_ferramentas_por_escopo(usuario):
    escrita = {t["name"] for t in Bearer(criar_chave(usuario)["token"]).rpc("tools/list").json()["result"]["tools"]}
    leitura = {t["name"] for t in Bearer(criar_chave(usuario, nome="r", scope="read")["token"]).rpc("tools/list").json()["result"]["tools"]}
    assert {"create_task", "set_recurring", "undo"} <= escrita
    assert "create_task" not in leitura and {"get_today", "list_tasks", "get_history"} <= leitura
    assert "delete_task" not in escrita  # a IA não exclui


def test_fluxo_completo_pela_ia(usuario):
    b = Bearer(criar_chave(usuario, nome="Assistente")["token"])
    res = b.tool("create_task", title="Revisar firewall", due_date="2030-01-01")
    assert not res["isError"] and "Revisar firewall" in texto(res)
    tid = int(texto(res).split("#")[1].split()[0])
    assert not b.tool("update_task", task_id=tid, due_date=None)["isError"]
    assert "prazo" not in texto(b.tool("list_tasks"))
    assert not b.tool("complete_task", task_id=tid)["isError"]
    rid = usuario.post("/recurring", {"label": "Conferir backups"}).json()["id"]
    assert not b.tool("set_recurring", task_id=rid, done=True)["isError"]
    hoje = texto(b.tool("get_today"))
    assert "[x]" in hoje and "Conferir backups" in hoje and "Revisar firewall" in hoje
    hist = texto(b.tool("get_history"))
    assert "IA (Assistente)" in hist


def test_ia_desfaz_o_proprio_engano(usuario):
    b = Bearer(criar_chave(usuario)["token"])
    tid = int(texto(b.tool("create_task", title="Errada")).split("#")[1].split()[0])
    hid = usuario.get("/history").json()[0]["id"]
    assert not b.tool("undo", history_id=hid)["isError"]
    assert all(t["id"] != tid for t in usuario.get("/board").json()["in_progress"])


def test_erros_viram_isError_ou_jsonrpc(usuario):
    b = Bearer(criar_chave(usuario)["token"])
    assert b.tool("complete_task", task_id=999999)["isError"]
    assert b.tool("create_task", title="")["isError"]
    assert b.rpc("tools/call", {"name": "nao_existe", "arguments": {}}).json()["error"]["code"] == -32602
    assert b.rpc("metodo/inexistente").json()["error"]["code"] == -32601
    leitura = Bearer(criar_chave(usuario, nome="r", scope="read")["token"])
    assert leitura.tool("create_task", title="x")["isError"]


def test_autenticacao_e_origem(usuario):
    sem = Bearer("nxs_invalida").rpc("tools/list")
    assert sem.status_code == 401 and "Bearer" in sem.headers.get("www-authenticate", "")
    # sessão do app (cookie) não serve para MCP
    r = usuario.c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401
    b = Bearer(criar_chave(usuario)["token"])
    assert b.rpc("tools/list", headers={"Origin": "https://site-malicioso.example"}).status_code == 403
    assert b.rpc("tools/list", headers={"Origin": "http://testserver"}).status_code == 200
    assert b.c.get("/mcp", headers=b.h).status_code == 405


def test_historico_registra_mcp(usuario):
    b = Bearer(criar_chave(usuario, nome="Claude")["token"])
    b.tool("create_task", title="Via MCP")
    h = usuario.get("/history").json()[0]
    assert (h["actor"], h["token_name"]) == ("mcp", "Claude")
    assert db.query_one("SELECT count(*) AS n FROM audit_log WHERE actor = 'mcp'")["n"] == 1
