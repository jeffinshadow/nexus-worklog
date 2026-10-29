"""Tarefa em mais de um projeto, projeto padrão e o tour guiado."""
from app.services import get_report_range
from conftest import Bearer, criar_chave, dia_hoje, hist, texto, uid_de


def _proj(u, nome):
    return u.post("/projects", {"name": nome}).json()["id"]


def _ids(board):
    return [t["id"] for t in board["in_progress"]]


def _desfazer(u, entity, entity_id):
    h = next(x for x in hist(u, entity=entity, entity_id=entity_id) if x["can_undo"])  # o 1º pode ser o "desfez"
    assert u.post(f"/history/{h['id']}/undo").status_code == 200


# ------------------------------------------------------- vários projetos --

def test_tarefa_em_dois_projetos_aparece_nos_dois(usuario):
    a, b, c = _proj(usuario, "Matriz"), _proj(usuario, "Filial"), _proj(usuario, "Outro")
    tid = usuario.post("/worklog", {"title": "Link entre as lojas", "project_id": a, "extra_project_ids": [b, a]}).json()["id"]
    so_a = usuario.post("/worklog", {"title": "Só da matriz", "project_id": a}).json()["id"]
    det = usuario.get(f"/worklog/{tid}").json()
    assert det["project_id"] == a and [x["id"] for x in det["extra_projects"]] == [b]  # o principal não se repete
    assert _ids(usuario.get(f"/board?project={b}").json()) == [tid]
    assert set(_ids(usuario.get(f"/board?project={a}").json())) == {tid, so_a}
    assert _ids(usuario.get(f"/board?project={c}").json()) == []
    assert _ids(usuario.get("/board?project=0").json()) == []
    card = next(t for t in usuario.get("/board").json()["in_progress"] if t["id"] == tid)
    assert [x["name"] for x in card["extra_projects"]] == ["Filial"]
    contagem = {p["id"]: p["open_tasks"] for p in usuario.get("/projects").json()}
    assert contagem == {a: 2, b: 1, c: 0}


def test_editar_projetos_extras(usuario, novo_usuario):
    a, b, c = _proj(usuario, "A"), _proj(usuario, "B"), _proj(usuario, "C")
    alheio = _proj(novo_usuario("outra@example.com"), "Dela")
    tid = usuario.post("/worklog", {"title": "x", "project_id": a}).json()["id"]
    extras = lambda: [x["id"] for x in usuario.get(f"/worklog/{tid}").json()["extra_projects"]]
    assert usuario.patch(f"/worklog/{tid}", {"extra_project_ids": [b, c, alheio]}).status_code == 200
    assert extras() == [b, c]  # projeto de outra pessoa não entra
    usuario.patch(f"/worklog/{tid}", {"project_id": b})  # o extra que virou principal sai da lista
    assert extras() == [c]
    usuario.patch(f"/worklog/{tid}", {"title": "y"})  # outro campo não mexe nos extras
    assert extras() == [c]
    _desfazer(usuario, "worklog", tid)  # volta o título; extras iguais
    _desfazer(usuario, "worklog", tid)  # volta o principal A e o extra B
    det = usuario.get(f"/worklog/{tid}").json()
    assert det["project_id"] == a and [x["id"] for x in det["extra_projects"]] == [b, c]
    usuario.patch(f"/worklog/{tid}", {"project_id": None})  # sem principal, sem extras
    assert extras() == []
    assert usuario.patch(f"/worklog/{tid}", {"extra_project_ids": [b]}).status_code == 200
    assert extras() == []


def test_relatorio_conta_a_tarefa_inteira_em_cada_projeto(usuario):
    a, b = _proj(usuario, "Matriz"), _proj(usuario, "Filial")
    tid = usuario.post("/worklog", {"title": "Link", "project_id": a, "extra_project_ids": [b]}).json()["id"]
    usuario.post(f"/worklog/{tid}/time", {"minutes": 60})
    usuario.post(f"/worklog/{tid}/finish")
    uid, hoje = uid_de(usuario), dia_hoje(usuario)
    so_b = get_report_range(uid, hoje, hoje, {"id": b, "name": "Filial"})
    assert so_b["summary"]["minutes"] == 60 and so_b["summary"]["pontual_done"] == 1
    geral = get_report_range(uid, hoje, hoje)
    assert geral["summary"]["minutes"] == 60  # o total não duplica
    por_projeto = {p["name"]: (p["minutes"], p["done"]) for p in geral["projects"]}
    assert por_projeto == {"Matriz": (60, 1), "Filial": (60, 1)} and geral["multi_project"]
    r = usuario.get(f"/reports/export?project={b}")  # projeto inteiro: começa no primeiro dia dele
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


def test_excluir_projeto_principal_promove_o_extra(usuario):
    a, b = _proj(usuario, "A"), _proj(usuario, "B")
    tid = usuario.post("/worklog", {"title": "x", "project_id": a, "extra_project_ids": [b]}).json()["id"]
    outra = usuario.post("/worklog", {"title": "y", "project_id": b, "extra_project_ids": [a]}).json()["id"]
    assert usuario.delete(f"/projects/{a}").status_code == 200
    det = usuario.get(f"/worklog/{tid}").json()
    assert det["project_id"] == b and det["extra_projects"] == []
    assert usuario.get(f"/worklog/{outra}").json()["extra_projects"] == []
    _desfazer(usuario, "project", a)
    det = usuario.get(f"/worklog/{tid}").json()
    assert det["project_id"] == a and [x["id"] for x in det["extra_projects"]] == [b]
    assert [x["id"] for x in usuario.get(f"/worklog/{outra}").json()["extra_projects"]] == [a]


def test_desfazer_exclusao_da_tarefa_devolve_os_extras(usuario):
    a, b = _proj(usuario, "A"), _proj(usuario, "B")
    tid = usuario.post("/worklog", {"title": "x", "project_id": a, "extra_project_ids": [b]}).json()["id"]
    assert usuario.delete(f"/worklog/{tid}").status_code == 200
    _desfazer(usuario, "worklog", tid)
    assert [x["id"] for x in usuario.get(f"/worklog/{tid}").json()["extra_projects"]] == [b]


def test_mcp_projetos_extras(usuario):
    _proj(usuario, "Matriz"), _proj(usuario, "Filial")
    b = Bearer(criar_chave(usuario, nome="Assistente")["token"])
    r = b.tool("create_task", title="Link", project="matriz", extra_projects=["Filial"])
    assert not r["isError"] and "{Matriz + Filial}" in texto(r), texto(r)
    assert b.tool("create_task", title="x", project="Matriz", extra_projects=["Inexistente"])["isError"]


# ------------------------------------------------------- projeto padrão --

def test_projeto_padrao(usuario, novo_usuario):
    a = _proj(usuario, "Suporte")
    assert usuario.put("/me/default-project", {"project_id": 999}).status_code == 400
    assert usuario.put("/me/default-project", {"project_id": a}).json() == {"default_project_id": a}
    assert usuario.get("/auth/me").json()["default_project_id"] == a
    sem = usuario.post("/worklog", {"title": "Sem projeto informado"}).json()["id"]
    nulo = usuario.post("/worklog", {"title": "Sem projeto de propósito", "project_id": None}).json()["id"]
    assert usuario.get(f"/worklog/{sem}").json()["project_id"] == a
    assert usuario.get(f"/worklog/{nulo}").json()["project_id"] is None
    # Modelo sem projeto também cai no padrão.
    m = usuario.post("/templates", {"name": "M", "title": "Do modelo", "checklist": []}).json()["id"]
    tid = usuario.post(f"/templates/{m}/use").json()["id"]
    assert usuario.get(f"/worklog/{tid}").json()["project_id"] == a
    # Arquivado deixa de valer (sem erro); limpar = nenhum.
    usuario.patch(f"/projects/{a}", {"archived": True})
    assert usuario.get(f"/worklog/{usuario.post('/worklog', {'title': 'z'}).json()['id']}").json()["project_id"] is None
    assert usuario.put("/me/default-project", {"project_id": a}).status_code == 400  # arquivado não se escolhe
    assert usuario.put("/me/default-project", {"project_id": None}).json() == {"default_project_id": None}
    alheio = _proj(novo_usuario("outra@example.com"), "Dela")
    assert usuario.put("/me/default-project", {"project_id": alheio}).status_code == 400


def test_projeto_padrao_na_atribuicao(admin, usuario, novo_usuario, monkeypatch):
    from app import mailer
    monkeypatch.setattr(mailer, "configured", lambda: False)
    chefe = novo_usuario("chefe@example.com")
    alvo = uid_de(usuario)
    assert admin.put(f"/admin/users/{uid_de(chefe)}/roles", {"roles": ["user", "assigner"]}).status_code == 200
    usuario.put("/me/assignments", {"accept": True})
    a = _proj(usuario, "Recebidas")
    usuario.put("/me/default-project", {"project_id": a})
    tid = chefe.post("/assign", {"user_id": alvo, "title": "Trocar o nobreak"}).json()["id"]
    assert usuario.get(f"/worklog/{tid}").json()["project_id"] == a


# ------------------------------------------------------------------ tour --

def test_tour_marca_e_reabre(usuario):
    assert usuario.get("/auth/me").json()["tour_done_at"] is None
    assert usuario.put("/me/tour", {"done": True}).json()["tour_done_at"]
    assert usuario.get("/auth/me").json()["tour_done_at"]
    assert usuario.put("/me/tour", {"done": False}).json()["tour_done_at"] is None
