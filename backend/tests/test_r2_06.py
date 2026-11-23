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
