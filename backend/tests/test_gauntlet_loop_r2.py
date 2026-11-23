"""Gauntlet loop, rodada 2: achados dos críticos nas áreas que a rodada 1 não tocou.

Datas fora de faixa, o que quem acompanha a equipe não recebe, vencimento de quem
saiu da equipe, chave de API de admin, cronômetro tudo ou nada, mês inválido e os
avisos de agenda que não se regravam."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import agenda, db
from app.config import config
from conftest import Bearer, criar_chave, dia_hoje, uid_de


def _equipe(admin, nome, *membros):
    r = admin.post("/admin/teams", {"name": nome, "member_ids": [uid_de(m) for m in membros]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_datas_fora_de_faixa_sao_recusadas_e_as_antigas_nao_derrubam_nada(usuario):
    assert usuario.post("/worklog", {"title": "Prazo sem fim", "due_date": "9999-12-31"}).status_code == 422
    assert usuario.post("/renewals", {"label": "Domínio", "expires_on": "0001-01-01"}).status_code == 422
    assert usuario.post("/renewals", {"label": "Domínio", "expires_on": "9999-12-31"}).status_code == 422
    t = usuario.post("/worklog", {"title": "Prazo normal", "due_date": "2030-05-10"}).json()
    assert usuario.patch(f"/worklog/{t['id']}", {"due_date": "2500-01-01"}).status_code == 422
    rid = usuario.post("/renewals", {"label": "Certificado", "expires_on": "2030-05-10"}).json()["id"]
    assert usuario.patch(f"/renewals/{rid}", {"expires_on": "0001-06-01"}).status_code == 422
    # Gravadas antes do limite (direto no banco): as telas e o calendário continuam de pé.
    db.execute("UPDATE worklog_tasks SET due_date = DATE '9999-12-31' WHERE id = %s", (t["id"],))
    db.execute("UPDATE renewals SET expires_on = DATE '0001-01-10' WHERE id = %s", (rid,))
    assert usuario.get("/renewals").status_code == 200
    assert usuario.get("/summary/handoff").status_code == 200
    path = usuario.post("/calendar", {"include_recurring": True}).json()["path"]
    ics = usuario.c.get(path)
    # Os eventos das datas absurdas (ano 9999 e ano 1) ficam de fora; o feed sai.
    assert ics.status_code == 200 and "Prazo normal" not in ics.text and "Certificado" not in ics.text


def test_quem_acompanha_nao_recebe_ranking_nem_backlog(admin, usuario):
    usuario.put("/me/viewers", {"accept": True})
    # Todo dia: o padrão (dias úteis) não é devido no sábado e no domingo, e o teste falhava no fim de semana.
    rid = usuario.post("/recurring", {"label": "Ronda", "freq": "weekly", "weekdays": 127}).json()["id"]
    usuario.post(f"/recurring/{rid}/toggle", {"done": True})
    usuario.post("/worklog", {"title": "Aberta"})
    uid = uid_de(usuario)
    mes = dia_hoje(usuario).strftime("%Y-%m")
    for url in (f"/viewer/users/{uid}/dashboard", f"/viewer/users/{uid}/dashboard?month={mes}"):
        r = admin.get(url)
        assert r.status_code == 200, r.text
        assert r.json()["task_adherence"] == {"tasks": []} and r.json()["backlog"] is None
    # A própria pessoa continua recebendo os dela.
    meu = usuario.get("/dashboard").json()
    assert meu["task_adherence"]["tasks"] and meu["backlog"] is not None


def test_vencimento_da_equipe_some_quando_quem_criou_sai_dela(admin, novo_usuario):
    ana, bia = novo_usuario("ana@example.com"), novo_usuario("bia@example.com")
    tid = _equipe(admin, "Infra", ana, bia)
    venc = (dia_hoje(ana) + timedelta(days=40)).isoformat()
    rid = ana.post("/renewals", {"label": "Certificado", "expires_on": venc, "team_id": tid}).json()["id"]
    assert [r["id"] for r in bia.get("/renewals").json()] == [rid]
    # Ana muda de setor: sai da equipe. O vencimento continua dela, mas a equipe antiga não vê mais.
    assert admin.put(f"/admin/users/{uid_de(ana)}/teams", {"team_ids": []}).status_code == 200
    assert bia.get("/renewals").json() == []
    assert bia.patch(f"/renewals/{rid}", {"expires_on": venc}).status_code == 404
    assert [r["id"] for r in ana.get("/renewals").json()] == [rid]


def test_chave_de_api_de_admin_nao_edita_vencimento_alheio(admin, novo_usuario):
    ana = novo_usuario("ana@example.com")
    tid = _equipe(admin, "Infra", ana)
    assert admin.put(f"/admin/users/{uid_de(admin)}/teams", {"team_ids": [tid]}).status_code == 200
    venc = (dia_hoje(ana) + timedelta(days=40)).isoformat()
    rid = ana.post("/renewals", {"label": "Licença", "expires_on": venc, "team_id": tid}).json()["id"]
    chave = Bearer(criar_chave(admin)["token"])
    assert chave.patch(f"/renewals/{rid}", {"label": "Outro nome"}).status_code == 403
    assert chave.delete(f"/renewals/{rid}").status_code == 403
    assert chave.patch(f"/renewals/{rid}", {"expires_on": venc}).status_code == 200  # renovar, como qualquer membro
    assert admin.patch(f"/renewals/{rid}", {"label": "Licença anual"}).status_code == 200  # pelo app, o admin edita


def test_parar_cronometro_e_tudo_ou_nada(usuario, monkeypatch):
    from app.routers import timer as tmod
    t = usuario.post("/worklog", {"title": "Atendimento"}).json()
    assert usuario.post("/timer/start", {"task_id": t["id"]}).status_code == 200
    db.execute("UPDATE task_timers SET started_at = now() - interval '30 minutes'")

    def quebra(*a, **k):
        raise RuntimeError("falha ao apontar")
    monkeypatch.setattr(tmod, "log_time", quebra)
    with pytest.raises(RuntimeError):
        usuario.post("/timer/stop")
    # O cronômetro continua rodando: o tempo não se perdeu.
    assert usuario.get("/timer").json()["timer"]["task_id"] == t["id"]
    monkeypatch.undo()
    r = usuario.post("/timer/stop")
    assert r.status_code == 200 and r.json()["stopped"]["minutes"] == 30
    assert usuario.get("/timer").json()["timer"] is None
    # Iniciar de novo com um cronômetro que ficou no banco (outro aparelho, ao mesmo tempo): sem erro.
    outra = usuario.post("/worklog", {"title": "Outra"}).json()
    assert usuario.post("/timer/start", {"task_id": t["id"]}).status_code == 200
    assert usuario.post("/timer/start", {"task_id": outra["id"]}).status_code == 200
    assert usuario.get("/timer").json()["timer"]["task_id"] == outra["id"]


def test_mes_com_ano_absurdo_responde_400(usuario):
    assert usuario.get("/dashboard?month=0001-01").status_code == 400
    assert usuario.get("/dashboard?month=0000-05").status_code == 400
    assert usuario.get("/dashboard?month=" + dia_hoje(usuario).strftime("%Y-%m")).status_code == 200


def test_aviso_de_agenda_nao_gasta_o_historico_a_cada_minuto(usuario):
    criar_chave(usuario)  # os avisos de agenda só saem para quem tem chave ou webhook
    hoje = dia_hoje(usuario)
    t = usuario.post("/worklog", {"title": "Peça", "status": "blocked", "blocked_reason": "fornecedor",
                                  "follow_up_on": hoje.isoformat()}).json()
    agora = datetime.combine(hoje, time(10, 0), tzinfo=ZoneInfo(config.APP_TZ))
    feitos = agenda.run_once(agora)
    assert (uid_de(usuario), f"followup:{t['id']}") in feitos
    topo = db.query_one("SELECT max(id) AS m FROM audit_log")["m"]
    assert agenda.run_once(agora + timedelta(minutes=1)) == []
    usuario.post("/worklog", {"title": "Depois"})
    # O id seguinte é o vizinho: a segunda passada não gastou número nenhum do histórico.
    assert db.query_one("SELECT max(id) AS m FROM audit_log")["m"] == topo + 1
