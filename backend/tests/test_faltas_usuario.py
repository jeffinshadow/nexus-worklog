"""Pequenas faltas do lado do usuário (gauntlet geral, R5): reabrir, editar
apontamento e anotação, exportações pelo período, ordem das rotinas, sair dos
outros aparelhos, chaves antigas, webhooks editáveis, descrição na atribuição."""
from app import db
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
