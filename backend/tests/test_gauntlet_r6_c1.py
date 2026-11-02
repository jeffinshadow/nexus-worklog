"""Gauntlet geral R6, lote C1 (servidor, segurança, dados, MCP): transferência
só para conta ativa e cancelar convite que não apaga tarefas; diretório de
quem manda tarefas; token fora do log; chave alheia no histórico; visualizador
por id; links de senha após trocar e-mail; portas e eventos de webhook; pedido
de convite opt-in, sem nome e com teto; tempo de tarefa transferida; Primeiro
amanhã que cai em feriado; aba velha reabrindo concluída; MCP por escopo;
política de privacidade; openapi."""
from datetime import timedelta

import pytest

from app import db, links, mailer, push, webhooks
from app.main import app
from app.routers import admin as admin_mod
from app.routers import assign as assign_mod
from app.routers import auth as auth_mod
from app.version import VERSION
from conftest import Api, Bearer, criar_chave, dia_hoje, hist, ligar_pedido_convite, texto, uid_de
from test_api_aberta import _novo, dns  # noqa: F401 — dns é fixture


class _Agora:
    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@pytest.fixture
def caixa(monkeypatch):
    enviados = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None: enviados.append((to, subject, text)))
    monkeypatch.setattr(auth_mod.threading, "Thread", _Agora)
    monkeypatch.setattr(admin_mod.threading, "Thread", _Agora)
    monkeypatch.setattr(assign_mod.threading, "Thread", _Agora)
    monkeypatch.setattr(push, "send", lambda *a, **k: 0)
    return enviados


def _papeis(admin, u, roles):
    assert admin.put(f"/admin/users/{uid_de(u)}/roles", {"roles": roles}).status_code == 200


def _pendente(admin, email="pend@example.com"):
    r = admin.post("/admin/users", {"email": email})
    assert r.status_code == 201 and "invite_url" in r.json(), r.text
    return db.query_one("SELECT id FROM users WHERE email = %s", (email,))["id"]


# ------------------------------------------------ transferência e convite --

def test_transferir_so_para_conta_ativa_e_cancelar_convite_nao_apaga(admin, novo_usuario, caixa):
    zeca = novo_usuario("zeca@example.com")
    t = zeca.post("/worklog", {"title": "Z tarefa"}).json()["id"]
    pend = _pendente(admin)
    r = admin.post(f"/admin/users/{uid_de(zeca)}/block", {"transfer_to": pend})
    assert r.status_code == 400 and "já ter entrado" in r.json()["detail"]
    assert db.query_one("SELECT blocked_at FROM users WHERE id = %s", (uid_de(zeca),))["blocked_at"] is None
    # Tarefa que chegou à conta pendente por outro caminho (dado antigo): cancelar recusa.
    db.execute("UPDATE worklog_tasks SET user_id = %s WHERE id = %s", (pend, t))
    r = admin.post(f"/admin/users/{pend}/cancel-invite")
    assert r.status_code == 409 and "1 tarefa" in r.json()["detail"] and "Excluir conta" in r.json()["detail"]
    assert db.query_one("SELECT 1 FROM worklog_tasks WHERE id = %s", (t,))
    # Sem tarefas, cancela como antes.
    db.execute("UPDATE worklog_tasks SET user_id = %s WHERE id = %s", (uid_de(zeca), t))
    assert admin.post(f"/admin/users/{pend}/cancel-invite").status_code == 200


# ---------------------------------------------- diretório de quem atribui --

def test_people_para_quem_manda_tarefas_sem_email_de_quem_nao_aceita(admin, novo_usuario):
    chefe = novo_usuario("chefe@example.com")
    _papeis(admin, chefe, ["user", "assigner"])
    sim = novo_usuario("sim@example.com")
    sim.put("/me/assignments", {"accept": True})
    novo_usuario("nao@example.com")
    lista = chefe.get("/assign/people").json()
    emails = {p.get("email") for p in lista}
    assert "sim@example.com" in emails and "nao@example.com" not in emails
    anon = [p for p in lista if "email" not in p]
    assert anon and all(set(p) == {"accepts", "everyone"} and p["accepts"] is False for p in anon)
    assert "nao@example.com" in {p["email"] for p in admin.get("/assign/people").json()}  # o admin vê tudo


# ----------------------------------------------------- token fora do log --

def test_link_por_post_com_token_no_corpo(admin, caixa):
    _pendente(admin, "nova@example.com")
    token = caixa[-1][2].split("#convite=")[1].split()[0]
    anon = Api()
    assert anon.post("/auth/link", {"kind": "invite", "token": token}).json()["email"] == "nova@example.com"
    assert anon.post("/auth/link", {"kind": "reset", "token": token}).status_code == 404
    # A forma antiga ainda responde (app em cache), fora do openapi.
    assert anon.get(f"/auth/link?kind=invite&token={token}").status_code == 200
    assert ("/api/auth/link", "get") not in {(p, m) for p, ops in app.openapi()["paths"].items() for m in ops}


def test_nginx_nao_grava_a_rota_do_link():
    import pathlib
    conf = (pathlib.Path(__file__).parents[2] / "web" / "nginx.conf")
    if not conf.exists():
        pytest.skip("nginx.conf fora do container de testes")
    txt = conf.read_text()
    bloco = txt.split("location = /api/auth/link", 1)[1].split("}", 1)[0]
    assert "access_log off" in bloco


# -------------------------------------------- chave alheia no histórico --

def test_chave_de_quem_atribui_nao_aparece_no_historico_de_quem_recebe(admin, novo_usuario, caixa):
    chefe = novo_usuario("chefe@example.com")
    _papeis(admin, chefe, ["user", "assigner"])
    ptb = novo_usuario("ptb@example.com")
    ptb.put("/me/assignments", {"accept": True})
    k = criar_chave(chefe, "chave-secreta-do-chefe")
    r = Bearer(k["token"]).post("/assign", {"user_id": uid_de(ptb), "title": "Via chave"})
    assert r.status_code == 201, r.text
    linhas = hist(ptb)
    assert linhas and all(x.get("token_name") != "chave-secreta-do-chefe" for x in linhas)
    assert db.query_one("SELECT count(*)::int AS n FROM audit_log WHERE user_id = %s AND token_id = %s",
                        (uid_de(ptb), k["id"]))["n"] == 0
    # No histórico de quem atribuiu, a chave dele continua aparecendo.
    assert any(x.get("token_name") == "chave-secreta-do-chefe" for x in hist(chefe))


# -------------------------------------------------- visualizador por id --

def test_visualizador_nao_abre_conta_bloqueada_ou_pendente_por_id(admin, novo_usuario, caixa):
    admin.put("/admin/org", {"team_visibility": "managers"})
    chefe = novo_usuario("chefe@example.com")
    _papeis(admin, chefe, ["user", "viewer"])
    ptb = novo_usuario("ptb@example.com")
    assert chefe.get(f"/viewer/users/{uid_de(ptb)}/board").status_code == 200
    assert admin.post(f"/admin/users/{uid_de(ptb)}/block").status_code == 200
    assert chefe.get(f"/viewer/users/{uid_de(ptb)}/board").status_code == 404
    assert chefe.get(f"/viewer/users/{uid_de(ptb)}/dashboard").status_code == 404
    pend = _pendente(admin)
    assert chefe.get(f"/viewer/users/{pend}/board").status_code == 404


# --------------------------------------- troca de e-mail e link de senha --

def test_trocar_email_invalida_link_de_senha_antigo(admin, usuario, caixa):
    uid = uid_de(usuario)
    velho = links.issue(uid, "reset")
    assert links.peek(velho, "reset")
    assert admin.put(f"/admin/users/{uid}/profile", {"email": "novo@example.com"}).status_code == 200
    assert links.peek(velho, "reset") is None
    # Pela própria pessoa (confirmação por link): o mesmo.
    velho = links.issue(uid, "reset")
    tok = links.issue(uid, "email", new_email="outro@example.com")
    assert Api().post("/auth/email/confirm", {"token": tok}).status_code == 200
    assert links.peek(velho, "reset") is None


# ------------------------------------------------------------ webhooks --

def test_webhook_so_portas_https_e_eventos_conhecidos(usuario, dns):  # noqa: F811
    assert _novo(usuario, "https://hooks.example.com:22/x").status_code == 400
    assert "443" in _novo(usuario, "https://hooks.example.com:5432/x").json()["detail"]
    assert _novo(usuario, "https://hooks.example.com:8443/x").status_code == 201
    r = _novo(usuario, events=["worklog.finsh"])
    assert r.status_code == 422 and "worklog.finsh" in r.text
    assert _novo(usuario, events=["followup.dua"]).status_code == 422
    assert _novo(usuario, events=["naoexiste.*"]).status_code == 422
    assert _novo(usuario, events=["worklog.finish", "followup.*", "renewal.warning"]).status_code == 201


def test_testar_webhook_cadastrado_em_porta_antiga_e_recusado(usuario, dns, monkeypatch):  # noqa: F811
    hid = _novo(usuario).json()["id"]
    db.execute("UPDATE webhooks SET url = 'https://hooks.example.com:22/' WHERE id = %s", (hid,))
    out = usuario.post(f"/webhooks/{hid}/test").json()
    assert out["ok"] is False and "443" in out["error"]
    assert webhooks.PORTS == {443, 8443, 80}


# ----------------------------------------------------- pedido de convite --

def _pedido(**kw):
    return {"name": "Visite http://golpe.example", "email": "vitima@example.com", "source": "colega",
            "reason": "Quero registrar o suporte.", **kw}


def test_pedido_de_convite_sem_nome_no_email_e_com_teto(monkeypatch, admin, caixa):
    import app.routers.invite_requests as ir
    monkeypatch.setattr(ir.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda self: target()})())
    assert Api().post("/auth/invite-request", _pedido()).status_code == 404  # opt-in: desligado
    ligar_pedido_convite()
    assert Api().post("/auth/invite-request", _pedido()).status_code == 202
    conf = [x for x in caixa if x[0] == "vitima@example.com"]
    assert conf and "golpe" not in conf[0][1] + conf[0][2]
    # Teto global por dia (somando todos os pedidos).
    db.execute("""INSERT INTO invite_requests (name, email, source, reason)
                  SELECT 'x', 'x' || g || '@example.com', 'outro', 'teste' FROM generate_series(1, %s) g""",
               (ir.DAILY_CAP,))
    r = Api().post("/auth/invite-request", _pedido(email="mais@example.com"))
    assert r.status_code == 429 and "Retry-After" in r.headers


# ------------------------------------------------- tempo de transferida --

def test_tempo_de_quem_saiu_nao_soma_na_tarefa_transferida(admin, novo_usuario, usuario, caixa):
    x = novo_usuario("x@example.com")
    t = x.post("/worklog", {"title": "Tarefa do X"}).json()["id"]
    assert x.post(f"/worklog/{t}/time", {"minutes": 90}).status_code in (200, 201)
    r = admin.post(f"/admin/users/{uid_de(x)}/block", {"transfer_to": uid_de(usuario)})
    assert r.status_code == 200 and r.json()["transferred"]["count"] == 1
    det = usuario.get(f"/worklog/{t}").json()
    assert det["minutes"] == 0 and det["time"] == []
    board = usuario.get("/board").json()
    assert next(w for w in board["in_progress"] if w["id"] == t)["minutes"] == 0
    hoje = dia_hoje(usuario)
    csv = usuario.get(f"/export/tarefas.csv?start={hoje.replace(day=1)}&end={hoje}").text
    linha = next(x for x in csv.splitlines() if "Tarefa do X" in x)
    assert ";90;" not in linha and ",90," not in linha
    # O tempo continua no registro de quem saiu.
    assert db.query_one("SELECT sum(minutes)::int AS m FROM time_entries WHERE user_id = %s", (uid_de(x),))["m"] == 90


# ------------------------------------------------------ primeiro amanhã --

def test_primeiro_amanha_de_um_feriado_vale_no_dia_seguinte(usuario):
    hoje = dia_hoje(usuario)
    a = usuario.post("/worklog", {"title": "Escolhida"}).json()["id"]
    b = usuario.post("/worklog", {"title": "Outra"}).json()["id"]
    db.execute("UPDATE worklog_tasks SET first_on = %s WHERE id = %s", (hoje - timedelta(days=1), a))
    abertas = usuario.get("/board").json()["in_progress"]
    assert abertas[0]["id"] == a and abertas[0]["first_on"] == hoje.isoformat()
    assert next(w for w in abertas if w["id"] == b)["first_on"] is None
    # Escolha mais nova (hoje) vence a de antes.
    db.execute("UPDATE worklog_tasks SET first_on = %s WHERE id = %s", (hoje, b))
    abertas = usuario.get("/board").json()["in_progress"]
    assert abertas[0]["id"] == b and next(w for w in abertas if w["id"] == a)["first_on"] != hoje.isoformat()
    # Mais de 7 dias: não vale mais.
    db.execute("UPDATE worklog_tasks SET first_on = %s", (hoje - timedelta(days=8),))
    assert all(w["first_on"] != hoje.isoformat() for w in usuario.get("/board").json()["in_progress"])


# ------------------------------------------------ concluída e aba velha --

def test_aba_velha_nao_reabre_concluida(usuario):
    t = usuario.post("/worklog", {"title": "Feita"}).json()["id"]
    assert usuario.post(f"/worklog/{t}/finish").status_code == 200
    r = usuario.patch(f"/worklog/{t}", {"status": "blocked", "blocked_reason": "peça"})
    assert r.status_code == 409 and "concluída" in r.json()["detail"]
    assert usuario.patch(f"/worklog/{t}", {"status": "in_progress"}).status_code == 409
    assert usuario.get(f"/worklog/{t}").json()["status"] == "done"
    assert usuario.patch(f"/worklog/{t}", {"status": "todo"}).status_code == 200  # reabrir de propósito


def test_concluir_de_novo_nao_reemite(usuario):
    t = usuario.post("/worklog", {"title": "Uma vez"}).json()["id"]
    usuario.post(f"/worklog/{t}/finish")
    r = usuario.post(f"/worklog/{t}/finish")
    assert r.status_code == 200 and r.json()["existing"] is True
    assert db.query_one("SELECT count(*)::int AS n FROM audit_log WHERE action = 'worklog.finish' AND entity_id = %s",
                        (t,))["n"] == 1
    ia = Bearer(criar_chave(usuario, scope="append")["token"])
    out = texto(ia.tool("complete_task", task_id=t))
    assert out.startswith("Já estava concluída")


# --------------------------------------------------------------- bordas --

def test_bordas_de_lista_e_mensagens(usuario):
    assert usuario.get("/worklog?offset=500000000").json() == []
    assert usuario.get("/history?offset=500000000").json() == []
    hoje = dia_hoje(usuario)
    r = usuario.get(f"/worklog?from={hoje}&to={hoje - timedelta(days=3)}")
    assert r.status_code == 400
    r = usuario.get(f"/board?day={hoje + timedelta(days=2)}")
    assert r.status_code == 400 and "futuro" in r.json()["detail"]
    r = usuario.get("/worklog/999999")
    assert r.status_code == 404 and "atualize" not in r.json()["detail"]


def test_desfazer_devolucao_avisa_quem_atribuiu(admin, novo_usuario, caixa, monkeypatch):
    chefe = novo_usuario("chefe@example.com")
    _papeis(admin, chefe, ["user", "assigner"])
    marina = novo_usuario("marina@example.com")
    marina.put("/me/assignments", {"accept": True})
    monkeypatch.setattr(assign_mod, "_spawn", lambda to, mail: caixa.append((to, mail.subject, mail.text())))
    tid = chefe.post("/assign", {"user_id": uid_de(marina), "title": "Trocar o nobreak"}).json()["id"]
    assert marina.post(f"/worklog/{tid}/return", {"reason": "não é comigo"}).status_code == 200
    lapide = next(h for h in hist(marina) if h["action"] == "worklog.delete")
    caixa.clear()
    assert marina.post(f"/history/{lapide['id']}/undo").status_code == 200
    assert any(to == "chefe@example.com" and assunto.startswith("Voltou atrás") for to, assunto, _ in caixa)


# ------------------------------------------------------------------ MCP --

def test_mcp_versao_listchanged_e_instrucoes_por_escopo(usuario):
    w = Bearer(criar_chave(usuario, "w")["token"])
    a = Bearer(criar_chave(usuario, "a", scope="append")["token"])
    r = Bearer(criar_chave(usuario, "r", scope="read")["token"])
    init = lambda c: c.rpc("initialize", {"protocolVersion": "2025-06-18"}).json()["result"]  # noqa: E731
    res = init(w)
    assert res["serverInfo"]["version"] == VERSION and VERSION in res["instructions"]
    assert res["capabilities"]["tools"]["listChanged"] is True and res["capabilities"]["prompts"]["listChanged"] is True
    assert "SÓ REGISTRA" not in res["instructions"]
    assert "SÓ REGISTRA" in init(a)["instructions"] and "SÓ DE LEITURA" in init(r)["instructions"]
    nomes = lambda c: {p["name"] for p in c.rpc("prompts/list").json()["result"]["prompts"]}  # noqa: E731
    assert "fechar_dia" in nomes(w) and "fechar_dia" not in nomes(r)
    assert "error" in r.rpc("prompts/get", {"name": "fechar_dia"}).json()
    # set_recurring da chave "só registrar" sem paused_until no esquema.
    sr = next(t for t in a.rpc("tools/list").json()["result"]["tools"] if t["name"] == "set_recurring")
    assert "paused_until" not in sr["inputSchema"]["properties"]
    # Sessão antiga: ferramenta ou argumento que sumiu explica que é para reconectar.
    err = w.rpc("tools/call", {"name": "ferramenta_velha", "arguments": {}}).json()["error"]["message"]
    assert "reconect" in err
    assert "reconect" in texto(w.tool("get_today", campo_velho=1))


def test_mcp_historico_sem_pode_desfazer_na_chave_que_so_registra(usuario):
    a = Bearer(criar_chave(usuario, "a", scope="append")["token"])
    w = Bearer(criar_chave(usuario, "w")["token"])
    a.tool("create_task", title="Pela append")
    assert "[pode desfazer]" not in texto(a.tool("get_history"))
    w.tool("create_task", title="Pela write")
    assert "[pode desfazer]" in texto(w.tool("get_history"))


def test_mcp_external_ref_em_anotacao_e_tempo(usuario):
    ia = Bearer(criar_chave(usuario)["token"])
    t = usuario.post("/worklog", {"title": "Fechar"}).json()["id"]
    for _ in range(2):
        ia.tool("log_time", task_id=t, minutes=30, external_ref="fechar-1")
        ia.tool("add_note", task_id=t, text="feito", external_ref="fechar-2")
    det = usuario.get(f"/worklog/{t}").json()
    assert det["minutes"] == 30 and len(det["notes"]) == 1
    assert "nada somado" in texto(ia.tool("log_time", task_id=t, minutes=30, external_ref="fechar-1"))


def test_mcp_conclusao_no_futuro_com_a_mensagem_certa(usuario):
    ia = Bearer(criar_chave(usuario)["token"])
    hoje = dia_hoje(usuario)
    res = ia.tool("create_task", title="Futura", status="done", completed_at=(hoje + timedelta(days=30)).isoformat())
    assert res["isError"] and "conclusão no futuro" in texto(res)


# --------------------------------------------------- política e openapi --

def test_politica_de_privacidade_no_login_conta_e_convite(admin, usuario, caixa):
    assert admin.put("/admin/org", {"privacy_url": "http://inseguro.example"}).status_code == 422
    out = admin.put("/admin/org", {"privacy_url": "https://empresa.example/privacidade"}).json()
    assert out["privacy_url"] == "https://empresa.example/privacidade"
    assert Api().get("/auth/options").json()["privacy_url"] == "https://empresa.example/privacidade"
    assert usuario.get("/auth/me").json()["privacy_url"] == "https://empresa.example/privacidade"
    _pendente(admin, "conv@example.com")
    assert "https://empresa.example/privacidade" in caixa[-1][2]
    assert admin.put("/admin/org", {"privacy_url": ""}).json()["privacy_url"] is None
    assert any(h["action"] == "app.privacy_url" for h in hist(admin))


def test_openapi_declara_bearer_rotas_do_app_e_cabecalhos():
    spec = app.openapi()
    assert spec["components"]["securitySchemes"]["bearer"]["scheme"] == "bearer"
    assert spec["security"] == [{"bearer": []}]
    assert spec["info"]["version"] == VERSION
    tokens = spec["paths"]["/api/tokens"]["post"]
    assert tokens["x-session-only"] is True and tokens["security"] == []
    assert spec["paths"]["/api/auth/login"]["post"]["security"] == []
    assert "security" not in spec["paths"]["/mcp"]["post"]
    lista = spec["paths"]["/api/worklog"]["get"]["responses"]["200"]
    assert "X-Total-Count" in lista["headers"]
    assert spec["paths"]["/api/worklog"]["get"]["responses"]["429"]["$ref"].endswith("TooManyRequests")
    assert "Retry-After" in spec["components"]["responses"]["TooManyRequests"]["headers"]
