"""Rotinas: pausar até uma data e "a cada N dias depois da última vez" (freq after)."""
from datetime import date, timedelta

from app import db, notify, services
from app.services import get_report_range, is_due, is_pending, next_due, _due_between
from conftest import Bearer, criar_chave, dia_hoje, hist, recuar_criacao, texto, uid_de

TODO_DIA = 127  # weekly com os 7 dias: não depende dos dias úteis


def _criar(u, **kw):
    body = {"label": "Ronda do prédio", "freq": "weekly", "weekdays": TODO_DIA, **kw}
    r = u.post("/recurring", body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _linha(u, rid, day=None):
    b = u.get("/board" + (f"?day={day}" if day else "")).json()
    return next(x for x in b["recurring"] if x["id"] == rid)


def _marcar(uid, rid, d):
    db.execute("INSERT INTO recurring_completions (task_id, user_id, completed_date) VALUES (%s, %s, %s)", (rid, uid, d))


def _pausa_antiga(rid, s, e):
    """Uma pausa pedida no passado (o app só pausa a partir de hoje)."""
    db.execute("INSERT INTO recurring_pauses (recurring_id, start_d, end_d) VALUES (%s, %s, %s)", (rid, s, e))


def _stat(uid, rid_label, a, b):
    r = get_report_range(uid, a, b)
    return next(x for x in r["recurring_stats"] if x["label"] == rid_label), r["summary"]


# ------------------------------------------------------------- regra (puro) --

def _after(start, n, feitas=(), pausas=()):
    return {"freq": "after", "interval_days": n, "start_d": start, "done_dates": sorted(feitas), "pauses": list(pausas)}


def test_after_sem_marcacao_conta_da_criacao_e_cada_ciclo_uma_vez():
    t = _after(date(2026, 1, 1), 30)
    venc = date(2026, 1, 31)
    assert next_due(t, date(2026, 1, 10)) == venc
    assert not is_pending(t, date(2026, 1, 30), 0) and is_pending(t, venc, 0) and is_pending(t, date(2026, 2, 20), 0)
    # Ninguém marcou: UMA falta, no último dia do ciclo (venc + 29), e abre o próximo.
    assert [d for d in (venc + timedelta(days=i) for i in range(60)) if is_due(t, d, 0)] == [date(2026, 3, 1), date(2026, 3, 31)]
    assert _due_between(t, date(2026, 1, 1), date(2026, 3, 31), 0) == 2


def test_after_marcar_atrasada_conta_feita_e_move_a_proxima():
    t = _after(date(2026, 1, 1), 30, feitas=[date(2026, 2, 5)])  # venceu 31/01, feita 05/02
    assert is_due(t, date(2026, 2, 5), 0)  # o ciclo devido, feito nesse dia
    assert _due_between(t, date(2026, 1, 1), date(2026, 3, 6), 0) == 1  # nenhuma falta
    assert next_due(t, date(2026, 2, 5)) == date(2026, 3, 7)  # virada de mês: 05/02 + 30
    assert next_due(t, date(2026, 2, 20)) == date(2026, 3, 7)
    assert not is_pending(t, date(2026, 3, 6), 0) and is_pending(t, date(2026, 3, 7), 0)


def test_after_marcar_antes_e_extra_e_adianta():
    t = _after(date(2026, 1, 1), 30, feitas=[date(2026, 1, 20)])
    assert not is_due(t, date(2026, 1, 20), 0)  # antes de vencer: extra
    assert next_due(t, date(2026, 1, 25)) == date(2026, 2, 19)
    assert not is_pending(t, date(2026, 1, 31), 0) and is_pending(t, date(2026, 2, 19), 0)


def test_after_virada_de_ano():
    t = _after(date(2026, 12, 1), 15, feitas=[date(2026, 12, 20)])
    assert next_due(t, date(2026, 12, 20)) == date(2027, 1, 4)
    assert next_due(t, date(2026, 12, 31)) == date(2027, 1, 4)


def test_pausa_tira_qualquer_agenda_e_after():
    semanal = {"freq": "weekly", "weekdays": TODO_DIA, "start_d": date(2026, 1, 1), "pauses": [[date(2026, 1, 5), date(2026, 1, 9)]]}
    assert _due_between(semanal, date(2026, 1, 1), date(2026, 1, 31), 0) == 26
    assert services.pause_end(semanal, date(2026, 1, 7)) == date(2026, 1, 9)
    assert services.pause_end(semanal, date(2026, 1, 10)) is None
    t = _after(date(2026, 1, 1), 3, pausas=[[date(2026, 1, 3), date(2026, 1, 10)]])
    assert not is_pending(t, date(2026, 1, 10), 0) and is_pending(t, date(2026, 1, 11), 0)  # volta vencida


# ------------------------------------------------------------------- pausa --

def test_pausar_tira_do_dia_lembrete_e_aviso_e_marcar_vira_extra(usuario):
    hoje, uid = dia_hoje(usuario), uid_de(usuario)
    rid = _criar(usuario, remind_at="09:00")
    fim = hoje + timedelta(days=19)
    r = usuario.post(f"/recurring/{rid}/pause", {"until": fim.isoformat()})
    assert r.status_code == 200 and r.json()["paused_until"] == fim.isoformat()
    x = _linha(usuario, rid)
    assert x["due"] is False and x["paused_until"] == fim.isoformat()
    assert not any(i["id"] == rid for i in usuario.get("/recurring/reminders").json()["items"])
    assert "Ronda do prédio" not in str(notify.build_evening(uid, hoje, True).blocks)
    assert not notify._rotina_devida(uid, hoje, services.work_mask(uid))
    # Marcar durante a pausa: conta como extra, fora do %.
    assert usuario.post(f"/recurring/{rid}/toggle", {"done": True}).status_code == 200
    st, s = _stat(uid, "Ronda do prédio", hoje, hoje)
    assert (st["due"], st["done"], st["extra"]) == (0, 0, 1) and (s["recurring_total"], s["recurring_extra"]) == (0, 1)
    assert "pausada até" in texto(Bearer(criar_chave(usuario)["token"]).tool("list_recurring"))


def test_pausa_nao_reescreve_o_passado_e_conta_so_os_dias_pausados(usuario):
    hoje, uid = dia_hoje(usuario), uid_de(usuario)
    rid = _criar(usuario)
    recuar_criacao(rid, 10)
    ini = hoje - timedelta(days=10)
    antes = _stat(uid, "Ronda do prédio", ini, hoje - timedelta(days=1))[0]
    assert antes["due"] == 10
    usuario.post(f"/recurring/{rid}/pause", {"until": (hoje + timedelta(days=3)).isoformat()})
    assert _stat(uid, "Ronda do prédio", ini, hoje - timedelta(days=1))[0]["due"] == 10  # passado intacto
    # Uma pausa antiga (3 dias) tira esses dias de todos os números: PDF, ranking, calendário, resumo.
    _pausa_antiga(rid, hoje - timedelta(days=6), hoje - timedelta(days=4))
    st, s = _stat(uid, "Ronda do prédio", ini, hoje - timedelta(days=1))
    assert st["due"] == 7 and s["recurring_total"] == 7
    assert st["marks"][4:7] == "OOO"  # dias pausados: fora da agenda na matriz
    dash = usuario.get("/dashboard").json()
    rank = next(x for x in dash["task_adherence"]["tasks"] if x["label"] == "Ronda do prédio")
    assert rank["slots"] == 7  # 10 dias passados - 3 pausados (hoje: pausada)
    pausados = {(hoje - timedelta(days=i)).isoformat() for i in (4, 5, 6)}
    assert all(d["slots"] == 0 for d in dash["heatmap"]["days"] if d["date"] in pausados)
    um = services._compact(get_report_range(uid, hoje - timedelta(days=6), hoje - timedelta(days=4)))
    assert um["missed"] == [] and um["recurring_total"] == 0


def test_pausa_volta_sozinha(usuario):
    hoje = dia_hoje(usuario)
    rid = _criar(usuario)
    recuar_criacao(rid, 5)
    _pausa_antiga(rid, hoje - timedelta(days=3), hoje - timedelta(days=1))  # acabou ontem
    x = _linha(usuario, rid)
    assert x["due"] is True and x["paused_until"] is None
    ontem = _linha(usuario, rid, (hoje - timedelta(days=1)).isoformat())
    assert ontem["due"] is False and ontem["paused_until"] == (hoje - timedelta(days=1)).isoformat()


def test_retomar_desfazer_e_validacoes(usuario, novo_usuario):
    hoje = dia_hoje(usuario)
    rid = _criar(usuario)
    assert usuario.post(f"/recurring/{rid}/pause", {"until": (hoje - timedelta(days=1)).isoformat()}).status_code == 400
    assert usuario.post(f"/recurring/{rid}/pause", {"until": (hoje + timedelta(days=400)).isoformat()}).status_code == 400
    assert usuario.delete(f"/recurring/{rid}/pause").status_code == 400  # não está pausada
    outro = novo_usuario("outro@example.com")
    assert outro.post(f"/recurring/{rid}/pause", {"until": hoje.isoformat()}).status_code == 404

    usuario.post(f"/recurring/{rid}/pause", {"until": (hoje + timedelta(days=5)).isoformat()})
    h = hist(usuario, entity="recurring", entity_id=rid)[0]
    assert h["action"] == "recurring.pause" and "pausou até" in h["summary"]
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert _linha(usuario, rid)["paused_until"] is None and _linha(usuario, rid)["due"] is True

    usuario.post(f"/recurring/{rid}/pause", {"until": (hoje + timedelta(days=5)).isoformat()})
    usuario.post(f"/recurring/{rid}/pause", {"until": (hoje + timedelta(days=9)).isoformat()})  # muda o fim
    assert _linha(usuario, rid)["paused_until"] == (hoje + timedelta(days=9)).isoformat()
    assert db.query_one("SELECT count(*) AS n FROM recurring_pauses WHERE recurring_id = %s", (rid,))["n"] == 1
    assert usuario.delete(f"/recurring/{rid}/pause").status_code == 200  # retomar agora: hoje já é devida
    assert _linha(usuario, rid)["due"] is True
    h = hist(usuario, entity="recurring", entity_id=rid)[0]
    assert h["action"] == "recurring.resume"
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert _linha(usuario, rid)["paused_until"] == (hoje + timedelta(days=9)).isoformat()


def test_trocar_a_agenda_leva_a_pausa(usuario):
    hoje = dia_hoje(usuario)
    rid = _criar(usuario)
    recuar_criacao(rid, 10)
    usuario.post(f"/recurring/{rid}/pause", {"until": (hoje + timedelta(days=4)).isoformat()})
    novo = usuario.patch(f"/recurring/{rid}", {"freq": "interval", "interval_days": 2}).json()["id"]
    assert novo != rid and _linha(usuario, novo)["paused_until"] == (hoje + timedelta(days=4)).isoformat()


# ------------------------------------------------------- depois da última vez --

def test_after_pela_api_proxima_data_e_numeros(usuario):
    hoje, uid = dia_hoje(usuario), uid_de(usuario)
    rid = _criar(usuario, label="Trocar o filtro", freq="after", interval_days=5)
    assert usuario.post("/recurring", {"label": "x", "freq": "after"}).status_code == 422  # exige interval_days
    x = _linha(usuario, rid)
    assert x["freq"] == "after" and x["due"] is False and x["next_due"] == (hoje + timedelta(days=5)).isoformat()
    recuar_criacao(rid, 7)  # venceu há 2 dias e ninguém marcou: continua para fazer
    x = _linha(usuario, rid)
    assert x["due"] is True and x["next_due"] == (hoje - timedelta(days=2)).isoformat()
    st, _ = _stat(uid, "Trocar o filtro", hoje - timedelta(days=7), hoje)
    assert (st["due"], st["done"]) == (0, 0)  # ciclo ainda aberto: não é falta
    assert usuario.post(f"/recurring/{rid}/toggle", {"done": True}).status_code == 200
    x = _linha(usuario, rid)
    assert x["due"] is True and x["done_today"] and x["next_due"] == (hoje + timedelta(days=5)).isoformat()
    st, _ = _stat(uid, "Trocar o filtro", hoje - timedelta(days=7), hoje)
    assert (st["due"], st["done"], st["extra"]) == (1, 1, 0)
    b = Bearer(criar_chave(usuario)["token"])
    assert "próxima em" in texto(b.tool("list_recurring"))


def test_after_falta_por_ciclo_no_relatorio(usuario):
    hoje, uid = dia_hoje(usuario), uid_de(usuario)
    rid = _criar(usuario, label="Trocar o filtro", freq="after", interval_days=3)
    recuar_criacao(rid, 12)  # criada há 12 dias: vence -9, ciclos [-9,-7] e [-6,-4] sem marcar = 2 faltas
    _marcar(uid, rid, hoje - timedelta(days=2))  # feita no 3º ciclo [-3,-1]
    st, _ = _stat(uid, "Trocar o filtro", hoje - timedelta(days=12), hoje)
    assert (st["due"], st["done"]) == (3, 1)
    assert _linha(usuario, rid)["next_due"] == (hoje + timedelta(days=1)).isoformat()


def test_after_reminder_aparece_enquanto_vencida(usuario):
    rid = _criar(usuario, label="Trocar o filtro", freq="after", interval_days=2, remind_at="08:00")
    assert not any(i["id"] == rid for i in usuario.get("/recurring/reminders").json()["items"])
    recuar_criacao(rid, 4)
    assert any(i["id"] == rid for i in usuario.get("/recurring/reminders").json()["items"])


def test_mcp_cria_after_pausa_e_retoma(usuario):
    hoje = dia_hoje(usuario)
    b = Bearer(criar_chave(usuario)["token"])
    out = texto(b.tool("create_recurring", label="Trocar o filtro", freq="after", interval_days=30))
    assert "30 dias depois da última vez" in out
    rid = int(out.split("R")[1].split()[0])
    fim = hoje + timedelta(days=10)
    assert f"pausada até {fim:%d/%m/%Y}" in texto(b.tool("set_recurring", recurring_id=rid, paused_until=fim.isoformat()))
    assert db.query_one("SELECT count(*) AS n FROM recurring_completions WHERE task_id = %s", (rid,))["n"] == 0
    assert "retomada" in texto(b.tool("set_recurring", recurring_id=rid, paused_until=None))
    assert _linha(usuario, rid)["paused_until"] is None
    out = texto(b.tool("create_recurring", label="Ronda", paused_until=fim.isoformat()))
    assert "pausada até" in out
