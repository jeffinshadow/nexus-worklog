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
