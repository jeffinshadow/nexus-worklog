def _criar(u, **kw):
    corpo = {"title": "Tarefa", **kw}
    r = u.post("/worklog", corpo)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _tarefa(u, tid):
    b = u.get("/board").json()
    return next(t for t in b["in_progress"] + b["done"] if t["id"] == tid)


def test_criar_e_listar(usuario):
    tid = _criar(usuario, description="desc", due_date="2030-01-10")
    t = _tarefa(usuario, tid)
    assert (t["title"], t["description"], t["due_date"]) == ("Tarefa", "desc", "2030-01-10")


def test_limpar_descricao_e_previsao(usuario):
    tid = _criar(usuario, description="desc", due_date="2030-01-10")
    r = usuario.patch(f"/worklog/{tid}", {"title": "Tarefa", "description": None, "status": "todo", "due_date": None})
    assert r.status_code == 200
    t = _tarefa(usuario, tid)
    assert t["description"] is None and t["due_date"] is None


def test_patch_parcial_preserva_o_resto(usuario):
    tid = _criar(usuario, description="desc", due_date="2030-01-10")
    usuario.patch(f"/worklog/{tid}", {"title": "Novo título"})
    t = _tarefa(usuario, tid)
    assert (t["title"], t["description"], t["due_date"]) == ("Novo título", "desc", "2030-01-10")


def test_finalizar_e_reabrir(usuario):
    tid = _criar(usuario)
    assert usuario.post(f"/worklog/{tid}/finish").status_code == 200
    assert _tarefa(usuario, tid)["status"] == "done"
    usuario.patch(f"/worklog/{tid}", {"status": "in_progress"})
    t = _tarefa(usuario, tid)
    assert t["status"] == "in_progress"


def test_isolamento_entre_usuarios(usuario, novo_usuario):
    tid = _criar(usuario)
    outro = novo_usuario("outro@example.com")
    assert outro.patch(f"/worklog/{tid}", {"title": "invasão"}).status_code == 404
    assert outro.delete(f"/worklog/{tid}").status_code == 404
    assert all(t["id"] != tid for t in outro.get("/board").json()["in_progress"])
