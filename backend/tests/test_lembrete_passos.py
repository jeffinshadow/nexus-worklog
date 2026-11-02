"""R5-A: lembrete com hora na tarefa (remind_at: aviso da tela, Adiar, "Ok",
notificação do aparelho, MCP, ICS, desfazer) e passos opcionais na rotina."""
import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app import db, push
from app.config import config
from conftest import Bearer, criar_chave, dia_hoje, hist, recuar_criacao, texto, uid_de
from test_push import Navegador, _ligar, caixa  # noqa: F401 — fixture da rede falsa

TZ = ZoneInfo(config.APP_TZ)


def _daqui(**kw):
    return (datetime.now(TZ) + timedelta(**kw)).replace(second=0, microsecond=0)


def _tarefa(u, **kw):
    r = u.post("/worklog", {"title": "Retornar a Ana", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _lembretes(u):
    return {t["id"]: t for t in u.get("/recurring/reminders").json()["tasks"]}


def _remind(tid):
    return db.query_one("SELECT remind_at, remind_snoozed_until, remind_seen_at FROM worklog_tasks WHERE id = %s", (tid,))


# ------------------------------------------------------------- lembrete --

def test_criar_com_lembrete_aparece_no_quadro_detalhe_e_aviso(usuario):
    quando = _daqui(hours=1)
    tid = _tarefa(usuario, remind_at=quando.strftime("%Y-%m-%dT%H:%M"))  # sem fuso = fuso da app
    assert datetime.fromisoformat(usuario.get(f"/worklog/{tid}").json()["remind_at"]) == quando
    card = next(t for t in usuario.get("/board").json()["in_progress"] if t["id"] == tid)
    assert datetime.fromisoformat(card["remind_at"]) == quando
    item = _lembretes(usuario)[tid]
    assert item["title"] == "Retornar a Ana" and item["snoozed_until"] is None


def test_hora_como_se_fala(usuario):
    tid = _tarefa(usuario, remind_at="amanhã 8h")
    r = _remind(tid)["remind_at"].astimezone(TZ)
    assert (r.date(), r.time()) == (dia_hoje(usuario) + timedelta(days=1), time(8, 0))
    tid2 = _tarefa(usuario, remind_at="7h30")  # a próxima vez que der 7h30
    r2 = _remind(tid2)["remind_at"].astimezone(TZ)
    assert r2.time() == time(7, 30) and r2 > datetime.now(TZ)


def test_lembrete_invalido_ou_no_passado(usuario):
    assert usuario.post("/worklog", {"title": "X", "remind_at": "2026-11-03"}).status_code == 422  # só o dia
    assert usuario.post("/worklog", {"title": "X", "remind_at": "abc"}).status_code == 422
    passado = _daqui(hours=-1).strftime("%Y-%m-%dT%H:%M")
    r = usuario.post("/worklog", {"title": "X", "remind_at": passado})
    assert r.status_code == 400 and "já passou" in r.json()["detail"]
    longe = _daqui(days=400).strftime("%Y-%m-%dT%H:%M")
    assert usuario.post("/worklog", {"title": "X", "remind_at": longe}).status_code == 400
    # Feita sem sinal (com a hora do aparelho): o horário que passou na fila fica e avisa já.
    agora = datetime.now(TZ).strftime("%Y-%m-%dT%H:%M")
    r = usuario.post("/worklog", {"title": "Sem sinal", "remind_at": passado, "created_at": agora})
    assert r.status_code == 201, r.text
    assert r.json()["id"] in _lembretes(usuario)


def test_concluida_nao_lembra(usuario):
    tid = _tarefa(usuario, remind_at=_daqui(minutes=30).isoformat())
    assert tid in _lembretes(usuario)
    usuario.post(f"/worklog/{tid}/finish")
    assert tid not in _lembretes(usuario)
    feita = _tarefa(usuario, status="done", remind_at=_daqui(minutes=30).isoformat())
    assert _remind(feita)["remind_at"] is None


def test_mudar_tirar_e_desfazer(usuario):
    antes = _daqui(hours=2)
    tid = _tarefa(usuario, remind_at=antes.isoformat())
    novo = _daqui(hours=3)
    assert usuario.patch(f"/worklog/{tid}", {"remind_at": novo.isoformat()}).status_code == 200
    assert _remind(tid)["remind_at"] == novo
    h = hist(usuario, entity="worklog", entity_id=tid)[0]
    assert h["action"] == "worklog.update" and h["can_undo"]
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert _remind(tid)["remind_at"] == antes
    assert usuario.patch(f"/worklog/{tid}", {"remind_at": None}).status_code == 200
    assert _remind(tid)["remind_at"] is None and tid not in _lembretes(usuario)
    # Editar outro campo não mexe no lembrete; reenviar o mesmo horário passado também não dá erro.
    tid2 = _tarefa(usuario, remind_at=_daqui(hours=1).isoformat())
    db.execute("UPDATE worklog_tasks SET remind_at = now() - interval '1 hour' WHERE id = %s", (tid2,))
    atual = _remind(tid2)["remind_at"]
    assert usuario.patch(f"/worklog/{tid2}", {"title": "Ligar", "remind_at": atual.isoformat()}).status_code == 200
    assert _remind(tid2)["remind_at"] == atual


def test_adiar_e_ok(usuario):
    tid = _tarefa(usuario, remind_at=_daqui(minutes=5).isoformat())
    r = usuario.post(f"/worklog/{tid}/snooze", {"minutes": 10})
    assert r.status_code == 200 and _lembretes(usuario)[tid]["snoozed_until"]
    assert usuario.post(f"/worklog/{tid}/snooze", {"minutes": 1}).status_code == 422
    db.execute("UPDATE worklog_tasks SET remind_at = now() - interval '1 minute' WHERE id = %s", (tid,))
    assert usuario.post(f"/worklog/{tid}/reminder-seen").status_code == 200
    assert tid not in _lembretes(usuario)                      # visto: não toca mais
    # Horário novo volta a valer (adiado e visto zeram).
    usuario.patch(f"/worklog/{tid}", {"remind_at": _daqui(hours=1).isoformat()})
    assert _remind(tid)["remind_seen_at"] is None and _remind(tid)["remind_snoozed_until"] is None
    assert tid in _lembretes(usuario)
    sem = _tarefa(usuario)
    assert usuario.post(f"/worklog/{sem}/snooze", {"minutes": 10}).status_code == 400
    assert usuario.post(f"/worklog/{sem}/reminder-seen").status_code == 400


def test_so_a_dona(usuario, novo_usuario):
    tid = _tarefa(usuario, remind_at=_daqui(hours=1).isoformat())
    outro = novo_usuario("outra@example.com")
    assert outro.post(f"/worklog/{tid}/snooze", {"minutes": 10}).status_code == 404
    assert outro.post(f"/worklog/{tid}/reminder-seen").status_code == 404
    assert tid not in _lembretes(outro)


def test_duplicar_nao_copia_o_lembrete(usuario):
    tid = _tarefa(usuario, remind_at=_daqui(hours=1).isoformat())
    copia = usuario.post(f"/worklog/{tid}/duplicate").json()["id"]
    assert _remind(copia)["remind_at"] is None


def test_notificacao_no_horario_repete_e_para(usuario, caixa):  # noqa: F811
    nav = _ligar(usuario)
    tid = _tarefa(usuario, remind_at=_daqui(hours=1).isoformat())
    hoje, uid = dia_hoje(usuario), uid_de(usuario)
    at = datetime.combine(hoje, time(15, 0), tzinfo=TZ)
    db.execute("UPDATE worklog_tasks SET remind_at = %s WHERE id = %s", (at, tid))
    stamp = f"{tid}:{at:%Y%m%d%H%M}"
    assert push.run_once(at - timedelta(minutes=1)) == []
    assert push.run_once(at) == [(uid, f"{stamp}:0")]
    msg = nav.abrir(caixa[-1][2])
    assert msg["title"] == "Retornar a Ana" and msg["kind"] == "lembrete" and msg["id"] == tid
    assert msg["body"] == "Lembrete: agora, às 15:00" and msg["url"] == f"/#/tarefas?id={tid}"
    assert [a["action"] for a in msg["actions"]] == ["concluir", "adiar"]
    assert push.run_once(at + timedelta(minutes=1)) == []
    # Adiado até 15:12: o +10 cai dentro do adiamento; o adiado sai no horário.
    db.execute("UPDATE worklog_tasks SET remind_snoozed_until = %s WHERE id = %s", (at + timedelta(minutes=12), tid))
    assert push.run_once(at + timedelta(minutes=10)) == []
    assert push.run_once(at + timedelta(minutes=12)) == [(uid, f"{stamp}:a{at.day:02d}1512")]
    db.execute("UPDATE worklog_tasks SET remind_seen_at = %s WHERE id = %s", (at + timedelta(minutes=13), tid))
    assert push.run_once(at + timedelta(minutes=30)) == []     # "Ok": para


def test_notificacao_escondida_e_desligada(usuario, caixa):  # noqa: F811
    nav = _ligar(usuario)
    tid = _tarefa(usuario, remind_at=_daqui(hours=1).isoformat())
    at = datetime.combine(dia_hoje(usuario), time(15, 0), tzinfo=TZ)
    db.execute("UPDATE worklog_tasks SET remind_at = %s WHERE id = %s", (at, tid))
    usuario.put("/push/prefs", {"hide_content": True})
    push.run_once(at)
    msg = nav.abrir(caixa[-1][2])
    assert msg["title"] == "Lembrete de tarefa" and "Ana" not in json.dumps(msg)
    usuario.put("/push/prefs", {"routine": False, "hide_content": False})
    assert push.run_once(at + timedelta(minutes=10)) == []


def test_lembrete_no_calendario(usuario):
    tid = _tarefa(usuario, remind_at=_daqui(hours=1).isoformat())
    path = usuario.post("/calendar", {"include_recurring": False}).json()["path"]
    ics = usuario.c.get(path).text
    assert f"UID:remind-{tid}@nexus-worklog" in ics and "BEGIN:VALARM" in ics and "Lembrete: Retornar a Ana" in ics


def test_lembrete_pela_ia(usuario):
    ia = Bearer(criar_chave(usuario)["token"])
    out = texto(ia.tool("create_task", title="Ligar pro fornecedor", remind_at="amanhã 8h"))
    assert "lembrar em" in out and "08:00" in out
    tid = db.query_one("SELECT id FROM worklog_tasks WHERE title = 'Ligar pro fornecedor'")["id"]
    out = texto(ia.tool("update_task", task_id=tid, remind_at=None))
    assert "lembrar em" not in out and _remind(tid)["remind_at"] is None
    r = ia.tool("update_task", task_id=tid, remind_at="2020-01-01T10:00")
    assert r.get("isError") and "já passou" in texto(r)


# ---------------------------------------------------------------- passos --

def _rotina(u, **kw):
    r = u.post("/recurring", {"label": "Ronda das 7h", "freq": "weekly", "weekdays": 127, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _passos(u, rid):
    return next(x for x in u.get("/board").json()["recurring"] if x["id"] == rid)["steps"]


def test_rotina_com_passos(usuario):
    rid = _rotina(usuario, steps=["  Casa de máquinas ", "", "Bombas", "Gerador"], remind_at="07:00")
    assert _passos(usuario, rid) == ["Casa de máquinas", "Bombas", "Gerador"]
    item = next(x for x in usuario.get("/recurring/reminders").json()["items"] if x["id"] == rid)
    assert item["steps"] == ["Casa de máquinas", "Bombas", "Gerador"]
    # Marcar conta uma vez; a evidência leva os não feitos (montada pelo app).
    r = usuario.post(f"/recurring/{rid}/toggle", {"done": True, "note": "feita, exceto: Gerador"})
    assert r.status_code == 200 and r.json()["note"] == "feita, exceto: Gerador"
    assert usuario.post("/recurring", {"label": "Y", "steps": ["x" * 81]}).status_code == 422
    assert usuario.post("/recurring", {"label": "Y", "steps": [f"p{i}" for i in range(13)]}).status_code == 422


def test_mudar_tirar_passos_e_desfazer(usuario):
    rid = _rotina(usuario, steps=["A", "B"])
    recuar_criacao(rid, 10)  # com passado: passos não trocam a rotina (só a agenda troca)
    r = usuario.patch(f"/recurring/{rid}", {"steps": ["A", "B", "C"]})
    assert r.json()["id"] == rid and _passos(usuario, rid) == ["A", "B", "C"]
    h = hist(usuario, entity="recurring", entity_id=rid)[0]
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert _passos(usuario, rid) == ["A", "B"]
    usuario.patch(f"/recurring/{rid}", {"steps": []})
    assert _passos(usuario, rid) is None
    usuario.patch(f"/recurring/{rid}", {"steps": ["A"]})
    novo = usuario.patch(f"/recurring/{rid}", {"freq": "daily"}).json()["id"]  # trocar a agenda leva os passos
    assert novo != rid
    assert db.query_one("SELECT steps FROM recurring_tasks WHERE id = %s", (novo,))["steps"] == ["A"]


def test_push_rotina_com_passos_nao_tem_marcar(usuario, caixa):  # noqa: F811
    nav = _ligar(usuario)
    _rotina(usuario, steps=["A", "B"], remind_at="09:00")
    push.run_once(datetime.combine(dia_hoje(usuario), time(9, 0), tzinfo=TZ))
    assert [a["action"] for a in nav.abrir(caixa[-1][2])["actions"]] == ["adiar"]


def test_pacote_traz_passos_na_ronda(usuario):
    packs = {p["id"]: p for p in usuario.get("/routine-packs").json()}
    ronda = next(i for i in packs["manutencao"]["items"] if i["key"] == "ronda")
    assert len(ronda["steps"]) >= 4
    usuario.post("/routine-packs/manutencao/apply", {"items": ["ronda"], "project": False})
    row = db.query_one("SELECT steps FROM recurring_tasks WHERE label = 'Fazer a ronda do prédio'")
    assert row["steps"] == ronda["steps"]


def test_passos_pela_ia(usuario):
    ia = Bearer(criar_chave(usuario)["token"])
    out = texto(ia.tool("create_recurring", label="Ronda noturna", steps=["Portões", "Câmeras"]))
    assert "passos: Portões; Câmeras" in out
    rid = db.query_one("SELECT id FROM recurring_tasks WHERE label = 'Ronda noturna'")["id"]
    out = texto(ia.tool("update_recurring", recurring_id=rid, steps=None))
    assert "passos" not in out
    assert "passos" not in texto(ia.tool("list_recurring"))
