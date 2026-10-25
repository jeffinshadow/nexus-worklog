"""Entrega 7: lançamento retroativo, external_ref e filtro por período."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import db
from conftest import Bearer, criar_chave, dia_hoje, hist, texto


def _task(u, tid):
    return u.get(f"/worklog/{tid}").json()


def local(iso):
    """Instante da API (UTC) no fuso da app, como 'AAAA-MM-DDTHH:MM'."""
    return datetime.fromisoformat(iso).astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%dT%H:%M")


def test_criar_retroativa_concluida_ciclo_positivo(usuario):
    hoje = dia_hoje(usuario)
    ini, fim = (hoje - timedelta(days=30)).isoformat(), (hoje - timedelta(days=25)).isoformat()
    r = usuario.post("/worklog", {"title": "Migração do AD", "created_at": ini, "completed_at": fim})
    assert r.status_code == 201, r.text
    t = _task(usuario, r.json()["id"])
    assert t["status"] == "done"  # completed_at sem status: já nasce concluída
    assert local(t["created_at"]) == f"{ini}T09:00"
    assert local(t["completed_at"]) == f"{fim}T18:00"


def test_regras_de_data(usuario):
    hoje = dia_hoje(usuario)
    amanha = (hoje + timedelta(days=1)).isoformat()
    longe = (hoje - timedelta(days=61)).isoformat()
    assert usuario.post("/worklog", {"title": "x", "created_at": amanha}).status_code == 400
    r = usuario.post("/worklog", {"title": "x", "created_at": longe})
    assert r.status_code == 400 and "60 dias" in r.json()["detail"]
    r = usuario.post("/worklog", {"title": "x", "created_at": (hoje - timedelta(days=5)).isoformat(),
                                  "completed_at": (hoje - timedelta(days=6)).isoformat()})
    assert r.status_code == 400 and "anterior à criação" in r.json()["detail"]
    r = usuario.post("/worklog", {"title": "x", "status": "todo", "completed_at": hoje.isoformat()})
    assert r.status_code == 422
    assert usuario.post("/worklog", {"title": "x", "created_at": "29/09/2026"}).status_code == 400


def test_concluir_com_data_e_sem_data(usuario):
    hoje = dia_hoje(usuario)
    tid = usuario.post("/worklog", {"title": "Backup", "created_at": (hoje - timedelta(days=10)).isoformat()}).json()["id"]
    dia = (hoje - timedelta(days=3)).isoformat()
    r = usuario.post(f"/worklog/{tid}/finish", {"completed_at": f"{dia}T14:30"})
    assert r.status_code == 200, r.text
    assert local(_task(usuario, tid)["completed_at"]) == f"{dia}T14:30"
    # Antes da criação: recusa.
    r = usuario.post(f"/worklog/{tid}/finish", {"completed_at": (hoje - timedelta(days=11)).isoformat()})
    assert r.status_code == 400
    # Sem corpo continua valendo "agora" (tarefa nova).
    t2 = usuario.post("/worklog", {"title": "Agora"}).json()["id"]
    assert usuario.post(f"/worklog/{t2}/finish").status_code == 200
    assert local(_task(usuario, t2)["completed_at"])[:10] == hoje.isoformat()


def test_corrigir_data_pelo_patch_e_desfazer(usuario):
    hoje = dia_hoje(usuario)
    tid = usuario.post("/worklog", {"title": "Relatório", "created_at": (hoje - timedelta(days=9)).isoformat(),
                                    "completed_at": (hoje - timedelta(days=2)).isoformat()}).json()["id"]
    antes = _task(usuario, tid)["completed_at"]
    nova = (hoje - timedelta(days=4)).isoformat()
    assert usuario.patch(f"/worklog/{tid}", {"completed_at": nova}).status_code == 200
    assert local(_task(usuario, tid)["completed_at"]).startswith(nova)
    # Em tarefa aberta, não.
    aberta = usuario.post("/worklog", {"title": "Aberta"}).json()["id"]
    assert usuario.patch(f"/worklog/{aberta}", {"completed_at": nova}).status_code == 400
    # Histórico + desfazer devolvem a data anterior.
    h = [x for x in hist(usuario, entity="worklog", entity_id=tid) if x["action"] == "worklog.update"][0]
    assert h["can_undo"]
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert _task(usuario, tid)["completed_at"] == antes


def test_limite_configuravel(admin, usuario):
    hoje = dia_hoje(usuario)
    d90 = (hoje - timedelta(days=90)).isoformat()
    assert usuario.post("/worklog", {"title": "x", "created_at": d90}).status_code == 400
    assert usuario.put("/admin/settings", {"retro_days": 120}).status_code == 403
    r = admin.put("/admin/settings", {"retro_days": 120})
    assert r.status_code == 200 and r.json()["retro_days"] == 120
    assert usuario.post("/worklog", {"title": "x", "created_at": d90}).status_code == 201
    assert usuario.get("/auth/me").json()["retro_days"] == 120
    assert admin.put("/admin/settings", {"retro_days": 0}).status_code == 422


def test_external_ref_idempotente_e_isolado(usuario, novo_usuario):
    r1 = usuario.post("/worklog", {"title": "Sessão 1", "external_ref": "sess-abc"})
    r2 = usuario.post("/worklog", {"title": "Sessão 1 (de novo)", "external_ref": "sess-abc"})
    assert r1.status_code == 201 and r2.status_code == 200
    assert r2.json() == {"id": r1.json()["id"], "existing": True}
    assert db.query_one("SELECT count(*)::int AS n FROM worklog_tasks WHERE external_ref = 'sess-abc'")["n"] == 1
    # Outra pessoa pode usar a mesma chave.
    outro = novo_usuario("outro@example.com")
    assert outro.post("/worklog", {"title": "Dele", "external_ref": "sess-abc"}).status_code == 201
    # Desfazer a criação libera a chave.
    h = [x for x in hist(usuario, entity="worklog", entity_id=r1.json()["id"]) if x["action"] == "worklog.create"][0]
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert usuario.post("/worklog", {"title": "Nova", "external_ref": "sess-abc"}).status_code == 201


def test_excluir_e_desfazer_mantem_ref(usuario):
    tid = usuario.post("/worklog", {"title": "Com ref", "external_ref": "r-1"}).json()["id"]
    assert usuario.delete(f"/worklog/{tid}").status_code == 200
    h = [x for x in hist(usuario, entity="worklog", entity_id=tid) if x["action"] == "worklog.delete"][0]
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert _task(usuario, tid)["external_ref"] == "r-1"


def test_listar_por_periodo(usuario):
    hoje = dia_hoje(usuario)
    d = lambda n: (hoje - timedelta(days=n)).isoformat()  # noqa: E731
    a = usuario.post("/worklog", {"title": "A", "created_at": d(20), "completed_at": d(2)}).json()["id"]
    b = usuario.post("/worklog", {"title": "B", "created_at": d(5)}).json()["id"]
    usuario.post("/worklog", {"title": "C"})
    ids = [t["id"] for t in usuario.get(f"/worklog?from={d(21)}&to={d(4)}").json()]
    assert ids == [b, a]
    ids = [t["id"] for t in usuario.get(f"/worklog?from={d(3)}&to={d(1)}&by=completed").json()]
    assert ids == [a]
    ids = [t["id"] for t in usuario.get(f"/worklog?from={d(21)}&status=open").json()]
    assert a not in ids and b in ids


def test_mcp_retroativo_ref_e_lista(usuario):
    ia = Bearer(criar_chave(usuario)["token"])
    hoje = dia_hoje(usuario)
    ini, fim = (hoje - timedelta(days=26)).isoformat(), (hoje - timedelta(days=25)).isoformat()
    res = ia.tool("create_task", title="Troca do switch", created_at=ini, completed_at=fim, external_ref="sess-42")
    assert not res["isError"], texto(res)
    assert "Criada" in texto(res) and "(ref sess-42)" in texto(res)
    res = ia.tool("create_task", title="Troca do switch", external_ref="sess-42")
    assert "Já existia" in texto(res)
    res = ia.tool("list_tasks", **{"from": ini, "to": ini})
    assert texto(res).count("Troca do switch") == 1 and f"criada {ini} 09:00" in texto(res)
    tid = usuario.post("/worklog", {"title": "Aberta", "created_at": ini}).json()["id"]
    res = ia.tool("complete_task", task_id=tid, completed_at=f"{fim}T10:15")
    assert not res["isError"] and f"concluída em {fim}" in texto(res)
    res = ia.tool("complete_task", task_id=tid, completed_at=(hoje + timedelta(days=2)).isoformat())
    assert res["isError"] and "futuro" in texto(res)
    res = ia.tool("update_task", task_id=tid, completed_at=ini)
    assert not res["isError"], texto(res)
    acoes = [h["action"] for h in hist(usuario)]
    assert acoes.count("worklog.create") >= 2 and "worklog.finish" in acoes
