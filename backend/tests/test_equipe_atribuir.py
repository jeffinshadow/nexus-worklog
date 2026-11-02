"""Atribuir dentro da Equipe: devolver tarefa com motivo (quem recebeu), o que
quem atribuiu vê e faz com a devolvida (atribuir de novo, encerrar), o desfazer,
"Precisa de atenção", o aviso do Hoje de quem atribui, webhook e MCP."""
import pytest

from app import db, mailer, webhooks
from app.routers import assign as assign_mod
from conftest import Bearer, criar_chave, hist, texto, uid_de


@pytest.fixture
def enviados(monkeypatch):
    """E-mails capturados (sem SMTP, sem thread) e o push desligado."""
    caixa = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(assign_mod, "_spawn", lambda to, mail: caixa.append((to, mail.subject, mail.text())))
    monkeypatch.setattr(assign_mod, "_push_return", lambda *a: None)
    return caixa


def _papeis(admin, u, roles):
    r = admin.put(f"/admin/users/{uid_de(u)}/roles", {"roles": roles})
    assert r.status_code == 200, r.text


@pytest.fixture
def cena(admin, novo_usuario, enviados):
    """Chefe (atribui), Kaique e Lia (aceitam receber)."""
    chefe = novo_usuario("chefe@example.com")
    kaique = novo_usuario("kaique@example.com")
    lia = novo_usuario("lia@example.com")
    _papeis(admin, chefe, ["user", "assigner"])
    kaique.put("/me/assignments", {"accept": True})
    lia.put("/me/assignments", {"accept": True})
    return chefe, kaique, lia


def _manda(chefe, para, title="Trocar reator do 3º andar", **kw):
    r = chefe.post("/assign", {"user_id": uid_de(para), "title": title, "description": "Levar escada", "priority": 1, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _linha(chefe, tid):
    return next(r for r in chefe.get("/assign/sent").json() if r["id"] == tid)


def test_devolver_tira_da_conta_e_avisa_quem_atribuiu(cena, enviados):
    chefe, kaique, _ = cena
    tid = _manda(chefe, kaique, due_date="2099-12-31", ticket="4821")
    enviados.clear()
    r = kaique.post(f"/worklog/{tid}/return", {"reason": "  não é da minha   área  "})
    assert r.status_code == 200, r.text
    assert r.json()["to"]
    # Saiu da conta de quem recebeu (como uma exclusão).
    assert kaique.get(f"/worklog/{tid}").status_code == 404
    # Quem atribuiu vê "devolvida" com o motivo e os campos para atribuir de novo.
    linha = _linha(chefe, tid)
    assert linha["status"] == "removed" and linha["ended"]["kind"] == "returned"
    assert linha["ended"]["reason"] == "não é da minha área" and linha["ended"]["resolved"] is None
    assert linha["ended"]["prefill"] == {"title": "Trocar reator do 3º andar", "description": "Levar escada",
                                         "due_date": "2099-12-31", "priority": 1, "ticket": "4821", "after_hours": False}
    # E-mail para quem atribuiu, com o motivo.
    assert len(enviados) == 1 and enviados[0][0] == "chefe@example.com"
    assert "Devolvida" in enviados[0][1] and "não é da minha área" in enviados[0][2]
    # Histórico nas duas pontas.
    dele = [h for h in hist(kaique, entity="worklog", entity_id=tid) if h["action"] == "worklog.delete"][0]
    assert "devolveu a tarefa" in dele["summary"] and "«não é da minha área»" in dele["summary"] and dele["can_undo"]
    meu = [h for h in hist(chefe) if h["action"] == "assign.returned"][0]
    assert "devolveu a tarefa" in meu["summary"] and "não é da minha área" in meu["summary"]


def test_devolver_regras(cena, novo_usuario):
    chefe, kaique, lia = cena
    tid = _manda(chefe, kaique)
    propria = kaique.post("/worklog", {"title": "Minha"}).json()["id"]
    assert kaique.post(f"/worklog/{propria}/return", {"reason": "não quero"}).status_code == 400  # não foi atribuída
    assert lia.post(f"/worklog/{tid}/return", {"reason": "não é minha"}).status_code == 404  # de outra pessoa
    assert kaique.post(f"/worklog/{tid}/return", {"reason": "x"}).status_code == 422  # motivo curto demais
    assert kaique.post(f"/worklog/{tid}/return", {"reason": "y" * 121}).status_code == 422
    assert kaique.post(f"/worklog/{tid}/return", {}).status_code == 422
    kaique.post(f"/worklog/{tid}/finish")
    assert kaique.post(f"/worklog/{tid}/return", {"reason": "já feita"}).status_code == 409  # concluída: reabra antes
    # Chave só de leitura não devolve; a de escrita, sim (a tarefa é dela).
    tid2 = _manda(chefe, kaique, title="Outra")
    leitura = Bearer(criar_chave(kaique, nome="leitura", scope="read")["token"])
    assert leitura.post(f"/worklog/{tid2}/return", {"reason": "férias"}).status_code == 403
    escrita = Bearer(criar_chave(kaique, nome="automação")["token"])
    assert escrita.post(f"/worklog/{tid2}/return", {"reason": "férias"}).status_code == 200


def test_encerrar_e_atribuir_de_novo(cena):
    chefe, kaique, lia = cena
    a = _manda(chefe, kaique, title="A")
    b = _manda(chefe, kaique, title="B")
    kaique.post(f"/worklog/{a}/return", {"reason": "de férias"})
    kaique.post(f"/worklog/{b}/return", {"reason": "outra área"})
    # Encerrar: fica na lista como encerrada; não dá para encerrar de novo.
    assert chefe.post(f"/assign/{a}/close").status_code == 200
    assert _linha(chefe, a)["ended"]["resolved"]["kind"] == "closed"
    assert chefe.post(f"/assign/{a}/close").status_code == 404
    assert any(h["action"] == "assign.close" and "encerrou" in h["summary"] for h in hist(chefe))
    # Atribuir de novo (a outra pessoa, com o título ajustado) resolve a devolução.
    assert chefe.post("/assign", {"user_id": uid_de(lia), "title": "B (revisada)", "from_return": a}).status_code == 409
    r = chefe.post("/assign", {"user_id": uid_de(lia), "title": "B (revisada)", "from_return": b})
    assert r.status_code == 201, r.text
    nova = r.json()["id"]
    res = _linha(chefe, b)["ended"]["resolved"]
    assert res["kind"] == "reassigned" and res["to"]
    assert lia.get(f"/worklog/{nova}").json()["title"] == "B (revisada)"
    assert chefe.post("/assign", {"user_id": uid_de(lia), "title": "de novo", "from_return": b}).status_code == 409
    # Quem não atribuiu não encerra a devolução de outro.
    assert lia.post(f"/assign/{b}/close").status_code == 403


def test_desfazer_devolucao(cena):
    chefe, kaique, _ = cena
    tid = _manda(chefe, kaique)
    kaique.post(f"/worklog/{tid}/notes", {"body": "fui olhar"})
    kaique.post(f"/worklog/{tid}/return", {"reason": "falta peça"})
    dele = [h for h in hist(kaique, entity="worklog", entity_id=tid) if h["action"] == "worklog.delete"][0]
    assert kaique.post(f"/history/{dele['id']}/undo").status_code == 200
    # Voltou inteira (com a anotação e quem atribuiu) e a lista de quem atribuiu volta ao normal.
    t = kaique.get(f"/worklog/{tid}").json()
    assert t["assigned_by_name"] and len(t["notes"]) == 1
    assert _linha(chefe, tid)["status"] == "todo" and _linha(chefe, tid)["ended"] is None
    assert assign_mod.open_returns(uid_de(chefe)) == []
    # Devolvida de novo e já resolvida por quem atribuiu: não volta pelo desfazer.
    kaique.post(f"/worklog/{tid}/return", {"reason": "falta peça mesmo"})
    assert _linha(chefe, tid)["ended"]["reason"] == "falta peça mesmo"
    chefe.post(f"/assign/{tid}/close")
    dele = [h for h in hist(kaique, entity="worklog", entity_id=tid) if h["action"] == "worklog.delete"][0]
    r = kaique.post(f"/history/{dele['id']}/undo")
    assert r.status_code == 409 and "resolveu a devolução" in r.json()["detail"]
    # Excluída depois de voltar: a linha diz "excluída" (não fica presa em devolvida).
    tid2 = _manda(chefe, kaique, title="Volta e sai")
    kaique.post(f"/worklog/{tid2}/return", {"reason": "engano"})
    h2 = [h for h in hist(kaique, entity="worklog", entity_id=tid2) if h["action"] == "worklog.delete"][0]
    kaique.post(f"/history/{h2['id']}/undo")
    kaique.delete(f"/worklog/{tid2}")
    assert _linha(chefe, tid2)["ended"]["kind"] == "deleted"
    assert all(r["id"] != tid2 for r in assign_mod.open_returns(uid_de(chefe)))


def test_precisa_de_atencao_mostra_a_devolvida(admin, cena):
    chefe, kaique, _ = cena
    _papeis(admin, chefe, ["user", "assigner", "viewer"])
    tid = _manda(chefe, kaique)
    kaique.post(f"/worklog/{tid}/return", {"reason": "sem acesso ao prédio"})
    # Kaique não compartilha o dia a dia: não entra em nada da equipe, mas a devolvida é do chefe.
    t = chefe.get("/viewer/team").json()
    assert t["people"] == []
    itens = [x for x in t["attention"] if x["kind"] == "returned"]
    assert len(itens) == 1 and itens[0]["task_id"] == tid and itens[0]["reason"] == "sem acesso ao prédio"
    chefe.post(f"/assign/{tid}/close")
    assert not [x for x in chefe.get("/viewer/team").json()["attention"] if x["kind"] == "returned"]


def test_aviso_do_hoje_para_quem_atribui(cena):
    chefe, kaique, lia = cena
    assert "assigned_news" not in kaique.get("/summary").json()  # sem o papel, nem vem
    assert chefe.get("/summary").json()["assigned_news"] is None  # nada ainda
    a = _manda(chefe, kaique, title="A")
    b = _manda(chefe, lia, title="B")
    _manda(chefe, lia, title="C (aberta)")
    kaique.post(f"/worklog/{a}/finish")
    lia.post(f"/worklog/{b}/return", {"reason": "outra área"})
    n = chefe.get("/summary").json()["assigned_news"]
    assert n["done"] == 1 and n["returned"] == 1
    # Visto: o próximo aviso conta daqui.
    assert chefe.post("/assign/news/seen").status_code == 200
    assert chefe.get("/summary").json()["assigned_news"] is None
    assert kaique.post("/assign/news/seen").status_code == 403


def test_webhook_e_mcp(cena):
    chefe, kaique, _ = cena
    tid = _manda(chefe, kaique)
    kaique.post(f"/worklog/{tid}/return", {"reason": "não é «minha» área"})
    row = db.query_one("SELECT * FROM audit_log WHERE user_id = %s AND action = 'assign.returned'", (uid_de(chefe),))
    body = webhooks.payload(row)
    assert body["action"] == "assign.returned" and body["entity_id"] == tid
    assert body["data"]["reason"] == "não é «minha» área" and body["data"]["title"] == "Trocar reator do 3º andar"
    assert webhooks.matches(["assign.returned"], "assign.returned", "assignment")
    # O feed/webhook de quem recebeu tem a lápide comum (worklog.delete).
    assert db.query_one("SELECT 1 FROM audit_log WHERE user_id = %s AND action = 'worklog.delete' AND entity_id = %s",
                        (uid_de(kaique), tid))
    ia = Bearer(criar_chave(chefe)["token"])
    txt = texto(ia.tool("list_assigned"))
    assert "devolvida" in txt and '«não é "minha" área»' in txt
