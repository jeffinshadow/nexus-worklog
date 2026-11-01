"""Hotfix: cronômetro esquecido por dias não pode travar concluir, parar ou trocar."""
from datetime import timedelta

from app import db
from conftest import Bearer, criar_chave, dia_hoje, texto


def test_cronometro_esquecido_nao_trava_concluir(usuario):
    tid = usuario.post("/worklog", {"title": "Link oscilando"}).json()["id"]
    hoje = dia_hoje(usuario)
    usuario.post(f"/worklog/{tid}/time", {"minutes": 600, "day": (hoje - timedelta(days=12)).isoformat()})
    usuario.post("/timer/start", {"task_id": tid})
    db.execute("UPDATE task_timers SET started_at = now() - interval '12 days' WHERE task_id = %s", (tid,))
    r = usuario.post(f"/worklog/{tid}/finish")
    assert r.status_code == 200, r.text
    t = usuario.get(f"/worklog/{tid}").json()
    assert t["status"] == "done" and t["minutes"] == 600  # esquecido: não inventa horas
    assert usuario.get("/timer").json()["timer"] is None


def test_parar_cronometro_com_dia_cheio(usuario):
    tid = usuario.post("/worklog", {"title": "x"}).json()["id"]
    hoje = dia_hoje(usuario)
    usuario.post(f"/worklog/{tid}/time", {"minutes": 1440, "day": hoje.isoformat()})

    def comecar_ontem():  # duas horas atrás, mas o dia dele já está cheio
        usuario.post("/timer/start", {"task_id": tid})
        db.execute("UPDATE task_timers SET started_at = now() - interval '2 hours' WHERE task_id = %s", (tid,))
        db.execute("UPDATE time_entries SET day = (now() - interval '2 hours') AT TIME ZONE 'America/Sao_Paulo' "
                   "WHERE task_id = %s", (tid,))

    comecar_ontem()
    r = usuario.post("/timer/stop")
    assert r.status_code == 200 and r.json()["stopped"] is None
    assert usuario.post("/timer/stop").status_code == 409
    comecar_ontem()
    res = Bearer(criar_chave(usuario)["token"]).tool("stop_timer")  # pelo MCP: parou, sem erro
    assert not res["isError"] and "24h" in texto(res)


# ---- gauntlet geral: esquecido pede o tempo; parada da fila não vale para outro cronômetro

def test_esquecido_para_sem_apontar_e_pede_o_tempo(usuario):
    tid = usuario.post("/worklog", {"title": "Ronda"}).json()["id"]
    usuario.post("/timer/start", {"task_id": tid})
    db.execute("UPDATE task_timers SET started_at = now() - interval '14 hours' WHERE task_id = %s", (tid,))
    st = usuario.post("/timer/stop").json()["stopped"]
    assert st["needs_review"] and st["minutes"] == 0 and st["task_id"] == tid and st["title"] == "Ronda"
    assert usuario.get(f"/worklog/{tid}").json()["minutes"] == 0
    assert usuario.get("/timer").json()["timer"] is None


def test_parada_de_outro_aparelho_nao_derruba_o_cronometro_novo(usuario):
    from datetime import datetime, timezone
    a = usuario.post("/worklog", {"title": "A"}).json()["id"]
    b = usuario.post("/worklog", {"title": "B"}).json()["id"]
    usuario.post("/timer/start", {"task_id": a})
    antes = datetime.now(timezone.utc).isoformat()  # o celular parou A aqui, sem sinal
    usuario.post("/timer/start", {"task_id": b})     # o computador trocou para B
    r = usuario.post("/timer/stop", {"task_id": a, "at": antes})
    assert r.status_code == 409 and "outro aparelho" in r.json()["detail"]
    assert usuario.get("/timer").json()["timer"]["task_id"] == b
    db.execute("UPDATE task_timers SET started_at = now() - interval '5 minutes' WHERE task_id = %s", (b,))
    cedo = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    db.execute("UPDATE task_timers SET started_at = now() + interval '1 minute' WHERE task_id = %s", (b,))
    assert usuario.post("/timer/stop", {"task_id": b, "at": cedo}).status_code == 409  # parou antes de começar
    db.execute("UPDATE task_timers SET started_at = now() - interval '5 minutes' WHERE task_id = %s", (b,))
    assert usuario.post("/timer/stop", {"task_id": b}).json()["stopped"]["minutes"] == 5


def test_inicio_sem_sinal_mais_antigo_que_o_cronometro_atual_da_409(usuario):
    from datetime import datetime, timedelta, timezone
    a = usuario.post("/worklog", {"title": "A"}).json()["id"]
    b = usuario.post("/worklog", {"title": "B"}).json()["id"]
    usuario.post("/timer/start", {"task_id": a})
    antes = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    assert usuario.post("/timer/start", {"task_id": b, "at": antes}).status_code == 409
    assert usuario.get("/timer").json()["timer"]["task_id"] == a


def test_concluir_sem_sinal_para_o_cronometro_na_hora_da_conclusao(usuario):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    inicio = (datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    tid = usuario.post("/worklog", {"title": "Disjuntor", "created_at": inicio}).json()["id"]
    usuario.post("/timer/start", {"task_id": tid})
    db.execute("UPDATE task_timers SET started_at = now() - interval '60 minutes' WHERE task_id = %s", (tid,))
    fim = (datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(minutes=50)).strftime("%Y-%m-%dT%H:%M")
    assert usuario.post(f"/worklog/{tid}/finish", {"completed_at": fim}).status_code == 200
    assert 9 <= usuario.get(f"/worklog/{tid}").json()["minutes"] <= 11
