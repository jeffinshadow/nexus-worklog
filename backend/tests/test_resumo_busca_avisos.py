"""Resumos, busca, exportação, calendário (ICS) e avisos por e-mail."""
import json
from datetime import date, datetime, timedelta

from app import db, notify
from conftest import Bearer, criar_chave, dia_hoje, recuar_criacao, uid_de


# ------------------------------------------------------------------ resumos --

def test_resumo_semana_e_ultimo_dia(usuario):
    pid = usuario.post("/projects", {"name": "Cliente X"}).json()["id"]
    tid = usuario.post("/worklog", {"title": "Entregue hoje", "project_id": pid}).json()["id"]
    usuario.post(f"/worklog/{tid}/time", {"minutes": 90})
    usuario.post(f"/worklog/{tid}/finish")
    s = usuario.get("/summary").json()
    assert s["week"]["pontual_done"] == 1 and s["week"]["minutes"] == 90
    assert s["week"]["deliveries"][0]["title"] == "Entregue hoje"
    assert s["week"]["projects"][0]["name"] == "Cliente X"
    assert "previous" in s["week"] and s["week"]["previous"]["pontual_done"] == 0
    assert date.fromisoformat(s["last_day"]["start"]) < dia_hoje(usuario)


def test_resumo_igual_aos_relatorios_separados(usuario):
    """O resumo lê o banco uma vez e recorta os quatro períodos: tem que dar
    exatamente o que dariam quatro relatórios independentes."""
    from app import services
    uid, hoje = uid_de(usuario), dia_hoje(usuario)
    pid = usuario.post("/projects", {"name": "Cliente Y"}).json()["id"]
    diaria = usuario.post("/recurring", {"label": "Backup"}).json()["id"]
    semanal = usuario.post("/recurring", {"label": "Relatório", "freq": "weekly", "weekdays": 0b1010}).json()["id"]
    for r in (diaria, semanal):
        recuar_criacao(r, 30)
    for i in range(0, 16):
        d = hoje - timedelta(days=i)
        if i % 3:  # falha um dia a cada três
            db.execute("INSERT INTO recurring_completions (task_id, user_id, completed_date, note) VALUES (%s, %s, %s, %s)",
                       (diaria, uid, d, "ok" if i % 2 else None))
        if i % 4 == 0:
            db.execute("INSERT INTO recurring_completions (task_id, user_id, completed_date) VALUES (%s, %s, %s)", (semanal, uid, d))
        tid = usuario.post("/worklog", {"title": f"Tarefa {i}", "project_id": pid if i % 2 else None}).json()["id"]
        db.execute("""UPDATE worklog_tasks SET status = 'done', created_at = %s::date + time '09:00',
                      completed_at = %s::date + time '15:00' WHERE id = %s""", (d, d, tid))
        db.execute("INSERT INTO time_entries (task_id, user_id, minutes, day) VALUES (%s, %s, %s, %s)", (tid, uid, 30 + i, d))
    usuario.post("/worklog", {"title": "Ainda aberta", "project_id": pid})

    s = services.get_summary(uid)
    mask = services.work_mask(uid)
    ws = services.week_start(hoje)
    prev_s = ws - timedelta(days=7)
    um = lambda a, b: services._compact(services.get_report_range(uid, a, b))
    week, prev = um(ws, hoje), um(prev_s, prev_s + (hoje - ws))
    week["previous"] = {k: prev[k] for k in ("recurring_done", "recurring_total", "pontual_done", "minutes", "start", "end")}
    assert s == {"today": hoje, "last_day": um(services.last_work_day(hoje, mask), hoje - timedelta(days=1)),
                 "week": week, "today_stats": um(hoje, hoje)}
    assert s["week"]["minutes"] > 0 and s["last_day"]["recurring_total"] > 0


# -------------------------------------------------------------------- busca --

def test_busca_sem_acento_em_tudo(usuario, novo_usuario):
    tid = usuario.post("/worklog", {"title": "Migração do Exchange", "description": "caixas do financeiro"}).json()["id"]
    outra = usuario.post("/worklog", {"title": "Outra coisa"}).json()["id"]
    usuario.post(f"/worklog/{outra}/notes", {"body": "Lembrar da MIGRACAO das regras de transporte"})
    usuario.post(f"/worklog/{outra}/checklist", {"label": "Testar migração"})
    usuario.post("/recurring", {"label": "Conferir migração pendente"})
    usuario.post("/projects", {"name": "Migração 2026"})

    r = usuario.get("/search?q=migracao").json()
    ids = [t["id"] for t in r["tasks"]]
    assert set(ids) == {tid, outra}
    kinds = {h["kind"] for t in r["tasks"] for h in t["hits"]}
    assert {"título", "anotação", "checklist"} <= kinds
    assert r["recurring"][0]["label"].startswith("Conferir") and r["projects"][0]["name"] == "Migração 2026"

    assert usuario.get("/search?q=FINANCEIRO").json()["tasks"][0]["hits"][0]["kind"] == "descrição"
    assert usuario.get("/search?q=a").status_code == 422
    assert usuario.get("/search?q=%25%25").json()["tasks"] == []  # curinga do LIKE não vaza
    outro = novo_usuario("outro@example.com")
    assert outro.get("/search?q=migracao").json()["tasks"] == []


# --------------------------------------------------------------- exportação --

def test_exportacoes(usuario):
    pid = usuario.post("/projects", {"name": "Loja"}).json()["id"]
    tid = usuario.post("/worklog", {"title": "Cabear; testar", "project_id": pid}).json()["id"]
    usuario.post(f"/worklog/{tid}/time", {"minutes": 75, "note": "lado norte"})
    usuario.post(f"/worklog/{tid}/notes", {"body": "ok"})
    usuario.post("/recurring", {"label": "Backup"})

    r = usuario.get("/export/apontamentos.csv")
    assert r.status_code == 200 and r.content.startswith("﻿".encode())
    linhas = r.content.decode("utf-8-sig").splitlines()
    assert linhas[0].startswith("data;minutos;horas") and ";75;1,25;" in linhas[1] and "lado norte" in linhas[1]

    t = usuario.get("/export/tarefas.csv").content.decode("utf-8-sig")
    assert '"Cabear; testar"' in t  # campo com ; vem entre aspas

    j = json.loads(usuario.get("/export/tudo.json").content)
    assert j["tasks"][0]["notes"][0]["body"] == "ok" and j["tasks"][0]["time"][0]["minutes"] == 75
    assert j["recurring"][0]["label"] == "Backup" and j["projects"][0]["name"] == "Loja"
    assert "password_hash" not in json.dumps(j)
    assert usuario.get("/export/senhas.txt").status_code == 404


# --------------------------------------------------------------- calendário --

def test_calendario_ics(usuario, novo_usuario):
    hoje = dia_hoje(usuario)
    usuario.post("/worklog", {"title": "Renovar certificado, urgente", "due_date": (hoje + timedelta(days=3)).isoformat(), "priority": 1})
    usuario.post("/worklog", {"title": "Sem prazo"})
    usuario.post("/recurring", {"label": "Backup off-site", "freq": "weekly", "weekdays": 0b0100010})
    usuario.post("/recurring", {"label": "Fechamento", "freq": "monthly", "month_day": 31})
    usuario.post("/recurring", {"label": "Dia 30", "freq": "monthly", "month_day": 30})

    assert usuario.get("/calendar").json()["active"] is False
    r = usuario.post("/calendar", {"include_recurring": True})
    assert r.status_code == 201
    path = r.json()["path"]
    assert path.startswith("/api/calendar/nxc_") and path.endswith(".ics")

    anon = usuario.c.__class__(usuario.c.app, base_url="http://testserver")  # sem cookie
    ics = anon.get(path)
    assert ics.status_code == 200 and ics.headers["content-type"].startswith("text/calendar")
    body = ics.text
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert "SUMMARY:Prazo: Renovar certificado\\, urgente" in body and "PRIORITY:1" in body
    assert f"DTSTART;VALUE=DATE:{(hoje + timedelta(days=3)):%Y%m%d}" in body
    assert "Sem prazo" not in body
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO,FR" in body
    assert "RRULE:FREQ=MONTHLY;BYMONTHDAY=-1" in body
    assert "RRULE:FREQ=MONTHLY;BYMONTHDAY=28,29,30;BYSETPOS=-1" in body
    assert all(len(l.encode()) <= 75 for l in body.split("\r\n"))

    usuario.patch("/calendar", {"include_recurring": False})
    assert "RRULE" not in anon.get(path).text

    novo = usuario.post("/calendar", {"include_recurring": True}).json()["path"]
    assert anon.get(path).status_code == 404 and anon.get(novo).status_code == 200  # trocar invalida o antigo
    usuario.delete("/calendar")
    assert anon.get(novo).status_code == 404
    assert anon.get("/api/calendar/qualquer.ics").status_code == 404

    b = Bearer(criar_chave(usuario)["token"])
    assert b.post("/calendar", {"include_recurring": True}).status_code == 403  # chave de API não gerencia


# ------------------------------------------------------------------- avisos --

class Caixa:
    def __init__(self, falha=False):
        self.enviados, self.falha = [], falha

    def __call__(self, to, subject, text, html):
        if self.falha:
            raise RuntimeError("smtp fora do ar")
        self.enviados.append({"to": to, "subject": subject, "text": text, "html": html})


def _proxima(d: date, weekday: int) -> date:
    return d + timedelta(days=(weekday - d.weekday()) % 7 or 7)


def test_preferencias_e_teste_sem_smtp(usuario):
    p = usuario.get("/notifications").json()
    assert p["morning"] is False and p["mail_configured"] is False and p["email"] == usuario.me["email"]
    r = usuario.c.put("/api/notifications", json={"morning": True, "morning_hour": 7, "weekly": True}, headers=usuario._h())
    assert r.status_code == 200 and r.json()["morning_hour"] == 7
    assert usuario.post("/notifications/test").status_code == 503
    assert usuario.c.put("/api/notifications", json={"morning_hour": 24}, headers=usuario._h()).status_code == 422
    h = usuario.get("/history?limit=1").json()[0]
    assert h["action"] == "notifications.update" and not h["can_undo"]


def test_aviso_da_manha_sai_uma_vez(usuario):
    uid = uid_de(usuario)
    segunda = _proxima(dia_hoje(usuario), 0)
    usuario.post("/worklog", {"title": "Prazo de segunda", "due_date": segunda.isoformat()})
    usuario.post("/worklog", {"title": "Já atrasada", "due_date": (dia_hoje(usuario) - timedelta(days=2)).isoformat()})
    usuario.post("/recurring", {"label": "Conferir backups"})
    usuario.c.put("/api/notifications", json={"morning": True, "morning_hour": 8}, headers=usuario._h())

    caixa = Caixa()
    assert notify.run_once(datetime(segunda.year, segunda.month, segunda.day, 7, 50), caixa) == []  # antes da hora
    feito = notify.run_once(datetime(segunda.year, segunda.month, segunda.day, 8, 1), caixa)
    assert feito == [(uid, "morning", "sent")]
    m = caixa.enviados[0]
    assert m["to"] == usuario.me["email"] and "Prazo de segunda" in m["text"] and "Já atrasada" in m["text"]
    assert "Conferir backups" in m["text"] and "<html" in m["html"] and "Abrir o Nexus" in m["html"]
    assert notify.run_once(datetime(segunda.year, segunda.month, segunda.day, 9, 0), caixa) == []  # não repete
    assert len(caixa.enviados) == 1

    domingo = segunda + timedelta(days=6)  # não útil: não sai
    assert notify.run_once(datetime(domingo.year, domingo.month, domingo.day, 8, 5), caixa) == []
    terca = segunda + timedelta(days=1)  # backend voltou às 11h: passou da janela de 2h
    assert notify.run_once(datetime(terca.year, terca.month, terca.day, 11, 0), caixa) == []


def test_aviso_sem_titulos_e_falha_registrada(usuario):
    uid = uid_de(usuario)
    segunda = _proxima(dia_hoje(usuario), 0)
    usuario.post("/worklog", {"title": "Segredo do cliente", "due_date": segunda.isoformat()})
    usuario.c.put("/api/notifications", json={"morning": True, "morning_hour": 8, "show_titles": False}, headers=usuario._h())
    caixa = Caixa()
    notify.run_once(datetime(segunda.year, segunda.month, segunda.day, 8, 0), caixa)
    assert "Segredo" not in caixa.enviados[0]["text"] and "Vencem hoje: 1" in caixa.enviados[0]["text"]

    terca = segunda + timedelta(days=1)
    usuario.post("/worklog", {"title": "Outra", "due_date": terca.isoformat()})
    assert notify.run_once(datetime(terca.year, terca.month, terca.day, 8, 0), Caixa(falha=True)) == [(uid, "morning", "error")]
    log = db.query_one("SELECT ok, error FROM notification_log WHERE user_id = %s AND ref_date = %s", (uid, terca))
    assert log["ok"] is False and "smtp fora do ar" in log["error"]


def test_aviso_da_tarde_e_semanal(usuario):
    uid = uid_de(usuario)
    hoje = dia_hoje(usuario)
    rid = usuario.post("/recurring", {"label": "Revisar fila"}).json()["id"]
    recuar_criacao(rid, 10)
    usuario.c.put("/api/notifications", json={"evening": True, "evening_hour": 17, "weekly": True, "weekly_hour": 8},
                  headers=usuario._h())
    segunda = _proxima(hoje, 0)
    caixa = Caixa()
    # semanal: só às segundas, na hora escolhida (resumo da semana anterior)
    assert notify.run_once(datetime(segunda.year, segunda.month, segunda.day, 8, 5), caixa) == [(uid, "weekly", "sent")]
    assert caixa.enviados[0]["subject"].startswith("Sua semana") and "Revisar fila" in caixa.enviados[0]["text"]
    feito = notify.run_once(datetime(segunda.year, segunda.month, segunda.day, 17, 30), caixa)
    assert feito == [(uid, "evening", "sent")]
    assert "Revisar fila" in caixa.enviados[1]["text"] and caixa.enviados[1]["subject"].startswith("Faltam 1 rotina")
    terca = segunda + timedelta(days=1)
    assert all(k != "weekly" for _, k, _ in notify.run_once(datetime(terca.year, terca.month, terca.day, 9, 0), caixa))


def test_busca_pela_ia(usuario):
    tid = usuario.post("/worklog", {"title": "Migração do Exchange"}).json()["id"]
    usuario.post(f"/worklog/{tid}/notes", {"body": "faltam as caixas compartilhadas"})
    b = Bearer(criar_chave(usuario, scope="read")["token"])
    res = b.tool("search", query="compartilhadas")
    texto = res["content"][0]["text"]
    assert not res["isError"] and f"#{tid} Migração do Exchange" in texto and "anotação: faltam as caixas" in texto
    assert b.tool("search", query="x")["isError"]
