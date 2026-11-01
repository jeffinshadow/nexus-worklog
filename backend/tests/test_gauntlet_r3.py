"""Gauntlet geral, rodada 3 (servidor e MCP): conta bloqueada fora da
atribuição, foto de perfil com o mesmo aceite das listas, desfazer do Duplicar,
alterar/cancelar atribuição sem apagar o que quem recebeu escreveu, rotina
"depois da última vez", cronômetro sem sobrepor tempo, pausa depois de trocar a
agenda e o MCP (pausa, retroativo, « », horário "7h30", erros em português)."""
import pytest

from app import db, mailer
from app.routers import assign as assign_mod
from conftest import hist, uid_de

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def caixa(monkeypatch):
    enviados = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None: enviados.append((to, subject, text)))
    monkeypatch.setattr(assign_mod, "_spawn", lambda to, mail: enviados.append((to, mail.subject, mail.text())))
    return enviados


def _papeis(admin, u, roles):
    assert admin.put(f"/admin/users/{uid_de(u)}/roles", {"roles": roles}).status_code == 200


@pytest.fixture
def par(admin, novo_usuario, caixa):
    chefe = novo_usuario("chefe@example.com")
    _papeis(admin, chefe, ["user", "assigner"])
    marina = novo_usuario("marina@example.com")
    marina.put("/me/assignments", {"accept": True})
    return chefe, marina


def _mandar(chefe, marina, **kw):
    r = chefe.post("/assign", {"user_id": uid_de(marina), "title": "Trocar o nobreak", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _foto(u):
    r = u.c.post("/api/me/avatar", content=PNG, headers=u._h({"Content-Type": "image/png"}))
    assert r.status_code == 200, r.text
    return r.json()["avatar"]


# ------------------------------------------------------- conta bloqueada --

def test_conta_bloqueada_nao_aceita_nem_recebe(admin, par, caixa):
    chefe, marina = par
    mid = uid_de(marina)
    tid = _mandar(chefe, marina)
    assert admin.post(f"/admin/users/{mid}/block").status_code == 200
    p = next(x for x in chefe.get("/assign/people").json() if x["id"] == mid)
    assert p["accepts"] is False and p["blocked"] is True
    caixa.clear()
    r = chefe.post("/assign", {"user_id": mid, "title": "Outra"})
    assert r.status_code == 404
    # Alterar a que já estava lá não manda e-mail para quem ninguém lê.
    assert chefe.patch(f"/assign/{tid}", {"title": "Trocar o nobreak 2"}).status_code == 200
    assert chefe.post(f"/assign/{tid}/cancel").status_code == 200
    assert caixa == []


# ------------------------------------------------------ foto de perfil --

def test_foto_so_de_quem_aparece_nas_listas(admin, novo_usuario):
    alvo = novo_usuario("alvo@example.com")
    url = _foto(alvo)
    chefe = novo_usuario("chefe@example.com")
    _papeis(admin, chefe, ["user", "assigner"])
    visto = novo_usuario("visto@example.com")
    _papeis(admin, visto, ["user", "viewer"])
    # Sem aceite nenhum: nem atribuidor nem visualizador veem.
    assert chefe.get(url.removeprefix("/api")).status_code == 404
    assert visto.get(url.removeprefix("/api")).status_code == 404
    assert admin.get(url.removeprefix("/api")).status_code == 200
    # Na lista do Atribuir, quem não aceita vai sem foto (a imagem daria 404).
    p = next(x for x in chefe.get("/assign/people").json() if x["email"] == "alvo@example.com")
    assert p["avatar"] is None
    # Aceitou receber tarefas: o atribuidor vê; o visualizador ainda não.
    alvo.put("/me/assignments", {"accept": True})
    assert chefe.get(url.removeprefix("/api")).status_code == 200
    assert visto.get(url.removeprefix("/api")).status_code == 404
    assert next(x for x in chefe.get("/assign/people").json() if x["email"] == "alvo@example.com")["avatar"] == url
    # Aceitou ser visto: o visualizador vê.
    alvo.put("/me/viewers", {"accept": True})
    assert visto.get(url.removeprefix("/api")).status_code == 200
    # A foto do admin (que não aceitou receber tarefas) não sai para o atribuidor.
    url_admin = _foto(admin)
    assert chefe.get(url_admin.removeprefix("/api")).status_code == 404
