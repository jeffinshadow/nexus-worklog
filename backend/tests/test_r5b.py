"""Lote R5-B: "Antes do PDF" em Meu mês (as concluídas do mês sem tempo ou sem
"como resolveu", as mesmas do PDF), "Primeiro amanhã" (até 3 tarefas que abrem
o Hoje do próximo dia útil e saem sozinhas) e a opção "Receber tarefas
atribuídas" em Admin › Para empresas e instituições (sql/041)."""
from datetime import date, timedelta

import pytest

from app import assignable, db, mailer
from app.routers import assign as assign_mod
from conftest import Bearer, criar_chave, dia_hoje, hist, texto, uid_de


def _concluida(u, titulo, dia, minutos=0, resolucao=None):
    tid = u.post("/worklog", {"title": titulo, "status": "done"}).json()["id"]
    db.execute("UPDATE worklog_tasks SET created_at = %s, completed_at = %s, resolution = %s WHERE id = %s",
               (f"{dia} 09:00-03", f"{dia} 11:00-03", resolucao, tid))
    if minutos:
        db.execute("INSERT INTO time_entries (task_id, user_id, minutes, day) VALUES (%s, %s, %s, %s)",
                   (tid, uid_de(u), minutos, dia))
    return tid


# ------------------------------------------------------------- antes do PDF --

def test_antes_do_pdf_lista_as_incompletas_do_mes(usuario, novo_usuario, admin):
    hoje = dia_hoje(usuario)
    mes = hoje.replace(day=1)
    dia = mes.isoformat()
    completa = _concluida(usuario, "Completa", dia, 30, "troquei o cabo")
    sem_tempo = _concluida(usuario, "Sem tempo", dia, 0, "reiniciei")
    sem_res = _concluida(usuario, "Sem resolução", dia, 15, None)
    nada = _concluida(usuario, "Nada", dia, 0, "   ")
    # Outro mês não entra.
    _concluida(usuario, "Mês passado", (mes - timedelta(days=3)).isoformat(), 0, None)
    ov = usuario.get(f"/dashboard?month={hoje:%Y-%m}").json()["overview"]
    ids = [x["id"] for x in ov["incomplete"]]
    assert set(ids) == {sem_tempo, sem_res, nada} and completa not in ids
    assert ov["incomplete_total"] == 3
    linha = next(x for x in ov["incomplete"] if x["id"] == sem_tempo)
    assert linha["minutes"] == 0 and linha["resolution"] is True and linha["done_date"] == dia
    assert next(x for x in ov["incomplete"] if x["id"] == sem_res)["resolution"] is False
    # As mesmas do PDF: o total de concluídas do mês bate com o da frase/PDF.
    assert ov["month"]["pontual_done"] == 4

    # Completar pelas rotas de sempre (tempo no dia da conclusão, PATCH resolution).
    assert usuario.post(f"/worklog/{sem_tempo}/time", {"minutes": 15, "day": dia}).status_code == 201
    assert usuario.patch(f"/worklog/{sem_res}", {"resolution": "ajustei o DNS"}).status_code == 200
    ov = usuario.get(f"/dashboard?month={hoje:%Y-%m}").json()["overview"]
    assert [x["id"] for x in ov["incomplete"]] == [nada] and ov["incomplete_total"] == 1

    # Quem acompanha a equipe não recebe a lista (é só da própria pessoa).
    vis = novo_usuario("vis@example.com")
    assert admin.put(f"/admin/users/{uid_de(vis)}/roles", {"roles": ["viewer"]}).status_code == 200
    usuario.put("/me/viewers", {"accept": True})
    ov = vis.get(f"/viewer/users/{uid_de(usuario)}/dashboard?month={hoje:%Y-%m}").json()["overview"]
    assert ov["incomplete"] == [] and ov["incomplete_total"] == 0


# ---------------------------------------------------------- primeiro amanhã --

def test_primeiro_amanha_escolhe_ate_3_e_abre_o_dia(usuario, novo_usuario):
    b = usuario.get("/board").json()
    hoje, dia = date.fromisoformat(b["today"]), date.fromisoformat(b["first_day"])
    assert dia > hoje
    ids = [usuario.post("/worklog", {"title": f"T{i}", "priority": 1 if i == 0 else 3}).json()["id"] for i in range(5)]
    r = usuario.put("/board/first", {"ids": [ids[4], ids[3], ids[4]]})
    assert r.status_code == 200, r.text
    assert r.json() == {"day": dia.isoformat(), "ids": [ids[4], ids[3]]}
    marcadas = {t["id"]: t["first_on"] for t in usuario.get("/board").json()["in_progress"]}
    assert marcadas[ids[4]] == dia.isoformat() and marcadas[ids[0]] is None
    # Trocar a escolha do mesmo dia substitui (a que saiu perde a marca).
    usuario.put("/board/first", {"ids": [ids[2]]})
    assert db.query_one("SELECT first_on FROM worklog_tasks WHERE id = %s", (ids[4],))["first_on"] is None
    # Até 3; só tarefas abertas da própria pessoa; dia entre amanhã e 7 dias.
    assert usuario.put("/board/first", {"ids": ids[:4]}).status_code == 422
    outra = novo_usuario("outra@example.com")
    alheia = outra.post("/worklog", {"title": "Dela"}).json()["id"]
    assert usuario.put("/board/first", {"ids": [alheia]}).status_code == 400
    feita = usuario.post("/worklog", {"title": "Feita", "status": "done"}).json()["id"]
    assert usuario.put("/board/first", {"ids": [feita]}).status_code == 400
    assert usuario.put("/board/first", {"ids": [ids[1]], "day": hoje.isoformat()}).status_code == 400
    assert usuario.put("/board/first", {"ids": [ids[1]], "day": (hoje + timedelta(days=8)).isoformat()}).status_code == 400
    assert db.query_one("SELECT first_on FROM worklog_tasks WHERE id = %s", (ids[2],))["first_on"] == dia  # nada mudou

    # No dia: a escolhida abre as abertas (antes da de prioridade alta) e o MCP mostra.
    db.execute("UPDATE worklog_tasks SET first_on = %s WHERE id = %s", (hoje, ids[2]))
    abertas = usuario.get("/board").json()["in_progress"]
    assert abertas[0]["id"] == ids[2] and abertas[1]["id"] == ids[0]
    ia = Bearer(criar_chave(usuario)["token"])
    txt = texto(ia.tool("get_today"))
    assert "Escolhidas para começar hoje (Primeiro amanhã): #%d T2" % ids[2] in txt
    # Escolha de ontem (feriado em que o app não abriu) continua valendo hoje (R6 funcional M2);
    # passados 7 dias, a marca não vale mais (sem apagar nada): volta à ordem de sempre.
    db.execute("UPDATE worklog_tasks SET first_on = %s WHERE id = %s", (hoje - timedelta(days=1), ids[2]))
    assert usuario.get("/board").json()["in_progress"][0]["id"] == ids[2]
    db.execute("UPDATE worklog_tasks SET first_on = %s WHERE id = %s", (hoje - timedelta(days=8), ids[2]))
    abertas = usuario.get("/board").json()["in_progress"]
    assert abertas[0]["id"] == ids[0]
    assert "Primeiro amanhã" not in texto(ia.tool("get_today"))
    # Concluída, sai da lista (só abertas aparecem).
    db.execute("UPDATE worklog_tasks SET first_on = %s WHERE id = %s", (hoje, ids[1]))
    usuario.post(f"/worklog/{ids[1]}/finish")
    assert all(t["id"] != ids[1] for t in usuario.get("/board").json()["in_progress"])
    # Lista vazia desfaz a escolha do dia.
    usuario.put("/board/first", {"ids": [ids[3]]})
    usuario.put("/board/first", {"ids": []})
    assert not db.query_one("SELECT 1 FROM worklog_tasks WHERE first_on = %s AND user_id = %s", (dia, uid_de(usuario)))


def test_revisao_da_semana_vira_o_primeiro_amanha(usuario):
    a = usuario.post("/worklog", {"title": "A"}).json()["id"]
    b = usuario.post("/worklog", {"title": "B"}).json()["id"]
    res = usuario.post("/review/week/done", {"next": [b, 999999]}).json()
    dia = usuario.get("/board").json()["first_day"]
    assert res["first"] == [b] and res["first_day"] == dia
    assert db.query_one("SELECT first_on FROM worklog_tasks WHERE id = %s", (b,))["first_on"].isoformat() == dia
    assert db.query_one("SELECT first_on FROM worklog_tasks WHERE id = %s", (a,))["first_on"] is None
    # Sem prioridades escolhidas, a escolha feita no fechamento do dia fica como está.
    usuario.put("/board/first", {"ids": [a]})
    res = usuario.post("/review/week/done", {"next": []}).json()
    assert res["first"] == [] and res["first_day"] is None
    assert db.query_one("SELECT first_on FROM worklog_tasks WHERE id = %s", (a,))["first_on"].isoformat() == dia


# ------------------------------------------------- receber tarefas atribuídas --

@pytest.fixture
def cena(admin, novo_usuario, monkeypatch):
    """Chefe (atribui), Ana (aceitou receber) e Bia (não aceitou)."""
    caixa = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(assign_mod, "_spawn", lambda to, mail: caixa.append((to, mail.subject, mail.text())))
    monkeypatch.setattr(assign_mod.push, "notify_assigned", lambda *a: None)
    chefe = novo_usuario("chefe@example.com")
    ana = novo_usuario("ana@example.com")
    bia = novo_usuario("bia@example.com")
    assert admin.put(f"/admin/users/{uid_de(chefe)}/roles", {"roles": ["user", "assigner"]}).status_code == 200
    ana.put("/me/assignments", {"accept": True})
    return chefe, ana, bia, caixa


def _org(admin, **kw):
    r = admin.put("/admin/org", kw)
    assert r.status_code == 200, r.text
    return r.json()


def _manda(chefe, para, title="Trocar lâmpada"):
    return chefe.post("/assign", {"user_id": uid_de(para), "title": title})


def test_receber_cada_pessoa_escolhe_e_todos_recebem(admin, cena, novo_usuario):
    chefe, ana, bia, caixa = cena
    ua, ub = uid_de(ana), uid_de(bia)
    aceita = lambda: {p["email"] for p in chefe.get("/assign/people").json() if p["accepts"]}  # noqa: E731
    ia = Bearer(criar_chave(chefe)["token"])

    # Padrão: cada pessoa escolhe. Bia fora da lista, do envio, da foto e do MCP.
    assert {"ana@example.com"} <= aceita() and "bia@example.com" not in aceita()
    assert assignable.can_receive(ua) and not assignable.can_receive(ub)
    assert _manda(chefe, bia).status_code == 403
    assert chefe.get(f"/me/avatar/{ub}").status_code == 404
    assert "bia@example.com" not in texto(ia.tool("list_assignable"))
    assert ia.tool("assign_task", to="bia@example.com", title="X").get("isError")

    # Todos recebem de quem atribui: Bia recebe, sem mudar o aceite guardado.
    out = _org(admin, assign_receive="all")
    assert out["assign_receive"] == "all" and out["assign_receive_since"]
    assert {"ana@example.com", "bia@example.com"} <= aceita()
    assert all(p["everyone"] for p in chefe.get("/assign/people").json())
    assert assignable.can_receive(ub)
    r = _manda(chefe, bia)
    assert r.status_code == 201, r.text
    assert "todos recebem tarefas de quem atribui" in caixa[-1][2]
    assert "bia@example.com" in texto(ia.tool("list_assignable"))
    assert "Atribuída a" in texto(ia.tool("assign_task", to="bia@example.com", title="Pelo MCP"))
    assert db.query_one("SELECT accepts_assignments_at FROM users WHERE id = %s", (ub,))["accepts_assignments_at"] is None
    # Conta bloqueada e convite ainda não aceito continuam sem receber.
    assert admin.post(f"/admin/users/{uid_de(ana)}/block").status_code in (200, 204)
    assert not assignable.can_receive(ua) and _manda(chefe, ana).status_code == 404
    pend = admin.post("/admin/users", {"email": "novo@example.com"}).json()
    pend_id = db.query_one("SELECT id FROM users WHERE email = 'novo@example.com'")["id"]
    assert pend and not assignable.can_receive(pend_id)
    # Quem não tem o papel Usuário (só admin) não recebe.
    so_vis = novo_usuario("vis@example.com")
    admin.put(f"/admin/users/{uid_de(so_vis)}/roles", {"roles": ["viewer"]})
    assert not assignable.can_receive(uid_de(so_vis))

    # Volta para "Cada pessoa escolhe": cada um com o que tinha (Bia sai de novo).
    _org(admin, assign_receive="self")
    assert "bia@example.com" not in aceita()
    assert _manda(chefe, bia).status_code == 403
    assert "bia@example.com" not in texto(ia.tool("list_assignable"))
    # As tarefas já recebidas ficam com ela.
    assert any(t["title"] == "Pelo MCP" for t in bia.get("/board").json()["in_progress"])


def test_receber_trava_o_aceite_com_409_e_log(admin, cena):
    _, ana, bia, _ = cena
    _org(admin, assign_receive="all")
    me = bia.get("/auth/me").json()
    assert me["org"]["assign_receive"] == "all"
    r = bia.put("/me/assignments", {"accept": True})
    assert r.status_code == 409
    assert "definido pela administração" in r.json()["detail"] and "guardada" in r.json()["detail"]
    assert ana.put("/me/assignments", {"accept": False}).status_code == 409
    assert ana.get("/auth/me").json()["accepts_assignments_at"]  # nada mudou
    _org(admin, assign_receive="self")
    assert ana.put("/me/assignments", {"accept": False}).status_code == 200
    # Log de admin: quem e quando, nas duas direções, com texto claro no Histórico.
    rows = db.query_all("SELECT after FROM audit_log WHERE action = 'app.assign_receive' ORDER BY id")
    assert [r["after"]["assign_receive"] for r in rows] == ["all", "self"]
    assert rows[0]["after"]["by"] == admin.me["email"]
    textos = [h["summary"] for h in hist(admin) if h["action"] == "app.assign_receive"]
    assert any("Todos recebem de quem atribui" in t for t in textos)
    assert any("Cada pessoa escolhe" in t for t in textos)
    # Só o admin muda; valor fora da lista = 422.
    assert bia.put("/admin/org", {"assign_receive": "all"}).status_code == 403
    assert admin.put("/admin/org", {"assign_receive": "todos"}).status_code == 422


def test_receber_aviso_unico_e_tour(admin, cena, novo_usuario):
    chefe, ana, bia, _ = cena
    assert bia.get("/auth/me").json()["assign_notice"] is False
    _org(admin, assign_receive="all")
    assert bia.get("/auth/me").json()["assign_notice"] is True
    assert bia.put("/me/assign-notice").status_code == 200
    assert bia.get("/auth/me").json()["assign_notice"] is False
    # Quem passou pelo tour com a opção ligada já viu a parada: sem aviso depois.
    assert ana.get("/auth/me").json()["assign_notice"] is True
    r = ana.put("/me/tour", {"done": True}).json()
    assert r["assign_notice"] is False
    # Desligar e ligar de novo: avisa outra vez quem já tinha visto.
    _org(admin, assign_receive="self")
    assert bia.get("/auth/me").json()["assign_notice"] is False
    _org(admin, assign_receive="all")
    assert bia.get("/auth/me").json()["assign_notice"] is True
    # Sem o papel Usuário, nada a avisar.
    so_admin = novo_usuario("adm2@example.com")
    admin.put(f"/admin/users/{uid_de(so_admin)}/roles", {"roles": ["admin"]})
    assert so_admin.get("/auth/me").json()["assign_notice"] is False
