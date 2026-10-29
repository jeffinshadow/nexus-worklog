"""Registro rico: agendas das rotinas, projetos, prioridade, checklist, anotações, tempo e relatório por projeto."""
from datetime import date, timedelta

from app import db
from app.services import get_report_range, is_due
from conftest import Bearer, criar_chave, hist, dia_hoje, recuar_criacao, texto

SEG_A_SEX = 0b0111110  # domingo = bit 0


def _desfazer_ultimo(u, entity, entity_id):
    h = hist(u, entity=entity, entity_id=entity_id)[0]
    assert h["can_undo"], h
    r = u.post(f"/history/{h['id']}/undo")
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ agendas --

def test_is_due_regras():
    sab, seg = date(2026, 10, 10), date(2026, 10, 12)
    assert not is_due({"freq": "daily"}, sab, SEG_A_SEX) and is_due({}, seg, SEG_A_SEX)
    so_sabado = {"freq": "weekly", "weekdays": 1 << 6}
    assert is_due(so_sabado, sab, SEG_A_SEX) and not is_due(so_sabado, seg, SEG_A_SEX)
    fim_mes = {"freq": "monthly", "month_day": 31}
    assert is_due(fim_mes, date(2026, 2, 28), 0) and not is_due(fim_mes, date(2026, 2, 27), 0)
    assert is_due(fim_mes, date(2026, 4, 30), 0) and is_due(fim_mes, date(2026, 5, 31), 0)
    dia15 = {"freq": "monthly", "month_day": 15}
    assert is_due(dia15, date(2026, 2, 15), 0) and not is_due(dia15, date(2026, 2, 28), 0)
    cada3 = {"freq": "interval", "interval_days": 3, "start_d": date(2026, 10, 1)}
    assert [d for d in range(1, 11) if is_due(cada3, date(2026, 10, d), 0)] == [1, 4, 7, 10]


def test_agenda_validacao(usuario):
    assert usuario.post("/recurring", {"label": "x", "freq": "weekly"}).status_code == 422
    assert usuario.post("/recurring", {"label": "x", "weekdays": 3}).status_code == 422
    assert usuario.post("/recurring", {"label": "x", "freq": "interval", "interval_days": 1}).status_code == 422
    r = usuario.post("/recurring", {"label": "Mensal", "freq": "monthly", "month_day": 31, "weekdays": 5})
    assert r.status_code == 201
    t = next(x for x in usuario.get("/board").json()["recurring"] if x["id"] == r.json()["id"])
    assert (t["freq"], t["month_day"], t["weekdays"]) == ("monthly", 31, None)  # normalizado


def test_quadro_marca_devida_e_extra(usuario):
    hoje = dia_hoje(usuario)
    bit_hoje = 1 << ((hoje.weekday() + 1) % 7)
    sim = usuario.post("/recurring", {"label": "Hoje sim", "freq": "weekly", "weekdays": bit_hoje}).json()["id"]
    nao = usuario.post("/recurring", {"label": "Hoje não", "freq": "weekly", "weekdays": 127 ^ bit_hoje}).json()["id"]
    rec = {x["id"]: x for x in usuario.get("/board").json()["recurring"]}
    assert rec[sim]["due"] is True and rec[nao]["due"] is False
    # Marcar a não devida conta como extra, não como atraso.
    assert usuario.post(f"/recurring/{nao}/toggle", {"done": True}).status_code == 200


def test_mudar_agenda_e_desfazer(usuario):
    tid = usuario.post("/recurring", {"label": "Backup"}).json()["id"]
    r = usuario.patch(f"/recurring/{tid}", {"freq": "interval", "interval_days": 7})
    assert r.status_code == 200, r.text
    t = next(x for x in usuario.get("/board").json()["recurring"] if x["id"] == tid)
    assert (t["freq"], t["interval_days"]) == ("interval", 7)
    _desfazer_ultimo(usuario, "recurring", tid)
    t = next(x for x in usuario.get("/board").json()["recurring"] if x["id"] == tid)
    assert t["freq"] == "daily" and t["interval_days"] is None


def test_intervalo_conta_da_criacao(usuario):
    tid = usuario.post("/recurring", {"label": "A cada 2", "freq": "interval", "interval_days": 2}).json()["id"]
    recuar_criacao(tid, 3)
    hoje = dia_hoje(usuario)
    devida = {}
    for i in range(4):
        d = hoje - timedelta(days=i)
        b = usuario.get(f"/board?day={d.isoformat()}").json()
        devida[3 - i] = next(x for x in b["recurring"] if x["id"] == tid)["due"]
    assert devida == {0: True, 1: False, 2: True, 3: False}


# ----------------------------------------------------------------- projetos --

def test_projetos_crud_e_filtro(usuario):
    r = usuario.post("/projects", {"name": "Loja Vila Velha"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert usuario.post("/projects", {"name": "Loja Vila Velha"}).status_code == 409
    a = usuario.post("/worklog", {"title": "Câmeras", "project_id": pid}).json()["id"]
    b = usuario.post("/worklog", {"title": "Interna"}).json()["id"]
    p = usuario.get("/projects").json()[0]
    assert p["name"] == "Loja Vila Velha" and p["color"].startswith("#") and p["open_tasks"] == 1

    ids = lambda q: {t["id"] for t in usuario.get(f"/board?{q}").json()["in_progress"]}
    assert ids(f"project={pid}") == {a} and ids("project=0") == {b} and ids("") == {a, b}

    t = usuario.get(f"/worklog/{a}").json()
    assert t["project_name"] == "Loja Vila Velha"
    assert usuario.patch(f"/worklog/{a}", {"project_id": None}).status_code == 200
    assert usuario.get(f"/worklog/{a}").json()["project_id"] is None


def test_projeto_de_outro_usuario_e_rejeitado(usuario, novo_usuario):
    outro = novo_usuario("outro@example.com")
    pid = outro.post("/projects", {"name": "Dele"}).json()["id"]
    assert usuario.post("/worklog", {"title": "x", "project_id": pid}).status_code == 400
    assert usuario.patch(f"/projects/{pid}", {"name": "Meu"}).status_code == 404


def test_excluir_projeto_solta_tarefas_e_desfaz(usuario):
    pid = usuario.post("/projects", {"name": "Temporário"}).json()["id"]
    tid = usuario.post("/worklog", {"title": "Tarefa", "project_id": pid}).json()["id"]
    assert usuario.delete(f"/projects/{pid}").status_code == 200
    assert usuario.get(f"/worklog/{tid}").json()["project_id"] is None
    _desfazer_ultimo(usuario, "project", pid)
    assert any(p["id"] == pid for p in usuario.get("/projects").json())


# --------------------------------------------------------------- prioridade --

def test_prioridade_ordena_quadro(usuario):
    baixa = usuario.post("/worklog", {"title": "Baixa", "priority": 3}).json()["id"]
    alta = usuario.post("/worklog", {"title": "Alta", "priority": 1}).json()["id"]
    normal = usuario.post("/worklog", {"title": "Normal"}).json()["id"]
    ordem = [t["id"] for t in usuario.get("/board").json()["in_progress"]]
    assert ordem == [alta, normal, baixa]
    assert usuario.post("/worklog", {"title": "x", "priority": 4}).status_code == 422


# ------------------------------------------------ checklist, notas e tempo --

def test_checklist_anotacoes_tempo(usuario):
    tid = usuario.post("/worklog", {"title": "Migrar servidor"}).json()["id"]
    i1 = usuario.post(f"/worklog/{tid}/checklist", {"label": "Backup"}).json()["id"]
    usuario.post(f"/worklog/{tid}/checklist", {"label": "Restaurar"})
    assert usuario.patch(f"/checklist/{i1}", {"done": True}).json()["done"] is True
    usuario.post(f"/worklog/{tid}/notes", {"body": "Backup ok, 40 GB"})
    hoje = dia_hoje(usuario)
    usuario.post(f"/worklog/{tid}/time", {"minutes": 90})
    usuario.post(f"/worklog/{tid}/time", {"minutes": 30, "day": (hoje - timedelta(days=1)).isoformat(), "note": "ontem"})
    assert usuario.post(f"/worklog/{tid}/time", {"minutes": 10, "day": (hoje + timedelta(days=1)).isoformat()}).status_code == 400
    assert usuario.post(f"/worklog/{tid}/time", {"minutes": 0}).status_code == 422

    t = usuario.get(f"/worklog/{tid}").json()
    assert [c["label"] for c in t["checklist"]] == ["Backup", "Restaurar"]
    assert t["notes"][0]["body"] == "Backup ok, 40 GB" and t["notes"][0]["actor"] == "web"
    assert t["minutes"] == 120 and len(t["time"]) == 2

    q = next(x for x in usuario.get("/board").json()["in_progress"] if x["id"] == tid)
    assert (q["check_done"], q["check_total"], q["notes_count"], q["minutes"]) == (1, 2, 1, 120)


def test_itens_de_outro_usuario_inacessiveis(usuario, novo_usuario):
    tid = usuario.post("/worklog", {"title": "Minha"}).json()["id"]
    item = usuario.post(f"/worklog/{tid}/checklist", {"label": "a"}).json()["id"]
    nota = usuario.post(f"/worklog/{tid}/notes", {"body": "n"}).json()["id"]
    tempo = usuario.post(f"/worklog/{tid}/time", {"minutes": 5}).json()["id"]
    outro = novo_usuario("outro@example.com")
    assert outro.get(f"/worklog/{tid}").status_code == 404
    assert outro.post(f"/worklog/{tid}/notes", {"body": "x"}).status_code == 404
    assert outro.patch(f"/checklist/{item}", {"done": True}).status_code == 404
    for path in (f"/checklist/{item}", f"/notes/{nota}", f"/time/{tempo}"):
        assert outro.delete(path).status_code == 404


def test_desfazer_itens(usuario):
    tid = usuario.post("/worklog", {"title": "T"}).json()["id"]
    item = usuario.post(f"/worklog/{tid}/checklist", {"label": "Item"}).json()["id"]
    usuario.patch(f"/checklist/{item}", {"done": True})
    _desfazer_ultimo(usuario, "checklist", item)
    assert usuario.get(f"/worklog/{tid}").json()["checklist"][0]["done"] is False

    nota = usuario.post(f"/worklog/{tid}/notes", {"body": "apagar"}).json()["id"]
    usuario.delete(f"/notes/{nota}")
    _desfazer_ultimo(usuario, "note", nota)
    assert usuario.get(f"/worklog/{tid}").json()["notes"][0]["body"] == "apagar"

    tempo = usuario.post(f"/worklog/{tid}/time", {"minutes": 45}).json()["id"]
    _desfazer_ultimo(usuario, "time", tempo)  # desfaz o lançamento
    assert usuario.get(f"/worklog/{tid}").json()["minutes"] == 0


def test_excluir_tarefa_leva_itens(usuario):
    tid = usuario.post("/worklog", {"title": "T"}).json()["id"]
    usuario.post(f"/worklog/{tid}/checklist", {"label": "a"})
    usuario.post(f"/worklog/{tid}/time", {"minutes": 5})
    assert usuario.delete(f"/worklog/{tid}").status_code == 200
    assert usuario.get(f"/worklog/{tid}").status_code == 404


# ---------------------------------------------------------------- relatório --

def test_relatorio_por_projeto(usuario):
    pid = usuario.post("/projects", {"name": "Cliente A"}).json()["id"]
    tid = usuario.post("/worklog", {"title": "Do cliente", "project_id": pid}).json()["id"]
    usuario.post(f"/worklog/{tid}/time", {"minutes": 60})
    usuario.post(f"/worklog/{tid}/finish")
    hoje = dia_hoje(usuario).isoformat()
    r = usuario.get(f"/reports/export?start={hoje}&end={hoje}&project={pid}")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert "cliente-a" in r.headers["content-disposition"]
    assert usuario.get(f"/reports/export?start={hoje}&end={hoje}&project=999").status_code == 400
    assert usuario.get(f"/reports/export?start={hoje}&end={hoje}").status_code == 200

    uid = db.query_one("SELECT user_id FROM projects WHERE id = %s", (pid,))["user_id"]
    outra = usuario.post("/worklog", {"title": "Sem projeto"}).json()["id"]
    usuario.post(f"/worklog/{outra}/time", {"minutes": 15})
    d = get_report_range(uid, dia_hoje(usuario), dia_hoje(usuario), {"id": pid, "name": "Cliente A"})
    assert d["summary"]["minutes"] == 60 and d["summary"]["pontual_done"] == 1
    assert d["summary"]["recurring_total"] == 0 and d["project"] == "Cliente A"
    assert get_report_range(uid, dia_hoje(usuario), dia_hoje(usuario))["summary"]["minutes"] == 75


# ---------------------------------------------------------------------- MCP --


def test_mcp_registro_rico(usuario):
    usuario.post("/projects", {"name": "Loja"})
    b = Bearer(criar_chave(usuario, nome="Assistente")["token"])
    res = b.tool("create_task", title="Instalar NVR", project="loja", priority="alta")
    assert not res["isError"], texto(res)
    tid = int(texto(res).split("#")[1].split()[0])
    assert b.tool("create_task", title="x", project="Inexistente")["isError"]

    lista = texto(b.tool("list_tasks"))
    assert "{Loja}" in lista and "prioridade alta" in lista
    assert "Loja (1 abertas, 0 objetivos)" in texto(b.tool("list_projects"))

    item = texto(b.tool("add_checklist_item", task_id=tid, label="Cabear"))
    iid = int(item.split("#")[1].split()[0])
    assert not b.tool("set_checklist_item", item_id=iid)["isError"]
    assert not b.tool("add_note", task_id=tid, text="Rack instalado")["isError"]
    assert not b.tool("log_time", task_id=tid, minutes=75, note="cabeamento")["isError"]

    det = texto(b.tool("get_task", task_id=tid))
    assert "[x] item" in det and "Rack instalado" in det and "1h15" in det

    nota = usuario.get(f"/worklog/{tid}").json()["notes"][0]
    assert (nota["actor"], nota["token_name"]) == ("mcp", "Assistente")
    assert not b.tool("update_task", task_id=tid, project=None)["isError"]
    assert usuario.get(f"/worklog/{tid}").json()["project_id"] is None


def test_relatorio_do_projeto_inteiro(usuario):
    pid = usuario.post("/projects", {"name": "Obra Antiga"}).json()["id"]
    tid = usuario.post("/worklog", {"title": "Começou há tempo", "project_id": pid}).json()["id"]
    # tarefa e projeto "nasceram" há 400 dias: passa do limite de 366 do período
    db.execute("UPDATE worklog_tasks SET created_at = now() - interval '400 days' WHERE id = %s", (tid,))
    db.execute("UPDATE projects SET created_at = now() - interval '400 days' WHERE id = %s", (pid,))
    usuario.post(f"/worklog/{tid}/time", {"minutes": 30})
    usuario.post(f"/worklog/{tid}/finish")

    r = usuario.get(f"/reports/export?project={pid}")
    assert r.status_code == 200 and r.content[:4] == b"%PDF", r.text[:200]
    assert "obra-antiga-projeto-completo.pdf" in r.headers["content-disposition"]

    from app.routers.reports import project_first_day
    uid = db.query_one("SELECT user_id FROM projects WHERE id = %s", (pid,))["user_id"]
    assert (dia_hoje(usuario) - project_first_day(uid, pid)).days in (399, 400, 401)

    # sem projeto, as datas continuam obrigatórias; com período, o limite vale
    assert usuario.get("/reports/export").status_code == 400
    hoje = dia_hoje(usuario)
    longe = (hoje - timedelta(days=400)).isoformat()
    assert usuario.get(f"/reports/export?start={longe}&end={hoje.isoformat()}&project={pid}").status_code == 400
    assert usuario.get(f"/reports/export?project=999").status_code == 400
