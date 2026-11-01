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
    # Na Equipe, só o resumo das rotinas: sem o ranking por rotina (não é placar).
    assert r["overview"]["behind"] == []
    assert (r["overview"]["routines"], r["overview"]["routines_full"]) == (2, 1)
    own = usuario.get(f"/dashboard?month={mes:%Y-%m}").json()["overview"]
    assert own["routines_full"] == 1 and len(own["behind"]) == 1  # a própria pessoa vê as dela


def test_pdf_sem_vermelho_nas_rotinas(usuario, monkeypatch):
    """O PDF não pinta de vermelho rotina abaixo de um limite (nem a perdida): fato, não nota.
    O vermelho fica para tarefa atrasada ou bloqueada, que não há aqui."""
    from app import report_pdf
    hoje, mes, _ = _preparar(usuario)  # "Ronda": 3 dias de ~30
    usadas = []

    def spy(nome):
        orig = getattr(report_pdf._Report, nome)

        def f(self, *c):
            usadas.append(tuple(c))
            return orig(self, *c)
        monkeypatch.setattr(report_pdf._Report, nome, f)
    for nome in ("set_text_color", "set_fill_color", "set_draw_color"):
        spy(nome)
    # O mês (matriz por dia) e um período longo (lista com barras).
    for start in (mes, mes - timedelta(days=70)):
        usadas.clear()
        r = usuario.get(f"/reports/export?start={start}&end={_fim(mes)}")
        assert r.status_code == 200 and r.content[:4] == b"%PDF"
        assert usadas and report_pdf.BAD not in usadas, start


def test_pdf_de_um_dia_sem_todos_teve():
    from app.report_pdf import _lede
    s = {"active_days": 1, "period_days": 1, "pontual_done": 0, "minutes": 0, "recurring_total": 0,
         "recurring_done": 0, "recurring_extra": 0, "open": 0, "overdue": 0}
    frase = _lede({"summary": s})
    assert "todos teve" not in frase and frase.startswith("O dia teve atividade registrada.")


# ------------------------------------------------- Meu mês v2 (o painel) --

def _meses_atras(m: date, n: int) -> date:
    for _ in range(n):
        m = _mes_anterior(m)
    return m


def test_tendencia_de_seis_meses_bate_com_o_pdf(usuario):
    """A série dos 6 meses usa a MESMA conta do PDF, mês a mês."""
    hoje = dia_hoje(usuario)
    mes = _mes_anterior(hoje)
    uid = uid_de(usuario)
    db.execute("UPDATE users SET created_at = now() - interval '400 days' WHERE id = %s", (uid,))
    rot = usuario.post("/recurring", {"label": "Ronda", "freq": "weekly", "weekdays": 127}).json()["id"]
    recuar_criacao(rot, 400)
    for i in range(6):  # do mês escolhido ao 5º anterior: i+1 tarefas, i+2 marcações
        m = _meses_atras(mes, i)
        for k in range(i + 1):
            _concluida(usuario, f"T{i}-{k}", m.replace(day=k + 1), 30 * (k + 1))
        for k in range(i + 2):
            db.execute("INSERT INTO recurring_completions (task_id, user_id, completed_date) VALUES (%s, %s, %s)",
                       (rot, uid, m.replace(day=k + 1)))
    ov = usuario.get(f"/dashboard?month={mes:%Y-%m}").json()["overview"]
    assert [t["month"] for t in ov["trend"]] == [f"{_meses_atras(mes, i):%Y-%m}" for i in range(5, -1, -1)]
    for t in ov["trend"]:
        m = date.fromisoformat(t["month"] + "-01")
        pdf = usuario.get(f"/reports/preview?start={m}&end={_fim(m)}").json()
        for k in ("recurring_done", "recurring_total", "pontual_done", "minutes"):
            assert t[k] == pdf[k], (t["month"], k)
    assert ov["trend"][-1]["pontual_done"] == 1 and ov["trend"][0]["pontual_done"] == 6
    # Média dos 5 anteriores (2..6 tarefas = 4); o mês tem 1: abaixo. Sem vermelho: só a palavra.
    assert ov["average"]["months"] == 5 and ov["average"]["pontual_done"] == 4.0
    assert ov["compare"]["tasks"] == "abaixo" and ov["compare"]["routines"] == "abaixo"
    # Semanas (domingo a sábado, cortadas no mês) somam o mês; dias = um por dia do mês.
    assert sum(w["pontual_done"] for w in ov["weeks"]) == ov["month"]["pontual_done"]
    assert sum(w["minutes"] for w in ov["weeks"]) == ov["month"]["minutes"]
    assert ov["weeks"][0]["start"] == f"{mes}" and ov["weeks"][-1]["end"] == f"{_fim(mes)}"
    assert len(ov["days"]) == _fim(mes).day
    d1 = ov["days"][0]
    assert (d1["due"], d1["done"], d1["extra"], d1["paused"]) == (1, 1, 0, False)
    assert sum(d["done"] for d in ov["days"]) == ov["month"]["recurring_done"]
    assert sum(d["due"] for d in ov["days"]) == ov["month"]["recurring_total"]


def test_palavra_neutra_na_media_e_sem_media_cedo(usuario):
    hoje = dia_hoje(usuario)
    mes = _mes_anterior(hoje)
    uid = uid_de(usuario)
    db.execute("UPDATE users SET created_at = %s WHERE id = %s", (f"{_meses_atras(mes, 3)} 08:00-03", uid))
    for i in range(4):  # 2 tarefas de 1h por mês, sempre: na média
        m = _meses_atras(mes, i)
        _concluida(usuario, f"A{i}", m.replace(day=2), 60)
        _concluida(usuario, f"B{i}", m.replace(day=3), 60)
    ov = usuario.get(f"/dashboard?month={mes:%Y-%m}").json()["overview"]
    assert len(ov["trend"]) == 4  # só desde o primeiro registro
    assert ov["compare"]["tasks"] == "na média" and ov["compare"]["minutes"] == "na média"
    assert ov["compare"]["routines"] is None  # sem rotinas, sem palavra
    # Um só mês anterior: ainda sem média.
    ov2 = usuario.get(f"/dashboard?month={_meses_atras(mes, 2):%Y-%m}").json()["overview"]
    assert ov2["average"] is None and set(ov2["compare"].values()) == {None}


def test_dia_pausado_e_extra_no_calendario(usuario):
    hoje = dia_hoje(usuario)
    mes = _mes_anterior(hoje)
    uid = uid_de(usuario)
    db.execute("UPDATE users SET created_at = now() - interval '100 days' WHERE id = %s", (uid,))
    seg = usuario.post("/recurring", {"label": "Segunda", "freq": "weekly", "weekdays": 2}).json()["id"]
    recuar_criacao(seg, 100)
    # extra: marcada num dia fora da agenda (o primeiro dia do mês que não é segunda)
    extra_dia = next(mes.replace(day=k) for k in range(1, 8) if mes.replace(day=k).weekday() != 0)
    db.execute("INSERT INTO recurring_completions (task_id, user_id, completed_date) VALUES (%s, %s, %s)",
               (seg, uid, extra_dia))
    db.execute("INSERT INTO recurring_pauses (recurring_id, start_d, end_d) VALUES (%s, %s, %s)",
               (seg, mes.replace(day=15), mes.replace(day=28)))
    ov = usuario.get(f"/dashboard?month={mes:%Y-%m}").json()["overview"]
    por_dia = {d["date"]: d for d in ov["days"]}
    e = por_dia[f"{extra_dia}"]
    assert (e["due"], e["done"], e["extra"]) == (0, 0, 1)
    seg_pausada = next(mes.replace(day=k) for k in range(15, 22) if mes.replace(day=k).weekday() == 0)
    p = por_dia[f"{seg_pausada}"]
    assert p["paused"] is True and p["due"] == 0
    assert por_dia[f"{mes.replace(day=14)}"]["paused"] is False  # antes da pausa


def test_equipe_sem_tendencia_nem_media(admin, usuario):
    hoje, mes, _ = _preparar(usuario)
    usuario.put("/me/viewers", {"accept": True})
    ov = admin.get(f"/viewer/users/{uid_de(usuario)}/dashboard?month={mes:%Y-%m}").json()["overview"]
    assert ov["trend"] == [] and ov["average"] is None and ov["compare"] is None
    assert ov["days"] and ov["weeks"]  # o mês dela, como no PDF, continua
    own = usuario.get(f"/dashboard?month={mes:%Y-%m}").json()["overview"]
    assert len(own["trend"]) >= 2  # a própria pessoa vê a tendência
