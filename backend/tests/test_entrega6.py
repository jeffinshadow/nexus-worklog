"""Entrega 6: cronômetro, número do chamado, plantão, modelos de tarefa,
fechamento do dia (today_stats) e os prompts prontos do MCP."""
from app import db

from conftest import Bearer, criar_chave, dia_hoje, hist, texto, uid_de


def _put(u, path, body):
    return u.c.put("/api" + path, json=body, headers=u._h())


def _recuar_timer(u, minutos):
    db.execute("UPDATE task_timers SET started_at = now() - make_interval(mins => %s) WHERE user_id = %s",
               (minutos, uid_de(u)))


def _tempo(u, tid):
    return u.get(f"/worklog/{tid}").json()["minutes"]


# ------------------------------------------------------------- cronômetro --

def test_cronometro_inicia_para_e_aponta(usuario):
    tid = usuario.post("/worklog", {"title": "Migrar fileserver"}).json()["id"]
    r = usuario.post("/timer/start", {"task_id": tid})
    assert r.status_code == 200 and r.json()["timer"]["task_id"] == tid
    assert usuario.get(f"/worklog/{tid}").json()["status"] == "in_progress"  # começou = em andamento
    assert usuario.get("/board").json()["timer"]["title"] == "Migrar fileserver"
    _recuar_timer(usuario, 25)
    st = usuario.post("/timer/stop").json()["stopped"]
    assert st["minutes"] == 25 and st["note"] == "cronômetro"
    assert _tempo(usuario, tid) == 25 and usuario.get("/timer").json()["timer"] is None
    assert usuario.post("/timer/stop").status_code == 409


def test_trocar_de_tarefa_aponta_a_anterior(usuario):
    a = usuario.post("/worklog", {"title": "A"}).json()["id"]
    b = usuario.post("/worklog", {"title": "B"}).json()["id"]
    usuario.post("/timer/start", {"task_id": a})
    _recuar_timer(usuario, 10)
    r = usuario.post("/timer/start", {"task_id": b}).json()
    assert r["stopped"]["task_id"] == a and r["timer"]["task_id"] == b
    assert _tempo(usuario, a) == 10


def test_concluir_para_o_cronometro_e_descartar_nao_aponta(usuario):
    tid = usuario.post("/worklog", {"title": "Trocar switch"}).json()["id"]
    usuario.post("/timer/start", {"task_id": tid})
    _recuar_timer(usuario, 40)
    usuario.post(f"/worklog/{tid}/finish")
    assert _tempo(usuario, tid) == 40 and usuario.get("/timer").json()["timer"] is None
    assert usuario.post("/timer/start", {"task_id": tid}).status_code == 400  # concluída
    outra = usuario.post("/worklog", {"title": "Outra"}).json()["id"]
    usuario.post("/timer/start", {"task_id": outra})
    assert usuario.delete("/timer").status_code == 200 and _tempo(usuario, outra) == 0


def test_cronometro_nao_atrapalha_o_desfazer(usuario):
    tid = usuario.post("/worklog", {"title": "Antes"}).json()["id"]
    usuario.patch(f"/worklog/{tid}", {"title": "Depois", "status": "in_progress"})
    usuario.post("/timer/start", {"task_id": tid})
    ed = next(h for h in hist(usuario, entity="worklog", entity_id=tid) if h["action"] == "worklog.update")
    assert ed["can_undo"]
    assert usuario.post(f"/history/{ed['id']}/undo").status_code == 200


def test_cronometro_conta_como_atividade(usuario):
    tid = usuario.post("/worklog", {"title": "X"}).json()["id"]
    db.execute("DELETE FROM audit_log")
    usuario.post("/timer/start", {"task_id": tid})
    a = usuario.get("/me/activity").json()
    assert a["last_activity"] is not None and a["timer"]["task_id"] == tid


def test_cronometro_e_de_cada_um(usuario, novo_usuario):
    tid = usuario.post("/worklog", {"title": "Minha"}).json()["id"]
    assert novo_usuario("outra@example.com").post("/timer/start", {"task_id": tid}).status_code == 404


# ------------------------------------------------------ chamado e plantão --

def test_chamado_normalizado_editado_e_buscado(usuario):
    tid = usuario.post("/worklog", {"title": "Impressora do RH", "ticket": " #4821 "}).json()["id"]
    assert usuario.get(f"/worklog/{tid}").json()["ticket"] == "4821"
    assert [t["id"] for t in usuario.get("/search?q=%234821").json()["tasks"]] == [tid]
    usuario.patch(f"/worklog/{tid}", {"ticket": None})
    assert usuario.get(f"/worklog/{tid}").json()["ticket"] is None
    assert usuario.post("/worklog", {"title": "x", "ticket": "9" * 41}).status_code == 422
    usuario.patch(f"/worklog/{tid}", {"ticket": "4821"})
    assert "4821" in usuario.c.get("/api/export/tarefas.csv").content.decode("utf-8-sig")


def test_plantao_separado_no_relatorio(usuario):
    hoje = dia_hoje(usuario).isoformat()
    a = usuario.post("/worklog", {"title": "Link caiu às 2h", "after_hours": True}).json()["id"]
    b = usuario.post("/worklog", {"title": "Rotina"}).json()["id"]
    usuario.post(f"/worklog/{a}/time", {"minutes": 90})
    usuario.post(f"/worklog/{b}/time", {"minutes": 30})
    p = usuario.get(f"/reports/preview?start={hoje}&end={hoje}").json()
    assert p["minutes"] == 120
    s = usuario.get("/summary").json()["today_stats"]
    assert (s["minutes"], s["minutes_after_hours"]) == (120, 90)
    r = usuario.c.get(f"/api/reports/export?start={hoje}&end={hoje}")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


def test_desfazer_exclusao_preserva_chamado_e_plantao(usuario):
    tid = usuario.post("/worklog", {"title": "Plantão", "ticket": "77", "after_hours": True}).json()["id"]
    usuario.delete(f"/worklog/{tid}")
    h = next(h for h in hist(usuario, entity="worklog", entity_id=tid) if h["action"] == "worklog.delete")
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    t = usuario.get(f"/worklog/{tid}").json()
    assert (t["ticket"], t["after_hours"]) == ("77", True)


def test_endereco_dos_chamados(usuario):
    assert _put(usuario, "/me/tickets", {"ticket_url": "https://glpi.exemplo/front/ticket.form.php?id={id}"}).status_code == 200
    assert usuario.get("/auth/me").json()["ticket_url"].endswith("id={id}")
    assert _put(usuario, "/me/tickets", {"ticket_url": "javascript:alert(1)"}).status_code == 422
    assert _put(usuario, "/me/tickets", {"ticket_url": ""}).json()["ticket_url"] is None


# ---------------------------------------------------------------- modelos --

def test_modelos_criar_usar_e_nome_unico(usuario):
    pid = usuario.post("/projects", {"name": "Matriz"}).json()["id"]
    body = {"name": "Onboarding", "title": "Onboarding de colaborador", "priority": 1, "project_id": pid,
            "checklist": ["Criar conta no AD", "  ", "Liberar VPN", "Entregar notebook"]}
    m = usuario.post("/templates", body)
    assert m.status_code == 201 and m.json()["checklist"] == ["Criar conta no AD", "Liberar VPN", "Entregar notebook"]
    assert usuario.post("/templates", {**body, "name": "onboarding"}).status_code == 409
    r = usuario.post(f"/templates/{m.json()['id']}/use")
    assert r.status_code == 201 and r.json()["checklist"] == 3
    t = usuario.get(f"/worklog/{r.json()['id']}").json()
    assert (t["title"], t["priority"], t["project_id"], len(t["checklist"])) == ("Onboarding de colaborador", 1, pid, 3)
    assert usuario.c.put(f"/api/templates/{m.json()['id']}", json={**body, "name": "Onboarding v2"},
                         headers=usuario._h()).json()["name"] == "Onboarding v2"
    assert usuario.delete(f"/templates/{m.json()['id']}").status_code == 200
    assert usuario.get("/templates").json() == []


def test_modelo_de_outro_usuario(usuario, novo_usuario):
    m = usuario.post("/templates", {"name": "Meu", "title": "Meu"}).json()
    outra = novo_usuario("outra@example.com")
    assert outra.post(f"/templates/{m['id']}/use").status_code == 404
    assert outra.get("/templates").json() == []


# -------------------------------------------------------------------- MCP --

def test_mcp_prompts_e_ferramentas_novas(usuario):
    b = Bearer(criar_chave(usuario)["token"])
    init = b.rpc("initialize", {"protocolVersion": "2025-06-18"}).json()["result"]
    assert "prompts" in init["capabilities"]
    nomes = [p["name"] for p in b.rpc("prompts/list").json()["result"]["prompts"]]
    assert nomes == ["resumo_semanal", "daily"]
    msg = b.rpc("prompts/get", {"name": "resumo_semanal", "arguments": {"para": "o cliente"}}).json()["result"]
    assert "o cliente" in msg["messages"][0]["content"]["text"]
    assert b.rpc("prompts/get", {"name": "nao_existe"}).json()["error"]["code"] == -32602

    tid = usuario.post("/worklog", {"title": "Backup do ERP"}).json()["id"]
    assert "iniciado" in texto(b.tool("start_timer", task_id=tid))
    assert "Cronômetro rodando" in texto(b.tool("get_today"))
    _recuar_timer(usuario, 15)
    assert "15 min" in texto(b.tool("stop_timer"))
    usuario.post("/templates", {"name": "Servidor novo", "title": "Subir servidor", "checklist": ["SO", "Backup"]})
    assert "Servidor novo" in texto(b.tool("list_templates"))
    assert "Criada pelo modelo" in texto(b.tool("create_from_template", template="servidor novo"))
    criada = texto(b.tool("create_task", title="Chamado da impressora", ticket="#99", after_hours=True))
    assert "(chamado 99)" in criada and "(plantão)" in criada
