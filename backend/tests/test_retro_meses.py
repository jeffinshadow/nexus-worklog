"""Retrospectiva por mês: as janelas do mês escolhido, sem backlog nem sequência no passado."""
from datetime import date, timedelta

from app import db
from conftest import dia_hoje, recuar_criacao, uid_de


def _mes_anterior(d: date) -> date:
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


def test_retrospectiva_do_mes_anterior(usuario):
    hoje = dia_hoje(usuario)
    mes = _mes_anterior(hoje)
    rid = usuario.post("/recurring", {"label": "Todo dia", "freq": "weekly", "weekdays": 127}).json()["id"]
    recuar_criacao(rid, 80)
    # Duas marcações no mês anterior (dias 3 e 10), feitas direto no banco (o app só volta 7 dias).
    for dia in (3, 10):
        db.execute("INSERT INTO recurring_completions (task_id, user_id, completed_date) VALUES (%s, %s, %s)",
                   (rid, uid_de(usuario), mes.replace(day=dia)))
    tid = usuario.post("/worklog", {"title": "Feita no mês passado", "status": "done"}).json()["id"]
    feita = mes.replace(day=12)
    db.execute("UPDATE worklog_tasks SET created_at = %s, completed_at = %s WHERE id = %s",
               (f"{feita} 10:00-03", f"{feita} 11:00-03", tid))
    db.execute("INSERT INTO time_entries (task_id, user_id, minutes, day) VALUES (%s, %s, 90, %s)",
               (tid, uid_de(usuario), feita))
    db.execute("UPDATE users SET created_at = now() - interval '80 days' WHERE id = %s", (uid_de(usuario),))

    r = usuario.get(f"/dashboard?month={mes:%Y-%m}").json()
    fim = date(mes.year, mes.month, 28) + timedelta(days=4)
    fim = fim - timedelta(days=fim.day)  # último dia do mês
    assert r["period"] == {"month": f"{mes:%Y-%m}", "start": mes.isoformat(), "end": fim.isoformat(), "now": False}
    assert r["months"][0] == f"{hoje:%Y-%m}" and f"{mes:%Y-%m}" in r["months"]
    assert r["backlog"] is None  # o backlog é do momento: não existe num mês passado
    rot = next(t for t in r["task_adherence"]["tasks"] if t["label"] == "Todo dia")
    assert rot["done"] == 2 and rot["slots"] == fim.day and rot["streak"] is None
    dias = r["heatmap"]["days"]
    assert dias[-1]["date"] == fim.isoformat() and date.fromisoformat(dias[0]["date"]).weekday() == 6  # domingo
    fora = [d for d in dias if d.get("out")]
    assert all(date.fromisoformat(d["date"]) < mes for d in fora)
    assert sum(d["done"] for d in dias) == 2
    assert sum(w["done"] for w in r["throughput"]["weeks"]) == 1
    assert [p["minutes"] for p in r["projects"]["items"]] == [90]

    # Sem mês: as janelas de sempre, com backlog e sequência.
    atual = usuario.get("/dashboard").json()
    assert atual["period"]["month"] is None and atual["period"]["now"] and atual["backlog"] is not None
    # Mês corrente: até hoje, com backlog.
    corrente = usuario.get(f"/dashboard?month={hoje:%Y-%m}").json()
    assert corrente["period"]["end"] == hoje.isoformat() and corrente["backlog"] is not None


def test_mes_invalido(usuario):
    hoje = dia_hoje(usuario)
    futuro = (hoje.replace(day=28) + timedelta(days=5)).replace(day=1)
    assert usuario.get(f"/dashboard?month={futuro:%Y-%m}").status_code == 400
    assert usuario.get("/dashboard?month=2026-13").status_code == 422
    assert usuario.get("/dashboard?month=out").status_code == 422


def test_visualizador_ve_o_mes(admin, usuario):
    uid = uid_de(usuario)
    mes = _mes_anterior(dia_hoje(usuario))
    r = admin.get(f"/viewer/users/{uid}/dashboard?month={mes:%Y-%m}")
    assert r.status_code == 200 and r.json()["period"]["month"] == f"{mes:%Y-%m}"
