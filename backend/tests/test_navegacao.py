"""Navegação e nomes: "blocked" aparece como "aguardando" (PDF, CSV, ICS, MCP)."""
from app import report_pdf
from conftest import Bearer, criar_chave, dia_hoje, texto


def test_aguardando_no_pdf_csv_e_mcp(usuario, monkeypatch):
    usuario.post("/worklog", {"title": "Trocar fonte do servidor", "status": "blocked",
                              "blocked_reason": "peça do fornecedor"})
    # PDF: a coluna "situação" das abertas usa o nome novo (o dado continua "blocked").
    escritos = []
    original = report_pdf._Report.text_at
    monkeypatch.setattr(report_pdf._Report, "text_at",
                        lambda self, x, y, w, h, text, align="L": (escritos.append(str(text)), original(self, x, y, w, h, text, align))[1])
    hoje = dia_hoje(usuario).isoformat()
    r = usuario.get(f"/reports/export?start={hoje}&end={hoje}")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert "aguardando" in escritos and "bloqueada" not in escritos
    # CSV: a coluna status.
    csv = usuario.get("/export/tarefas.csv").text
    assert "aguardando" in csv and "bloqueada" not in csv
    assert usuario.get("/worklog?status=open").json()[0]["status"] == "blocked"
    # MCP: a linha da tarefa e a passagem de turno falam "aguardando"; a IA aprende o nome.
    ia = Bearer(criar_chave(usuario)["token"])
    assert "[aguardando: peça do fornecedor]" in texto(ia.tool("list_tasks"))
    passagem = texto(ia.tool("get_handoff"))
    assert "Aguardando (1):" in passagem and "Bloquead" not in passagem
    tools = {t["name"]: t for t in ia.rpc("tools/list").json()["result"]["tools"]}
    assert "blocked = aguardando" in tools["create_task"]["inputSchema"]["properties"]["status"]["description"]
    prompts = str(ia.rpc("prompts/list").json())
    assert "bloquead" not in prompts.lower()


def test_duplicar_tarefa(usuario, novo_usuario):
    p1 = usuario.post("/projects", {"name": "Matriz"}).json()["id"]
    p2 = usuario.post("/projects", {"name": "Filial"}).json()["id"]
    tid = usuario.post("/worklog", {"title": "Preventiva do nobreak", "description": "sala 2", "priority": 1,
                                    "project_id": p1, "extra_project_ids": [p2], "due_date": dia_hoje(usuario).isoformat(),
                                    "ticket": "77", "status": "blocked", "blocked_reason": "chave"}).json()["id"]
    for label in ("Medir bateria", "Limpar filtro"):
        usuario.post(f"/worklog/{tid}/checklist", {"label": label})
    item = usuario.get(f"/worklog/{tid}").json()["checklist"][0]["id"]
    usuario.patch(f"/checklist/{item}", {"done": True})
    usuario.post(f"/worklog/{tid}/notes", {"body": "feito"})
    usuario.post(f"/worklog/{tid}/time", {"minutes": 30})
    r = usuario.post(f"/worklog/{tid}/duplicate")
    assert r.status_code == 201
    n = usuario.get(f"/worklog/{r.json()['id']}").json()
    assert (n["title"], n["description"], n["priority"], n["status"], n["project_id"]) == ("Preventiva do nobreak", "sala 2", 1, "todo", p1)
    assert [p["id"] for p in n["extra_projects"]] == [p2]
    assert [(c["label"], c["done"]) for c in n["checklist"]] == [("Medir bateria", False), ("Limpar filtro", False)]
    assert not n["notes"] and not n["minutes"] and n["due_date"] is None and n["ticket"] is None
    assert n["blocked_reason"] is None and n["completed_at"] is None
    # A original não muda.
    assert usuario.get(f"/worklog/{tid}").json()["checklist"][0]["done"] is True
    # Tarefa de outra pessoa: não encontrada.
    outra = novo_usuario("outra@example.com")
    assert outra.post(f"/worklog/{tid}/duplicate").status_code == 404
