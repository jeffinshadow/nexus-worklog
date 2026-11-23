"""Rodada 2, pacote r2-06 (acabamento da atribuição): `editable` segue a regra
do PATCH e `cancelable` não cai junto; nome de conta excluída em "atribuída de
novo a"; limite por destinatário conferido dentro da transação e sem contar as
canceladas; devolver com cronômetro esquecido; 429 pelo MCP; desfazer a
devolução x atribuir de novo ao mesmo tempo."""
import threading
import time

import pytest

from app import db, mailer
from app.routers import assign as assign_mod
from conftest import SENHA_PADRAO, Api, Bearer, criar_chave, hist, papeis, texto, uid_de


@pytest.fixture
def cena(admin, novo_usuario, monkeypatch):
    """Chefe (atribui), Kaique e Lia (aceitam receber). E-mail capturado, push desligado."""
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(assign_mod, "_spawn", lambda to, mail: None)
    monkeypatch.setattr(assign_mod, "_push_return", lambda *a: None)
    chefe = novo_usuario("chefe@example.com")
    kaique = novo_usuario("kaique@example.com")
    lia = novo_usuario("lia@example.com")
    papeis(admin, chefe, ["user", "assigner"])
    kaique.put("/me/assignments", {"accept": True})
    lia.put("/me/assignments", {"accept": True})
    return chefe, kaique, lia


def _manda(chefe, para, title="Trocar reator do 3º andar", **kw):
    r = chefe.post("/assign", {"user_id": uid_de(para), "title": title, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _linha(chefe, tid):
    return next(r for r in chefe.get("/assign/sent").json() if r["id"] == tid)


def _conta(sql, *p):
    return db.query_one(f"SELECT count(*)::int AS n FROM {sql}", p)["n"]


# ------------------------------------------- editable = a regra do PATCH --

def test_editable_cai_com_o_aceite_desligado_e_cancelable_fica(cena):
    chefe, kaique, _ = cena
    tid = _manda(chefe, kaique)
    linha = _linha(chefe, tid)
    assert linha["editable"] is True and linha["cancelable"] is True
    assert "open" not in linha and "receives" not in linha  # só de uso interno
    assert kaique.put("/me/assignments", {"accept": False}).status_code == 200
    linha = _linha(chefe, tid)
    # A lista diz o mesmo que as rotas: alterar é recusado, cancelar continua valendo.
    assert linha["editable"] is False and linha["cancelable"] is True
    assert chefe.patch(f"/assign/{tid}", {"title": "Reescrita depois do não"}).status_code == 403
    assert chefe.post(f"/assign/{tid}/cancel").status_code == 200


def test_editable_de_conta_bloqueada_segue_o_patch(cena, admin):
    chefe, kaique, _ = cena
    tid = _manda(chefe, kaique)
    assert admin.post(f"/admin/users/{uid_de(kaique)}/block").status_code == 200
    # O PATCH aceita corrigir tarefa de conta bloqueada (sem e-mail): a lista acompanha.
    assert _linha(chefe, tid)["editable"] is True
    assert chefe.patch(f"/assign/{tid}", {"title": "Corrigida"}).status_code == 200


# ------------------------------------- "atribuída de novo a" conta excluída --

def test_atribuida_de_novo_a_conta_excluida_vem_sem_o_nome(cena):
    chefe, kaique, lia = cena
    assert lia.put("/me/profile", {"display_name": "Lia Monteiro"}).status_code == 200
    tid = _manda(chefe, kaique)
    assert kaique.post(f"/worklog/{tid}/return", {"reason": "não é da minha área"}).status_code == 200
    _manda(chefe, lia, from_return=tid)
    assert _linha(chefe, tid)["ended"]["resolved"]["to"] == "Lia Monteiro"
    assert lia.post("/me/delete", {"password": SENHA_PADRAO}).status_code == 200
    linha = _linha(chefe, tid)
    assert linha["ended"]["resolved"]["kind"] == "reassigned" and linha["ended"]["resolved"]["to"] == "conta excluída"
    assert "Lia" not in str(linha) and "lia@" not in str(linha)
    # Quem devolveu continua na instância: aparece como antes.
    assert linha["to_email"] == "kaique@example.com" and linha["ended"]["reason"] == "não é da minha área"


# ------------------------------------------------ limite por destinatário --

def _duas_ao_mesmo_tempo(a, b):
    """Duas chamadas (cada uma com o seu cliente) largadas juntas; devolve os status em ordem."""
    largada, res = threading.Barrier(2), []

    def roda(f):
        largada.wait()
        res.append(f().status_code)
    ts = [threading.Thread(target=roda, args=(f,)) for f in (a, b)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return sorted(res)


@pytest.fixture
def devagar(monkeypatch):
    """Alarga a janela entre conferir (limite, devolução em aberto) e gravar a tarefa."""
    real = assign_mod.default_project

    def projeto(uid):
        time.sleep(0.4)
        return real(uid)
    monkeypatch.setattr(assign_mod, "default_project", projeto)


def test_limite_vale_para_envios_simultaneos(cena, devagar):
    chefe, kaique, _ = cena
    for i in range(19):
        _manda(chefe, kaique, title=f"Tarefa {i}")
    outro = Api()
    outro.login("chefe@example.com", SENHA_PADRAO)
    corpo = {"user_id": uid_de(kaique), "title": "A 20ª, duas vezes"}
    res = _duas_ao_mesmo_tempo(lambda: chefe.post("/assign", corpo), lambda: outro.post("/assign", corpo))
    assert res == [201, 429]
    assert _conta("worklog_tasks WHERE user_id = %s", uid_de(kaique)) == 20


def test_limite_nao_conta_atribuicao_cancelada(cena):
    chefe, kaique, _ = cena
    ids = [_manda(chefe, kaique, title=f"Tarefa {i}") for i in range(20)]
    r = chefe.post("/assign", {"user_id": uid_de(kaique), "title": "A 21ª"})
    assert r.status_code == 429 and 1 <= int(r.headers["Retry-After"]) <= 600
    assert "muitas tarefas para a mesma pessoa" in r.json()["detail"]
    # Cancelou uma (engano): abre uma vaga, e só uma.
    assert chefe.post(f"/assign/{ids[0]}/cancel").status_code == 200
    _manda(chefe, kaique, title="No lugar da cancelada")
    assert chefe.post("/assign", {"user_id": uid_de(kaique), "title": "Outra"}).status_code == 429
    # Quem recebeu desfez o cancelamento (a tarefa voltou para ela): volta a contar.
    assert chefe.post(f"/assign/{ids[1]}/cancel").status_code == 200
    h = next(x for x in hist(kaique, entity="worklog", entity_id=ids[1]) if x["action"] == "worklog.delete")
    assert kaique.post(f"/history/{h['id']}/undo").status_code == 200
    assert chefe.post("/assign", {"user_id": uid_de(kaique), "title": "Outra"}).status_code == 429


# ------------------------------------ devolver com cronômetro esquecido --

def test_devolver_com_cronometro_esquecido_descarta_o_tempo(cena):
    chefe, kaique, _ = cena
    tid = _manda(chefe, kaique)
    assert kaique.post("/timer/start", {"task_id": tid}).status_code in (200, 201)
    db.execute("UPDATE task_timers SET started_at = now() - interval '13 hours' WHERE task_id = %s", (tid,))
    assert kaique.post(f"/worklog/{tid}/return", {"reason": "não é da minha área"}).status_code == 200
    assert kaique.get("/timer").json()["timer"] is None
    # Mais de 12 h rodando: o tempo é descartado (timer.discard), não vira apontamento.
    assert _conta("audit_log WHERE action = 'timer.discard' AND user_id = %s AND entity_id = %s", uid_de(kaique), tid) == 1
    lapide = db.query_one("SELECT before FROM audit_log WHERE action = 'worklog.delete' AND entity_id = %s", (tid,))["before"]
    assert lapide["children"]["time"] == []
    assert _conta("time_entries WHERE user_id = %s", uid_de(kaique)) == 0
    # O desfazer devolve a tarefa sem tempo fantasma.
    h = next(x for x in hist(kaique, entity="worklog", entity_id=tid) if x["action"] == "worklog.delete")
    assert kaique.post(f"/history/{h['id']}/undo").status_code == 200
    assert kaique.get(f"/worklog/{tid}").json()["minutes"] == 0
