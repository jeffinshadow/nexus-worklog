"""Pequenas faltas do lado do usuário (gauntlet geral, R5): reabrir, editar
apontamento e anotação, exportações pelo período, ordem das rotinas, sair dos
outros aparelhos, chaves antigas, webhooks editáveis, descrição na atribuição."""
from datetime import timedelta

from app import db
from app.services import app_today
from conftest import SENHA_PADRAO, Api
from test_api_aberta import _novo, dns  # noqa: F401 — dns é fixture
from test_admin_gauntlet import _linha, _mandar, caixa, par  # noqa: F401 — caixa e par são fixtures


def _tarefa(u, **extra):
    r = u.post("/worklog", {"title": "Trocar disjuntor", **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _ultimo(u, entity, eid):
    return u.get(f"/history?limit=1&entity={entity}&entity_id={eid}").json()[0]


# ------------------------------------------------------------------ reabrir --

def test_reabrir_concluida_e_desfazer(usuario):
    tid = _tarefa(usuario)
    assert usuario.post(f"/worklog/{tid}/finish", {"resolution": "trocado"}).status_code == 200
    antes = usuario.get(f"/worklog/{tid}").json()
    assert usuario.patch(f"/worklog/{tid}", {"status": "todo"}).status_code == 200
    t = usuario.get(f"/worklog/{tid}").json()
    assert t["status"] == "todo" and t["completed_at"] is None
    h = _ultimo(usuario, "worklog", tid)
    assert h["summary"].startswith("reabriu a tarefa") and h["can_undo"]
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    t = usuario.get(f"/worklog/{tid}").json()
    assert t["status"] == "done" and t["completed_at"] == antes["completed_at"] and t["resolution"] == "trocado"


# ------------------------------------------------- corrigir tempo e anotação --

def test_corrigir_apontamento(usuario):
    tid = _tarefa(usuario)
    e = usuario.post(f"/worklog/{tid}/time", {"minutes": 90, "note": "visita"}).json()
    r = usuario.patch(f"/time/{e['id']}", {"minutes": 180})
    assert r.status_code == 200 and r.json()["minutes"] == 180 and r.json()["note"] == "visita"
    assert usuario.get(f"/worklog/{tid}").json()["minutes"] == 180
    h = _ultimo(usuario, "time", e["id"])
    assert "corrigiu um apontamento" in h["summary"] and "1h30 → 3h" in h["summary"] and h["can_undo"]
    # tirar a observação (null) e mudar o dia
    ontem = str(app_today() - timedelta(days=1))
    r = usuario.patch(f"/time/{e['id']}", {"note": None, "day": ontem})
    assert r.status_code == 200 and r.json()["note"] is None and str(r.json()["day"]) == ontem
    # desfazer volta o último passo
    h = _ultimo(usuario, "time", e["id"])
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    row = db.query_one("SELECT minutes, note FROM time_entries WHERE id = %s", (e["id"],))
    assert row == {"minutes": 180, "note": "visita"}


def test_corrigir_apontamento_valida_como_o_lancamento(usuario):
    tid = _tarefa(usuario)
    a = usuario.post(f"/worklog/{tid}/time", {"minutes": 600}).json()
    usuario.post(f"/worklog/{tid}/time", {"minutes": 600})
    # 600 + 600 = 20 h; passar este para 900 daria 25 h no dia
    r = usuario.patch(f"/time/{a['id']}", {"minutes": 900})
    assert r.status_code == 400 and "24 h" in r.json()["detail"]
    # para 840 cabe (o próprio apontamento não conta duas vezes)
    assert usuario.patch(f"/time/{a['id']}", {"minutes": 840}).status_code == 200
    assert usuario.patch(f"/time/{a['id']}", {"day": "2999-01-01"}).status_code == 400
    assert usuario.patch(f"/time/{a['id']}", {"minutes": 0}).status_code == 422
    assert usuario.patch("/time/999999", {"minutes": 10}).status_code == 404


def test_corrigir_anotacao_mantem_a_hora(usuario):
    tid = _tarefa(usuario)
    n = usuario.post(f"/worklog/{tid}/notes", {"body": "trocado o disjunotr"}).json()
    r = usuario.patch(f"/notes/{n['id']}", {"body": "  trocado o disjuntor  "})
    assert r.status_code == 200 and r.json()["body"] == "trocado o disjuntor"
    assert r.json()["created_at"] == n["created_at"]
    assert usuario.patch(f"/notes/{n['id']}", {"body": "   "}).status_code == 422
    h = _ultimo(usuario, "note", n["id"])
    assert h["summary"].startswith("editou uma anotação") and h["can_undo"]
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert usuario.get(f"/worklog/{tid}").json()["notes"][0]["body"] == "trocado o disjunotr"


def test_nao_corrige_tempo_nem_anotacao_de_outra_pessoa(usuario, novo_usuario):
    outra = novo_usuario("outra@example.com")
    tid = _tarefa(usuario)
    e = usuario.post(f"/worklog/{tid}/time", {"minutes": 30}).json()
    n = usuario.post(f"/worklog/{tid}/notes", {"body": "minha"}).json()
    assert outra.patch(f"/time/{e['id']}", {"minutes": 60}).status_code == 404
    assert outra.patch(f"/notes/{n['id']}", {"body": "dela"}).status_code == 404
    assert db.query_one("SELECT minutes FROM time_entries WHERE id = %s", (e["id"],))["minutes"] == 30
    assert db.query_one("SELECT body FROM task_notes WHERE id = %s", (n["id"],))["body"] == "minha"


# --------------------------------------------------------- texto do checklist --

def test_corrigir_texto_do_item_fica_no_lugar(usuario, novo_usuario):
    tid = _tarefa(usuario)
    a = usuario.post(f"/worklog/{tid}/checklist", {"label": "Deligar o disjuntor"}).json()
    usuario.post(f"/worklog/{tid}/checklist", {"label": "Testar"})
    r = usuario.patch(f"/checklist/{a['id']}", {"label": "Desligar o disjuntor"})
    assert r.status_code == 200 and r.json()["label"] == "Desligar o disjuntor" and r.json()["done"] is False
    assert [c["label"] for c in usuario.get(f"/worklog/{tid}").json()["checklist"]] == ["Desligar o disjuntor", "Testar"]
    h = _ultimo(usuario, "checklist", a["id"])
    assert h["summary"].startswith("editou o item") and h["can_undo"]
    assert novo_usuario("outra@example.com").patch(f"/checklist/{a['id']}", {"label": "x"}).status_code == 404
    assert usuario.patch(f"/checklist/{a['id']}", {"label": ""}).status_code == 422


# ------------------------------------------------------ exportar pelo período --

def _linhas(r):
    assert r.status_code == 200, r.text
    return [l.split(";") for l in r.content.decode("utf-8-sig").strip().split("\r\n")]


def test_exportar_tempo_e_tarefas_pelo_periodo(usuario):
    hoje = app_today()
    antiga, nova = _tarefa(usuario, title="Antiga"), _tarefa(usuario, title="Nova")
    usuario.post(f"/worklog/{antiga}/time", {"minutes": 60, "day": str(hoje - timedelta(days=40))})
    usuario.post(f"/worklog/{nova}/time", {"minutes": 30})
    # a antiga foi concluída há 35 dias (antes do período)
    db.execute("UPDATE worklog_tasks SET status = 'done', created_at = now() - interval '45 days', "
               "completed_at = now() - interval '35 days' WHERE id = %s", (antiga,))
    q = f"?start={hoje - timedelta(days=7)}&end={hoje}"
    tempo = _linhas(usuario.get("/export/apontamentos.csv" + q))
    assert len(tempo) == 2 and tempo[1][1] == "30"
    r = usuario.get("/export/apontamentos.csv" + q)
    assert f"nexus-apontamentos-{hoje - timedelta(days=7)}-a-{hoje}.csv" in r.headers["content-disposition"]
    tarefas = _linhas(usuario.get("/export/tarefas.csv" + q))
    assert tarefas[0][-2:] == ["minutos_no_periodo", "horas_no_periodo"]
    assert [t[1] for t in tarefas[1:]] == ["Nova"] and tarefas[1][-2] == "30"
    # sem período: tudo, como antes (sem as colunas do período)
    assert len(_linhas(usuario.get("/export/apontamentos.csv"))) == 3
    tudo = _linhas(usuario.get("/export/tarefas.csv"))
    assert len(tudo) == 3 and tudo[0][-1] == "como_resolveu"
    # período pela metade ou invertido
    assert usuario.get(f"/export/tarefas.csv?start={hoje}").status_code == 400
    assert usuario.get(f"/export/apontamentos.csv?start={hoje}&end={hoje - timedelta(days=1)}").status_code == 400


# --------------------------------------------------------- ordem das rotinas --

def _rotina(u, label):
    r = u.post("/recurring", {"label": label})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _ordem(u):
    return [r["label"] for r in u.get("/board").json()["recurring"]]


def test_ordem_das_rotinas_com_desfazer(usuario, novo_usuario):
    a, b, c = (_rotina(usuario, x) for x in ("Abrir a loja", "Ar-condicionado", "Câmeras"))
    assert usuario.post("/recurring/order", {"ids": [c, a, b]}).json() == {"ok": True}
    assert _ordem(usuario) == ["Câmeras", "Abrir a loja", "Ar-condicionado"]
    # lista parcial: a que faltou fica depois, na ordem que tinha
    assert usuario.post("/recurring/order", {"ids": [b]}).status_code == 200
    assert _ordem(usuario) == ["Ar-condicionado", "Câmeras", "Abrir a loja"]
    # nova entra no fim
    _rotina(usuario, "Fechar")
    assert _ordem(usuario)[-1] == "Fechar"
    h = usuario.get("/history?limit=1&entity=recurring_order").json()[0]
    assert h["summary"] == "mudou a ordem das rotinas" and h["can_undo"]
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert _ordem(usuario) == ["Câmeras", "Abrir a loja", "Ar-condicionado", "Fechar"]
    # repetida, de outra pessoa ou excluída: recusa
    assert usuario.post("/recurring/order", {"ids": [a, a]}).status_code == 400
    outra = novo_usuario("outra@example.com")
    x = _rotina(outra, "Dela")
    assert usuario.post("/recurring/order", {"ids": [x, a]}).status_code == 400
    assert outra.post("/recurring/order", {"ids": [a]}).status_code == 400
    usuario.delete(f"/recurring/{c}")
    assert usuario.post("/recurring/order", {"ids": [c, a]}).status_code == 400
    # trocar a agenda (vira outra rotina) mantém o lugar
    usuario.post("/recurring/order", {"ids": [b, a]})
    db.execute("UPDATE recurring_tasks SET created_at = now() - interval '3 days' WHERE id = %s", (a,))
    usuario.post(f"/recurring/{a}/toggle", {"done": True, "day": str(app_today() - timedelta(days=1))})
    assert usuario.patch(f"/recurring/{a}", {"label": "Abrir a loja", "freq": "weekly", "weekdays": 62}).status_code == 200
    assert _ordem(usuario)[:2] == ["Ar-condicionado", "Abrir a loja"]


# ------------------------------------------------- sair dos outros aparelhos --

def test_sair_dos_outros_aparelhos_sem_trocar_a_senha(usuario, novo_usuario):
    email = usuario.me["email"]
    antes = usuario.get("/auth/sessions").json()["others"]  # a do 1º acesso (senha temporária) também conta
    celular, notebook = Api(), Api()
    celular.login(email, SENHA_PADRAO)
    notebook.login(email, SENHA_PADRAO)
    outra = novo_usuario("outra@example.com")
    chave = usuario.post("/tokens", {"name": "IA"}).json()
    assert usuario.get("/auth/sessions").json() == {"others": antes + 2}
    r = usuario.post("/auth/logout-others")
    assert r.status_code == 200 and r.json() == {"ok": True, "ended": antes + 2}
    assert usuario.get("/auth/me").status_code == 200          # este continua
    assert celular.get("/auth/me").status_code == 401           # os outros saíram
    assert notebook.get("/auth/me").status_code == 401
    assert outra.get("/auth/me").status_code == 200             # outra pessoa: nada muda
    assert usuario.get("/auth/sessions").json() == {"others": 0}
    # a senha e a chave de API continuam valendo
    assert Api().login(email, SENHA_PADRAO).status_code == 200
    from conftest import Bearer
    assert Bearer(chave["token"]).get("/worklog").status_code == 200
    assert usuario.get("/history?limit=5").json()[0]["summary"] == "saiu dos outros aparelhos"
    # sem CSRF não sai; por chave de API, nem lista
    assert usuario.c.post("/api/auth/logout-others").status_code == 403
    assert Bearer(chave["token"]).get("/auth/sessions").status_code in (401, 403)


# ------------------------------------------------------------ chaves antigas --

def test_renovar_chave_vencida(usuario, novo_usuario):
    from conftest import Bearer
    k = usuario.post("/tokens", {"name": "IA", "expires_in_days": 30}).json()
    db.execute("UPDATE api_tokens SET expires_at = now() - interval '1 day' WHERE id = %s", (k["id"],))
    assert Bearer(k["token"]).get("/worklog").status_code == 401
    r = usuario.post(f"/tokens/{k['id']}/renew", {"expires_in_days": 90})
    assert r.status_code == 200 and r.json()["active"] is True
    assert Bearer(k["token"]).get("/worklog").status_code == 200       # a mesma chave volta
    lista = {t["id"]: t for t in usuario.get("/tokens").json()}
    assert lista[k["id"]]["active"]
    assert usuario.get("/history?limit=1&entity=token").json()[0]["summary"].startswith("renovou a validade")
    # revogada não volta; de outra pessoa, nem se vê; uma chave não renova chave
    assert usuario.delete(f"/tokens/{k['id']}").status_code == 200
    assert usuario.post(f"/tokens/{k['id']}/renew", {"expires_in_days": 90}).status_code == 404
    k2 = usuario.post("/tokens", {"name": "Outra"}).json()
    assert novo_usuario("outra@example.com").post(f"/tokens/{k2['id']}/renew", {}).status_code == 404
    assert Bearer(k2["token"]).post(f"/tokens/{k2['id']}/renew", {}).status_code in (401, 403)
    assert usuario.post(f"/tokens/{k2['id']}/renew", {"expires_in_days": 0}).status_code == 422


# ------------------------------------------------------------ editar webhook --

def test_editar_webhook_mantem_o_segredo(usuario, dns, novo_usuario):
    from app import webhooks
    w = _novo(usuario, events=["worklog.finish"]).json()
    salt = db.query_one("SELECT secret_salt FROM webhooks WHERE id = %s", (w["id"],))["secret_salt"]
    r = usuario.patch(f"/webhooks/{w['id']}", {"events": ["worklog.*", "note.*", "note.*"]})
    assert r.status_code == 200 and r.json()["events"] == ["note.*", "worklog.*"]
    r = usuario.patch(f"/webhooks/{w['id']}", {"url": "https://hooks.example.com/outro"})
    assert r.status_code == 200 and r.json()["url"] == "https://hooks.example.com/outro"
    row = db.query_one("SELECT secret_salt, events FROM webhooks WHERE id = %s", (w["id"],))
    assert row["secret_salt"] == salt and webhooks.secret_for(row["secret_salt"]) == w["secret"]
    assert usuario.get("/history?limit=1&entity=webhook").json()[0]["summary"].startswith("editou o webhook")
    # a mesma checagem do cadastro: rede interna, http, eventos inválidos
    for url in ("http://hooks.example.com/x", "https://interno.example.com/x", "https://127.0.0.1/x"):
        assert usuario.patch(f"/webhooks/{w['id']}", {"url": url}).status_code == 400, url
    assert usuario.patch(f"/webhooks/{w['id']}", {"events": ["tudo"]}).status_code == 422
    assert usuario.patch(f"/webhooks/{w['id']}", {"events": []}).status_code == 422
    assert db.query_one("SELECT url FROM webhooks WHERE id = %s", (w["id"],))["url"] == "https://hooks.example.com/outro"
    # de outra pessoa não; por chave de API não
    assert novo_usuario("outra@example.com").patch(f"/webhooks/{w['id']}", {"events": ["*"]}).status_code == 404
    from conftest import Bearer
    k = usuario.post("/tokens", {"name": "IA"}).json()
    assert Bearer(k["token"]).patch(f"/webhooks/{w['id']}", {"events": ["*"]}).status_code in (401, 403)


# ------------------------------------------------ atribuir: descrição longa --

def test_atribuir_descricao_em_linhas_e_alterar_a_descricao(par, caixa):
    chefe, marina = par
    desc = "Sala 2, rack da esquerda.\nDesligar antes o servidor de arquivos.\nLevar a escada."
    tid = _mandar(chefe, marina, description=desc)
    assert marina.get(f"/worklog/{tid}").json()["description"] == desc
    assert _linha(chefe, tid)["description"] == desc
    caixa.clear()
    r = chefe.patch(f"/assign/{tid}", {"description": "  Sala 3, não a 2.  "})
    assert r.status_code == 200 and r.json()["description"] == "Sala 3, não a 2."
    assert marina.get(f"/worklog/{tid}").json()["description"] == "Sala 3, não a 2."
    assert caixa and caixa[-1][0] == "marina@example.com"
    # null tira; mais de 300 não
    assert chefe.patch(f"/assign/{tid}", {"description": None}).status_code == 200
    assert marina.get(f"/worklog/{tid}").json()["description"] is None
    assert chefe.patch(f"/assign/{tid}", {"description": "x" * 301}).status_code == 422
    # quem recebeu mudou a descrição: quem atribuiu não grava por cima
    marina.patch(f"/worklog/{tid}", {"description": "do jeito dela"})
    r = chefe.patch(f"/assign/{tid}", {"description": "outra"})
    assert r.status_code == 409 and "a descrição" in r.json()["detail"]
    assert marina.get(f"/worklog/{tid}").json()["description"] == "do jeito dela"
