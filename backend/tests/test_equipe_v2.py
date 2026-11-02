"""Equipe v2: o painel da equipe (/viewer/team) soma só quem pode ser visto
(visibility.visible_sql), bate com o CSV e com o PDF/Meu mês de cada pessoa,
não vaza quem não aceitou em nenhum número, cartão ou item, e é só do papel
"Vê a equipe"."""
from datetime import date, timedelta

import pytest

from app import db, services
from app.routers import assign as assign_mod
from conftest import Bearer, criar_chave, dia_hoje, recuar_criacao, uid_de


@pytest.fixture(autouse=True)
def _sem_email(monkeypatch):
    monkeypatch.setattr(assign_mod, "_spawn", lambda to, mail: None)


def _mes_anterior(d: date) -> date:
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


def _fim(m: date) -> date:
    return (m.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def _pessoa(u, nome, mes, minutos, projeto, aceita=True):
    """Uma rotina diária feita em metade dos dias, duas concluídas com tempo
    no mês, uma aguardando e uma vencendo amanhã."""
    uid = uid_de(u)
    db.execute("UPDATE users SET created_at = now() - interval '120 days', display_name = %s WHERE id = %s", (nome, uid))
    rot = u.post("/recurring", {"label": f"Ronda {nome}", "freq": "weekly", "weekdays": 127}).json()["id"]
    recuar_criacao(rot, 120)
    for dia in range(1, _fim(mes).day + 1, 2):
        db.execute("INSERT INTO recurring_completions (task_id, user_id, completed_date) VALUES (%s, %s, %s)",
                   (rot, uid, mes.replace(day=dia)))
    pid = u.post("/projects", {"name": projeto}).json()["id"]
    for i, dia in enumerate((3, 12)):
        d = mes.replace(day=dia)
        tid = u.post("/worklog", {"title": f"Entrega {nome} {i}", "status": "done", "project_id": pid}).json()["id"]
        db.execute("UPDATE worklog_tasks SET created_at = %s, completed_at = %s WHERE id = %s",
                   (f"{d} 09:00-03", f"{d} 11:00-03", tid))
        db.execute("INSERT INTO time_entries (task_id, user_id, minutes, day) VALUES (%s, %s, %s, %s)",
                   (tid, uid, minutos, d))
    esp = u.post("/worklog", {"title": f"Aguardando {nome}"}).json()["id"]
    u.patch(f"/worklog/{esp}", {"status": "blocked", "blocked_reason": "peça"})
    db.execute("UPDATE worklog_tasks SET blocked_at = now() - interval '4 days' WHERE id = %s", (esp,))
    amanha = (dia_hoje(u) + timedelta(days=1)).isoformat()
    u.post("/worklog", {"title": f"Vence {nome}", "due_date": amanha})
    if aceita:
        assert u.put("/me/viewers", {"accept": True}).status_code == 200
    return uid


def _csv_minutos(api, start, end):
    linhas = api.get(f"/viewer/export/apontamentos.csv?start={start}&end={end}").content.decode("utf-8-sig").splitlines()
    return sum(int(l.split(";")[1]) for l in linhas[1:]), {l.split(";")[-1] for l in linhas[1:]}


def test_painel_soma_so_quem_aceitou_e_bate_com_csv_e_pdf(admin, novo_usuario):
    zelia = novo_usuario("zelia@example.com")
    ana = novo_usuario("ana@example.com")
    caio = novo_usuario("caio@example.com")
    hoje = dia_hoje(admin)
    mes = _mes_anterior(hoje)
    m = mes.strftime("%Y-%m")
    uz = _pessoa(zelia, "Zélia", mes, 30, "Cliente Z")
    ua = _pessoa(ana, "Ana", mes, 45, "Cliente A")
    uc = _pessoa(caio, "Caio", mes, 600, "Segredo do Caio", aceita=False)

    r = admin.get(f"/viewer/team?month={m}")
    assert r.status_code == 200, r.text
    t = r.json()
    # Cartões: só quem aceitou, em ordem alfabética (Ana antes de Zélia, mesmo criada depois).
    assert [p["name"] for p in t["people"]] == ["Ana", "Zélia"]
    assert t["people_count"] == 2 and t["hidden_count"] == 1  # Caio (quem acompanha não conta a si mesmo)
    assert all(set(p) >= {"open", "waiting", "last_activity", "avatar"} for p in t["people"])
    assert {p["id"] for p in t["people"]} == {ua, uz}
    # Nada por pessoa além dos cartões: nem média, nem tendência, nem ranking.
    assert not {"average", "compare", "behind", "ranking"} & set(t)

    # Horas: as mesmas do CSV da equipe no mês (e sem as 10h do Caio).
    total, emails = _csv_minutos(admin, mes.isoformat(), _fim(mes).isoformat())
    assert t["month"]["minutes"] == total == 2 * 30 + 2 * 45
    assert "caio@example.com" not in emails
    # Rotinas e concluídas: a soma do PDF/Meu mês de cada pessoa (mesma conta).
    soma = {"recurring_done": 0, "recurring_total": 0, "pontual_done": 0, "minutes": 0}
    for uid in (ua, uz):
        ov = admin.get(f"/viewer/users/{uid}/dashboard?month={m}").json()["overview"]["month"]
        pdf = services.get_report_range(uid, mes, _fim(mes))["summary"]
        for k in soma:
            assert ov[k] == pdf[k]
            soma[k] += pdf[k]
    for k in soma:
        assert t["month"][k] == soma[k], k
    assert t["month"]["recurring_total"] > 0 and t["month"]["pontual_done"] == 4
    # A série de 6 meses é da equipe e termina no mês escolhido, com os mesmos números.
    assert t["trend"][-1]["month"] == m and t["trend"][-1]["minutes"] == total
    assert len(t["trend"]) <= 6
    # Aguardando: só da equipe visível (1 de cada).
    assert t["waiting"] == 2
    # Tempo por projeto: só os projetos de quem aceitou.
    nomes = {p["name"] for p in t["projects"]}
    assert nomes == {"Cliente A", "Cliente Z"}
    assert sum(p["minutes"] for p in t["projects"]) == total
    # Precisa de atenção: nada do Caio, até 6 itens, cada um com a pessoa e a tarefa.
    att = t["attention"]
    assert att and len(att) <= 6
    assert all(x["user_id"] in (ua, uz) for x in att)
    assert not any("Caio" in x["title"] for x in att)
    assert {x["kind"] for x in att} == {"waiting", "due"}
    assert any(x["kind"] == "waiting" and x["days"] == 4 for x in att)

    # Caio passa a permitir: entra; Ana desliga: sai de tudo.
    caio.put("/me/viewers", {"accept": True})
    ana.put("/me/viewers", {"accept": False})
    t = admin.get(f"/viewer/team?month={m}").json()
    assert [p["name"] for p in t["people"]] == ["Caio", "Zélia"]
    assert t["month"]["minutes"] == 2 * 30 + 2 * 600
    assert all(x["user_id"] in (uc, uz) for x in t["attention"])
    assert "Cliente A" not in {p["name"] for p in t["projects"]}


def test_atribuidas_por_mim_paradas_ou_aguardando(admin, novo_usuario):
    admin.put(f"/admin/users/{uid_de(admin)}/roles", {"roles": ["admin", "user", "viewer", "assigner"]})
    bia = novo_usuario("bia@example.com")
    leo = novo_usuario("leo@example.com")
    for u in (bia, leo):
        u.put("/me/assignments", {"accept": True})
    bia.put("/me/viewers", {"accept": True})
    parada = admin.post("/assign", {"user_id": uid_de(bia), "title": "Trocar o nobreak"}).json()["id"]
    nova = admin.post("/assign", {"user_id": uid_de(bia), "title": "Recém-chegada"}).json()["id"]
    escondida = admin.post("/assign", {"user_id": uid_de(leo), "title": "Do Leo"}).json()["id"]
    db.execute("UPDATE worklog_tasks SET assigned_at = now() - interval '6 days' WHERE id = ANY(%s)", ([parada, escondida],))
    t = admin.get("/viewer/team").json()
    ids = {x["task_id"]: x for x in t["attention"]}
    assert parada in ids and ids[parada]["kind"] == "assigned" and ids[parada]["days"] == 6
    assert nova not in ids          # ainda dentro do prazo de começar
    assert escondida not in ids     # Leo não permitiu ser visto
    assert t["can_assign"] is True
    # Quem recebeu começou (anotou): deixa de estar parada.
    bia.post(f"/worklog/{parada}/notes", {"body": "Pedi orçamento"})
    t = admin.get("/viewer/team").json()
    assert parada not in {x["task_id"] for x in t["attention"]}


def test_equipe_vazia_mantem_o_painel(admin, usuario):
    usuario.post("/worklog", {"title": "Só minha"})
    t = admin.get("/viewer/team").json()
    assert t["people"] == [] and t["people_count"] == 0 and t["hidden_count"] == 1
    assert t["attention"] == [] and t["projects"] == []
    assert t["month"]["minutes"] == 0 and t["month"]["recurring_total"] == 0 and t["month"]["pontual_done"] == 0
    assert t["waiting"] == 0 and t["open"] == 0
    assert t["trend"] and t["trend"][-1]["month"] == t["period"]["month"]
    assert t["months"] == [t["period"]["month"]]
    assert admin.get("/viewer/team?month=2999-01").status_code == 400  # mês no futuro


def test_so_o_papel_ve_a_equipe_e_so_pelo_app(admin, usuario, novo_usuario):
    assert usuario.get("/viewer/team").status_code == 403
    chefe = novo_usuario("chefe@example.com")
    admin.put(f"/admin/users/{uid_de(chefe)}/roles", {"roles": ["user", "assigner"]})
    assert chefe.get("/viewer/team").status_code == 403  # atribuir não é ver a equipe
    assert Bearer(criar_chave(admin)["token"]).get("/viewer/team").status_code == 403
