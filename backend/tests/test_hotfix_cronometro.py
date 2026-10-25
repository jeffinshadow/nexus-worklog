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
    assert t["status"] == "done" and t["minutes"] == 1440  # 600 já apontados + 840 que cabiam no dia
    assert usuario.get("/timer").json()["timer"] is None


def test_parar_cronometro_com_dia_cheio(usuario):
    tid = usuario.post("/worklog", {"title": "x"}).json()["id"]
    ontem = (dia_hoje(usuario) - timedelta(days=1)).isoformat()
    usuario.post(f"/worklog/{tid}/time", {"minutes": 1440, "day": ontem})

    def comecar_ontem():
        usuario.post("/timer/start", {"task_id": tid})
        db.execute("UPDATE task_timers SET started_at = (%s::date + time '10:00') AT TIME ZONE 'America/Sao_Paulo' "
                   "WHERE task_id = %s", (ontem, tid))

    comecar_ontem()
    r = usuario.post("/timer/stop")
    assert r.status_code == 200 and r.json()["stopped"] is None
    assert usuario.post("/timer/stop").status_code == 409
    comecar_ontem()
    res = Bearer(criar_chave(usuario)["token"]).tool("stop_timer")  # pelo MCP: parou, sem erro
    assert not res["isError"] and "24h" in texto(res)
