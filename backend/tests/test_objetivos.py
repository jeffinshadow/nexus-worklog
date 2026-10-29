"""Projetos com objetivos: ordem de execução, tarefas vinculadas, progresso e status."""
from conftest import Bearer, criar_chave, hist, texto


def _proj(u, nome="App do cliente"):
    return u.post("/projects", {"name": nome}).json()["id"]


def _obj(u, pid, titulo, **kw):
    r = u.post(f"/projects/{pid}/objectives", {"title": titulo, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _desfazer(u, entity, entity_id):
    h = next(x for x in hist(u, entity=entity, entity_id=entity_id) if x["can_undo"])
    r = u.post(f"/history/{h['id']}/undo")
    assert r.status_code == 200, r.text


def _ov(u, pid):
    r = u.get(f"/projects/{pid}/overview")
    assert r.status_code == 200, r.text
    return r.json()


def test_objetivos_em_ordem_com_progresso_e_status(usuario):
    pid = _proj(usuario)
    login, pag = _obj(usuario, pid, "Login"), _obj(usuario, pid, "Pagamentos", due_date="2030-01-31")
    # Com objetivo e sem projeto: o projeto vem do objetivo; a fila cresce na ordem.
    t1 = usuario.post("/worklog", {"title": "Tela de login", "objective_id": login}).json()["id"]
    t2 = usuario.post("/worklog", {"title": "Recuperar senha", "objective_id": login}).json()["id"]
    solta = usuario.post("/worklog", {"title": "Ideia solta", "project_id": pid}).json()["id"]
    det = usuario.get(f"/worklog/{t1}").json()
    assert det["project_id"] == pid and det["objective_title"] == "Login"
    o = _ov(usuario, pid)
    assert [x["title"] for x in o["objectives"]] == ["Login", "Pagamentos"]
    bl = o["objectives"][0]
    assert [t["id"] for t in bl["tasks"]] == [t1, t2] and (bl["total"], bl["done"], bl["status"]) == (2, 0, "todo")
    assert o["objectives"][1]["status"] == "todo" and o["objectives"][1]["due_date"] == "2030-01-31"
    assert [t["id"] for t in o["unassigned"]["tasks"]] == [solta]
    # Status automático: em andamento, concluído, e reabre com tarefa nova.
    usuario.patch(f"/worklog/{t1}", {"status": "in_progress"})
    assert _ov(usuario, pid)["objectives"][0]["status"] == "in_progress"
    usuario.post(f"/worklog/{t1}/finish"); usuario.post(f"/worklog/{t2}/finish")
    bl = _ov(usuario, pid)["objectives"][0]
    assert (bl["done"], bl["status"], len(bl["done_tasks"])) == (2, "done", 2)
    usuario.post("/worklog", {"title": "Login social", "objective_id": login})
    assert _ov(usuario, pid)["objectives"][0]["status"] == "in_progress"  # 2 de 3: reabriu
    # Ordem dos objetivos.
    assert usuario.post(f"/projects/{pid}/objectives/order", {"ids": [pag, login]}).status_code == 200
    assert [x["title"] for x in _ov(usuario, pid)["objectives"]] == ["Pagamentos", "Login"]
    assert usuario.post(f"/projects/{pid}/objectives/order", {"ids": [pag]}).status_code == 400  # faltou um
    # Contagens na lista de projetos.
    p = next(x for x in usuario.get("/projects").json() if x["id"] == pid)
    assert (p["objectives"], p["done_tasks"]) == (2, 2)


def test_ordem_das_tarefas_e_mover_de_bloco(usuario):
    pid = _proj(usuario)
    a, b = _obj(usuario, pid, "A"), _obj(usuario, pid, "B")
    t1, t2, t3 = (usuario.post("/worklog", {"title": n, "objective_id": a}).json()["id"] for n in ("1", "2", "3"))
    assert usuario.post(f"/projects/{pid}/tasks/order", {"objective_id": a, "task_ids": [t3, t1, t2]}).status_code == 200
    assert [t["id"] for t in _ov(usuario, pid)["objectives"][0]["tasks"]] == [t3, t1, t2]
    # Arrastar t1 para B: muda de objetivo (com histórico e desfazer).
    usuario.post(f"/projects/{pid}/tasks/order", {"objective_id": b, "task_ids": [t1]})
    o = _ov(usuario, pid)
    assert [t["id"] for t in o["objectives"][1]["tasks"]] == [t1]
    _desfazer(usuario, "worklog", t1)
    assert usuario.get(f"/worklog/{t1}").json()["objective_id"] == a
    # Para "Sem objetivo".
    usuario.post(f"/projects/{pid}/tasks/order", {"objective_id": None, "task_ids": [t2]})
    assert [t["id"] for t in _ov(usuario, pid)["unassigned"]["tasks"]] == [t2]
    # Tarefa de outro projeto não entra.
    outra = usuario.post("/worklog", {"title": "fora", "project_id": _proj(usuario, "Outro")}).json()["id"]
    assert usuario.post(f"/projects/{pid}/tasks/order", {"objective_id": a, "task_ids": [outra]}).status_code == 400


def test_objetivo_so_do_projeto_principal(usuario, novo_usuario):
    pid, outro = _proj(usuario), _proj(usuario, "Outro")
    a = _obj(usuario, pid, "A")
    x = _obj(usuario, outro, "X")
    assert usuario.post("/worklog", {"title": "t", "project_id": pid, "objective_id": x}).status_code == 400
    tid = usuario.post("/worklog", {"title": "t", "objective_id": a}).json()["id"]
    assert usuario.patch(f"/worklog/{tid}", {"objective_id": x}).status_code == 400
    # Trocar o projeto tira do objetivo; tirar o projeto também.
    usuario.patch(f"/worklog/{tid}", {"project_id": outro})
    assert usuario.get(f"/worklog/{tid}").json()["objective_id"] is None
    assert usuario.patch(f"/worklog/{tid}", {"objective_id": x}).status_code == 200
    usuario.patch(f"/worklog/{tid}", {"objective_id": None})
    assert usuario.get(f"/worklog/{tid}").json()["objective_id"] is None
    # De outra pessoa: nada.
    alheio = novo_usuario("outra@example.com")
    assert alheio.get(f"/projects/{pid}/overview").status_code == 404
    assert alheio.patch(f"/objectives/{a}", {"title": "hack"}).status_code == 404
    assert alheio.post("/worklog", {"title": "t", "objective_id": a}).status_code == 400


def test_editar_excluir_e_desfazer(usuario):
    pid = _proj(usuario)
    a = _obj(usuario, pid, "Antigo", description="desc")
    t1 = usuario.post("/worklog", {"title": "t1", "objective_id": a}).json()["id"]
    r = usuario.patch(f"/objectives/{a}", {"title": "Novo", "due_date": "2030-05-01"})
    assert r.json()["title"] == "Novo" and r.json()["description"] == "desc"
    _desfazer(usuario, "objective", a)
    assert _ov(usuario, pid)["objectives"][0]["title"] == "Antigo"
    # Excluir: a tarefa volta para "Sem objetivo"; desfazer devolve.
    assert usuario.delete(f"/objectives/{a}").json()["tasks"] == 1
    o = _ov(usuario, pid)
    assert o["objectives"] == [] and [t["id"] for t in o["unassigned"]["tasks"]] == [t1]
    _desfazer(usuario, "objective", a)
    o = _ov(usuario, pid)
    assert [t["id"] for t in o["objectives"][0]["tasks"]] == [t1]


def test_excluir_projeto_e_desfazer_devolve_os_objetivos(usuario):
    pid = _proj(usuario)
    a = _obj(usuario, pid, "A")
    t1 = usuario.post("/worklog", {"title": "t1", "objective_id": a}).json()["id"]
    assert usuario.delete(f"/projects/{pid}").status_code == 200
    assert usuario.get(f"/worklog/{t1}").json()["objective_id"] is None
    _desfazer(usuario, "project", pid)
    o = _ov(usuario, pid)
    assert [x["title"] for x in o["objectives"]] == ["A"] and [t["id"] for t in o["objectives"][0]["tasks"]] == [t1]


def test_excluir_tarefa_e_desfazer_mantem_o_objetivo(usuario):
    pid = _proj(usuario)
    a = _obj(usuario, pid, "A")
    t1 = usuario.post("/worklog", {"title": "t1", "objective_id": a}).json()["id"]
    usuario.delete(f"/worklog/{t1}")
    _desfazer(usuario, "worklog", t1)
    assert usuario.get(f"/worklog/{t1}").json()["objective_id"] == a


def test_ia_e_objetivos(usuario):
    pid = _proj(usuario, "App")
    _obj(usuario, pid, "Login")
    b = Bearer(criar_chave(usuario)["token"])
    r = b.tool("create_task", title="Tela de login", objective="login")
    assert not r["isError"] and "[objetivo: Login]" in texto(r) and "{App}" in texto(r), texto(r)
    lista = texto(b.tool("list_objectives", project="App"))
    assert "1. #" in lista and "Login" in lista and "Tela de login" in lista and "0/1" in lista
    assert b.tool("create_task", title="x", objective="Inexistente")["isError"]
