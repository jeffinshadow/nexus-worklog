"""Auditoria p04 (fila sem sinal): o que o app passou a pedir ao servidor. A fila em si
(fila.js) é conferida no navegador; aqui fica o contrato de que ela depende."""
from datetime import date, timedelta


def test_tempo_reenviado_pela_fila_nao_duplica(usuario):
    """Resposta perdida: a fila reenvia o apontamento com o mesmo external_ref e o mesmo dia."""
    tid = usuario.post("/worklog", {"title": "Trocar a fonte do servidor"}).json()["id"]
    ontem = (date.today() - timedelta(days=1)).isoformat()
    corpo = {"minutes": 25, "day": ontem, "note": None, "external_ref": "app-p04-tempo-1"}
    a = usuario.post(f"/worklog/{tid}/time", corpo)
    b = usuario.post(f"/worklog/{tid}/time", corpo)
    assert a.status_code == 201 and b.status_code == 200, (a.text, b.text)
    assert b.json()["id"] == a.json()["id"] and b.json()["existing"]
    t = usuario.get(f"/worklog/{tid}").json()
    assert t["minutes"] == 25 and len(t["time"]) == 1 and t["time"][0]["day"] == ontem


def test_quadro_do_hoje_com_50_concluidas_e_o_das_rotinas_com_1(usuario):
    """O Hoje pede /board?done_limit=50 e quem só usa as rotinas pede done_limit=1:
    as abertas e as rotinas vêm inteiras; só a lista de concluídas encolhe."""
    usuario.post("/recurring", {"label": "Conferir o backup"})
    for i in range(3):
        usuario.post("/worklog", {"title": f"Feita {i}", "status": "done"})
    usuario.post("/worklog", {"title": "Aberta"})
    cheio = usuario.get("/board").json()
    hoje = usuario.get("/board?done_limit=50").json()
    rotinas = usuario.get("/board?done_limit=1").json()
    assert [t["id"] for t in hoje["done"]] == [t["id"] for t in cheio["done"]] and len(hoje["done"]) == 3
    assert len(rotinas["done"]) == 1 and rotinas["done_total"] == 3
    for b in (hoje, rotinas):
        assert b["recurring"] == cheio["recurring"] and len(b["recurring"]) == 1
        assert [t["id"] for t in b["in_progress"]] == [t["id"] for t in cheio["in_progress"]]
        assert b["today"] == cheio["today"]
