"""Pequenas faltas do lado do usuário (gauntlet geral, R5): reabrir, editar
apontamento e anotação, exportações pelo período, ordem das rotinas, sair dos
outros aparelhos, chaves antigas, webhooks editáveis, descrição na atribuição."""
from datetime import timedelta

from app import db
from app.services import app_today
from conftest import SENHA_PADRAO, Api


def _tarefa(u, **extra):
    r = u.post("/worklog", {"title": "Trocar disjuntor", **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _ultimo(u, entity, eid):
    return u.get(f"/history?limit=1&entity={entity}&entity_id={eid}").json()[0]


# ------------------------------------------------------------------ reabrir --

def test_reabrir_concluida_e_desfazer(usuario):
    tid = _tarefa(usuario)
    assert usuario.post(f"/worklog/{tid}/finish", {"resolution": "trocado"}).status_code == 200
    antes = usuario.get(f"/worklog/{tid}").json()
    assert usuario.patch(f"/worklog/{tid}", {"status": "todo"}).status_code == 200
    t = usuario.get(f"/worklog/{tid}").json()
    assert t["status"] == "todo" and t["completed_at"] is None
    h = _ultimo(usuario, "worklog", tid)
    assert h["summary"].startswith("reabriu a tarefa") and h["can_undo"]
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    t = usuario.get(f"/worklog/{tid}").json()
    assert t["status"] == "done" and t["completed_at"] == antes["completed_at"] and t["resolution"] == "trocado"


# ------------------------------------------------- corrigir tempo e anotação --

def test_corrigir_apontamento(usuario):
    tid = _tarefa(usuario)
    e = usuario.post(f"/worklog/{tid}/time", {"minutes": 90, "note": "visita"}).json()
    r = usuario.patch(f"/time/{e['id']}", {"minutes": 180})
    assert r.status_code == 200 and r.json()["minutes"] == 180 and r.json()["note"] == "visita"
    assert usuario.get(f"/worklog/{tid}").json()["minutes"] == 180
    h = _ultimo(usuario, "time", e["id"])
    assert "corrigiu um apontamento" in h["summary"] and "1h30 → 3h" in h["summary"] and h["can_undo"]
    # tirar a observação (null) e mudar o dia
    ontem = str(app_today() - timedelta(days=1))
    r = usuario.patch(f"/time/{e['id']}", {"note": None, "day": ontem})
    assert r.status_code == 200 and r.json()["note"] is None and str(r.json()["day"]) == ontem
    # desfazer volta o último passo
    h = _ultimo(usuario, "time", e["id"])
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    row = db.query_one("SELECT minutes, note FROM time_entries WHERE id = %s", (e["id"],))
    assert row == {"minutes": 180, "note": "visita"}


def test_corrigir_apontamento_valida_como_o_lancamento(usuario):
    tid = _tarefa(usuario)
    a = usuario.post(f"/worklog/{tid}/time", {"minutes": 600}).json()
    usuario.post(f"/worklog/{tid}/time", {"minutes": 600})
    # 600 + 600 = 20 h; passar este para 900 daria 25 h no dia
    r = usuario.patch(f"/time/{a['id']}", {"minutes": 900})
    assert r.status_code == 400 and "24 h" in r.json()["detail"]
    # para 840 cabe (o próprio apontamento não conta duas vezes)
    assert usuario.patch(f"/time/{a['id']}", {"minutes": 840}).status_code == 200
    assert usuario.patch(f"/time/{a['id']}", {"day": "2999-01-01"}).status_code == 400
    assert usuario.patch(f"/time/{a['id']}", {"minutes": 0}).status_code == 422
    assert usuario.patch("/time/999999", {"minutes": 10}).status_code == 404


def test_corrigir_anotacao_mantem_a_hora(usuario):
    tid = _tarefa(usuario)
    n = usuario.post(f"/worklog/{tid}/notes", {"body": "trocado o disjunotr"}).json()
    r = usuario.patch(f"/notes/{n['id']}", {"body": "  trocado o disjuntor  "})
    assert r.status_code == 200 and r.json()["body"] == "trocado o disjuntor"
    assert r.json()["created_at"] == n["created_at"]
    assert usuario.patch(f"/notes/{n['id']}", {"body": "   "}).status_code == 422
    h = _ultimo(usuario, "note", n["id"])
    assert h["summary"].startswith("editou uma anotação") and h["can_undo"]
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert usuario.get(f"/worklog/{tid}").json()["notes"][0]["body"] == "trocado o disjunotr"


def test_nao_corrige_tempo_nem_anotacao_de_outra_pessoa(usuario, novo_usuario):
    outra = novo_usuario("outra@example.com")
    tid = _tarefa(usuario)
    e = usuario.post(f"/worklog/{tid}/time", {"minutes": 30}).json()
    n = usuario.post(f"/worklog/{tid}/notes", {"body": "minha"}).json()
    assert outra.patch(f"/time/{e['id']}", {"minutes": 60}).status_code == 404
    assert outra.patch(f"/notes/{n['id']}", {"body": "dela"}).status_code == 404
    assert db.query_one("SELECT minutes FROM time_entries WHERE id = %s", (e["id"],))["minutes"] == 30
    assert db.query_one("SELECT body FROM task_notes WHERE id = %s", (n["id"],))["body"] == "minha"


# --------------------------------------------------------- texto do checklist --

def test_corrigir_texto_do_item_fica_no_lugar(usuario, novo_usuario):
    tid = _tarefa(usuario)
    a = usuario.post(f"/worklog/{tid}/checklist", {"label": "Deligar o disjuntor"}).json()
    usuario.post(f"/worklog/{tid}/checklist", {"label": "Testar"})
    r = usuario.patch(f"/checklist/{a['id']}", {"label": "Desligar o disjuntor"})
    assert r.status_code == 200 and r.json()["label"] == "Desligar o disjuntor" and r.json()["done"] is False
    assert [c["label"] for c in usuario.get(f"/worklog/{tid}").json()["checklist"]] == ["Desligar o disjuntor", "Testar"]
    h = _ultimo(usuario, "checklist", a["id"])
    assert h["summary"].startswith("editou o item") and h["can_undo"]
    assert novo_usuario("outra@example.com").patch(f"/checklist/{a['id']}", {"label": "x"}).status_code == 404
    assert usuario.patch(f"/checklist/{a['id']}", {"label": ""}).status_code == 422
