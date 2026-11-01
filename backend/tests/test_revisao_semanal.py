"""Revisão semanal guiada (último dia útil, revisão feita/dispensada, texto da
semana, MCP) e tarefa aguardando parada (N dias, configuração, avisos da manhã)."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app import db, notify, push, review
from app.config import config
from conftest import Bearer, criar_chave, dia_hoje, texto, uid_de


def _aguardando_ha(tid, dias):
    db.execute("UPDATE worklog_tasks SET blocked_at = now() - make_interval(days => %s) WHERE id = %s", (dias, tid))


def _so_hoje_util(monkeypatch, hoje):
    """Agenda com um dia útil só, hoje: hoje é o último dia útil da semana."""
    monkeypatch.setattr(review, "work_mask", lambda uid: 1 << ((hoje.weekday() + 1) % 7))


# ------------------------------------------------------------- regras puras --

def test_ultimo_dia_util_da_semana():
    qua = date(2026, 11, 4)                                     # semana de dom 01/11 a sáb 07/11
    assert review.week_bounds(qua) == (date(2026, 11, 1), date(2026, 11, 7))
    assert review.review_day(qua, 62) == date(2026, 11, 6)      # seg–sex: a sexta
    assert review.review_day(qua, 126) == date(2026, 11, 7)     # com sábado: o sábado
    assert review.review_day(qua, 1 | 2) == date(2026, 11, 2)   # dom e seg: a segunda
    assert review.review_day(date(2026, 11, 1), 62) == date(2026, 11, 6)  # domingo já é a semana nova
    assert review.review_day(qua, 0) is None


def test_parada_conta_dias_e_ignora_quem_tem_data():
    hoje = date(2026, 11, 10)
    tz = ZoneInfo(config.APP_TZ)
    def t(i, dias, follow=None, status="blocked"):
        return {"id": i, "title": f"T{i}", "status": status, "blocked_reason": None, "follow_up_on": follow,
                "blocked_at": datetime.combine(hoje - timedelta(days=dias), time(23, 30), tz).astimezone(timezone.utc)}
    abertas = [t(1, 4), t(2, 5), t(3, 12), t(4, 9, follow=hoje), t(5, 30, status="todo")]
    assert [(x["id"], x["days"]) for x in review.stale_waiting(abertas, hoje, 5)] == [(3, 12), (2, 5)]
    assert [x["id"] for x in review.stale_to_remind(abertas, hoje, 5)] == [3, 2]   # dia 5 e dia 12 (5 + 7)
    assert [x["id"] for x in review.stale_to_remind(abertas, hoje, 4)] == [1]      # 4 sim; 5 e 12 não
    assert review.stale_line({"title": "Peça", "days": 6}) == "«Peça» está aguardando há 6 dias. Quer marcar quando cobrar?"


# ---------------------------------------------------------------- revisão --

def test_revisao_da_semana_e_texto(usuario):
    hoje = dia_hoje(usuario)
    feita = usuario.post("/worklog", {"title": "Troca do nobreak", "status": "done", "resolution": "bateria nova"}).json()["id"]
    sem = usuario.post("/worklog", {"title": "Reset de senha", "status": "done"}).json()["id"]
    velha = usuario.post("/worklog", {"title": "Antiga", "status": "done",
                                      "created_at": (hoje - timedelta(days=9)).isoformat(),
                                      "completed_at": (hoje - timedelta(days=8)).isoformat()}).json()["id"]
    abertas = [usuario.post("/worklog", {"title": f"Aberta {i}", "priority": 1 if i == 3 else 2}).json()["id"] for i in range(4)]
    agu = usuario.post("/worklog", {"title": "Link da filial", "status": "blocked", "blocked_reason": "operadora"}).json()["id"]
    r = usuario.get("/review/week").json()
    assert r["week_start"] <= hoje.isoformat() <= r["week_end"] and r["done_at"] is None
    assert {t["id"] for t in r["done"]} == {feita, sem} and velha not in {t["id"] for t in r["done"]}
    assert next(t for t in r["done"] if t["id"] == sem)["resolution"] is None
    assert {t["id"] for t in r["open"]} == set(abertas) and [t["id"] for t in r["waiting"]] == [agu]
    assert len(r["suggestions"]) == 3 and r["suggestions"][0] == abertas[3]  # prioridade alta primeiro
    res = usuario.post("/review/week/done", {"next": [abertas[1], 999999]})
    assert res.status_code == 200 and res.json()["done_at"]
    txt = res.json()["text"]
    assert "O que fechou (2):" in txt and "Troca do nobreak — bateria nova" in txt
    assert "O que ficou (4):" in txt and "Link da filial — operadora" in txt
    assert "O que vem na próxima semana:\n- Aberta 1" in txt and "999999" not in txt
    assert usuario.get("/review/week").json()["done_at"]
    assert usuario.post("/review/week/done", {"next": [1, 2, 3, 4]}).status_code == 422  # até 3


def test_convite_so_no_ultimo_dia_util_e_uma_vez(usuario, monkeypatch):
    hoje = dia_hoje(usuario)
    assert usuario.get("/summary").json()["review"]["invite"] is (review.review_day(hoje, 62) == hoje)
    _so_hoje_util(monkeypatch, hoje)
    assert usuario.get("/summary").json()["review"]["invite"] is True
    assert usuario.post("/review/week/dismiss").json()["dismissed_at"]   # "Agora não"
    assert usuario.get("/summary").json()["review"]["invite"] is False
    # Dispensar não conta como feita; fazer depois continua valendo.
    assert usuario.get("/summary").json()["review"]["reviewed"] is False
    usuario.post("/review/week/done")
    assert usuario.get("/summary").json()["review"]["reviewed"] is True
    # Na semana seguinte, o convite volta.
    monkeypatch.setattr(review, "app_today", lambda: hoje + timedelta(days=7))
    assert review.hints(uid_de(usuario))["invite"] is True


def test_revisao_feita_sem_dispensar_tambem_cala_o_convite(usuario, monkeypatch):
    _so_hoje_util(monkeypatch, dia_hoje(usuario))
    usuario.post("/review/week/done")
    assert usuario.get("/summary").json()["review"]["invite"] is False


def test_revisao_e_da_propria_pessoa(usuario, novo_usuario):
    usuario.post("/worklog", {"title": "Só minha", "status": "done"})
    outro = novo_usuario("outro@example.com")
    assert outro.get("/review/week").json()["done"] == []
    outro.post("/review/week/done")
    assert usuario.get("/review/week").json()["done_at"] is None
    leitura = Bearer(criar_chave(usuario, nome="r", scope="read")["token"])
    assert leitura.get("/review/week").status_code == 200
    assert leitura.post("/review/week/done").status_code == 403   # registrar é escrita


def test_mcp_get_week_review(usuario):
    usuario.post("/worklog", {"title": "Backup restaurado", "status": "done"})
    usuario.post("/worklog", {"title": "Trocar crachá"})
    tid = usuario.post("/worklog", {"title": "Peça do switch", "status": "blocked"}).json()["id"]
    _aguardando_ha(tid, 9)
    ia = Bearer(criar_chave(usuario, nome="r", scope="read")["token"])
    nomes = {t["name"] for t in ia.rpc("tools/list").json()["result"]["tools"]}
    assert "get_week_review" in nomes
    out = texto(ia.tool("get_week_review"))
    assert "Backup restaurado (sem \"como resolveu\")" in out
    assert "Sugestões para a próxima semana:" in out and "Trocar crachá" in out
    assert "Peça do switch (há 9 dias)" in out


# ---------------------------------------------------------- tarefa parada --

def test_parada_no_hoje_e_configuracao(usuario):
    tid = usuario.post("/worklog", {"title": "Peça do switch", "status": "blocked", "blocked_reason": "fornecedor"}).json()["id"]
    assert usuario.get("/summary").json()["review"]["stale"] == []
    _aguardando_ha(tid, 6)
    rv = usuario.get("/summary").json()["review"]
    assert rv["stale_days"] == 5 and rv["stale"] == [{"id": tid, "title": "Peça do switch", "blocked_reason": "fornecedor", "days": 6}]
    # Configurações > Conta: avisar com 7 dias.
    prefs = usuario.get("/auth/me").json()["assistant"]
    assert prefs["stale_days"] == 5
    assert usuario.put("/me/assistant", {**prefs, "stale_days": 7}).json()["stale_days"] == 7
    assert usuario.get("/summary").json()["review"]["stale"] == []
    assert usuario.put("/me/assistant", {**prefs, "stale_days": 0}).status_code == 422
    assert usuario.put("/me/assistant", {**prefs, "stale_days": 61}).status_code == 422
    usuario.put("/me/assistant", {**prefs, "stale_days": 5})
    # Com dia para cobrar, sai do aviso (a cobrança tem aviso próprio).
    usuario.patch(f"/worklog/{tid}", {"follow_up_on": (dia_hoje(usuario) + timedelta(days=2)).isoformat()})
    assert usuario.get("/summary").json()["review"]["stale"] == []


def test_parada_no_email_da_manha_so_no_dia_n(usuario):
    hoje, uid = dia_hoje(usuario), uid_de(usuario)
    tid = usuario.post("/worklog", {"title": "Peça do switch", "status": "blocked"}).json()["id"]
    def bloco():
        return [i for h, itens in notify.build_morning(uid, hoje, True).blocks if h == "Aguardando faz tempo" for i in itens]
    _aguardando_ha(tid, 5)
    assert bloco() == ["«Peça do switch» está aguardando há 5 dias. Quer marcar quando cobrar?"]
    _aguardando_ha(tid, 6)
    assert bloco() == []                     # não repete todo dia
    _aguardando_ha(tid, 12)
    assert len(bloco()) == 1                 # uma semana depois, de novo


def test_parada_no_push_da_manha(usuario, monkeypatch):
    enviados = []
    monkeypatch.setattr(push, "send", lambda uid, msg: enviados.append(msg))
    hoje = dia_hoje(usuario)
    usuario.post("/auth/settings", {"work_days": 127})
    tid = usuario.post("/worklog", {"title": "Peça do switch", "status": "blocked"}).json()["id"]
    _aguardando_ha(tid, 5)
    p = push.prefs(uid_de(usuario))
    agora = datetime.combine(hoje, time(8, 0), tzinfo=ZoneInfo(config.APP_TZ))
    assert push._morning(uid_de(usuario), p, agora, 127) == ["parada"]
    assert enviados[0]["title"] == "Aguardando faz tempo" and "há 5 dias" in enviados[0]["body"]
    assert push._morning(uid_de(usuario), p, agora, 127) == []   # uma vez por dia
