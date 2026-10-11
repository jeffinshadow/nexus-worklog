"""Regressões da revisão (gauntlet R1): cada teste trava uma correção."""
from datetime import timedelta

from app import db, security
from app.services import get_report_range
from conftest import Api, Bearer, SENHA_PADRAO, criar_chave, dia_hoje, hist, recuar_criacao, texto, uid_de


def _desfazer(u, entity, entity_id):
    h = hist(u, entity=entity, entity_id=entity_id)[0]
    return u.post(f"/history/{h['id']}/undo")


# ------------------------------------------------------------------ segurança --

def test_apontamento_com_data_antiga_ou_dia_lotado_e_recusado(usuario):
    tid = usuario.post("/worklog", {"title": "T"}).json()["id"]
    hoje = dia_hoje(usuario)
    assert usuario.post(f"/worklog/{tid}/time", {"minutes": 1, "day": "0001-01-01"}).status_code == 400
    assert usuario.post(f"/worklog/{tid}/time", {"minutes": 1, "day": (hoje - timedelta(days=367)).isoformat()}).status_code == 400
    assert usuario.post(f"/worklog/{tid}/time", {"minutes": 1000}).status_code == 201
    assert usuario.post(f"/worklog/{tid}/time", {"minutes": 441}).status_code == 400  # passaria de 24h no dia
    assert usuario.post(f"/worklog/{tid}/time", {"minutes": 440}).status_code == 201


def test_projeto_inteiro_tem_teto_de_dias(usuario):
    pid = usuario.post("/projects", {"name": "Antigo"}).json()["id"]
    db.execute("UPDATE projects SET created_at = now() - interval '20 years' WHERE id = %s", (pid,))
    r = usuario.get(f"/reports/export?project={pid}")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


def test_periodo_de_366_dias_inclusivo(usuario):
    hoje = dia_hoje(usuario)
    ok = (hoje - timedelta(days=365)).isoformat()
    longo = (hoje - timedelta(days=366)).isoformat()
    assert usuario.get(f"/reports/export?start={ok}&end={hoje.isoformat()}").status_code == 200
    assert usuario.get(f"/reports/export?start={longo}&end={hoje.isoformat()}").status_code == 400
    # fim no futuro é cortado em hoje antes de medir
    futuro = (hoje + timedelta(days=200)).isoformat()
    assert usuario.get(f"/reports/export?start={ok}&end={futuro}").status_code == 200


def test_reset_de_senha_revoga_chaves_e_calendario(admin, usuario):
    chave = criar_chave(usuario)["token"]
    path = usuario.post("/calendar", {"include_recurring": True}).json()["path"]
    uid = uid_de(usuario)
    assert admin.post(f"/admin/users/{uid}/reset-password").status_code == 200
    anon = Api()
    assert anon.c.get(path).status_code == 404
    assert Bearer(chave).get("/board").status_code == 401


def test_bloqueio_por_email_conta_so_falhas(usuario):
    email = usuario.me["email"]
    for _ in range(12):  # entradas corretas não gastam a cota do e-mail
        assert Api().c.post("/api/auth/login", json={"email": email, "password": SENHA_PADRAO}).status_code == 200
        security.login_limiter._hits = {k: v for k, v in security.login_limiter._hits.items() if not k.startswith("ip:")}


def test_mcp_recusa_lote(usuario):
    b = Bearer(criar_chave(usuario)["token"])
    r = b.c.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}] * 3, headers=b.h)
    assert r.status_code == 400 and r.json()["error"]["code"] == -32600


def test_csv_neutraliza_formula(usuario):
    tid = usuario.post("/worklog", {"title": '=HYPERLINK("http://x";"clique")'}).json()["id"]
    usuario.post(f"/worklog/{tid}/time", {"minutes": 5, "note": "@SUM(1)"})
    tarefas = usuario.get("/export/tarefas.csv").content.decode("utf-8-sig")
    tempos = usuario.get("/export/apontamentos.csv").content.decode("utf-8-sig")
    assert "'=HYPERLINK" in tarefas and "'@SUM(1)" in tempos


def test_sessao_nao_grava_a_cada_requisicao(usuario):
    exp1 = db.query_one("SELECT max(expires_at) AS e FROM sessions")["e"]
    usuario.get("/board")
    usuario.get("/board")
    assert db.query_one("SELECT max(expires_at) AS e FROM sessions")["e"] == exp1


# ------------------------------------------------------------------ desfazer --

def test_desfazer_criacao_com_filhos_e_recusado(usuario):
    tid = usuario.post("/worklog", {"title": "Com horas"}).json()["id"]
    criou = hist(usuario, entity="worklog", entity_id=tid)[0]["id"]
    usuario.post(f"/worklog/{tid}/time", {"minutes": 180})
    assert usuario.post(f"/history/{criou}/undo").status_code == 409
    assert usuario.get(f"/worklog/{tid}").json()["minutes"] == 180


def test_desfazer_exclusao_devolve_anotacoes_checklist_e_tempo(usuario):
    tid = usuario.post("/worklog", {"title": "Cliente"}).json()["id"]
    usuario.post(f"/worklog/{tid}/time", {"minutes": 300, "note": "5h"})
    usuario.post(f"/worklog/{tid}/notes", {"body": "importante"})
    usuario.post(f"/worklog/{tid}/checklist", {"label": "item"})
    usuario.delete(f"/worklog/{tid}")
    assert _desfazer(usuario, "worklog", tid).status_code == 200
    t = usuario.get(f"/worklog/{tid}").json()
    assert t["minutes"] == 300 and t["notes"][0]["body"] == "importante" and t["checklist"][0]["label"] == "item"


def test_desfazer_exclusao_de_projeto_devolve_tarefas(usuario):
    pid = usuario.post("/projects", {"name": "Cliente A"}).json()["id"]
    ids = [usuario.post("/worklog", {"title": f"T{i}", "project_id": pid}).json()["id"] for i in range(3)]
    usuario.delete(f"/projects/{pid}")
    assert _desfazer(usuario, "project", pid).status_code == 200
    assert {usuario.get(f"/worklog/{i}").json()["project_id"] for i in ids} == {pid}


def test_avisos_nao_bloqueiam_desfazer_dos_dias_uteis(usuario):
    usuario.post("/auth/settings", {"work_days": 2})
    usuario.c.put("/api/notifications", json={"morning": True}, headers=usuario._h())
    h = [x for x in hist(usuario) if x["action"] == "settings.update"][0]
    assert h["can_undo"] and usuario.post(f"/history/{h['id']}/undo").status_code == 200


def test_reativar_pelo_patch_nao_existe_mais(usuario):
    rid = usuario.post("/recurring", {"label": "R"}).json()["id"]
    usuario.delete(f"/recurring/{rid}")
    assert usuario.patch(f"/recurring/{rid}", {"active": True}).status_code == 400  # campo ignorado: nada a atualizar


# ------------------------------------------------------------------ vigência --

def test_removida_hoje_sem_fazer_nao_conta_como_devida(usuario):
    rid = usuario.post("/recurring", {"label": "Removida"}).json()["id"]
    recuar_criacao(rid, 3)
    usuario.delete(f"/recurring/{rid}")
    hoje = dia_hoje(usuario)
    r = get_report_range(uid_de(usuario), hoje, hoje)
    assert all(x["label"] != "Removida" or x["due"] == 0 for x in r["recurring_stats"])


def test_inativa_legada_fica_fora_dos_indicadores(usuario):
    rid = usuario.post("/recurring", {"label": "Legado"}).json()["id"]
    recuar_criacao(rid, 10)
    db.execute("UPDATE recurring_tasks SET active = false, deactivated_at = NULL WHERE id = %s", (rid,))
    hoje = dia_hoje(usuario)
    r = get_report_range(uid_de(usuario), hoje - timedelta(days=6), hoje)
    assert all(x["label"] != "Legado" for x in r["recurring_stats"])


def test_mesmos_numeros_no_quadro_resumo_e_relatorio(usuario):
    """Uma regra só: devidas x feitas de hoje batem entre quadro, resumo e relatório."""
    a = usuario.post("/recurring", {"label": "A"}).json()["id"]
    b = usuario.post("/recurring", {"label": "B"}).json()["id"]
    for rid in (a, b):
        recuar_criacao(rid, 10)
    usuario.post(f"/recurring/{a}/toggle", {"done": True})
    board = usuario.get("/board").json()
    devidas = [r for r in board["recurring"] if r["due"]]
    hoje = dia_hoje(usuario)
    rep = get_report_range(uid_de(usuario), hoje, hoje)["summary"]
    assert rep["recurring_total"] == len(devidas)
    assert rep["recurring_done"] == sum(1 for r in devidas if r["done_today"])
    assert rep["recurring_extra"] == sum(1 for r in board["recurring"] if not r["due"] and r["done_today"])


# ------------------------------------------------------------------- PDF/MCP --

def test_pdf_com_muitas_rotinas_nao_explode_paginas(usuario):
    for i in range(16):
        rid = usuario.post("/recurring", {"label": f"Rotina de verificação número {i}"}).json()["id"]
        recuar_criacao(rid, 20)
    hoje = dia_hoje(usuario)
    r = usuario.get(f"/reports/export?start={(hoje - timedelta(days=13)).isoformat()}&end={hoje.isoformat()}")
    assert r.status_code == 200
    import re
    assert len(re.findall(rb"/Type\s*/Page(?!s)", r.content)) < 12  # antes: uma página por linha


def test_mcp_hoje_respeita_agenda_e_resumo(usuario):
    hoje = dia_hoje(usuario)
    nao_hoje = 127 ^ (1 << ((hoje.weekday() + 1) % 7))
    usuario.post("/recurring", {"label": "Fora da agenda", "freq": "weekly", "weekdays": nao_hoje})
    b = Bearer(criar_chave(usuario, scope="read")["token"])
    t = texto(b.tool("get_today"))
    assert "Fora da agenda" not in t and "Rotinas de hoje (0/0" in t
    assert "(fora da agenda)" in texto(b.tool("list_recurring"))
    assert "Semana até hoje" in texto(b.tool("get_summary"))
