"""Meu mês: o resumo do mês (overview em /dashboard?month=) bate com o PDF do
mesmo mês e traz o mês anterior, as rotinas para trás e as entregas."""
from datetime import date, timedelta

from app import db
from conftest import dia_hoje, recuar_criacao, uid_de


def _mes_anterior(d: date) -> date:
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


def _fim(m: date) -> date:
    return (m.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def _concluida(u, titulo, dia, minutos, resolucao=None):
    tid = u.post("/worklog", {"title": titulo, "status": "done"}).json()["id"]
    db.execute("UPDATE worklog_tasks SET created_at = %s, completed_at = %s, resolution = %s WHERE id = %s",
               (f"{dia} 09:00-03", f"{dia} 11:00-03", resolucao, tid))
    if minutos:
        db.execute("INSERT INTO time_entries (task_id, user_id, minutes, day) VALUES (%s, %s, %s, %s)",
                   (tid, uid_de(u), minutos, dia))
    return tid


def _preparar(u):
    hoje = dia_hoje(u)
    mes = _mes_anterior(hoje)
    ante = _mes_anterior(mes)
    uid = uid_de(u)
    db.execute("UPDATE users SET created_at = now() - interval '100 days' WHERE id = %s", (uid,))
    todo = u.post("/recurring", {"label": "Conferir backup", "freq": "weekly", "weekdays": 127}).json()["id"]
    pouco = u.post("/recurring", {"label": "Ronda", "freq": "weekly", "weekdays": 127}).json()["id"]
    recuar_criacao(todo, 100)
    recuar_criacao(pouco, 100)
    for dia in range(1, _fim(mes).day + 1):  # backup todo dia; ronda só em 3
        db.execute("INSERT INTO recurring_completions (task_id, user_id, completed_date) VALUES (%s, %s, %s)",
                   (todo, uid, mes.replace(day=dia)))
    for dia in (2, 5, 9):
        db.execute("INSERT INTO recurring_completions (task_id, user_id, completed_date) VALUES (%s, %s, %s)",
                   (pouco, uid, mes.replace(day=dia)))
    db.execute("INSERT INTO recurring_completions (task_id, user_id, completed_date) VALUES (%s, %s, %s)",
               (pouco, uid, ante.replace(day=4)))
    _concluida(u, "Curta", mes.replace(day=3), 15)
    _concluida(u, "Longa", mes.replace(day=7), 200, "Troquei o switch do andar 2")
    _concluida(u, "Sem tempo", mes.replace(day=8), 0)
    _concluida(u, "Do mês anterior", ante.replace(day=10), 45)
    return hoje, mes, ante


def test_resumo_do_mes_bate_com_o_pdf(usuario):
    hoje, mes, ante = _preparar(usuario)
    ov = usuario.get(f"/dashboard?month={mes:%Y-%m}").json()["overview"]
    # O PDF do mês usa get_report_range; a prévia do PDF devolve os mesmos números.
    pdf = usuario.get(f"/reports/preview?start={mes}&end={_fim(mes)}").json()
    for k in ("recurring_done", "recurring_total", "pontual_done", "minutes"):
        assert ov["month"][k] == pdf[k], k
    assert ov["month"]["pontual_done"] == 3 and ov["month"]["minutes"] == 215
    assert ov["month"]["recurring_total"] == 2 * _fim(mes).day
    assert ov["month"]["now"] is False
    # O mês anterior, inteiro, também como no PDF dele.
    pdf_ante = usuario.get(f"/reports/preview?start={ante}&end={_fim(ante)}").json()
    assert ov["previous"]["month"] == f"{ante:%Y-%m}"
    for k in ("recurring_done", "recurring_total", "pontual_done", "minutes"):
        assert ov["previous"][k] == pdf_ante[k], k
    # Rotinas: só a que ficou para trás, com dias feitos de previstos.
    assert ov["routines"] == 2
    assert ov["behind"] == [{"label": "Ronda", "due": _fim(mes).day, "done": 3}]
    # Entregas: do maior tempo ao menor, com o "como resolveu".
    assert [d["title"] for d in ov["deliveries"]] == ["Longa", "Curta", "Sem tempo"]
    assert ov["deliveries"][0]["resolution"] == "Troquei o switch do andar 2" and ov["deliveries"][0]["minutes"] == 200
    assert ov["projects"] == [{"name": None, "color": None, "minutes": 215}]


def test_mes_corrente_e_sem_mes_anterior(usuario):
    hoje = dia_hoje(usuario)
    ov = usuario.get(f"/dashboard?month={hoje:%Y-%m}").json()["overview"]
    assert ov["month"]["now"] is True and ov["month"]["end"] == hoje.isoformat()
    assert ov["previous"] is None  # a conta é de hoje: não há mês anterior para comparar
    pdf = usuario.get(f"/reports/preview?start={hoje.replace(day=1)}&end={hoje}").json()
    for k in ("recurring_done", "recurring_total", "pontual_done", "minutes"):
        assert ov["month"][k] == pdf[k], k
    # Sem mês (janelas móveis), não há resumo.
    assert "overview" not in usuario.get("/dashboard").json()


def test_visualizador_ve_o_resumo(admin, usuario):
    hoje, mes, _ = _preparar(usuario)
    usuario.put("/me/viewers", {"accept": True})
    r = admin.get(f"/viewer/users/{uid_de(usuario)}/dashboard?month={mes:%Y-%m}").json()
    assert r["overview"]["month"]["pontual_done"] == 3
