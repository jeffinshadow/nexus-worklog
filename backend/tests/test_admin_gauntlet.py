"""Gauntlet geral, perfil "Quem administra": cancelar convite, bloquear acesso
e o que quem atribuiu pode fazer depois de mandar a tarefa."""
import pytest

from app import db, mailer
from app.routers import assign as assign_mod
from app.routers import auth as auth_mod
from conftest import Api, SENHA_PADRAO, criar_chave, hist, uid_de


class _Agora:
    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@pytest.fixture
def caixa(monkeypatch):
    enviados = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None: enviados.append((to, subject, text)))
    monkeypatch.setattr(auth_mod.threading, "Thread", _Agora)
    monkeypatch.setattr(assign_mod, "_spawn", lambda to, mail: enviados.append((to, mail.subject, mail.text())))
    return enviados


def _papeis(admin, u, roles):
    assert admin.put(f"/admin/users/{uid_de(u)}/roles", {"roles": roles}).status_code == 200


# ------------------------------------------------------------ convite --

def test_cancelar_convite_pendente(admin, caixa, novo_usuario):
    r = admin.post("/admin/users", {"email": "engano@example.com"})
    token = r.json()["invite_url"].split("#convite=")[1]
    uid = next(u["id"] for u in admin.get("/admin/users").json() if u["email"] == "engano@example.com")
    assert Api().post(f"/admin/users/{uid}/cancel-invite").status_code in (401, 403)
    r = admin.post(f"/admin/users/{uid}/cancel-invite")
    assert r.status_code == 200 and r.json()["email"] == "engano@example.com"
    assert all(u["email"] != "engano@example.com" for u in admin.get("/admin/users").json())
    # O link morreu junto com a conta.
    assert Api().post("/auth/invite/accept", {"token": token, "password": SENHA_PADRAO}).status_code == 400
    assert any(h["action"] == "user.invite_cancel" and "engano@example.com" in h["summary"] for h in hist(admin))
    # Conta que já aceitou não sai por aqui (é Excluir conta, com o e-mail).
    usuario = novo_usuario()
    assert admin.post(f"/admin/users/{uid_de(usuario)}/cancel-invite").status_code == 400
    assert usuario.get("/auth/me").status_code == 200


# ------------------------------------------------------------ bloquear --

def test_bloquear_acesso_e_liberar(admin, caixa, novo_usuario):
    usuario = novo_usuario()
    uid = uid_de(usuario)
    tid = usuario.post("/worklog", {"title": "Fica guardada"}).json()["id"]
    criar_chave(usuario, scope="read")
    assert admin.post(f"/admin/users/{uid_de(admin)}/block").status_code == 400  # a própria conta
    r = admin.post(f"/admin/users/{uid}/block")
    assert r.status_code == 200, r.text
    # Sessão derrubada, chave revogada, senha antiga não entra, esqueci a senha não manda link.
    assert usuario.get("/auth/me").status_code == 401
    assert db.query_one("SELECT count(*)::int AS n FROM api_tokens WHERE user_id = %s AND revoked_at IS NULL", (uid,))["n"] == 0
    assert Api().post("/auth/login", {"email": usuario.me["email"], "password": SENHA_PADRAO}).status_code == 401
    caixa.clear()
    assert Api().post("/auth/forgot", {"email": usuario.me["email"]}).status_code == 200
    assert caixa == []
    linha = next(u for u in admin.get("/admin/users").json() if u["id"] == uid)
    assert linha["blocked_at"]
    # Os dados ficam.
    assert db.query_one("SELECT 1 FROM worklog_tasks WHERE id = %s", (tid,))
    # Redefinir senha libera (senha temporária, troca no 1º login).
    temp = admin.post(f"/admin/users/{uid}/reset-password").json()["temp_password"]
    assert not next(u for u in admin.get("/admin/users").json() if u["id"] == uid)["blocked_at"]
    volta = Api()
    volta.login(usuario.me["email"], temp)
    assert volta.get("/auth/me").json()["must_change_password"]


def test_bloquear_convite_pendente_pede_cancelar(admin, caixa):
    admin.post("/admin/users", {"email": "pendente@example.com"})
    uid = next(u["id"] for u in admin.get("/admin/users").json() if u["email"] == "pendente@example.com")
    r = admin.post(f"/admin/users/{uid}/block")
    assert r.status_code == 400 and "Cancelar convite" in r.json()["detail"]


def test_lista_de_contas_diz_se_permitiu_o_visualizador(admin, novo_usuario):
    usuario = novo_usuario()
    linha = lambda: next(u for u in admin.get("/admin/users").json() if u["id"] == uid_de(usuario))  # noqa: E731
    assert linha()["viewers_allowed"] is False
    usuario.put("/me/viewers", {"accept": True})
    assert linha()["viewers_allowed"] is True


# ------------------------------------------------------------ atribuir --

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


def _linha(chefe, tid):
    return next(x for x in chefe.get("/assign/sent").json() if x["id"] == tid)


def test_quem_atribuiu_altera_enquanto_a_fazer(par, caixa):
    chefe, marina = par
    tid = _mandar(chefe, marina, due_date="2030-01-10")
    assert _linha(chefe, tid)["editable"] is True
    caixa.clear()
    r = chefe.patch(f"/assign/{tid}", {"title": "Trocar o nobreak da sala 2", "priority": 1, "due_date": None})
    assert r.status_code == 200, r.text
    t = marina.get(f"/worklog/{tid}").json()
    assert t["title"] == "Trocar o nobreak da sala 2" and t["priority"] == 1 and t["due_date"] is None
    assert caixa and caixa[-1][0] == "marina@example.com" and "alterada" in caixa[-1][1].lower()
    # Histórico nas duas pontas; quem recebeu pode desfazer a alteração (a tarefa é dela).
    assert any(h["action"] == "assign.update" for h in hist(chefe))
    rec = next(h for h in hist(marina, entity="worklog", entity_id=tid) if h["action"] == "worklog.assign_update")
    assert "que tinha atribuído a você" in rec["summary"] and rec["can_undo"]
    assert marina.post(f"/history/{rec['id']}/undo").status_code == 200
    assert marina.get(f"/worklog/{tid}").json()["title"] == "Trocar o nobreak"
    # Outra pessoa não mexe; título vazio não vale.
    assert marina.patch(f"/assign/{tid}", {"title": "x"}).status_code == 403
    assert chefe.patch(f"/assign/{tid}", {"title": "  "}).status_code == 422
    assert chefe.patch(f"/assign/{tid}", {}).status_code == 400


def test_depois_de_comecar_e_so_de_quem_recebeu(par):
    chefe, marina = par
    tid = _mandar(chefe, marina)
    marina.post(f"/worklog/{tid}/notes", {"body": "vi o modelo"})
    assert _linha(chefe, tid)["editable"] is False
    assert chefe.patch(f"/assign/{tid}", {"title": "outro"}).status_code == 409
    assert chefe.post(f"/assign/{tid}/cancel").status_code == 409
    tid2 = _mandar(chefe, marina)
    marina.patch(f"/worklog/{tid2}", {"status": "in_progress"})
    assert chefe.post(f"/assign/{tid2}/cancel").status_code == 409
    assert marina.get(f"/worklog/{tid2}").status_code == 200


def test_cancelar_atribuicao_fica_na_lista(par, caixa):
    chefe, marina = par
    tid = _mandar(chefe, marina)
    caixa.clear()
    assert chefe.post(f"/assign/{tid}/cancel").status_code == 200
    assert marina.get(f"/worklog/{tid}").status_code == 404
    assert caixa and caixa[-1][0] == "marina@example.com" and "cancelada" in caixa[-1][1].lower()
    linha = _linha(chefe, tid)
    assert linha["status"] == "removed" and linha["ended"]["kind"] == "canceled" and linha["ended"]["at"]
    assert linha["title"] == "Trocar o nobreak" and linha["to_name"]
    rec = next(h for h in hist(marina, entity="worklog", entity_id=tid) if h["action"] == "worklog.assign_cancel")
    assert "cancelou" in rec["summary"] and not rec["can_undo"]
    assert chefe.post(f"/assign/{tid}/cancel").status_code == 404


def test_excluida_ou_concluida_por_quem_recebeu(par):
    chefe, marina = par
    apagar = _mandar(chefe, marina)
    concluir = _mandar(chefe, marina)
    assert marina.delete(f"/worklog/{apagar}").status_code == 200
    marina.post(f"/worklog/{concluir}/finish")
    sent = {x["id"]: x for x in chefe.get("/assign/sent").json()}
    assert sent[apagar]["status"] == "removed" and sent[apagar]["ended"]["kind"] == "deleted" and sent[apagar]["ended"]["at"]
    assert sent[concluir]["status"] == "done" and sent[concluir]["completed_at"] and sent[concluir]["ended"] is None
    # Desfez a exclusão: volta como tarefa normal (não aparece duas vezes).
    rec = next(h for h in hist(marina, entity="worklog", entity_id=apagar) if h["action"] == "worklog.delete")
    assert marina.post(f"/history/{rec['id']}/undo").status_code == 200
    ids = [x["id"] for x in chefe.get("/assign/sent").json()]
    assert ids.count(apagar) == 1 and _linha(chefe, apagar)["status"] == "todo"
