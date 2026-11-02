"""Gauntlet geral, rodada 4: desfazer a exclusão devolve a chave externa das
anotações e do tempo; "depois da última vez" segue a marcação feita na rotina
antiga depois da troca; desfazer uma pausa antiga não vira falta no passado."""
from datetime import timedelta

from app import db
from conftest import dia_hoje, hist, recuar_criacao, uid_de

TODO_DIA = 127


def _linha_rotina(u, rid):
    return next(x for x in u.get("/board").json()["recurring"] if x["id"] == rid)


def test_desfazer_exclusao_devolve_external_ref_de_anotacao_e_tempo(usuario):
    t = usuario.post("/worklog", {"title": "Chamado 77", "external_ref": "crm-77"}).json()["id"]
    n = usuario.post(f"/worklog/{t}/notes", {"body": "Troquei o cabo", "external_ref": "crm-77-n1"}).json()["id"]
    e = usuario.post(f"/worklog/{t}/time", {"minutes": 15, "external_ref": "crm-77-t1"}).json()["id"]
    assert usuario.delete(f"/worklog/{t}").status_code == 200
    h = next(x for x in hist(usuario, entity="worklog", entity_id=t) if x["action"] == "worklog.delete")
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert db.query_one("SELECT external_ref FROM task_notes WHERE id = %s", (n,))["external_ref"] == "crm-77-n1"
    assert db.query_one("SELECT external_ref FROM time_entries WHERE id = %s", (e,))["external_ref"] == "crm-77-t1"
    # O reenvio da integração não duplica.
    assert usuario.post(f"/worklog/{t}/notes", {"body": "Troquei o cabo", "external_ref": "crm-77-n1"}).status_code == 200
    assert usuario.post(f"/worklog/{t}/time", {"minutes": 15, "external_ref": "crm-77-t1"}).status_code == 200
    assert db.query_one("SELECT count(*)::int AS n FROM task_notes WHERE task_id = %s", (t,))["n"] == 1
    assert db.query_one("SELECT sum(minutes)::int AS m FROM time_entries WHERE task_id = %s", (t,))["m"] == 15


def test_lapide_de_anotacao_e_tempo_leva_external_ref(usuario, monkeypatch):
    from app.routers import history
    monkeypatch.setattr(history, "FEED_LAG_SECONDS", 0)
    t = usuario.post("/worklog", {"title": "Chamado 78"}).json()["id"]
    n = usuario.post(f"/worklog/{t}/notes", {"body": "x", "external_ref": "crm-78-n1"}).json()["id"]
    e = usuario.post(f"/worklog/{t}/time", {"minutes": 5, "external_ref": "crm-78-t1"}).json()["id"]
    assert usuario.delete(f"/notes/{n}").status_code == 200
    assert usuario.delete(f"/time/{e}").status_code == 200
    itens = usuario.get("/history?after=0").json()
    refs = {i["action"]: i.get("external_ref") for i in itens if i["action"] in ("note.delete", "time.delete")}
    assert refs == {"note.delete": "crm-78-n1", "time.delete": "crm-78-t1"}
    # E o desfazer da exclusão avulsa também devolve a chave.
    h = next(x for x in hist(usuario) if x["action"] == "note.delete")
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert db.query_one("SELECT external_ref FROM task_notes WHERE id = %s", (n,))["external_ref"] == "crm-78-n1"


def test_marcar_a_rotina_antiga_depois_da_troca_move_a_ultima_vez(usuario):
    hoje = dia_hoje(usuario)
    rid = usuario.post("/recurring", {"label": "Trocar o filtro", "freq": "after", "interval_days": 3}).json()["id"]
    recuar_criacao(rid, 20)
    db.execute("INSERT INTO recurring_completions (task_id, user_id, completed_date) VALUES (%s, %s, %s)",
               (rid, uid_de(usuario), hoje - timedelta(days=6)))
    novo = usuario.patch(f"/recurring/{rid}", {"freq": "after", "interval_days": 5}).json()["id"]
    ontem = (hoje - timedelta(days=1)).isoformat()
    assert _linha_rotina(usuario, novo)["next_due"] == ontem
    # Lembrou que trocou o filtro ontem: marca no quadro de ontem (lá aparece a antiga).
    assert usuario.post(f"/recurring/{rid}/toggle", {"done": True, "day": ontem}).status_code == 200
    linha = _linha_rotina(usuario, novo)
    assert linha["next_due"] == (hoje + timedelta(days=4)).isoformat() and linha["due"] is False
    # Desfazer a marcação volta a contar da anterior.
    h = next(x for x in hist(usuario, entity="recurring", entity_id=rid) if x["action"] == "recurring.toggle")
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert _linha_rotina(usuario, novo)["next_due"] == ontem


def test_desfazer_pausa_antiga_nao_vira_falta_no_passado(usuario):
    hoje = dia_hoje(usuario)
    rid = usuario.post("/recurring", {"label": "WSUS", "freq": "weekly", "weekdays": TODO_DIA}).json()["id"]
    recuar_criacao(rid, 20)
    assert usuario.post(f"/recurring/{rid}/pause", {"until": (hoje + timedelta(days=14)).isoformat()}).status_code == 200
    # A pausa foi pedida há 5 dias.
    db.execute("UPDATE recurring_pauses SET start_d = %s WHERE recurring_id = %s", (hoje - timedelta(days=5), rid))
    db.execute("""UPDATE audit_log SET created_at = created_at - interval '5 days'
                   WHERE entity_id = %s AND action = 'recurring.pause'""", (rid,))
    h = next(x for x in hist(usuario, entity="recurring", entity_id=rid) if x["action"] == "recurring.pause")
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    p = db.query_one("SELECT start_d, end_d FROM recurring_pauses WHERE recurring_id = %s", (rid,))
    assert p["start_d"] == hoje - timedelta(days=5) and p["end_d"] == hoje - timedelta(days=1)
    assert _linha_rotina(usuario, rid)["paused_until"] is None  # de hoje em diante volta a valer


def test_equipe_lista_so_quem_entrou_e_tem_acesso_em_ordem_de_nome(admin, novo_usuario):
    ze, ana, bloq = novo_usuario("ze@example.com"), novo_usuario("ana@example.com"), novo_usuario("bloq@example.com")
    for u, nome in ((ze, "Zé Campos"), (ana, "Ana Lima"), (bloq, "Bia Bloqueada")):
        assert u.put("/me/viewers", {"accept": True}).status_code == 200
        db.execute("UPDATE users SET display_name = %s WHERE id = %s", (nome, uid_de(u)))
    assert admin.post(f"/admin/users/{uid_de(bloq)}/block").status_code == 200
    assert admin.post("/admin/users", {"email": "convite@example.com"}).status_code == 201
    db.execute("UPDATE users SET viewers_allowed = true, invite_pending = true WHERE email = 'convite@example.com'")
    lista = admin.get("/viewer/users").json()
    emails, nomes = [u["email"] for u in lista], [u["name"] for u in lista]
    assert "bloq@example.com" not in emails and "convite@example.com" not in emails
    assert nomes.index("Ana Lima") < nomes.index("Zé Campos")


def test_foto_reenviada_com_a_mesma_chave_nao_duplica(usuario):
    from test_fotos import _foto
    t = usuario.post("/worklog", {"title": "Rack B"}).json()["id"]
    corpo = {**_foto(), "external_ref": "app-foto-1"}
    r1 = usuario.post(f"/worklog/{t}/photos", corpo)
    r2 = usuario.post(f"/worklog/{t}/photos", corpo)  # a fila reenviou depois do timeout
    assert (r1.status_code, r2.status_code) == (201, 200)
    assert r2.json()["id"] == r1.json()["id"] and r2.json()["existing"] is True
    assert len(usuario.get(f"/worklog/{t}").json()["photos"]) == 1
    assert usuario.post(f"/worklog/{t}/photos", _foto()).status_code == 201  # sem chave: foto nova
