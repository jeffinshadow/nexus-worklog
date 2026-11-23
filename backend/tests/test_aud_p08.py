"""Auditoria, pacote p08 (atribuição e devolução): devolver é tudo ou nada, não
apaga horas de outra pessoa e leva o cronômetro para a lápide; alcance de
/assign/people e /assign/sent; a mesma devolução não é decidida duas vezes;
limite por destinatário; conta excluída sem e-mail nem motivo."""
import threading
import time

import pytest

from app import audit, db, mailer
from app.routers import assign as assign_mod
from conftest import SENHA_PADRAO, Api, Bearer, criar_chave, hist, uid_de


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
    r = chefe.post("/assign", {"user_id": uid_de(para), "title": title, "description": "Levar escada", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _linha(chefe, tid):
    return next(r for r in chefe.get("/assign/sent").json() if r["id"] == tid)


def _conta(sql, *p):
    return db.query_one(f"SELECT count(*)::int AS n FROM {sql}", p)["n"]


# ------------------------------------------------- devolver: tudo ou nada --

def test_devolver_que_falha_no_meio_nao_perde_nada(cena, monkeypatch):
    chefe, kaique, _ = cena
    tid = _manda(chefe, kaique)
    assert kaique.post(f"/worklog/{tid}/notes", {"body": "Liguei para o síndico"}).status_code == 201
    assert kaique.post(f"/worklog/{tid}/time", {"minutes": 45}).status_code == 201
    real = audit.record

    def falha(ctx, action, *a, **kw):
        if action == "assign.returned":  # a 2ª linha do histórico: a tarefa e a lápide já foram
            raise RuntimeError("banco fora no meio da devolução")
        return real(ctx, action, *a, **kw)
    monkeypatch.setattr(audit, "record", falha)
    with pytest.raises(RuntimeError):
        kaique.post(f"/worklog/{tid}/return", {"reason": "não é da minha área"})
    monkeypatch.setattr(audit, "record", real)
    # Nada saiu: tarefa, anotação e tempo no lugar, sem lápide solta.
    t = kaique.get(f"/worklog/{tid}").json()
    assert t["minutes"] == 45 and len(t["notes"]) == 1
    assert not [h for h in hist(kaique, entity="worklog", entity_id=tid) if h["action"] == "worklog.delete"]
    assert _linha(chefe, tid)["status"] == "todo"
    # E a devolução de verdade continua funcionando depois.
    assert kaique.post(f"/worklog/{tid}/return", {"reason": "não é da minha área"}).status_code == 200


def test_cancelar_que_falha_no_meio_nao_perde_a_tarefa(cena, monkeypatch):
    chefe, kaique, _ = cena
    tid = _manda(chefe, kaique)
    real = audit.record

    def falha(ctx, action, *a, **kw):
        if action == "assign.cancel":
            raise RuntimeError("banco fora no meio do cancelamento")
        return real(ctx, action, *a, **kw)
    monkeypatch.setattr(audit, "record", falha)
    with pytest.raises(RuntimeError):
        chefe.post(f"/assign/{tid}/cancel")
    monkeypatch.setattr(audit, "record", real)
    assert kaique.get(f"/worklog/{tid}").status_code == 200
    assert not [h for h in hist(kaique, entity="worklog", entity_id=tid) if h["action"] == "worklog.delete"]


def test_alterar_que_falha_no_meio_nao_muda_a_tarefa(cena, monkeypatch, enviados):
    chefe, kaique, _ = cena
    tid = _manda(chefe, kaique)
    enviados.clear()
    real = audit.record

    def falha(ctx, action, *a, **kw):
        if action == "assign.update":
            raise RuntimeError("banco fora no meio da alteração")
        return real(ctx, action, *a, **kw)
    monkeypatch.setattr(audit, "record", falha)
    with pytest.raises(RuntimeError):
        chefe.patch(f"/assign/{tid}", {"title": "Outro título"})
    monkeypatch.setattr(audit, "record", real)
    assert kaique.get(f"/worklog/{tid}").json()["title"] == "Trocar reator do 3º andar"
    assert not [h for h in hist(kaique, entity="worklog", entity_id=tid) if h["action"] == "worklog.assign_update"]
    assert enviados == []  # o e-mail só sai depois de gravar


def test_devolver_com_horas_de_outra_pessoa_e_recusado(cena):
    chefe, kaique, lia = cena
    tid = _manda(chefe, kaique)
    assert kaique.post(f"/worklog/{tid}/time", {"minutes": 30}).status_code == 201
    # Como depois de uma transferência pelo admin: a tarefa guarda horas de quem a tinha.
    db.execute("""INSERT INTO time_entries (task_id, user_id, minutes, day) VALUES (%s, %s, 50, current_date)""",
               (tid, uid_de(lia)))
    r = kaique.post(f"/worklog/{tid}/return", {"reason": "não é da minha área"})
    assert r.status_code == 409 and "guarda horas de quem a passou" in r.json()["detail"]
    assert kaique.get(f"/worklog/{tid}").status_code == 200
    assert _conta("time_entries WHERE task_id = %s", tid) == 2


def test_lapide_da_devolucao_guarda_de_quem_e_cada_apontamento(cena):
    chefe, kaique, _ = cena
    tid = _manda(chefe, kaique)
    assert kaique.post(f"/worklog/{tid}/time", {"minutes": 30}).status_code == 201
    assert kaique.post(f"/worklog/{tid}/return", {"reason": "não é da minha área"}).status_code == 200
    lapide = db.query_one("SELECT before FROM audit_log WHERE action = 'worklog.delete' AND entity_id = %s", (tid,))["before"]
    assert [e["user_id"] for e in lapide["children"]["time"]] == [uid_de(kaique)]


def test_devolver_com_cronometro_rodando_leva_o_tempo_para_a_lapide(cena):
    chefe, kaique, _ = cena
    tid = _manda(chefe, kaique)
    assert kaique.post("/timer/start", {"task_id": tid}).status_code in (200, 201)
    db.execute("UPDATE task_timers SET started_at = now() - interval '25 minutes' WHERE task_id = %s", (tid,))
    assert kaique.post(f"/worklog/{tid}/return", {"reason": "não é da minha área"}).status_code == 200
    assert kaique.get("/timer").json()["timer"] is None
    lapide = db.query_one("SELECT before FROM audit_log WHERE action = 'worklog.delete' AND entity_id = %s", (tid,))["before"]
    tempo = lapide["children"]["time"]
    assert len(tempo) == 1 and tempo[0]["minutes"] == 25 and tempo[0]["user_id"] == uid_de(kaique)
    # O desfazer devolve a tarefa com o tempo do cronômetro.
    h = [x for x in hist(kaique, entity="worklog", entity_id=tid) if x["action"] == "worklog.delete"][0]
    assert kaique.post(f"/history/{h['id']}/undo").status_code == 200
    assert kaique.get(f"/worklog/{tid}").json()["minutes"] == 25


# ------------------------------------------------------------- alcance --

def test_chave_de_admin_nao_lista_todas_as_contas(admin, novo_usuario):
    aceita = novo_usuario("aceita@example.com")
    novo_usuario("recusa@example.com")
    aceita.put("/me/assignments", {"accept": True})
    _papeis(admin, admin, ["admin", "user", "assigner"])
    # Pelo app, o admin vê todas as contas, com e-mail.
    pelo_app = admin.get("/assign/people").json()
    assert {"aceita@example.com", "recusa@example.com"} <= {p.get("email") for p in pelo_app}
    # Pela chave (leitura), só o que o papel "Manda tarefas" vê: quem não aceita vem anônimo.
    chave = Bearer(criar_chave(admin, scope="read")["token"])
    r = chave.get("/assign/people")
    assert r.status_code == 200, r.text
    emails = {p.get("email") for p in r.json()}
    assert "aceita@example.com" in emails and "recusa@example.com" not in emails
    assert {"accepts": False, "everyone": False} in r.json()


def test_nao_aceitam_nao_conta_bloqueada_nem_convite_pendente(cena, admin, novo_usuario):
    chefe, _, _ = cena
    novo_usuario("recusa@example.com")
    bloqueada = novo_usuario("bloqueada@example.com")
    assert admin.post(f"/admin/users/{uid_de(bloqueada)}/block").status_code == 200
    db.execute("""INSERT INTO users (email, password_hash, role, invite_pending) VALUES ('pendente@example.com', 'x', 'user', true)""")
    db.execute("INSERT INTO user_roles (user_id, role) SELECT id, 'user' FROM users WHERE email = 'pendente@example.com'")
    anonimas = [p for p in chefe.get("/assign/people").json() if "email" not in p]
    # Só "recusa" (o admin semeado não tem registro próprio... se tiver, conta também).
    esperado = _conta("""users u WHERE u.accepts_assignments_at IS NULL AND u.blocked_at IS NULL AND NOT u.invite_pending
                           AND u.email <> 'chefe@example.com'
                           AND EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'user')""")
    assert len(anonimas) == esperado
    assert esperado == _conta("""users u WHERE u.accepts_assignments_at IS NULL AND u.email <> 'chefe@example.com'
                                   AND EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'user')""") - 2
    # O admin (pelo app) continua vendo as duas, com o bloqueio.
    todos = {p.get("email"): p for p in admin.get("/assign/people").json()}
    assert todos["bloqueada@example.com"]["blocked"] and "pendente@example.com" in todos and "pending" not in todos["pendente@example.com"]


def test_sent_fora_da_equipe_vem_sem_descricao_nem_motivo(cena, admin):
    chefe, kaique, lia = cena
    tid = _manda(chefe, kaique)
    outra = _manda(chefe, lia)
    assert kaique.patch(f"/worklog/{tid}", {"status": "blocked", "blocked_reason": "esperando a peça"}).status_code == 200
    linha = _linha(chefe, tid)
    assert linha["description"] == "Levar escada" and linha["blocked_reason"] == "esperando a peça"
    # Com equipes: chefe e Lia numa, Kaique em outra (fora do alcance do chefe).
    a = admin.post("/admin/teams", {"name": "Elétrica"}).json()["id"]
    b = admin.post("/admin/teams", {"name": "Hidráulica"}).json()["id"]
    assert admin.put(f"/admin/users/{uid_de(chefe)}/teams", {"team_ids": [a]}).status_code == 200
    assert admin.put(f"/admin/users/{uid_de(lia)}/teams", {"team_ids": [a]}).status_code == 200
    assert admin.put(f"/admin/users/{uid_de(kaique)}/teams", {"team_ids": [b]}).status_code == 200
    linha = _linha(chefe, tid)
    assert linha["same_team"] is False and linha["title"] and linha["status"] == "blocked"
    assert linha["description"] is None and linha["blocked_reason"] is None
    assert _linha(chefe, outra)["description"] == "Levar escada"  # na mesma equipe, como antes


def test_alterar_com_aceite_desligado_e_recusado_e_cancelar_continua(cena, enviados):
    chefe, kaique, _ = cena
    tid = _manda(chefe, kaique)
    assert kaique.put("/me/assignments", {"accept": False}).status_code == 200
    enviados.clear()
    r = chefe.patch(f"/assign/{tid}", {"title": "Reescrita depois do não"})
    assert r.status_code in (403, 409), r.text
    assert kaique.get(f"/worklog/{tid}").json()["title"] == "Trocar reator do 3º andar"
    assert enviados == []
    # Cancelar continua valendo: tira da conta de quem não quer mais receber.
    assert chefe.post(f"/assign/{tid}/cancel").status_code == 200
    assert kaique.get(f"/worklog/{tid}").status_code == 404


# -------------------------------------------- a mesma devolução, uma vez --

def _duas_ao_mesmo_tempo(chefe, a, b):
    """Duas chamadas de quem atribuiu, em sessões separadas, largadas juntas."""
    outro = Api()
    outro.login("chefe@example.com", SENHA_PADRAO)
    largada, res = threading.Barrier(2), []

    def roda(api, f):
        largada.wait()
        res.append(f(api).status_code)
    ts = [threading.Thread(target=roda, args=(chefe, a)), threading.Thread(target=roda, args=(outro, b))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return sorted(res)


@pytest.fixture
def devagar(monkeypatch):
    """Alarga a janela entre conferir a devolução e gravar a decisão."""
    real_p, real_r = assign_mod.default_project, audit.record

    def projeto(uid):
        time.sleep(0.4)
        return real_p(uid)

    def grava(ctx, action, *a, **kw):
        if action == "assign.close":
            time.sleep(0.4)
        return real_r(ctx, action, *a, **kw)
    monkeypatch.setattr(assign_mod, "default_project", projeto)
    monkeypatch.setattr(audit, "record", grava)


def test_atribuir_de_novo_duas_vezes_cria_uma_tarefa(cena, devagar):
    chefe, kaique, lia = cena
    tid = _manda(chefe, kaique)
    assert kaique.post(f"/worklog/{tid}/return", {"reason": "não é da minha área"}).status_code == 200
    corpo = {"user_id": uid_de(lia), "title": "Trocar reator do 3º andar", "from_return": tid}
    res = _duas_ao_mesmo_tempo(chefe, lambda x: x.post("/assign", corpo), lambda x: x.post("/assign", corpo))
    assert res == [201, 409]
    assert _conta("worklog_tasks WHERE user_id = %s", uid_de(lia)) == 1
    assert _conta("audit_log WHERE action = 'assign.send' AND after->>'from_return' = %s", str(tid)) == 1


def test_atribuir_de_novo_e_encerrar_juntos_so_um_vale(cena, devagar):
    chefe, kaique, lia = cena
    tid = _manda(chefe, kaique)
    assert kaique.post(f"/worklog/{tid}/return", {"reason": "não é da minha área"}).status_code == 200
    corpo = {"user_id": uid_de(lia), "title": "Trocar reator do 3º andar", "from_return": tid}
    res = _duas_ao_mesmo_tempo(chefe, lambda x: x.post("/assign", corpo), lambda x: x.post(f"/assign/{tid}/close"))
    assert res in ([200, 409], [201, 404])
    decisoes = (_conta("audit_log WHERE action = 'assign.send' AND after->>'from_return' = %s", str(tid))
                + _conta("audit_log WHERE action = 'assign.close' AND entity_id = %s", tid))
    assert decisoes == 1


def test_encerrar_e_atribuir_de_novo_em_serie_continuam(cena):
    chefe, kaique, lia = cena
    tid = _manda(chefe, kaique)
    assert kaique.post(f"/worklog/{tid}/return", {"reason": "não é da minha área"}).status_code == 200
    assert chefe.post(f"/assign/{tid}/close").status_code == 200
    assert chefe.post(f"/assign/{tid}/close").status_code == 404
    r = chefe.post("/assign", {"user_id": uid_de(lia), "title": "De novo", "from_return": tid})
    assert r.status_code == 409


# --------------------------------------------------------------- limite --

def test_limite_de_atribuicoes_por_destinatario(cena):
    chefe, kaique, lia = cena
    for i in range(20):
        _manda(chefe, kaique, title=f"Tarefa {i}")
    r = chefe.post("/assign", {"user_id": uid_de(kaique), "title": "A 21ª"})
    assert r.status_code == 429 and 1 <= int(r.headers["Retry-After"]) <= 600
    assert _conta("worklog_tasks WHERE user_id = %s", uid_de(kaique)) == 20
    # Outro destinatário passa (o limite é por par), e por chave de API vale o mesmo teto.
    _manda(chefe, lia)
    chave = Bearer(criar_chave(chefe)["token"])
    assert chave.post("/assign", {"user_id": uid_de(kaique), "title": "Pela chave"}).status_code == 429
    assert chave.post("/assign", {"user_id": uid_de(lia), "title": "Pela chave"}).status_code == 201
    # Passada a janela, volta a aceitar.
    db.execute("UPDATE audit_log SET created_at = created_at - interval '11 minutes' WHERE action = 'assign.send'")
    assert chefe.post("/assign", {"user_id": uid_de(kaique), "title": "Depois da janela"}).status_code == 201


# ------------------------------------------------------- conta excluída --

def test_conta_excluida_aparece_sem_email_nem_motivo(cena):
    chefe, kaique, lia = cena
    devolvida = _manda(chefe, kaique, title="Devolvida antes de sair")
    assert kaique.post(f"/worklog/{devolvida}/return", {"reason": "estarei em visita a cliente"}).status_code == 200
    ficou = _manda(chefe, kaique, title="Ficou na conta")
    da_lia = _manda(chefe, lia)
    assert lia.post(f"/worklog/{da_lia}/return", {"reason": "sem tempo esta semana"}).status_code == 200
    assert _linha(chefe, devolvida)["to_email"] == "kaique@example.com"
    assert kaique.post("/me/delete", {"password": SENHA_PADRAO}).status_code == 200
    for tid in (devolvida, ficou):
        linha = _linha(chefe, tid)
        assert linha["to_name"] == "conta excluída" and linha["to_email"] is None
        assert "kaique" not in str(linha).lower() and "visita a cliente" not in str(linha)
    assert _linha(chefe, devolvida)["ended"]["reason"] is None
    # "Precisa de atenção" (devoluções em aberto) também não traz nome nem motivo.
    aberta = next(r for r in assign_mod.open_returns(uid_de(chefe)) if r["id"] == devolvida)
    assert aberta["to_name"] == "conta excluída" and aberta["reason"] is None
    # Quem continua na instância aparece como antes.
    linha = _linha(chefe, da_lia)
    assert linha["to_email"] == "lia@example.com" and linha["ended"]["reason"] == "sem tempo esta semana"


def test_falha_de_email_nao_grava_o_endereco_no_log(monkeypatch, caplog):
    def quebra(*a, **kw):
        raise OSError("smtp fora")
    monkeypatch.setattr(mailer, "send", quebra)

    class M:
        subject = "x"
        def text(self): return "t"
        def html(self): return "h"
    with caplog.at_level("WARNING", logger="uvicorn.error"):
        assign_mod._send("kaique@example.com", M())
    assert "falhou" in caplog.text and "kaique@example.com" not in caplog.text
