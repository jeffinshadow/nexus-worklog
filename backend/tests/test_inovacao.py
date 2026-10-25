"""Inovação (lote 1): evidência na rotina, impedimento, passagem de turno e aviso a quem atribuiu."""
from datetime import timedelta

from app import mailer
from app.routers import assign as assign_mod
from conftest import Bearer, criar_chave, dia_hoje, hist, recuar_criacao, texto, uid_de


def _rotina(u, label="Conferir backup"):
    return u.post("/recurring", {"label": label}).json()["id"]


def _da_rotina(u, rid, day=None):
    q = f"?day={day}" if day else ""
    return [r for r in u.get(f"/board{q}").json()["recurring"] if r["id"] == rid][0]


def test_evidencia_na_rotina_e_desfazer(usuario):
    rid = _rotina(usuario)
    r = usuario.post(f"/recurring/{rid}/toggle", {"done": True, "note": "  backup OK,   2,1 TB "})
    assert r.status_code == 200 and r.json()["note"] == "backup OK, 2,1 TB"
    assert _da_rotina(usuario, rid)["note"] == "backup OK, 2,1 TB"
    # Remarcar sem nota mantém; com nota, troca (e o histórico guarda o antes).
    usuario.post(f"/recurring/{rid}/toggle", {"done": True})
    assert _da_rotina(usuario, rid)["note"] == "backup OK, 2,1 TB"
    usuario.post(f"/recurring/{rid}/toggle", {"done": True, "note": "backup OK, 2,3 TB"})
    h = [x for x in hist(usuario, entity="recurring", entity_id=rid)][0]
    assert "evidência" in h["summary"] and h["can_undo"]
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert _da_rotina(usuario, rid)["note"] == "backup OK, 2,1 TB"
    # Desmarcar e desfazer devolve a evidência.
    usuario.post(f"/recurring/{rid}/toggle", {"done": False})
    h = [x for x in hist(usuario, entity="recurring", entity_id=rid)][0]
    usuario.post(f"/history/{h['id']}/undo")
    assert _da_rotina(usuario, rid)["note"] == "backup OK, 2,1 TB"
    assert usuario.post(f"/recurring/{rid}/toggle", {"done": True, "note": "x" * 201}).status_code == 422
    # Mandar vazio apaga a evidência (corrigir um engano).
    usuario.post(f"/recurring/{rid}/toggle", {"done": True, "note": ""})
    assert _da_rotina(usuario, rid)["note"] is None


def test_evidencia_no_relatorio_e_export(usuario):
    rid = _rotina(usuario, "Revisar alertas")
    recuar_criacao(rid, 3)
    ontem = (dia_hoje(usuario) - timedelta(days=1)).isoformat()
    usuario.post(f"/recurring/{rid}/toggle", {"done": True, "day": ontem, "note": "3 alertas, nenhum crítico"})
    pdf = usuario.get(f"/reports/export?start={ontem}&end={ontem}")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    js = usuario.get("/export/tudo.json").json()
    rec = [r for r in js["recurring"] if r["label"] == "Revisar alertas"][0]
    assert rec["evidence"][0]["note"] == "3 alertas, nenhum crítico"


def test_impedimento_com_motivo(usuario):
    tid = usuario.post("/worklog", {"title": "Trocar link", "status": "blocked", "blocked_reason": "operadora"}).json()["id"]
    t = usuario.get(f"/worklog/{tid}").json()
    assert t["blocked_reason"] == "operadora" and t["blocked_at"]
    usuario.patch(f"/worklog/{tid}", {"blocked_reason": "visita técnica da operadora"})
    assert usuario.get(f"/worklog/{tid}").json()["blocked_reason"] == "visita técnica da operadora"
    usuario.patch(f"/worklog/{tid}", {"status": "in_progress"})
    t = usuario.get(f"/worklog/{tid}").json()
    assert t["blocked_reason"] is None and t["blocked_at"] is None
    # Desfazer volta o bloqueio com o motivo.
    h = [x for x in hist(usuario, entity="worklog", entity_id=tid) if x["action"] == "worklog.update"][0]
    usuario.post(f"/history/{h['id']}/undo")
    assert usuario.get(f"/worklog/{tid}").json()["blocked_reason"] == "visita técnica da operadora"
    # Motivo fora de bloqueio é ignorado na criação.
    t2 = usuario.post("/worklog", {"title": "x", "blocked_reason": "nada"}).json()["id"]
    assert usuario.get(f"/worklog/{t2}").json()["blocked_reason"] is None


def test_passagem_de_turno_app_e_mcp(usuario):
    usuario.post("/worklog", {"title": "Firewall da filial", "status": "blocked", "blocked_reason": "aprovação da diretoria"})
    usuario.post("/worklog", {"title": "Impressora do RH", "ticket": "4821"})
    fim = usuario.post("/worklog", {"title": "Reset de senha"}).json()["id"]
    usuario.patch(f"/worklog/{fim}", {"after_hours": True})
    usuario.post(f"/worklog/{fim}/finish")
    txt = usuario.get("/summary/handoff").json()["text"]
    assert "Passagem de turno" in txt and "aguardando aprovação da diretoria" in txt
    assert "Impressora do RH (chamado 4821)" in txt and "Reset de senha (plantão)" in txt
    ia = Bearer(criar_chave(usuario)["token"])
    assert "aguardando aprovação da diretoria" in texto(ia.tool("get_handoff"))
    assert "(aguardando aprovação da diretoria)" in texto(ia.tool("list_tasks"))


def test_mcp_evidencia(usuario):
    rid = _rotina(usuario)
    ia = Bearer(criar_chave(usuario)["token"])
    res = ia.tool("set_recurring", recurring_id=rid, note="ok, 12 jobs")
    assert not res["isError"] and "Evidência: ok, 12 jobs" in texto(res)


def test_aviso_a_quem_atribuiu(admin, usuario, novo_usuario, monkeypatch):
    caixa = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(assign_mod, "_spawn", lambda to, mail: caixa.append((to, mail.subject)))
    chefe = novo_usuario("chefe@example.com")
    admin.put(f"/admin/users/{uid_de(chefe)}/roles", {"roles": ["user", "assigner"]})
    usuario.put("/me/assignments", {"accept": True})
    tid = chefe.post("/assign", {"user_id": uid_de(usuario), "title": "Inventário"}).json()["id"]
    caixa.clear()
    usuario.post(f"/worklog/{tid}/finish")
    assert caixa == [("chefe@example.com", "Concluída: Inventário")]
    # Editar a tarefa já concluída não manda de novo.
    usuario.patch(f"/worklog/{tid}", {"title": "Inventário do CPD"})
    assert len(caixa) == 1
    # Reabrir e concluir de novo não manda outra vez.
    usuario.patch(f"/worklog/{tid}", {"status": "todo"})
    usuario.patch(f"/worklog/{tid}", {"status": "done"})
    assert len(caixa) == 1
    # Tarefa própria (não atribuída) não avisa ninguém.
    t2 = usuario.post("/worklog", {"title": "Minha"}).json()["id"]
    usuario.post(f"/worklog/{t2}/finish")
    assert len(caixa) == 1


def test_rotina_exige_evidencia(usuario):
    rid = usuario.post("/recurring", {"label": "Revisão de acessos", "require_note": True}).json()["id"]
    r = usuario.post(f"/recurring/{rid}/toggle", {"done": True})
    assert r.status_code == 400 and "evidência" in r.json()["detail"]
    assert usuario.post(f"/recurring/{rid}/toggle", {"done": True, "note": "  "}).status_code == 400
    assert usuario.post(f"/recurring/{rid}/toggle", {"done": True, "note": "3 contas revogadas"}).status_code == 200
    assert _da_rotina(usuario, rid)["require_note"] is True
    # Desligar a exigência pelo PATCH (rotina criada hoje: muda no lugar) e desfazer.
    usuario.patch(f"/recurring/{rid}", {"require_note": False})
    assert _da_rotina(usuario, rid)["require_note"] is False
    h = [x for x in hist(usuario, entity="recurring", entity_id=rid) if x["action"] == "recurring.update"][0]
    usuario.post(f"/history/{h['id']}/undo")
    assert _da_rotina(usuario, rid)["require_note"] is True


def test_csv_de_plantao(usuario):
    t = usuario.post("/worklog", {"title": "Queda do link", "after_hours": True, "ticket": "77"}).json()["id"]
    usuario.post(f"/worklog/{t}/time", {"minutes": 90, "note": "madrugada"})
    usuario.post(f"/worklog/{t}/finish")
    sem = usuario.post("/worklog", {"title": "Sem plantão"}).json()["id"]
    usuario.post(f"/worklog/{sem}/time", {"minutes": 30})
    csv = usuario.get("/export/plantao.csv").content.decode("utf-8-sig").splitlines()
    assert csv[0].startswith("data;tarefa_id;tarefa")
    assert any("Queda do link;77" in l and ";90;1,5;madrugada" in l for l in csv)
    assert not any("Sem plantão" in l for l in csv)
    assert csv[-1].startswith("total;") and ";90;1,5;" in csv[-1]
    assert usuario.get("/export/plantao.csv?start=2026-02-01&end=2026-01-01").status_code == 400


def test_cobrar_em_e_desfazer_exclusao(usuario):
    tid = usuario.post("/worklog", {"title": "Link da filial", "status": "blocked", "blocked_reason": "operadora",
                                    "follow_up_on": "2030-01-10"}).json()["id"]
    assert usuario.get(f"/worklog/{tid}").json()["follow_up_on"] == "2030-01-10"
    assert "cobrar dia 10/01" in usuario.get("/summary/handoff").json()["text"]
    # Excluir e desfazer devolve o impedimento inteiro.
    usuario.delete(f"/worklog/{tid}")
    h = [x for x in hist(usuario, entity="worklog", entity_id=tid) if x["action"] == "worklog.delete"][0]
    usuario.post(f"/history/{h['id']}/undo")
    t = usuario.get(f"/worklog/{tid}").json()
    assert t["blocked_reason"] == "operadora" and t["blocked_at"] and t["follow_up_on"] == "2030-01-10"
    usuario.patch(f"/worklog/{tid}", {"status": "in_progress"})
    assert usuario.get(f"/worklog/{tid}").json()["follow_up_on"] is None


def test_csv_de_rotinas_auditoria(usuario):
    rid = usuario.post("/recurring", {"label": "Antivírus", "freq": "weekly", "weekdays": 127}).json()["id"]
    usuario.post(f"/recurring/{rid}/toggle", {"done": True, "note": "0 ameaças"})
    linhas = usuario.get("/export/rotinas.csv").content.decode("utf-8-sig").splitlines()
    assert linhas[0] == "data;rotina;agenda;feita;evidencia"
    assert any(";Antivírus;prevista;sim;0 ameaças" in l for l in linhas)
    # Apagar a evidência aparece certo no histórico.
    usuario.post(f"/recurring/{rid}/toggle", {"done": True, "note": ""})
    assert hist(usuario, entity="recurring", entity_id=rid)[0]["summary"].startswith("apagou a evidência")


def test_rotinas_csv_mostra_a_falta(usuario):
    rid = usuario.post("/recurring", {"label": "Patch semanal", "freq": "weekly", "weekdays": 127}).json()["id"]
    recuar_criacao(rid, 3)
    hoje = dia_hoje(usuario)
    ontem = (hoje - timedelta(days=1)).isoformat()
    linhas = usuario.get(f"/export/rotinas.csv?start={(hoje - timedelta(days=2)).isoformat()}&end=2099-01-01").content.decode("utf-8-sig").splitlines()
    # Ninguém marcou nada nesses dias: a falta aparece, e o futuro não.
    assert f"{ontem};Patch semanal;prevista;não;" in linhas
    assert any(l.startswith(hoje.isoformat()) and ";pendente;" in l for l in linhas)
    assert not any(l.startswith("2099") for l in linhas)


def test_cobrar_em_validacao_calendario_e_manha(usuario):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app import notify
    hoje = dia_hoje(usuario)
    ontem = (hoje - timedelta(days=1)).isoformat()
    assert usuario.post("/worklog", {"title": "x", "status": "blocked", "follow_up_on": ontem}).status_code == 422
    tid = usuario.post("/worklog", {"title": "Peça do servidor", "status": "blocked", "blocked_reason": "Dell",
                                    "follow_up_on": hoje.isoformat()}).json()["id"]
    # Editar outra coisa sem mandar a data não é barrado.
    assert usuario.patch(f"/worklog/{tid}", {"title": "Peça do servidor R740"}).status_code == 200
    ics = usuario.c.get(usuario.post("/calendar", {}).json()["path"]).text.replace("\r\n ", "")
    assert "Cobrar: Dell — Peça do servidor R740" in ics
    m = notify.build_morning(uid_de(usuario), hoje, True)
    assert any(h == "Cobrar hoje" and any("Peça do servidor R740 (aguardando Dell)" in i for i in itens) for h, itens in m.blocks)
