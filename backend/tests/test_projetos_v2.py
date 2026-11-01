"""Projetos v2: ícone (biblioteca fixa, padrão pasta), números do cartão numa
consulta só (em aberto, aguardando, horas no mês, objetivos, última atividade),
próximos prazos e arquivar decidindo o que fazer com as tarefas em aberto."""
from app import db
from app.schemas import PROJECT_ICONS
from conftest import Bearer, criar_chave, dia_hoje, hist, texto


def _proj(u, nome, **kw):
    r = u.post("/projects", {"name": nome, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _lista(u, **kw):
    q = "&".join(f"{k}={v}" for k, v in kw.items())
    return {p["name"]: p for p in u.get("/projects" + (f"?{q}" if q else "")).json()}


# ------------------------------------------------------------------ ícone --

def test_icone_padrao_valido_e_invalido(usuario):
    assert len(PROJECT_ICONS) == 24 and PROJECT_ICONS[0] == "pasta"
    p = _proj(usuario, "Sem escolha")
    assert p["icon"] == "pasta"  # nunca fica sem ícone
    assert db.query_one("SELECT icon FROM projects WHERE id = %s", (p["id"],))["icon"] is None  # NULL = pasta
    q = _proj(usuario, "Loja Centro", icon="loja")
    assert q["icon"] == "loja"
    for ruim in ("foguete", "", "LOJA", "../x"):
        r = usuario.post("/projects", {"name": "X " + ruim, "icon": ruim})
        assert r.status_code == 422, (ruim, r.text)
    assert usuario.post("/projects", {"name": "Pasta explícita", "icon": "pasta"}).json()["icon"] == "pasta"
    assert usuario.post("/projects", {"name": "Nulo", "icon": None}).json()["icon"] == "pasta"
    assert _lista(usuario)["Loja Centro"]["icon"] == "loja"


def test_patch_icone_e_desfazer(usuario):
    p = _proj(usuario, "Clínica Sul")
    r = usuario.patch(f"/projects/{p['id']}", {"icon": "clinica"})
    assert r.status_code == 200 and r.json()["icon"] == "clinica"
    # outro campo não mexe no ícone
    assert usuario.patch(f"/projects/{p['id']}", {"name": "Clínica Sul 2"}).json()["icon"] == "clinica"
    assert usuario.patch(f"/projects/{p['id']}", {"icon": "nave"}).status_code == 422
    assert usuario.get(f"/projects/{p['id']}/overview").json()["project"]["icon"] == "clinica"
    # null volta para a pasta (NULL no banco)
    assert usuario.patch(f"/projects/{p['id']}", {"icon": None}).json()["icon"] == "pasta"
    assert db.query_one("SELECT icon FROM projects WHERE id = %s", (p["id"],))["icon"] is None
    # desfazer a última edição devolve o ícone anterior
    h = next(x for x in hist(usuario, entity="project", entity_id=p["id"]) if x["can_undo"])
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert _lista(usuario)["Clínica Sul 2"]["icon"] == "clinica"


def test_icone_nas_tarefas_no_mes_e_no_excluir(usuario):
    a = _proj(usuario, "Prédio A", icon="predio")
    b = _proj(usuario, "Rede B", icon="rede")
    tid = usuario.post("/worklog", {"title": "Trocar switch", "project_id": a["id"], "extra_project_ids": [b["id"]]}).json()["id"]
    solta = usuario.post("/worklog", {"title": "Sem projeto"}).json()["id"]
    card = next(t for t in usuario.get("/board").json()["in_progress"] if t["id"] == tid)
    assert card["project_icon"] == "predio" and card["extra_projects"][0]["icon"] == "rede"
    assert next(t for t in usuario.get("/board").json()["in_progress"] if t["id"] == solta)["project_icon"] is None
    assert usuario.get(f"/worklog/{tid}").json()["project_icon"] == "predio"
    assert usuario.get("/search?q=switch").json()["tasks"][0]["project_icon"] == "predio"
    ov = usuario.get(f"/projects/{a['id']}/overview").json()
    assert ov["unassigned"]["tasks"][0]["project_icon"] == "predio"
    # Meu mês: tempo por projeto com o ícone
    usuario.post(f"/worklog/{tid}/time", {"minutes": 30})
    ov = usuario.get(f"/dashboard?month={dia_hoje(usuario):%Y-%m}").json()["overview"]
    assert {p["name"]: p["icon"] for p in ov["projects"]} == {"Prédio A": "predio", "Rede B": "rede"}
    # excluir e desfazer devolve o ícone
    assert usuario.delete(f"/projects/{a['id']}").status_code == 200
    h = next(x for x in hist(usuario, entity="project", entity_id=a["id"]) if x["can_undo"])
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert _lista(usuario)["Prédio A"]["icon"] == "predio"


def test_mcp_icone_com_enum(usuario):
    b = Bearer(criar_chave(usuario)["token"])
    tools = {t["name"]: t for t in b.rpc("tools/list").json()["result"]["tools"]}
    for nome in ("create_project", "update_project"):
        sch = tools[nome]["inputSchema"]["properties"]["icon"]
        assert set(PROJECT_ICONS) <= set(sch["enum"])
    r = b.tool("create_project", name="Fábrica Norte", icon="fabrica")
    assert not r["isError"] and "(ícone fabrica)" in texto(r)
    assert _lista(usuario)["Fábrica Norte"]["icon"] == "fabrica"
    assert b.tool("create_project", name="Outro", icon="disco-voador")["isError"]
    r = b.tool("update_project", project="Fábrica Norte", icon="eletrica")
    assert not r["isError"] and _lista(usuario)["Fábrica Norte"]["icon"] == "eletrica"
    assert not b.tool("update_project", project="Fábrica Norte", icon=None)["isError"]
    assert _lista(usuario)["Fábrica Norte"]["icon"] == "pasta"
    assert "Fábrica Norte" in texto(b.tool("list_projects"))


def test_exportacao_leva_o_icone(usuario):
    _proj(usuario, "Escola", icon="escola")
    _proj(usuario, "Padrão")
    dados = usuario.get("/export/tudo.json").json()
    assert {p["name"]: p["icon"] for p in dados["projects"]} == {"Escola": "escola", "Padrão": "pasta"}


# ---------------------------------------------------------------- números --

def test_numeros_do_cartao_com_extras_e_ultima_atividade(usuario, novo_usuario):
    a, b = _proj(usuario, "A")["id"], _proj(usuario, "B")["id"]
    vazio = _proj(usuario, "Vazio")["id"]
    t1 = usuario.post("/worklog", {"title": "aberta", "project_id": a, "extra_project_ids": [b]}).json()["id"]
    t2 = usuario.post("/worklog", {"title": "espera", "project_id": a}).json()["id"]
    usuario.patch(f"/worklog/{t2}", {"status": "blocked", "blocked_reason": "peça"})
    t3 = usuario.post("/worklog", {"title": "feita", "project_id": a}).json()["id"]
    usuario.post(f"/worklog/{t3}/finish")
    usuario.post(f"/worklog/{t1}/time", {"minutes": 45})
    # tempo de outro mês não entra nas horas do mês
    hoje = dia_hoje(usuario)
    usuario.post(f"/worklog/{t3}/time", {"minutes": 20})
    db.execute("UPDATE time_entries SET day = %s WHERE task_id = %s", (hoje.replace(day=1).replace(year=hoje.year - 1), t3))
    # objetivos: um concluído (todas feitas), um aberto, um vazio
    o1 = usuario.post(f"/projects/{a}/objectives", {"title": "Um"}).json()["id"]
    usuario.post(f"/projects/{a}/objectives", {"title": "Dois"})
    usuario.patch(f"/worklog/{t3}", {"objective_id": o1})
    # projeto de outra pessoa não conta
    outra = novo_usuario("outra@example.com")
    oid = outra.post("/projects", {"name": "A"}).json()["id"]
    outra.post("/worklog", {"title": "dela", "project_id": oid})

    L = _lista(usuario)
    assert (L["A"]["open_tasks"], L["A"]["waiting_tasks"], L["A"]["done_tasks"], L["A"]["total_tasks"]) == (2, 1, 1, 3)
    assert L["A"]["minutes_month"] == 45 and L["B"]["minutes_month"] == 45  # extra conta inteiro
    assert (L["B"]["open_tasks"], L["B"]["waiting_tasks"]) == (1, 0)
    assert (L["A"]["objectives"], L["A"]["objectives_done"]) == (2, 1)
    assert (L["Vazio"]["open_tasks"], L["Vazio"]["minutes_month"], L["Vazio"]["objectives"]) == (0, 0, 0)
    assert L["Vazio"]["last_activity"] == L["Vazio"]["created_at"]  # sem nada: a criação
    # última atividade: anotação recente numa tarefa onde o projeto é extra
    db.execute("UPDATE projects SET created_at = now() - interval '30 days' WHERE id = ANY(%s)", ([a, b, vazio],))
    db.execute("UPDATE worklog_tasks SET created_at = now() - interval '20 days', completed_at = NULL WHERE id = %s", (t1,))
    db.execute("UPDATE time_entries SET created_at = now() - interval '20 days'")
    db.execute("UPDATE worklog_tasks SET created_at = now() - interval '25 days', blocked_at = now() - interval '25 days',"
               " completed_at = CASE WHEN completed_at IS NULL THEN NULL ELSE now() - interval '25 days' END WHERE user_id ="
               " (SELECT user_id FROM worklog_tasks WHERE id = %s) AND id <> %s", (t1, t1))
    db.execute("UPDATE project_objectives SET created_at = now() - interval '25 days'")
    L = _lista(usuario)
    antes = L["B"]["last_activity"]
    usuario.post(f"/worklog/{t1}/notes", {"body": "passei lá"})
    depois = _lista(usuario)["B"]["last_activity"]
    assert depois > antes
    # cabeçalho do projeto aberto: os mesmos números
    p = usuario.get(f"/projects/{a}/overview").json()["project"]
    assert (p["open_tasks"], p["waiting_tasks"], p["minutes_month"], p["icon"]) == (2, 1, 45, "pasta")
    # external_ref devolve o mesmo formato
    usuario.patch(f"/projects/{vazio}", {"archived": True})
    assert usuario.get("/projects").json()[0]["name"] == "A"
    assert "Vazio" not in _lista(usuario) and "Vazio" in _lista(usuario, include_archived="true")


def test_proximos_prazos_do_projeto(usuario):
    pid = _proj(usuario, "Obra")["id"]
    hoje = dia_hoje(usuario)
    from datetime import timedelta
    d = lambda n: (hoje + timedelta(days=n)).isoformat()
    usuario.post("/worklog", {"title": "depois", "project_id": pid, "due_date": d(10)})
    usuario.post("/worklog", {"title": "atrasada", "project_id": pid, "due_date": d(-2)})
    usuario.post("/worklog", {"title": "sem prazo", "project_id": pid})
    feita = usuario.post("/worklog", {"title": "feita", "project_id": pid, "due_date": d(1)}).json()["id"]
    usuario.post(f"/worklog/{feita}/finish")
    usuario.post(f"/projects/{pid}/objectives", {"title": "Entrega", "due_date": d(3)})
    up = usuario.get(f"/projects/{pid}/overview").json()["upcoming"]
    assert [(x["kind"], x["title"]) for x in up] == [("task", "atrasada"), ("objective", "Entrega"), ("task", "depois")]


# --------------------------------------------------------------- arquivar --

def test_arquivar_mantendo(usuario):
    a = _proj(usuario, "Velho")["id"]
    usuario.post("/worklog", {"title": "x", "project_id": a})
    r = usuario.post(f"/projects/{a}/archive", {})
    assert r.status_code == 200 and r.json()["kept"] == 1
    p = _lista(usuario, include_archived="true")["Velho"]
    assert p["archived"] and p["open_tasks"] == 1


def test_arquivar_concluindo(usuario):
    a = _proj(usuario, "Velho")["id"]
    b = _proj(usuario, "Outro")["id"]
    t1 = usuario.post("/worklog", {"title": "um", "project_id": a}).json()["id"]
    t2 = usuario.post("/worklog", {"title": "dois", "project_id": a}).json()["id"]
    so_extra = usuario.post("/worklog", {"title": "do outro", "project_id": b, "extra_project_ids": [a]}).json()["id"]
    r = usuario.post(f"/projects/{a}/archive", {"open_tasks": "done"})
    assert r.status_code == 200 and r.json()["done"] == 2
    for t in (t1, t2):
        det = usuario.get(f"/worklog/{t}").json()
        assert det["status"] == "done" and det["completed_at"]
    assert usuario.get(f"/worklog/{so_extra}").json()["status"] != "done"  # o principal dela é outro
    assert _lista(usuario, include_archived="true")["Velho"]["archived"]
    # cada tarefa concluída fica no histórico (dá para desfazer uma a uma)
    acoes = [x["action"] for x in hist(usuario, entity="worklog", entity_id=t1)]
    assert "worklog.finish" in acoes


def test_arquivar_movendo(usuario, novo_usuario):
    a = _proj(usuario, "Velho")["id"]
    b = _proj(usuario, "Novo")["id"]
    arq = _proj(usuario, "Arquivado")["id"]
    usuario.patch(f"/projects/{arq}", {"archived": True})
    o = usuario.post(f"/projects/{a}/objectives", {"title": "Fase 1"}).json()["id"]
    t1 = usuario.post("/worklog", {"title": "um", "project_id": a, "objective_id": o}).json()["id"]
    t2 = usuario.post("/worklog", {"title": "dois", "project_id": a, "extra_project_ids": [b]}).json()["id"]
    feita = usuario.post("/worklog", {"title": "feita", "project_id": a}).json()["id"]
    usuario.post(f"/worklog/{feita}/finish")
    alheio = novo_usuario("outra@example.com").post("/projects", {"name": "Dela"}).json()["id"]
    # destino inválido: sem destino, o próprio, de outra pessoa, arquivado
    assert usuario.post(f"/projects/{a}/archive", {"open_tasks": "move"}).status_code == 422
    for alvo in (a, alheio, arq, 999999):
        assert usuario.post(f"/projects/{a}/archive", {"open_tasks": "move", "move_to": alvo}).status_code == 400
    assert not _lista(usuario)["Velho"]["archived"]  # nada mudou
    r = usuario.post(f"/projects/{a}/archive", {"open_tasks": "move", "move_to": b})
    assert r.status_code == 200 and r.json()["moved"] == 2
    d1, d2 = usuario.get(f"/worklog/{t1}").json(), usuario.get(f"/worklog/{t2}").json()
    assert d1["project_id"] == b and d1["objective_id"] is None  # o objetivo era do projeto antigo
    assert d2["project_id"] == b and d2["extra_projects"] == []   # o extra que virou principal sai da lista
    assert usuario.get(f"/worklog/{feita}").json()["project_id"] == a  # concluída fica no histórico do projeto
    L = _lista(usuario, include_archived="true")
    assert L["Velho"]["archived"] and L["Velho"]["open_tasks"] == 0 and L["Novo"]["open_tasks"] == 2
    # de outra pessoa: 404
    assert novo_usuario("terceira@example.com").post(f"/projects/{a}/archive", {}).status_code == 404
