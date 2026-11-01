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
