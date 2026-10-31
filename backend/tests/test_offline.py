"""Feito sem sinal e enviado depois: o cronômetro usa a hora do aparelho
(até 24 h atrás), concluir usa a hora informada e criar não duplica."""
from datetime import datetime, timedelta, timezone


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def test_cronometro_com_a_hora_do_aparelho(usuario):
    tid = usuario.post("/worklog", {"title": "Troca do nobreak"}).json()["id"]
    agora = datetime.now(timezone.utc)
    r = usuario.post("/timer/start", {"task_id": tid, "at": _iso(agora - timedelta(minutes=50))})
    assert r.status_code == 200, r.text
    r = usuario.post("/timer/stop", {"at": _iso(agora - timedelta(minutes=5))})
    assert r.json()["stopped"]["minutes"] == 45


def test_cronometro_velho_demais_e_relogio_adiantado(usuario):
    tid = usuario.post("/worklog", {"title": "Rack"}).json()["id"]
    agora = datetime.now(timezone.utc)
    assert usuario.post("/timer/start", {"task_id": tid, "at": _iso(agora - timedelta(hours=25))}).status_code == 400
    assert usuario.post("/timer/start", {"task_id": tid, "at": _iso(agora + timedelta(hours=2))}).status_code == 200  # vale como agora
    assert usuario.post("/timer/stop").json()["stopped"]["minutes"] == 1


def test_parar_antes_de_iniciar_nao_da_tempo_negativo(usuario):
    tid = usuario.post("/worklog", {"title": "Switch"}).json()["id"]
    agora = datetime.now(timezone.utc)
    usuario.post("/timer/start", {"task_id": tid, "at": _iso(agora - timedelta(minutes=10))})
    assert usuario.post("/timer/stop", {"at": _iso(agora - timedelta(minutes=30))}).json()["stopped"]["minutes"] == 1


def test_criar_reenviado_nao_duplica(usuario):
    corpo = {"title": "Impressora do RH", "external_ref": "app-6f1c2a"}
    a = usuario.post("/worklog", corpo).json()
    b = usuario.post("/worklog", corpo).json()
    assert a["id"] == b["id"] and b.get("existing")
