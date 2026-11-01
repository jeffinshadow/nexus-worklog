"""Páginas nas listas grandes: limit + offset, total em X-Total-Count (ou no
corpo, quando a resposta é um objeto), ordem estável com desempate pelo id,
offset além do fim = lista vazia, e sem parâmetros tudo igual a antes."""
from app import db
from conftest import Bearer, criar_chave, hist, texto, uid_de


def _tarefas(u, n, titulo="Tarefa", **extra):
    return [u.post("/worklog", {"title": f"{titulo} {i:02d}", **extra}).json()["id"] for i in range(n)]


def _concluir(u, ids):
    for tid in ids:
        assert u.post(f"/worklog/{tid}/finish").status_code == 200


# ------------------------------------------------------------- histórico --

def test_historico_paginas_total_e_ordem(usuario):
    _tarefas(usuario, 35)
    r = usuario.get("/history?limit=10&offset=0")
    assert r.status_code == 200
    total = int(r.headers["X-Total-Count"])
    assert total >= 35 and len(r.json()) == 10
    vistos = []
    for off in range(0, total, 10):
        pagina = usuario.get(f"/history?limit=10&offset={off}").json()
        vistos += [x["id"] for x in pagina]
    assert len(vistos) == total == len(set(vistos))  # nenhuma linha em duas páginas
    assert vistos == sorted(vistos, reverse=True)    # do mais novo ao mais velho
    assert usuario.get(f"/history?limit=10&offset={total}").json() == []  # além do fim: vazia, não erro
    assert int(usuario.get(f"/history?limit=10&offset={total + 50}").headers["X-Total-Count"]) == total


def test_historico_sem_parametros_igual_a_antes(usuario):
    _tarefas(usuario, 60)
    r = usuario.get("/history")
    assert len(r.json()) == 50 and r.headers["X-Total-Count"]  # padrão continua 50
    assert [x["id"] for x in r.json()] == [x["id"] for x in usuario.get("/history?offset=0&limit=50").json()]
    assert usuario.get("/history?offset=-1").status_code == 422
    assert usuario.get("/history?limit=201").status_code == 422
    # entity/entity_id contam junto
    tid = _tarefas(usuario, 1, "Única")[0]
    usuario.patch(f"/worklog/{tid}", {"title": "Única editada"})
    r = usuario.get(f"/history?entity=worklog&entity_id={tid}&limit=1&offset=1")
    assert r.headers["X-Total-Count"] == "2" and r.json()[0]["action"] == "worklog.create"
    # o feed (after) não muda: sem total, do mais velho ao mais novo
    feed = usuario.get("/history?after=0&limit=5")
    assert "X-Total-Count" not in feed.headers


# ------------------------------------------------------------ /worklog --

def test_worklog_periodo_paginas(usuario):
    _tarefas(usuario, 23)
    r = usuario.get("/worklog?limit=10&offset=20")
    assert r.headers["X-Total-Count"] == "23" and len(r.json()) == 3
    todas = [t["id"] for off in (0, 10, 20) for t in usuario.get(f"/worklog?limit=10&offset={off}").json()]
    assert len(todas) == 23 == len(set(todas))
    assert [t["id"] for t in usuario.get("/worklog").json()] == todas  # sem parâmetros: as mesmas (até 200)
    assert usuario.get("/worklog?limit=10&offset=30").json() == []


# --------------------------------------------------------------- quadro --

def test_quadro_concluidas_paginam_e_total_real(usuario):
    ids = _tarefas(usuario, 25)
    _concluir(usuario, ids)
    b = usuario.get("/board").json()
    assert len(b["done"]) == 25 and b["done_total"] == 25  # padrão: até 200, como antes
    p1 = usuario.get("/board?done_limit=20&done_offset=0").json()
    p2 = usuario.get("/board?done_limit=20&done_offset=20").json()
    assert (len(p1["done"]), len(p2["done"]), p2["done_total"]) == (20, 5, 25)
    juntas = [t["id"] for t in p1["done"] + p2["done"]]
    assert juntas == [t["id"] for t in b["done"]] and len(set(juntas)) == 25
    assert usuario.get("/board?done_limit=20&done_offset=40").json()["done"] == []
    assert usuario.get("/board?done_limit=201").status_code == 422
    # filtro de projeto vale para o total também
    pid = usuario.post("/projects", {"name": "Filtro"}).json()["id"]
    _concluir(usuario, _tarefas(usuario, 3, "No projeto", project_id=pid))
    assert usuario.get(f"/board?project={pid}&done_limit=2").json()["done_total"] == 3


def test_quadro_concluidas_ordem_estavel_com_mesma_hora(usuario):
    ids = _tarefas(usuario, 6)
    _concluir(usuario, ids)
    db.execute("UPDATE worklog_tasks SET completed_at = now() - interval '1 hour' WHERE id = ANY(%s)", (ids,))
    paginas = [t["id"] for off in (0, 2, 4) for t in usuario.get(f"/board?done_limit=2&done_offset={off}").json()["done"]]
    assert paginas == sorted(ids, reverse=True)  # mesma hora: desempate pelo id


# ---------------------------------------------------------------- busca --

def test_busca_paginas_por_secao_e_totais(usuario):
    _tarefas(usuario, 45, "Rede da matriz")
    nota = _tarefas(usuario, 1, "Impressora")[0]
    usuario.post(f"/worklog/{nota}/notes", {"body": "cabo de rede trocado"})
    for i in range(12):
        usuario.post("/recurring", {"label": f"Conferir rede {i:02d}"})
    for i in range(3):
        usuario.post("/projects", {"name": f"Rede {i}"})

    r = usuario.get("/search?q=rede")  # sem parâmetros: 40 tarefas e 20 de cada lateral, como antes
    d = r.json()
    assert len(d["tasks"]) == 40 and d["total_tasks"] == 46 and r.headers["X-Total-Count"] == "46"
    assert (len(d["recurring"]), d["total_recurring"], len(d["projects"]), d["total_projects"]) == (12, 12, 3, 3)

    vistos = []
    for off in (0, 20, 40):
        p = usuario.get(f"/search?q=rede&limit=20&offset={off}").json()
        assert p["total_tasks"] == 46
        vistos += [t["id"] for t in p["tasks"]]
    assert len(vistos) == 46 == len(set(vistos))
    assert vistos == [t["id"] for t in d["tasks"]] + vistos[40:]  # mesma ordem que a resposta inteira
    # a que casou pela anotação vem com o trecho, mesmo fora da 1ª página
    achada = next(t for off in (0, 20, 40) for t in usuario.get(f"/search?q=rede&limit=20&offset={off}").json()["tasks"] if t["id"] == nota)
    assert any(x["kind"] == "anotação" for x in achada["hits"])

    lado = usuario.get("/search?q=rede&side_limit=10&rec_offset=10&proj_offset=0").json()
    assert [x["label"] for x in lado["recurring"]] == ["Conferir rede 10", "Conferir rede 11"]
    assert lado["total_recurring"] == 12
    fim = usuario.get("/search?q=rede&limit=20&offset=100&side_limit=10&rec_offset=50&proj_offset=50").json()
    assert (fim["tasks"], fim["total_tasks"], fim["recurring"], fim["total_recurring"], fim["total_projects"]) == ([], 46, [], 12, 3)
    assert usuario.get("/search?q=rede&limit=101").status_code == 422


def test_busca_abertas_antes_das_concluidas(usuario):
    abertas = _tarefas(usuario, 3, "Switch aberta")
    feitas = _tarefas(usuario, 3, "Switch feita")
    _concluir(usuario, feitas)
    ids = [t["id"] for t in usuario.get("/search?q=switch&limit=2&offset=0").json()["tasks"]] + \
          [t["id"] for t in usuario.get("/search?q=switch&limit=2&offset=2").json()["tasks"]] + \
          [t["id"] for t in usuario.get("/search?q=switch&limit=2&offset=4").json()["tasks"]]
    assert set(ids[:3]) == set(abertas) and set(ids[3:]) == set(feitas)


# ------------------------------------------------------------- projetos --

def test_projeto_concluidas_por_bloco_total_certo_e_paginas(usuario):
    pid = usuario.post("/projects", {"name": "Obra"}).json()["id"]
    oid = usuario.post(f"/projects/{pid}/objectives", {"title": "Fundação"}).json()["id"]
    no_obj = _tarefas(usuario, 34, "Bloco", objective_id=oid)
    soltas = _tarefas(usuario, 4, "Solta", project_id=pid)
    _concluir(usuario, no_obj + soltas)
    _tarefas(usuario, 2, "Aberta", objective_id=oid)

    o = usuario.get(f"/projects/{pid}/overview").json()
    ob = o["objectives"][0]
    assert (ob["done"], ob["total"], len(ob["done_tasks"])) == (34, 36, 30)  # o número é o real; a lista, as 30 primeiras
    assert (o["unassigned"]["done"], len(o["unassigned"]["done_tasks"])) == (4, 4)
    assert o["totals"]["done"] == 38 and o["totals"]["total"] == 40

    r = usuario.get(f"/projects/{pid}/done?objective={oid}&limit=10&offset=30")
    assert r.headers["X-Total-Count"] == "34" and len(r.json()) == 4
    todas = [t["id"] for off in (0, 10, 20, 30) for t in usuario.get(f"/projects/{pid}/done?objective={oid}&limit=10&offset={off}").json()]
    assert len(todas) == 34 == len(set(todas))
    assert todas[:30] == [t["id"] for t in ob["done_tasks"]]
    sem = usuario.get(f"/projects/{pid}/done?objective=0")
    assert sem.headers["X-Total-Count"] == "4" and {t["id"] for t in sem.json()} == set(soltas)
    assert usuario.get(f"/projects/{pid}/done?objective={oid}&offset=99").json() == []

    outro = usuario.post("/projects", {"name": "Outro"}).json()["id"]
    assert usuario.get(f"/projects/{outro}/done?objective={oid}").status_code in (400, 404)
    assert usuario.get(f"/projects/{pid}/done").status_code == 422  # objective é obrigatório


def test_projeto_concluidas_isoladas_por_pessoa(usuario, novo_usuario):
    pid = usuario.post("/projects", {"name": "Meu"}).json()["id"]
    outra = novo_usuario("outra@example.com")
    assert outra.get(f"/projects/{pid}/done?objective=0").status_code == 404


# ------------------------------------------------------------------ MCP --

def test_mcp_offset_em_historico_tarefas_e_busca(usuario):
    b = Bearer(criar_chave(usuario)["token"])
    _tarefas(usuario, 12, "Backup do servidor")
    p1 = texto(b.tool("get_history", limit=5))
    p2 = texto(b.tool("get_history", limit=5, offset=5))
    assert p1 and p2 and not set(p1.splitlines()) & set(p2.splitlines())

    lista = texto(b.tool("list_tasks", limit=5))
    assert "offset=5" in lista and "de 12" in lista
    resto = texto(b.tool("list_tasks", limit=5, offset=10))
    assert len([x for x in resto.splitlines() if "Backup" in x]) == 2 and "offset=" not in resto

    _tarefas(usuario, 35, "Servidor extra")
    busca = texto(b.tool("search", query="servidor"))
    assert "offset=40" in busca
    assert "offset=" not in texto(b.tool("search", query="servidor", offset=40))
    assert hist(usuario, limit=1, offset=0)  # o app continua lendo do mesmo jeito
    assert uid_de(usuario)
