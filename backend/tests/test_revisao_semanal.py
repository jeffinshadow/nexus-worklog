"""Revisão semanal guiada (último dia útil, revisão feita/dispensada, texto da
semana, MCP). A "tarefa parada" não é mais um aviso próprio: o Aguardando sugere o dia de cobrar."""
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
    assert "Aguardando há" not in out      # sem aviso de tarefa parada


# ------------------------------------------- aguardando: cobrar em 5 dias úteis --

def test_aguardando_sem_aviso_de_parada_e_com_dia_sugerido(usuario):
    hoje = dia_hoje(usuario)
    tid = usuario.post("/worklog", {"title": "Peça do switch", "status": "blocked", "blocked_reason": "fornecedor"}).json()["id"]
    _aguardando_ha(tid, 12)
    rv = usuario.get("/summary").json()["review"]
    assert "stale" not in rv and "stale_days" not in rv and "invite" in rv     # nada de "tarefa parada"
    assert "stale" not in usuario.get("/review/week").json()
    # O diálogo Aguardando já traz o dia para cobrar: 5 dias úteis à frente (a interface soma; o servidor aceita).
    d = hoje
    for _ in range(5):
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
    novo = usuario.post("/worklog", {"title": "Aprovação", "status": "blocked", "blocked_reason": "gestor", "follow_up_on": d.isoformat()})
    assert novo.status_code == 201
    nid = novo.json()["id"]
    assert usuario.get(f"/worklog/{nid}").json()["follow_up_on"] == d.isoformat()
    # O dia é editável e pode ser limpo.
    assert usuario.patch(f"/worklog/{nid}", {"follow_up_on": None}).status_code == 200
    assert usuario.get(f"/worklog/{nid}").json()["follow_up_on"] is None
    # Os avisos da manhã (e-mail e push) não têm mais o bloco de tarefa parada.
    assert "Aguardando faz tempo" not in [h for h, _ in notify.build_morning(uid_de(usuario), hoje, True).blocks]
    assert not hasattr(review, "stale_waiting") and not hasattr(push, "stale_to_remind")
