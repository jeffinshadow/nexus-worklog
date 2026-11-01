"""Lote G — API aberta: feed de mudanças, idempotência, webhooks, contrato e dados."""
import pytest

from app import db
from app.routers import history
from conftest import Bearer, criar_chave


@pytest.fixture(autouse=True)
def _sem_atraso(monkeypatch):
    # O feed esconde os últimos 2 s (ordem dos ids); nos testes, tudo aparece já.
    monkeypatch.setattr(history, "FEED_LAG_SECONDS", 0)


# ---------------------------------------------------------------- feed (F1) --

def test_feed_em_ordem_crescente_com_lapide_e_external_ref(usuario):
    b = Bearer(criar_chave(usuario, scope="read")["token"])
    inicio = b.get("/history?after=0").json()
    cursor = inicio[-1]["id"] if inicio else 0
    t = usuario.post("/worklog", {"title": "Alerta disco", "external_ref": "zbx-1"}).json()["id"]
    usuario.post(f"/worklog/{t}/finish")
    usuario.delete(f"/worklog/{t}")
    itens = b.get(f"/history?after={cursor}").json()
    assert [i["action"] for i in itens] == ["worklog.create", "worklog.finish", "worklog.delete"]
    assert [i["id"] for i in itens] == sorted(i["id"] for i in itens)
    assert all(i["entity"] == "worklog" and i["entity_id"] == t and i["external_ref"] == "zbx-1" for i in itens)
    assert {"id", "at", "actor", "token_name"} <= set(itens[0])
    # O cursor avança: depois do último, nada.
    assert b.get(f"/history?after={itens[-1]['id']}").json() == []
    assert len(b.get(f"/history?after={cursor}&limit=2").json()) == 2


def test_feed_so_da_propria_pessoa(usuario, novo_usuario):
    outro = novo_usuario("outro@example.com")
    outro.post("/worklog", {"title": "Do outro"})
    usuario.post("/worklog", {"title": "Minha"})
    meus = usuario.get("/history?after=0").json()
    ids_outro = {r["id"] for r in db.query_all(
        "SELECT a.id FROM audit_log a JOIN users u ON u.id = a.user_id WHERE u.email = 'outro@example.com'")}
    assert meus and not ({i["id"] for i in meus} & ids_outro)


def test_feed_cursor_alem_da_retencao_410(usuario):
    for n in range(4):
        usuario.post("/worklog", {"title": f"T{n}"})
    ids = [i["id"] for i in usuario.get("/history?after=0").json()]
    db.execute("DELETE FROM audit_log WHERE id <= %s", (ids[2],))  # a faxina de 180 dias levou o começo
    assert usuario.get(f"/history?after={ids[0]}").status_code == 410
    assert usuario.get(f"/history?after={ids[2]}").status_code == 200  # cursor logo antes do que restou: ok
    assert usuario.get("/history?after=0").status_code == 200  # recomeçar do zero sempre vale


# ------------------------------------------------------- idempotência (I1) --

def test_anotacao_e_tempo_com_external_ref_nao_duplicam(usuario):
    b = Bearer(criar_chave(usuario)["token"])
    t = b.post("/worklog", {"title": "Chamado 42"}).json()["id"]
    r1 = b.post(f"/worklog/{t}/notes", {"body": "Reiniciei o serviço", "external_ref": "n8n-1"})
    r2 = b.post(f"/worklog/{t}/notes", {"body": "Reiniciei o serviço", "external_ref": "n8n-1"})
    assert r1.status_code == 201 and r2.status_code == 200
    assert r2.json()["existing"] and r2.json()["id"] == r1.json()["id"]
    r1 = b.post(f"/worklog/{t}/time", {"minutes": 30, "external_ref": "n8n-2"})
    r2 = b.post(f"/worklog/{t}/time", {"minutes": 30, "external_ref": "n8n-2"})
    assert r1.status_code == 201 and r2.status_code == 200 and r2.json()["id"] == r1.json()["id"]
    det = b.get(f"/worklog/{t}").json()
    assert len(det["notes"]) == 1 and det["minutes"] == 30
    # Sem external_ref continua como sempre (duplica de propósito).
    assert b.post(f"/worklog/{t}/notes", {"body": "outra"}).status_code == 201
    assert b.post(f"/worklog/{t}/notes", {"body": "outra"}).status_code == 201


def test_external_ref_e_por_pessoa(usuario, novo_usuario):
    outro = novo_usuario("outro@example.com")
    t1 = usuario.post("/worklog", {"title": "A"}).json()["id"]
    t2 = outro.post("/worklog", {"title": "B"}).json()["id"]
    assert usuario.post(f"/worklog/{t1}/time", {"minutes": 5, "external_ref": "x"}).status_code == 201
    assert outro.post(f"/worklog/{t2}/time", {"minutes": 5, "external_ref": "x"}).status_code == 201


def test_busca_por_external_ref(usuario):
    t = usuario.post("/worklog", {"title": "Alerta", "external_ref": "zbx-9"}).json()["id"]
    usuario.post("/worklog", {"title": "Outra"})
    assert [x["id"] for x in usuario.get("/worklog?external_ref=zbx-9").json()] == [t]
    assert usuario.get("/worklog?external_ref=nao-existe").json() == []
    p = usuario.post("/projects", {"name": "Cliente X", "external_ref": "crm-7"}).json()["id"]
    usuario.patch(f"/projects/{p}", {"archived": True})
    achou = usuario.get("/projects?external_ref=crm-7").json()
    assert [x["id"] for x in achou] == [p] and achou[0]["external_ref"] == "crm-7"
    assert usuario.get("/projects?external_ref=nada").json() == []
