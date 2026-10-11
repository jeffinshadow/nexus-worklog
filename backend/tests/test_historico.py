from datetime import date, timedelta

from conftest import Bearer, criar_chave, recuar_criacao


def _hist(u, **kw):
    q = "&".join(f"{k}={v}" for k, v in kw.items())
    return u.get(f"/history?{q}").json()


def _board(u):
    b = u.get("/board").json()
    return {t["id"]: t for t in b["in_progress"] + b["done"]}


def test_origem_web_e_api_com_nome_da_chave(usuario):
    usuario.post("/worklog", {"title": "Pelo app"})
    Bearer(criar_chave(usuario, nome="Claude do Kaique")["token"]).post("/worklog", {"title": "Pela IA"})
    h = [x for x in _hist(usuario) if x["action"] == "worklog.create"]
    assert {(x["actor"], x["token_name"]) for x in h} == {("web", None), ("api", "Claude do Kaique")}


def test_desfazer_criacao_edicao_conclusao_exclusao(usuario):
    tid = usuario.post("/worklog", {"title": "Original", "description": "d"}).json()["id"]
    usuario.patch(f"/worklog/{tid}", {"title": "Editada"})
    ultimo = _hist(usuario, entity="worklog", entity_id=tid)[0]
    assert ultimo["action"] == "worklog.update" and ultimo["can_undo"]
    assert usuario.post(f"/history/{ultimo['id']}/undo").status_code == 200
    assert _board(usuario)[tid]["title"] == "Original"

    usuario.post(f"/worklog/{tid}/finish")
    h = _hist(usuario, entity="worklog", entity_id=tid)[0]
    usuario.post(f"/history/{h['id']}/undo")
    assert _board(usuario)[tid]["status"] == "todo"

    usuario.delete(f"/worklog/{tid}")
    assert tid not in _board(usuario)
    h = _hist(usuario, entity="worklog", entity_id=tid)[0]
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    t = _board(usuario)[tid]
    assert (t["title"], t["description"]) == ("Original", "d")


def test_so_desfaz_a_mais_recente_de_cada_item(usuario):
    tid = usuario.post("/worklog", {"title": "A"}).json()["id"]
    usuario.patch(f"/worklog/{tid}", {"title": "B"})
    usuario.patch(f"/worklog/{tid}", {"title": "C"})
    hs = _hist(usuario, entity="worklog", entity_id=tid)
    antigo = next(x for x in hs if x["action"] == "worklog.update" and not x["can_undo"])
    assert usuario.post(f"/history/{antigo['id']}/undo").status_code == 409
    assert usuario.post(f"/history/{hs[0]['id']}/undo").status_code == 200
    assert usuario.post(f"/history/{hs[0]['id']}/undo").status_code == 409  # já desfeita
    assert _board(usuario)[tid]["title"] == "B"


def test_desfazer_marcacao_de_recorrente_e_dias_uteis(usuario):
    rid = usuario.post("/recurring", {"label": "Backups"}).json()["id"]
    recuar_criacao(rid, 5)
    hoje = date.fromisoformat(usuario.get("/board").json()["today"])
    dia = (hoje - timedelta(days=2)).isoformat()
    usuario.post(f"/recurring/{rid}/toggle", {"done": True, "day": dia})
    h = _hist(usuario, entity="recurring", entity_id=rid)[0]
    assert h["action"] == "recurring.toggle" and "Backups" in h["summary"]
    usuario.post(f"/history/{h['id']}/undo")
    assert not any(r["done_today"] for r in usuario.get(f"/board?day={dia}").json()["recurring"])

    usuario.post("/auth/settings", {"work_days": 127})
    h = _hist(usuario, entity="user")[0]
    usuario.post(f"/history/{h['id']}/undo")
    assert usuario.get("/auth/me").json()["work_days"] == 62


def test_historico_isolado_e_admin_registrado(admin, usuario, novo_usuario):
    usuario.post("/worklog", {"title": "minha"})
    outro = novo_usuario("outro@example.com")
    assert all(x["action"] != "worklog.create" for x in _hist(outro))
    convites = [x for x in _hist(usuario) if x["action"] == "user.invite"]
    assert convites and convites[0]["actor"] == "admin" and not convites[0]["can_undo"]
    h = _hist(usuario)[0]
    assert outro.post(f"/history/{h['id']}/undo").status_code == 404
