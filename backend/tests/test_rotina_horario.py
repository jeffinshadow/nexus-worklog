"""Horário da rotina: a interface lembra perto dele (GET /recurring/reminders)."""
from conftest import hist, recuar_criacao


def _criar(u, **kw):
    r = u.post("/recurring", {"label": "Conferir backups", "freq": "weekly", "weekdays": 127, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _lembrete(u, rid):
    return next((x for x in u.get("/recurring/reminders").json()["items"] if x["id"] == rid), None)


def test_criar_com_horario_aparece_nos_lembretes(usuario):
    rid = _criar(usuario, remind_at="09:30")
    assert _lembrete(usuario, rid) == {"id": rid, "label": "Conferir backups", "remind_at": "09:30",
                                       "require_note": False, "done": False}
    assert next(x for x in usuario.get("/board").json()["recurring"] if x["id"] == rid)["remind_at"].startswith("09:30")
    usuario.post(f"/recurring/{rid}/toggle", {"done": True})
    assert _lembrete(usuario, rid)["done"] is True


def test_sem_horario_ou_fora_da_agenda_nao_lembra(usuario):
    sem = _criar(usuario)
    assert _lembrete(usuario, sem) is None
    from conftest import dia_hoje
    outro_dia = 1 << ((dia_hoje(usuario).weekday() + 2) % 7)  # domingo = bit 0; nunca o de hoje
    fora = _criar(usuario, remind_at="10:00", weekdays=outro_dia)
    assert _lembrete(usuario, fora) is None


def test_mudar_e_tirar_horario_sem_trocar_a_rotina(usuario):
    rid = _criar(usuario, remind_at="09:00")
    recuar_criacao(rid, 10)  # com passado: só a agenda troca a rotina, o horário não
    r = usuario.patch(f"/recurring/{rid}", {"remind_at": "14:15"})
    assert r.json()["id"] == rid and _lembrete(usuario, rid)["remind_at"] == "14:15"
    usuario.patch(f"/recurring/{rid}", {"label": "Backups"})  # sem o campo: mantém
    assert _lembrete(usuario, rid)["remind_at"] == "14:15"
    usuario.patch(f"/recurring/{rid}", {"remind_at": None})
    assert _lembrete(usuario, rid) is None


def test_trocar_agenda_leva_o_horario_e_desfazer_volta(usuario):
    rid = _criar(usuario, remind_at="08:45")
    recuar_criacao(rid, 10)
    novo = usuario.patch(f"/recurring/{rid}", {"freq": "daily"}).json()["id"]
    assert novo != rid
    b = usuario.get("/board").json()["recurring"]
    if any(x["id"] == novo and x["due"] for x in b):  # hoje pode não ser dia útil
        assert _lembrete(usuario, novo)["remind_at"] == "08:45"
    # Desfazer a mudança de horário devolve o anterior.
    usuario.patch(f"/recurring/{novo}", {"remind_at": "11:00"})
    h = hist(usuario, entity="recurring", entity_id=novo)[0]
    assert h["action"] == "recurring.update"
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    from app import db
    assert str(db.query_one("SELECT remind_at FROM recurring_tasks WHERE id = %s", (novo,))["remind_at"]) == "08:45:00"


def test_horario_invalido(usuario):
    assert usuario.post("/recurring", {"label": "X", "remind_at": "25:00"}).status_code == 422
