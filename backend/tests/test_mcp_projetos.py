"""A IA monta projetos e objetivos pelo MCP: sem duplicar, isolada por usuário,
com histórico e desfazer (inclusive da ordem)."""
from conftest import Bearer, criar_chave, hist, texto


def _ia(u):
    return Bearer(criar_chave(u)["token"])


def _id(res):
    assert not res["isError"], texto(res)
    return int(texto(res).split("#")[1].split()[0])


def _ordem(u, pid):
    return [o["title"] for o in u.get(f"/projects/{pid}/objectives").json()]


def _desfazer_ultima(b, u):
    hid = next(h["id"] for h in hist(u) if h["can_undo"])
    r = b.tool("undo", history_id=hid)
    assert not r["isError"], texto(r)


def test_criar_projeto_sem_duplicar(usuario):
    b = _ia(usuario)
    pid = _id(b.tool("create_project", name="Gestão", description="Portal do cliente"))
    assert usuario.get(f"/projects/{pid}/overview").json()["project"]["description"] == "Portal do cliente"
    # mesmo nome sem acento e em outra caixa: devolve o existente
    r = b.tool("create_project", name="GESTAO")
    assert _id(r) == pid and "Já existia" in texto(r)
    # external_ref repetido: devolve o mesmo, mesmo com outro nome
    ref = _id(b.tool("create_project", name="Gateway", external_ref="sessao-1"))
    assert _id(b.tool("create_project", name="Outro nome", external_ref="sessao-1")) == ref
    assert len(usuario.get("/projects").json()) == 2
    # o app também recusa o nome repetido sem acento
    assert usuario.post("/projects", {"name": "gestao"}).status_code == 409


def test_editar_arquivar_e_listar(usuario):
    b = _ia(usuario)
    pid = _id(b.tool("create_project", name="Gateway"))
    for t in ("Autenticação", "Pagamentos", "Relatórios"):
        assert not b.tool("create_objective", project="gateway", title=t)["isError"]
    usuario.post("/worklog", {"title": "Rota de pagamento", "project_id": pid})
    assert "#%d Gateway (1 abertas, 3 objetivos)" % pid in texto(b.tool("list_projects"))
    r = b.tool("update_project", project="Gateway", description="API de cobrança", archived=True)
    assert not r["isError"] and "[arquivado]" in texto(r)
    lista = texto(b.tool("list_projects"))
    assert "[arquivado]" in lista and "API de cobrança" in lista
    assert usuario.get("/projects").json() == []  # arquivado sai dos seletores
    assert b.tool("update_project", project="Gateway")["isError"]  # nada a mudar
    _desfazer_ultima(b, usuario)
    p = usuario.get("/projects").json()[0]
    assert (p["archived"], p["description"]) == (False, None)


def test_objetivos_posicao_titulo_unico_e_status_automatico(usuario):
    b = _ia(usuario)
    _id(b.tool("create_project", name="App"))
    pid = usuario.get("/projects").json()[0]["id"]
    a = _id(b.tool("create_objective", project="App", title="Login", due_date="2030-01-31"))
    _id(b.tool("create_objective", project="App", title="Pagamentos"))
    r = b.tool("create_objective", project="App", title="Cadastro", position=1)
    assert texto(r).startswith("Criado: 1. #"), texto(r)
    assert _ordem(usuario, pid) == ["Cadastro", "Login", "Pagamentos"]
    r = b.tool("create_objective", project="app", title="login")
    assert _id(r) == a and "Já existia" in texto(r)
    assert b.tool("create_objective", project="App", title="x", status="done")["isError"]
    r = b.tool("update_objective", objective="Login", project="App", title="Login social", position=3, due_date=None)
    assert not r["isError"] and texto(r).startswith("Atualizado: 3. #"), texto(r)
    assert _ordem(usuario, pid) == ["Cadastro", "Pagamentos", "Login social"]
    assert b.tool("update_objective", objective="Pagamentos", title="Cadastro")["isError"]  # título já usado
    assert b.tool("update_objective", objective=str(a), status="todo")["isError"]
    # o app também recusa título repetido no mesmo projeto
    assert usuario.post(f"/projects/{pid}/objectives", {"title": "CADASTRO"}).status_code == 409
    # external_ref
    ref = _id(b.tool("create_objective", project="App", title="Deploy", external_ref="obj-1"))
    assert _id(b.tool("create_objective", project="App", title="Outro", external_ref="obj-1")) == ref


def test_reordenar_inteiro_e_desfazer(usuario):
    b = _ia(usuario)
    _id(b.tool("create_project", name="App"))
    pid = usuario.get("/projects").json()[0]["id"]
    ids = [_id(b.tool("create_objective", project="App", title=t)) for t in ("A", "B", "C")]
    assert b.tool("reorder_objectives", project="App", order=["C", "A"])["isError"]  # faltou B
    assert b.tool("reorder_objectives", project="App", order=["C", "A", "a", "B"])["isError"]  # repetido
    assert _ordem(usuario, pid) == ["A", "B", "C"]
    r = b.tool("reorder_objectives", project="App", order=["c", ids[0], "B"])
    assert not r["isError"] and texto(r).startswith("Nova ordem:\n1. #%d C" % ids[2]), texto(r)
    assert _ordem(usuario, pid) == ["C", "A", "B"]
    assert any("reordenou os objetivos de “App”" in h["summary"] for h in hist(usuario))
    _desfazer_ultima(b, usuario)
    assert _ordem(usuario, pid) == ["A", "B", "C"]


def test_desfazer_criacao_e_sem_exclusao(usuario):
    b = _ia(usuario)
    _id(b.tool("create_project", name="App"))
    pid = usuario.get("/projects").json()[0]["id"]
    _id(b.tool("create_objective", project="App", title="A"))
    _desfazer_ultima(b, usuario)
    assert _ordem(usuario, pid) == []
    nomes = {t["name"] for t in b.rpc("tools/list").json()["result"]["tools"]}
    assert {"create_project", "update_project", "create_objective", "update_objective", "reorder_objectives"} <= nomes
    assert not any(n.startswith("delete_") for n in nomes)
    leitura = Bearer(criar_chave(usuario, nome="r", scope="read")["token"])
    assert leitura.tool("create_project", name="X")["isError"]


def test_isolamento_entre_usuarios(usuario, novo_usuario):
    outro = novo_usuario("outra@example.com")
    pid_outro = outro.post("/projects", {"name": "Gateway"}).json()["id"]
    outro.post(f"/projects/{pid_outro}/objectives", {"title": "Login"})
    b = _ia(usuario)
    # mesmo nome de outra pessoa: cria o próprio, sem colidir
    r = b.tool("create_project", name="Gateway")
    pid = _id(r)
    assert pid != pid_outro and texto(r).startswith("Criado")
    assert b.tool("update_project", project=str(pid_outro), name="hack")["isError"]
    assert b.tool("create_objective", project=str(pid_outro), title="x")["isError"]
    assert texto(b.tool("create_objective", project="Gateway", title="Login")).startswith("Criado")
    assert b.tool("reorder_objectives", project=str(pid_outro), order=["Login"])["isError"]
    assert [o["title"] for o in outro.get(f"/projects/{pid_outro}/objectives").json()] == ["Login"]
    assert outro.get("/projects").json()[0]["name"] == "Gateway"
