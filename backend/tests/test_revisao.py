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
    assert usuario.patch(f"/recurring/{rid}", {"active": True}).status_code == 404  # removida não se edita (nem reativa)


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


def test_admin_exporta_horas_da_equipe(admin, usuario, novo_usuario):
    outro = novo_usuario("outro@example.com")
    for u, m in ((usuario, 30), (outro, 45)):
        pid = u.post("/projects", {"name": "Loja X"}).json()["id"]
        tid = u.post("/worklog", {"title": "Cabear", "project_id": pid}).json()["id"]
        u.post(f"/worklog/{tid}/time", {"minutes": m})
    csv = admin.get("/admin/export/apontamentos.csv").content.decode("utf-8-sig").splitlines()
    assert csv[0].endswith(";usuario") and len(csv) == 3
    assert {l.split(";")[-1] for l in csv[1:]} == {usuario.me["email"], "outro@example.com"}
    assert usuario.get("/admin/export/apontamentos.csv").status_code == 403


# ================================================================ rodada 2 --

def test_mudar_agenda_preserva_o_passado(usuario):
    rid = usuario.post("/recurring", {"label": "Backup"}).json()["id"]
    recuar_criacao(rid, 20)
    hoje = dia_hoje(usuario)
    ontem = hoje - timedelta(days=1)
    usuario.post(f"/recurring/{rid}/toggle", {"done": True, "day": ontem.isoformat()})
    usuario.post(f"/recurring/{rid}/toggle", {"done": True})
    antes = get_report_range(uid_de(usuario), hoje - timedelta(days=14), ontem)["summary"]

    r = usuario.patch(f"/recurring/{rid}", {"freq": "interval", "interval_days": 30})
    novo = r.json()["id"]
    assert r.status_code == 200 and novo != rid and r.json()["replaced"] == rid
    depois = get_report_range(uid_de(usuario), hoje - timedelta(days=14), ontem)["summary"]
    assert depois == antes  # passado intacto
    board = {x["id"]: x for x in usuario.get("/board").json()["recurring"]}
    assert novo in board and board[novo]["done_today"]  # a marcação de hoje foi junto
    assert rid not in board
    # rotina criada hoje muda no lugar (não há passado a proteger)
    r2 = usuario.patch(f"/recurring/{novo}", {"freq": "weekly", "weekdays": 2})
    assert r2.json()["id"] == novo


def test_resumo_cobre_do_ultimo_dia_util_ate_ontem(usuario):
    s = usuario.get("/summary").json()
    assert s["last_day"]["end"] == (dia_hoje(usuario) - timedelta(days=1)).isoformat()


def test_desfazer_filho_que_sumiu_com_a_tarefa_da_409(usuario):
    tid = usuario.post("/worklog", {"title": "T"}).json()["id"]
    eid = usuario.post(f"/worklog/{tid}/time", {"minutes": 120}).json()["id"]
    usuario.delete(f"/worklog/{tid}")
    assert _desfazer(usuario, "time", eid).status_code == 409


def test_desfazer_marcacao_fora_da_janela_da_409(usuario):
    rid = usuario.post("/recurring", {"label": "Patch"}).json()["id"]
    recuar_criacao(rid, 30)
    usuario.post(f"/recurring/{rid}/toggle", {"done": True})
    antigo = (dia_hoje(usuario) - timedelta(days=20)).isoformat()
    db.execute("""UPDATE audit_log SET before = jsonb_set(before, '{day}', to_jsonb(%s::text)),
                                       after = jsonb_set(after, '{day}', to_jsonb(%s::text))
                   WHERE entity = 'recurring' AND entity_id = %s AND action = 'recurring.toggle'""",
               (antigo, antigo, rid))
    assert _desfazer(usuario, "recurring", rid).status_code == 409


def test_desfazer_respeita_24h_por_dia(usuario):
    tid = usuario.post("/worklog", {"title": "T"}).json()["id"]
    eid = usuario.post(f"/worklog/{tid}/time", {"minutes": 600}).json()["id"]
    usuario.delete(f"/time/{eid}")
    usuario.post(f"/worklog/{tid}/time", {"minutes": 1000})
    assert _desfazer(usuario, "time", eid).status_code == 409


def test_trocar_senha_revoga_chaves_e_calendario(usuario):
    chave = criar_chave(usuario)["token"]
    path = usuario.post("/calendar", {"include_recurring": True}).json()["path"]
    r = usuario.post("/auth/change-password", {"current_password": SENHA_PADRAO, "new_password": "Outra-Senha-Forte-2"})
    assert r.status_code == 200
    assert Bearer(chave).get("/board").status_code == 401
    assert Api().c.get(path).status_code == 404


def test_erros_de_um_ip_nao_trancam_a_dona_da_conta(usuario):
    email = usuario.me["email"]
    atacante = {"X-Client-IP": "203.0.113.9"}
    for _ in range(10):
        Api().c.post("/api/auth/login", json={"email": email, "password": "errada-errada"}, headers=atacante)
    assert Api().c.post("/api/auth/login", json={"email": email, "password": "errada-errada"}, headers=atacante).status_code == 429
    dona = Api().c.post("/api/auth/login", json={"email": email, "password": SENHA_PADRAO}, headers={"X-Client-IP": "198.51.100.7"})
    assert dona.status_code == 200
    assert Api().c.post("/api/auth/login", json={"email": email, "password": "x" * 129}).status_code == 422


def test_limite_de_pdf_por_usuario(usuario):
    hoje = dia_hoje(usuario).isoformat()
    codes = [usuario.get(f"/reports/export?start={hoje}&end={hoje}").status_code for _ in range(7)]
    assert codes[:6] == [200] * 6 and codes[6] == 429


def test_aviso_sai_em_dia_nao_util_com_rotina_devida(usuario):
    from datetime import datetime
    from app import notify
    hoje = dia_hoje(usuario)
    domingo = hoje + timedelta(days=(6 - hoje.weekday()) % 7 or 7)
    usuario.post("/recurring", {"label": "Backup de domingo", "freq": "weekly", "weekdays": 1})
    usuario.c.put("/api/notifications", json={"morning": True, "morning_hour": 8}, headers=usuario._h())
    enviados = []
    feito = notify.run_once(datetime(domingo.year, domingo.month, domingo.day, 8, 5),
                            lambda to, subj, text, html: enviados.append(text))
    assert feito and feito[0][1:] == ("morning", "sent") and "Backup de domingo" in enviados[0]


def _expand_rrule(rule: str, first, until):
    """Expande as RRULE que o app gera (só os formatos dele) — para comparar com is_due."""
    import calendar as cal
    p = dict(x.split("=") for x in rule.split(";"))
    out, d = set(), first
    while d <= until:
        if p["FREQ"] == "DAILY":
            if (d - first).days % int(p["INTERVAL"]) == 0:
                out.add(d)
        elif p["FREQ"] == "WEEKLY":
            if ["MO", "TU", "WE", "TH", "FR", "SA", "SU"][d.weekday()] in p["BYDAY"].split(","):
                out.add(d)
        elif p["FREQ"] == "MONTHLY":
            last = cal.monthrange(d.year, d.month)[1]
            dias = [last if int(x) == -1 else int(x) for x in p["BYMONTHDAY"].split(",")]
            dias = [x for x in dias if x <= last]
            if p.get("BYSETPOS") == "-1":
                dias = [max(dias)]
            if d.day in dias:
                out.add(d)
        d += timedelta(days=1)
    return out


def test_ics_equivale_a_is_due_em_dois_anos():
    from datetime import date
    from app.routers.calendar import _rrule
    from app.services import is_due
    ini, fim = date(2027, 1, 1), date(2028, 12, 31)  # 2028 é bissexto
    casos = [
        {"freq": "monthly", "month_day": 31}, {"freq": "monthly", "month_day": 30},
        {"freq": "monthly", "month_day": 29}, {"freq": "monthly", "month_day": 15},
        {"freq": "interval", "interval_days": 9}, {"freq": "weekly", "weekdays": 0b1000101},
        {"freq": "daily"},
    ]
    for c in casos:
        t = {"weekdays": None, "month_day": None, "interval_days": None, **c, "start_d": ini}
        esperado = {ini + timedelta(days=i) for i in range((fim - ini).days + 1) if is_due(t, ini + timedelta(days=i), 62)}
        assert _expand_rrule(_rrule(t, 62), ini, fim) == esperado, c


def test_ordem_das_abertas(usuario):
    hoje = dia_hoje(usuario)
    ids = {}
    ids["normal_prazo"] = usuario.post("/worklog", {"title": "a", "due_date": (hoje + timedelta(days=3)).isoformat()}).json()["id"]
    ids["alta"] = usuario.post("/worklog", {"title": "b", "priority": 1}).json()["id"]
    ids["hoje"] = usuario.post("/worklog", {"title": "c", "due_date": hoje.isoformat(), "priority": 3}).json()["id"]
    ids["atrasada"] = usuario.post("/worklog", {"title": "d", "due_date": (hoje - timedelta(days=1)).isoformat(), "priority": 3}).json()["id"]
    ordem = [t["id"] for t in usuario.get("/board").json()["in_progress"]]
    assert ordem == [ids["atrasada"], ids["hoje"], ids["alta"], ids["normal_prazo"]]
