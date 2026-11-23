"""Rodada 2, pacote r2-01: excluir a conta de quem recebeu uma tarefa transferida
não apaga em cascata as horas de quem a passou (409 sem transferência; com
transferência, a tarefa e as horas seguem para quem recebe)."""
from app import db
from conftest import SENHA_PADRAO, uid_de


def _cena(admin, novo_usuario):
    """A apontou 30 min numa tarefa e foi bloqueado com transfer_to B: a tarefa é de B, as horas são de A."""
    a, b, c = (novo_usuario(f"{n}@example.com") for n in ("a", "b", "c"))
    tid = a.post("/worklog", {"title": "Trocar o switch"}).json()["id"]
    assert a.post(f"/worklog/{tid}/time", {"minutes": 30}).status_code in (200, 201)
    assert admin.post(f"/admin/users/{uid_de(a)}/block", {"transfer_to": uid_de(b)}).status_code == 200
    return a, b, c, tid


def _horas(u):
    return db.query_one("SELECT count(*)::int AS n, coalesce(sum(minutes), 0)::int AS m FROM time_entries"
                        " WHERE user_id = %s", (uid_de(u),))


def _dono(tid):
    row = db.query_one("SELECT user_id FROM worklog_tasks WHERE id = %s", (tid,))
    return row and row["user_id"]


def _excluir(admin, u, email, **kw):
    return admin.post(f"/admin/users/{uid_de(u)}/delete", {"confirm_email": email, **kw})


def test_excluir_quem_recebeu_sem_transferir_da_409_e_as_horas_ficam(admin, novo_usuario):
    a, b, _c, tid = _cena(admin, novo_usuario)
    uid_b = uid_de(b)
    r = _excluir(admin, b, "b@example.com")
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert "1 tarefa com horas de outra pessoa" in d and "transfira as tarefas para outra pessoa" in d
    # Nada foi apagado: a conta, a tarefa e as horas de A.
    assert db.query_one("SELECT 1 FROM users WHERE id = %s", (uid_b,))
    assert _dono(tid) == uid_b
    assert _horas(a) == {"n": 1, "m": 30}


def test_excluir_quem_recebeu_com_transferencia_leva_tarefa_e_horas(admin, novo_usuario):
    a, b, c, tid = _cena(admin, novo_usuario)
    uid_b = uid_de(b)
    r = _excluir(admin, b, "b@example.com", transfer_to=uid_de(c))
    assert r.status_code == 200, r.text
    assert r.json()["transferred"]["count"] == 1
    assert not db.query_one("SELECT 1 FROM users WHERE id = %s", (uid_b,))
    assert _dono(tid) == uid_de(c)
    assert _horas(a) == {"n": 1, "m": 30}


def test_conta_sem_horas_de_outra_pessoa_exclui_como_antes(admin, novo_usuario):
    """Guarda do comportamento antigo (passa também sem a correção): tempo próprio sai com a conta."""
    b = novo_usuario("b@example.com")
    tid = b.post("/worklog", {"title": "Só minha"}).json()["id"]
    b.post(f"/worklog/{tid}/time", {"minutes": 45})
    uid_b = uid_de(b)
    r = _excluir(admin, b, "b@example.com")
    assert r.status_code == 200 and r.json()["tasks"] == 1 and r.json()["transferred"] is None
    assert _dono(tid) is None
    assert db.query_one("SELECT count(*)::int AS n FROM time_entries WHERE user_id = %s", (uid_b,))["n"] == 0


def test_concluida_com_horas_de_outra_pessoa_segue_na_exclusao_e_fica_no_bloqueio(admin, novo_usuario, caixa):
    a, b, c, tid = _cena(admin, novo_usuario)
    uid_b = uid_de(b)
    assert b.post(f"/worklog/{tid}/finish", {"resolution": "Trocado"}).status_code == 200
    propria = b.post("/worklog", {"title": "Concluída só de B"}).json()["id"]
    assert b.post(f"/worklog/{propria}/finish").status_code == 200
    antes = db.query_one("SELECT status, completed_at, resolution FROM worklog_tasks WHERE id = %s", (tid,))
    assert antes["status"] == "done"
    # Sem transferência a concluída também barra (é ela que guarda as horas de A).
    assert _excluir(admin, b, "b@example.com").status_code == 409
    caixa.clear()
    r = _excluir(admin, b, "b@example.com", transfer_to=uid_de(c))
    assert r.status_code == 200, r.text
    assert r.json()["transferred"]["count"] == 1  # só a que guarda horas de outra pessoa
    assert r.json()["transferred"]["emailed"] is False and not caixa  # concluída não é trabalho a avisar
    assert not db.query_one("SELECT 1 FROM users WHERE id = %s", (uid_b,))
    depois = db.query_one("SELECT user_id, status, completed_at, resolution FROM worklog_tasks WHERE id = %s", (tid,))
    assert depois.pop("user_id") == uid_de(c) and depois == antes
    assert _dono(propria) is None  # a concluída só de B sai com a conta, como antes
    assert _horas(a) == {"n": 1, "m": 30}


def test_bloquear_com_transferencia_continua_movendo_so_as_abertas(admin, novo_usuario):
    a, b, c, tid = _cena(admin, novo_usuario)
    assert b.post(f"/worklog/{tid}/finish").status_code == 200
    r = admin.post(f"/admin/users/{uid_de(b)}/block", {"transfer_to": uid_de(c)})
    assert r.status_code == 200 and r.json()["transferred"]["count"] == 0
    assert _dono(tid) == uid_de(b)


def test_excluir_a_propria_conta_com_horas_de_outra_pessoa_da_409(admin, novo_usuario):
    a, b, _c, tid = _cena(admin, novo_usuario)
    r = b.post("/me/delete", {"password": SENHA_PADRAO})
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == ("esta conta guarda tarefas com horas de outra pessoa; "
                                  "peça ao admin para excluir com transferência")
    assert _dono(tid) == uid_de(b) and _horas(a) == {"n": 1, "m": 30}
    assert b.get("/auth/me").status_code == 200  # a sessão segue
