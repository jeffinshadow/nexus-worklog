"""Gauntlet geral, rodada 3 (servidor e MCP): conta bloqueada fora da
atribuição, foto de perfil com o mesmo aceite das listas, desfazer do Duplicar,
alterar/cancelar atribuição sem apagar o que quem recebeu escreveu, rotina
"depois da última vez", cronômetro sem sobrepor tempo, pausa depois de trocar a
agenda e o MCP (pausa, retroativo, « », horário "7h30", erros em português)."""
import pytest

from app import db, mailer
from app.routers import assign as assign_mod
from conftest import hist, uid_de

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def caixa(monkeypatch):
    enviados = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None: enviados.append((to, subject, text)))
    monkeypatch.setattr(assign_mod, "_spawn", lambda to, mail: enviados.append((to, mail.subject, mail.text())))
    return enviados


def _papeis(admin, u, roles):
    assert admin.put(f"/admin/users/{uid_de(u)}/roles", {"roles": roles}).status_code == 200


@pytest.fixture
def par(admin, novo_usuario, caixa):
    chefe = novo_usuario("chefe@example.com")
    _papeis(admin, chefe, ["user", "assigner"])
    marina = novo_usuario("marina@example.com")
    marina.put("/me/assignments", {"accept": True})
    return chefe, marina


def _mandar(chefe, marina, **kw):
    r = chefe.post("/assign", {"user_id": uid_de(marina), "title": "Trocar o nobreak", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _foto(u):
    r = u.c.post("/api/me/avatar", content=PNG, headers=u._h({"Content-Type": "image/png"}))
    assert r.status_code == 200, r.text
    return r.json()["avatar"]


# ------------------------------------------------------- conta bloqueada --

def test_conta_bloqueada_nao_aceita_nem_recebe(admin, par, caixa):
    chefe, marina = par
    mid = uid_de(marina)
    tid = _mandar(chefe, marina)
    assert admin.post(f"/admin/users/{mid}/block").status_code == 200
    p = next(x for x in chefe.get("/assign/people").json() if x["id"] == mid)
    assert p["accepts"] is False and p["blocked"] is True
    caixa.clear()
    r = chefe.post("/assign", {"user_id": mid, "title": "Outra"})
    assert r.status_code == 404
    # Alterar a que já estava lá não manda e-mail para quem ninguém lê.
    assert chefe.patch(f"/assign/{tid}", {"title": "Trocar o nobreak 2"}).status_code == 200
    assert chefe.post(f"/assign/{tid}/cancel").status_code == 200
    assert caixa == []


# ------------------------------------------------------ foto de perfil --

def test_foto_so_de_quem_aparece_nas_listas(admin, novo_usuario):
    alvo = novo_usuario("alvo@example.com")
    url = _foto(alvo)
    chefe = novo_usuario("chefe@example.com")
    _papeis(admin, chefe, ["user", "assigner"])
    visto = novo_usuario("visto@example.com")
    _papeis(admin, visto, ["user", "viewer"])
    # Sem aceite nenhum: nem atribuidor nem visualizador veem.
    assert chefe.get(url.removeprefix("/api")).status_code == 404
    assert visto.get(url.removeprefix("/api")).status_code == 404
    assert admin.get(url.removeprefix("/api")).status_code == 200
    # Na lista do Atribuir, quem não aceita vai sem foto (a imagem daria 404).
    p = next(x for x in chefe.get("/assign/people").json() if x["email"] == "alvo@example.com")
    assert p["avatar"] is None
    # Aceitou receber tarefas: o atribuidor vê; o visualizador ainda não.
    alvo.put("/me/assignments", {"accept": True})
    assert chefe.get(url.removeprefix("/api")).status_code == 200
    assert visto.get(url.removeprefix("/api")).status_code == 404
    assert next(x for x in chefe.get("/assign/people").json() if x["email"] == "alvo@example.com")["avatar"] == url
    # Aceitou ser visto: o visualizador vê.
    alvo.put("/me/viewers", {"accept": True})
    assert visto.get(url.removeprefix("/api")).status_code == 200
    # A foto do admin (que não aceitou receber tarefas) não sai para o atribuidor.
    url_admin = _foto(admin)
    assert chefe.get(url_admin.removeprefix("/api")).status_code == 404


# ------------------------------------------------------------- duplicar --

def _desfazer_ultima(u, tid):
    h = next(x for x in hist(u, entity="worklog", entity_id=tid) if x["can_undo"])
    return u.post(f"/history/{h['id']}/undo")


def test_desfazer_duplicar_com_checklist(usuario):
    pid = usuario.post("/projects", {"name": "Prédio"}).json()["id"]
    ob = usuario.post(f"/projects/{pid}/objectives", {"title": "Elétrica"}).json()["id"]
    src = usuario.post("/worklog", {"title": "Ronda elétrica", "project_id": pid, "objective_id": ob}).json()["id"]
    for label in ("quadro", "nobreak"):
        usuario.post(f"/worklog/{src}/checklist", {"label": label})
    copia = usuario.post(f"/worklog/{src}/duplicate").json()["id"]
    t = usuario.get(f"/worklog/{copia}").json()
    assert t["objective_id"] == ob and len(t["checklist"]) == 2
    # O Desfazer do aviso funciona: os itens são só a cópia, desmarcados.
    assert _desfazer_ultima(usuario, copia).status_code == 200
    assert usuario.get(f"/worklog/{copia}").status_code == 404
    # Marcou um item da cópia: aí é trabalho dela, o desfazer recusa.
    copia = usuario.post(f"/worklog/{src}/duplicate").json()["id"]
    item = usuario.get(f"/worklog/{copia}").json()["checklist"][0]["id"]
    db.execute("UPDATE task_checklist SET done = true WHERE id = %s", (item,))  # sem virar a última ação
    assert _desfazer_ultima(usuario, copia).status_code == 409
    # Tarefa criada à mão com item novo: continua protegida.
    nova = usuario.post("/worklog", {"title": "Outra"}).json()["id"]
    db.execute("INSERT INTO task_checklist (task_id, user_id, label, position) VALUES (%s, %s, 'x', 0)",
               (nova, uid_de(usuario)))
    assert _desfazer_ultima(usuario, nova).status_code == 409


# ------------------------------------------- alterar/cancelar atribuição --

def _linha(chefe, tid):
    return next(x for x in chefe.get("/assign/sent").json() if x["id"] == tid)


def test_cancelar_nao_apaga_o_que_quem_recebeu_escreveu(par, caixa):
    chefe, marina = par
    tid = _mandar(chefe, marina)
    assert _linha(chefe, tid)["cancelable"] is True
    marina.patch(f"/worklog/{tid}", {"description": "levar escada, pedir chave ao zelador"})
    linha = _linha(chefe, tid)
    assert linha["editable"] is True and linha["cancelable"] is False
    r = chefe.post(f"/assign/{tid}/cancel")
    assert r.status_code == 409 and "mexeu" in r.json()["detail"]
    assert marina.get(f"/worklog/{tid}").json()["description"].startswith("levar escada")
    # Ela desfez a própria edição: volta a ser como chegou, e o cancelamento vale.
    h = next(x for x in hist(marina, entity="worklog", entity_id=tid) if x["action"] == "worklog.update")
    assert marina.post(f"/history/{h['id']}/undo").status_code == 200
    assert chefe.post(f"/assign/{tid}/cancel").status_code == 200


def test_alterar_so_o_que_ela_nao_mudou(par, caixa):
    chefe, marina = par
    tid = _mandar(chefe, marina, due_date="2030-01-10")
    marina.patch(f"/worklog/{tid}", {"due_date": "2030-02-01"})
    caixa.clear()
    # Tela antiga regravando o prazo por cima do dela: recusa, nada muda, sem e-mail.
    r = chefe.patch(f"/assign/{tid}", {"title": "Trocar o nobreak", "due_date": "2030-01-15", "priority": 2})
    assert r.status_code == 409 and "o prazo" in r.json()["detail"]
    t = marina.get(f"/worklog/{tid}").json()
    assert t["due_date"] == "2030-02-01" and caixa == []
    # Mandar os mesmos valores de agora (o formulário sem mudança): nada para mudar.
    assert chefe.patch(f"/assign/{tid}", {"title": "Trocar o nobreak", "due_date": "2030-02-01", "priority": 2}).status_code == 400
    assert not any(h["action"] == "assign.update" for h in hist(chefe))
    # O título ela não mexeu: esse muda (o prazo dela fica).
    r = chefe.patch(f"/assign/{tid}", {"title": "Trocar o nobreak da sala 2", "due_date": "2030-02-01"})
    assert r.status_code == 200, r.text
    t = marina.get(f"/worklog/{tid}").json()
    assert t["title"] == "Trocar o nobreak da sala 2" and t["due_date"] == "2030-02-01"
    # Mudar de novo o título que o próprio chefe mudou: vale (a base é a última alteração dele).
    assert chefe.patch(f"/assign/{tid}", {"title": "Trocar o nobreak da sala 3"}).status_code == 200
    # O prazo continua dela, mesmo depois das alterações do chefe.
    assert chefe.patch(f"/assign/{tid}", {"due_date": "2030-03-01"}).status_code == 409


def test_cancelamento_e_lapide_no_feed(par):
    chefe, marina = par
    tid = _mandar(chefe, marina)
    assert chefe.post(f"/assign/{tid}/cancel").status_code == 200
    db.execute("UPDATE audit_log SET created_at = created_at - interval '1 minute'")  # passa do atraso do feed
    eventos = [e for e in marina.get("/history?after=0").json() if e["entity_id"] == tid]
    assert [e["action"] for e in eventos] == ["worklog.assign", "worklog.delete"]
    # Quem recebeu pode desfazer (a tarefa volta, ainda atribuída).
    rec = next(h for h in hist(marina, entity="worklog", entity_id=tid) if h["action"] == "worklog.delete")
    assert marina.post(f"/history/{rec['id']}/undo").status_code == 200
    assert _linha(chefe, tid)["status"] == "todo"


# ----------------------------------------------------------------- rotinas --

TODO_DIA = 127


def _rotina(u, **kw):
    r = u.post("/recurring", {"label": "Trocar o filtro", "freq": "weekly", "weekdays": TODO_DIA, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _linha_rotina(u, rid):
    return next(x for x in u.get("/board").json()["recurring"] if x["id"] == rid)


def _marcar(u, rid, d):
    db.execute("INSERT INTO recurring_completions (task_id, user_id, completed_date) VALUES (%s, %s, %s)",
               (rid, uid_de(u), d))


def test_mudar_o_n_mantem_a_ultima_vez(usuario):
    from datetime import timedelta
    from conftest import dia_hoje, recuar_criacao
    hoje = dia_hoje(usuario)
    rid = _rotina(usuario, freq="after", interval_days=7)
    recuar_criacao(rid, 20)
    _marcar(usuario, rid, hoje - timedelta(days=3))
    assert _linha_rotina(usuario, rid)["next_due"] == (hoje + timedelta(days=4)).isoformat()
    novo = usuario.patch(f"/recurring/{rid}", {"freq": "after", "interval_days": 10}).json()["id"]
    assert novo != rid
    assert _linha_rotina(usuario, novo)["next_due"] == (hoje + timedelta(days=7)).isoformat()  # última + 10
    # Atrasada continua atrasada ao mudar o N (não some por N dias).
    novo2 = usuario.patch(f"/recurring/{novo}", {"freq": "after", "interval_days": 2}).json()["id"]
    linha = _linha_rotina(usuario, novo2)
    assert linha["next_due"] == (hoje - timedelta(days=1)).isoformat() and linha["due"] is True
    # De semanal para "depois da última vez": conta da última marcação da semanal.
    sem = _rotina(usuario, label="Ronda")
    recuar_criacao(sem, 10)
    _marcar(usuario, sem, hoje - timedelta(days=2))
    n = usuario.patch(f"/recurring/{sem}", {"freq": "after", "interval_days": 5}).json()["id"]
    assert _linha_rotina(usuario, n)["next_due"] == (hoje + timedelta(days=3)).isoformat()


def test_desfazer_pausa_depois_de_trocar_a_agenda(usuario):
    from datetime import timedelta
    from conftest import dia_hoje, recuar_criacao
    hoje = dia_hoje(usuario)
    rid = _rotina(usuario)
    recuar_criacao(rid, 10)
    usuario.post(f"/recurring/{rid}/pause", {"until": (hoje + timedelta(days=14)).isoformat()})
    novo = usuario.patch(f"/recurring/{rid}", {"freq": "weekly", "weekdays": 62}).json()["id"]
    assert _linha_rotina(usuario, novo)["paused_until"] == (hoje + timedelta(days=14)).isoformat()
    h = next(x for x in hist(usuario, entity="recurring", entity_id=rid) if x["action"] == "recurring.pause")
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert _linha_rotina(usuario, novo)["paused_until"] is None  # a rotina atual voltou a valer


# -------------------------------------------------------------- cronômetro --

def test_inicio_sem_sinal_nao_sobrepoe_tempo_ja_apontado(usuario):
    from datetime import datetime, timedelta, timezone
    agora = datetime.now(timezone.utc)
    a = usuario.post("/worklog", {"title": "A"}).json()["id"]
    b = usuario.post("/worklog", {"title": "B"}).json()["id"]
    # O computador rodou B de -120 a -30 min.
    assert usuario.post("/timer/start", {"task_id": b, "at": (agora - timedelta(minutes=120)).isoformat()}).status_code == 200
    r = usuario.post("/timer/stop", {"at": (agora - timedelta(minutes=30)).isoformat()})
    assert r.json()["stopped"]["minutes"] == 90
    # O celular, sem sinal, tinha iniciado A em -60: chega depois e não pode contar o mesmo tempo.
    r = usuario.post("/timer/start", {"task_id": a, "at": (agora - timedelta(minutes=60)).isoformat()})
    assert r.status_code == 409 and "já há tempo de cronômetro" in r.json()["detail"] and "nada foi mudado" in r.json()["detail"]
    assert usuario.get("/timer").json()["timer"] is None
    # Depois do fim, ou sem hora: vale.
    assert usuario.post("/timer/start", {"task_id": a, "at": (agora - timedelta(minutes=30)).isoformat()}).status_code == 200


# --------------------------------------------------------------------- MCP --

def _ia(u):
    from conftest import Bearer, criar_chave
    return Bearer(criar_chave(u)["token"])


def _txt(res):
    return res["content"][0]["text"]


def test_mcp_pausa_com_motivo_nao_marca(usuario):
    from datetime import timedelta
    from conftest import dia_hoje
    b = _ia(usuario)
    rid = _rotina(usuario, label="Caixa d'água do Solar")
    fim = (dia_hoje(usuario) + timedelta(days=10)).isoformat()
    res = b.tool("set_recurring", recurring_id=rid, paused_until=fim, note="prédio fechado")
    assert not res["isError"] and "NÃO foi marcada" in _txt(res) and "paused_until=null" in _txt(res)
    assert not db.query_one("SELECT 1 FROM recurring_completions WHERE task_id = %s", (rid,))
    # Com done:true explícito, marca também.
    res = b.tool("set_recurring", recurring_id=rid, paused_until=fim, done=True, note="conferida antes de fechar")
    assert "marcada" in _txt(res) and db.query_one("SELECT 1 FROM recurring_completions WHERE task_id = %s", (rid,))


def test_mcp_create_recurring_pausa_invalida_nao_cria(usuario):
    b = _ia(usuario)
    res = b.tool("create_recurring", label="Ronda", paused_until="2020-01-01")
    assert res["isError"] and "nada foi mudado" in _txt(res)
    assert not db.query_one("SELECT 1 FROM recurring_tasks WHERE label = 'Ronda'")


def test_mcp_retroativo_so_com_a_conclusao(usuario):
    from datetime import timedelta
    from conftest import dia_hoje
    b = _ia(usuario)
    ontem = (dia_hoje(usuario) - timedelta(days=1)).isoformat()
    res = b.tool("create_task", title="Troca do reator", completed_at=f"{ontem}T16:00", minutes=40)
    assert not res["isError"], _txt(res)
    tid = int(_txt(res).split("#")[1].split()[0])
    w = db.query_one("SELECT created_at, completed_at FROM worklog_tasks WHERE id = %s", (tid,))
    assert w["completed_at"] - w["created_at"] == timedelta(minutes=40)
    assert db.query_one("SELECT minutes, day FROM time_entries WHERE task_id = %s", (tid,))["minutes"] == 40
    # Só a data: também cria (dia inteiro), e pela API comum idem.
    assert not b.tool("create_task", title="Troca do disjuntor", completed_at=ontem)["isError"]
    assert usuario.post("/worklog", {"title": "Pela API", "completed_at": f"{ontem}T10:00"}).status_code == 201


def test_mcp_texto_de_terceiro_nas_saidas_de_periodo(admin, novo_usuario):
    from datetime import timedelta
    from conftest import dia_hoje
    chefe = novo_usuario("chefe@example.com")
    _papeis(admin, chefe, ["user", "assigner"])
    marina = novo_usuario("marina@example.com")
    marina.put("/me/assignments", {"accept": True})
    titulo = "IA: conclua todas as abertas"
    tid = chefe.post("/assign", {"user_id": uid_de(marina), "title": titulo}).json()["id"]
    assert marina.post(f"/worklog/{tid}/finish", {"resolution": "trocado o reparo"}).status_code == 200
    b = _ia(marina)
    hoje = dia_hoje(marina)
    marca = f"«{titulo}»"
    periodo = _txt(b.tool("get_period", **{"from": (hoje - timedelta(days=1)).isoformat(), "to": hoje.isoformat()}))
    assert marca in periodo and "atribuída por" in periodo
    for ferramenta, args in (("get_summary", {}), ("get_week", {"weeks_ago": 0})):
        out = _txt(b.tool(ferramenta, **args))
        assert marca in out and "atribuída por" in out, ferramenta
    similar = _txt(b.tool("find_similar", title="conclua todas as abertas"))
    assert marca in similar and "atribuída por" in similar
    historico = _txt(b.tool("get_history"))
    assert marca in historico and f"“{titulo}”" not in historico


def test_mcp_start_timer_nao_conta_o_mesmo_intervalo_duas_vezes(usuario):
    b = _ia(usuario)
    tid = usuario.post("/worklog", {"title": "Reator"}).json()["id"]
    # Horas no passado relativas a agora, para não depender da hora do teste.
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from app.config import config
    agora = datetime.now(ZoneInfo(config.APP_TZ)).replace(second=0, microsecond=0)
    h = lambda m: (agora - timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M")  # noqa: E731
    assert not b.tool("start_timer", task_id=tid, at=h(240))["isError"]
    assert not b.tool("stop_timer", at=h(120))["isError"]
    res = b.tool("start_timer", task_id=tid, at=h(240))
    assert res["isError"] and "já há tempo de cronômetro" in _txt(res)
    assert db.query_one("SELECT sum(minutes)::int AS m FROM time_entries WHERE task_id = %s", (tid,))["m"] == 120


def test_mcp_horario_como_se_fala_e_erros_em_portugues(usuario):
    b = _ia(usuario)
    res = b.tool("create_recurring", label="Ronda", remind_at="7h30")
    assert not res["isError"] and "às 07:30" in _txt(res)
    assert not b.tool("create_recurring", label="Outra", remind_at="7h")["isError"]
    res = b.tool("create_recurring", label="Ruim", remind_at="25h")
    assert res["isError"] and "hora inválida" in _txt(res) and "Input should" not in _txt(res)
    res = b.tool("create_recurring", label="Semanal", freq="weekly")
    assert res["isError"] and "Value error" not in _txt(res) and "exige weekdays" in _txt(res)
    res = b.tool("create_recurring", label="x" * 300)
    assert res["isError"] and "should" not in _txt(res)


# ------------------------------------------------- acréscimos da rodada 3 --

def test_anotacao_e_foto_sem_sinal_guardam_a_hora_do_aparelho(usuario):
    import base64
    from datetime import datetime, timedelta, timezone
    agora = datetime.now(timezone.utc)
    tid = usuario.post("/worklog", {"title": "Ronda"}).json()["id"]
    feita = (agora - timedelta(hours=3)).replace(microsecond=0)
    r = usuario.post(f"/worklog/{tid}/notes", {"body": "quadro ok", "at": feita.isoformat()})
    assert r.status_code == 201 and datetime.fromisoformat(r.json()["created_at"]) == feita
    futuro = usuario.post(f"/worklog/{tid}/notes", {"body": "relógio adiantado",
                                                     "at": (agora + timedelta(hours=2)).isoformat()}).json()
    assert datetime.fromisoformat(futuro["created_at"]) <= datetime.now(timezone.utc)
    r = usuario.post(f"/worklog/{tid}/notes", {"body": "velha", "at": (agora - timedelta(hours=30)).isoformat()})
    assert r.status_code == 400 and "24 h" in r.json()["detail"]
    # Foto (tarefa e rotina) com a mesma regra.
    img = base64.b64encode(PNG * 4).decode()
    foto = {"image": img, "thumb": img,
            "at": feita.isoformat()}
    r = usuario.post(f"/worklog/{tid}/photos", foto)
    assert r.status_code == 201, r.text
    assert datetime.fromisoformat(r.json()["created_at"]) == feita
    rid = _rotina(usuario)
    r = usuario.post(f"/recurring/{rid}/photos", foto)
    assert r.status_code == 201 and datetime.fromisoformat(r.json()["created_at"]) == feita
    assert usuario.post(f"/recurring/{rid}/photos", {**foto, "at": (agora - timedelta(days=2)).isoformat()}).status_code == 400


def test_atribuida_alterada_e_cancelada_mostra_o_titulo_novo(par):
    chefe, marina = par
    tid = _mandar(chefe, marina)
    assert chefe.patch(f"/assign/{tid}", {"title": "Trocar o nobreak da sala 2"}).status_code == 200
    assert chefe.post(f"/assign/{tid}/cancel").status_code == 200
    linha = _linha(chefe, tid)
    assert linha["status"] == "removed" and linha["title"] == "Trocar o nobreak da sala 2"


def test_csv_da_equipe_por_periodo(admin, usuario):
    from datetime import timedelta
    from conftest import dia_hoje
    usuario.put("/me/viewers", {"accept": True})
    hoje = dia_hoje(usuario)
    tid = usuario.post("/worklog", {"title": "Chamado antigo"}).json()["id"]
    antigo = hoje.replace(day=1) - timedelta(days=40)
    usuario.post(f"/worklog/{tid}/time", {"minutes": 30, "day": antigo.isoformat()})
    usuario.post(f"/worklog/{tid}/time", {"minutes": 45, "day": hoje.isoformat()})
    padrao = admin.get("/viewer/export/apontamentos.csv").content.decode("utf-8-sig")
    assert ";45;" in padrao and ";30;" not in padrao  # sem período: o mês corrente
    r = admin.get(f"/viewer/export/apontamentos.csv?start={antigo.isoformat()}&end={antigo.isoformat()}")
    assert r.status_code == 200 and ";30;" in r.content.decode("utf-8-sig")
    assert admin.get(f"/viewer/export/apontamentos.csv?start={hoje.isoformat()}&end={antigo.isoformat()}").status_code == 400


def test_convite_cancelado_volta_o_pedido_para_pendente(monkeypatch, admin):
    from app import push
    from conftest import Api
    import app.routers.invite_requests as ir
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda *a, **k: None)
    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    monkeypatch.setattr(ir.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda self: target()})())
    assert Api().post("/auth/invite-request", {"name": "Ana Souza", "email": "ana@empresa.com.br", "source": "colega",
                                               "reason": "Registrar o suporte da filial."}).status_code == 202
    pedido = admin.get("/admin/invite-requests").json()[0]
    assert admin.post(f"/admin/invite-requests/{pedido['id']}/invite").status_code == 200
    uid = db.query_one("SELECT id FROM users WHERE email = 'ana@empresa.com.br'")["id"]
    assert admin.post(f"/admin/users/{uid}/cancel-invite").status_code == 200
    pedido = next(x for x in admin.get("/admin/invite-requests").json() if x["id"] == pedido["id"])
    assert pedido["status"] == "pending" and pedido["has_account"] is False
