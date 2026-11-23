"""Auditoria, pacote p09: desfazer e rotinas (troca de agenda, pausas, projeto
excluído, log de admin). Regra geral: o desfazer nunca responde ok sem ter
mudado alguma coisa."""
import threading
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app import audit, db
from app.routers import recurring as rec
from conftest import ADMIN_EMAIL, ADMIN_PW, Api, Bearer, SENHA_PADRAO, criar_chave, dia_hoje, hist, recuar_criacao, uid_de


def _ativas(u):
    return db.query_all("SELECT id, label, freq, weekdays FROM recurring_tasks WHERE user_id = %s AND active ORDER BY id",
                        (uid_de(u),))


def _ultima(u, action, **kw):
    return next(h for h in hist(u, limit=200, **kw) if h["action"] == action)


def _intacto(u, hid):
    """O desfazer recusado não mexe no histórico: a ação segue desfazível e não há linha "undo"."""
    assert db.query_one("SELECT undone_at FROM audit_log WHERE id = %s", (hid,))["undone_at"] is None
    assert not db.query_one("SELECT 1 FROM audit_log WHERE user_id = %s AND action = 'undo'", (uid_de(u),))


def _juntos(*chamadas):
    """Roda as chamadas ao mesmo tempo (uma thread cada) e devolve os resultados na ordem."""
    largada, out = threading.Barrier(len(chamadas)), [None] * len(chamadas)

    def _run(i, f):
        largada.wait()
        out[i] = f()
    ts = [threading.Thread(target=_run, args=(i, f)) for i, f in enumerate(chamadas)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return out


def _outra_sessao(u):
    o = Api()
    o.login(u.me["email"], SENHA_PADRAO)
    return o


# ------------------------------------------------- troca de agenda e desfazer --
def test_desfazer_renomeacao_depois_da_troca_de_agenda_e_recusado(usuario):
    rid = usuario.post("/recurring", {"label": "Triagem"}).json()["id"]
    recuar_criacao(rid, 5)
    assert usuario.patch(f"/recurring/{rid}", {"label": "Triagem renomeada"}).status_code == 200
    novo = usuario.patch(f"/recurring/{rid}", {"freq": "weekly", "weekdays": 42}).json()
    assert novo["replaced"] == rid

    ren = _ultima(usuario, "recurring.update", entity="recurring", entity_id=rid)
    assert ren["can_undo"] is False  # o Histórico não oferece
    r = usuario.post(f"/history/{ren['id']}/undo")
    assert r.status_code == 409 and "desfaça a troca primeiro" in r.json()["detail"]
    assert [x["id"] for x in _ativas(usuario)] == [novo["id"]]  # uma rotina ativa, não duas
    _intacto(usuario, ren["id"])

    # Desfeita a troca, a renomeação volta a poder ser desfeita.
    troca = _ultima(usuario, "recurring.replace")
    assert usuario.post(f"/history/{troca['id']}/undo").status_code == 200
    ren = _ultima(usuario, "recurring.update", entity="recurring", entity_id=rid)
    assert ren["can_undo"] is True
    assert usuario.post(f"/history/{ren['id']}/undo").status_code == 200
    assert [(x["id"], x["label"]) for x in _ativas(usuario)] == [(rid, "Triagem")]


def test_desfazer_marcacao_depois_da_troca_de_agenda(usuario):
    hoje = dia_hoje(usuario)
    rid = usuario.post("/recurring", {"label": "Backups"}).json()["id"]
    recuar_criacao(rid, 5)
    ontem = (hoje - timedelta(days=1)).isoformat()
    usuario.post(f"/recurring/{rid}/toggle", {"done": True, "day": ontem})
    antiga = _ultima(usuario, "recurring.toggle", entity="recurring", entity_id=rid)
    usuario.post(f"/recurring/{rid}/toggle", {"done": True})
    de_hoje = _ultima(usuario, "recurring.toggle", entity="recurring", entity_id=rid)
    novo = usuario.patch(f"/recurring/{rid}", {"freq": "weekly", "weekdays": 127}).json()["id"]

    # A marcação de hoje passou para a rotina nova: 409, e ela segue marcada.
    h = next(x for x in hist(usuario, limit=200) if x["id"] == de_hoje["id"])
    assert h["can_undo"] is False
    r = usuario.post(f"/history/{de_hoje['id']}/undo")
    assert r.status_code == 409 and "desfaça a troca primeiro" in r.json()["detail"]
    assert db.query_one("SELECT 1 FROM recurring_completions WHERE task_id = %s AND completed_date = %s", (novo, hoje))
    _intacto(usuario, de_hoje["id"])
    # A de ontem ficou na antiga, mas não é mais a última ação dela: recusada também, sem mexer em nada.
    assert usuario.post(f"/history/{antiga['id']}/undo").status_code == 409
    assert db.query_one("SELECT 1 FROM recurring_completions WHERE task_id = %s AND completed_date = %s", (rid, ontem))


def test_desfazer_marcacao_que_ja_nao_existe_e_recusado(usuario):
    """O DELETE que não apaga nada não vira "ok"."""
    rid = usuario.post("/recurring", {"label": "Backups"}).json()["id"]
    usuario.post(f"/recurring/{rid}/toggle", {"done": True})
    h = _ultima(usuario, "recurring.toggle")
    db.execute("DELETE FROM recurring_completions WHERE task_id = %s", (rid,))
    r = usuario.post(f"/history/{h['id']}/undo")
    assert r.status_code == 409
    _intacto(usuario, h["id"])


def test_desfazer_a_troca_dos_dias_uteis_mantem_o_passado(usuario):
    hoje = dia_hoje(usuario)
    usuario.post("/auth/settings", {"work_days": 62})  # seg a sex
    rid = usuario.post("/recurring", {"label": "Conferir backup"}).json()["id"]
    recuar_criacao(rid, 28)
    periodo = {"start": (hoje - timedelta(days=27)).isoformat(), "end": (hoje - timedelta(days=1)).isoformat()}

    def devidas():
        return usuario.get("/reports/preview", params=periodo).json()["recurring_total"]

    antes = devidas()
    assert usuario.post("/auth/settings", {"work_days": 127}).status_code == 200
    assert devidas() == antes
    troca = _ultima(usuario, "recurring.replace")
    assert usuario.post(f"/history/{troca['id']}/undo").status_code == 200
    assert devidas() == antes  # eram +8 faltas retroativas
    volta = _ativas(usuario)
    assert [(x["id"], x["freq"], x["weekdays"]) for x in volta] == [(rid, "weekly", 62)]


def test_troca_de_agenda_repetida_nao_multiplica_rotinas(usuario):
    rid = usuario.post("/recurring", {"label": "Revisar PRs"}).json()["id"]
    recuar_criacao(rid, 5)
    # As duas chamadas leram a rotina ainda ativa (o retrato é de antes): só a primeira troca.
    ctx = {"user_id": uid_de(usuario), "actor": "web"}
    snap = audit.recurring_snapshot(rid, ctx["user_id"])
    rec.replace_routine(ctx, snap, {"label": snap["label"], "freq": "weekly", "weekdays": 42})
    with pytest.raises(HTTPException) as e:
        rec.replace_routine(ctx, snap, {"label": snap["label"], "freq": "weekly", "weekdays": 42})
    assert e.value.status_code == 409 and "já foi alterada" in e.value.detail
    assert len(_ativas(usuario)) == 1
    assert len([h for h in hist(usuario, limit=200) if h["action"] == "recurring.replace"]) == 1


def test_dois_patch_simultaneos_criam_uma_rotina_so(usuario):
    outra = _outra_sessao(usuario)
    for _ in range(5):
        for r in _ativas(usuario):
            usuario.delete(f"/recurring/{r['id']}")
        rid = usuario.post("/recurring", {"label": "Revisar PRs"}).json()["id"]
        recuar_criacao(rid, 5)
        res = _juntos(*[lambda c=c: c.patch(f"/recurring/{rid}", {"freq": "weekly", "weekdays": 42}) for c in (usuario, outra)])
        codigos = sorted(r.status_code for r in res)
        assert codigos[0] == 200 and codigos[1] in (404, 409), codigos
        ativas = _ativas(usuario)
        assert len(ativas) == 1 and ativas[0]["id"] != rid


# ------------------------------------------------------------------ pausas --
def test_retomar_encerra_todas_as_pausas_de_hoje(usuario):
    hoje = dia_hoje(usuario)
    rid = usuario.post("/recurring", {"label": "Ronda"}).json()["id"]
    assert usuario.post(f"/recurring/{rid}/pause", {"until": (hoje + timedelta(days=10)).isoformat()}).status_code == 200
    # A segunda pausa que duas chamadas simultâneas deixavam.
    db.execute("INSERT INTO recurring_pauses (recurring_id, start_d, end_d) VALUES (%s, %s, %s)",
               (rid, hoje, hoje + timedelta(days=17)))
    assert usuario.delete(f"/recurring/{rid}/pause").json()["paused_until"] is None
    assert not db.query_one("SELECT 1 FROM recurring_pauses WHERE recurring_id = %s AND start_d <= %s AND end_d >= %s",
                            (rid, hoje, hoje))
    item = next(r for r in usuario.get("/board").json()["recurring"] if r["id"] == rid)
    assert not item.get("paused_until")
    assert usuario.delete(f"/recurring/{rid}/pause").status_code == 400  # já não está pausada


# ------------------------------------------------------------------ toggle --
def test_toggle_repetido_nao_grava_historico(usuario):
    rid = usuario.post("/recurring", {"label": "Backups"}).json()["id"]
    for _ in range(3):
        assert usuario.post(f"/recurring/{rid}/toggle", {"done": True}).status_code == 200
    for _ in range(3):
        assert usuario.post(f"/recurring/{rid}/toggle", {"done": False}).status_code == 200
    linhas = [h for h in hist(usuario, limit=200) if h["action"] == "recurring.toggle"]
    assert [h["summary"].split()[0] for h in linhas] == ["desmarcou", "marcou"]


def test_40_pares_desmarcar_marcar_o_historico_bate_com_o_estado(usuario):
    outra = _outra_sessao(usuario)
    hoje = dia_hoje(usuario)
    rid = usuario.post("/recurring", {"label": "Backups"}).json()["id"]
    usuario.post(f"/recurring/{rid}/toggle", {"done": True})
    for _ in range(40):
        res = _juntos(lambda: usuario.post(f"/recurring/{rid}/toggle", {"done": False}),
                      lambda: outra.post(f"/recurring/{rid}/toggle", {"done": True}))
        assert [r.status_code for r in res] == [200, 200]
        feita = bool(db.query_one("SELECT 1 FROM recurring_completions WHERE task_id = %s AND completed_date = %s",
                                  (rid, hoje)))
        ultima = db.query_one("""SELECT after FROM audit_log WHERE action = 'recurring.toggle' AND entity_id = %s
                                  ORDER BY id DESC LIMIT 1""", (rid,))["after"]
        assert ultima["done"] == feita
    # Nenhuma linha repetida: cada uma é uma mudança de verdade, alternando.
    linhas = db.query_all("""SELECT before, after FROM audit_log WHERE action = 'recurring.toggle' AND entity_id = %s
                              ORDER BY id""", (rid,))
    assert all(x["before"]["done"] != x["after"]["done"] for x in linhas)
    assert all(a["after"]["done"] != b["after"]["done"] for a, b in zip(linhas, linhas[1:]))


# ---------------------------------------------------------- projeto excluído --
def test_desfazer_exclusao_de_projeto_religa_vencimento_modelo_e_padrao(usuario):
    uid = uid_de(usuario)
    hoje = dia_hoje(usuario)
    p = usuario.post("/projects", {"name": "Infra"}).json()["id"]
    q = usuario.post("/projects", {"name": "Outro"}).json()["id"]
    venc = [usuario.post("/renewals", {"label": f"Certificado {i}", "expires_on": (hoje + timedelta(days=40)).isoformat(),
                                       "project_id": p}).json()["id"] for i in range(2)]
    mod = usuario.post("/templates", {"name": "Padrão", "title": "Abrir chamado", "project_id": p}).json()["id"]
    assert usuario.put("/me/default-project", {"project_id": p}).status_code == 200

    assert usuario.delete(f"/projects/{p}").status_code == 200
    assert db.query_one("SELECT default_project_id FROM users WHERE id = %s", (uid,))["default_project_id"] is None
    # Um dos vencimentos ganhou outro projeto depois da exclusão: fica como está.
    db.execute("UPDATE renewals SET project_id = %s WHERE id = %s", (q, venc[1]))

    h = _ultima(usuario, "project.delete")
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert db.query_one("SELECT project_id FROM renewals WHERE id = %s", (venc[0],))["project_id"] == p
    assert db.query_one("SELECT project_id FROM renewals WHERE id = %s", (venc[1],))["project_id"] == q
    assert db.query_one("SELECT project_id FROM task_templates WHERE id = %s", (mod,))["project_id"] == p
    assert db.query_one("SELECT default_project_id FROM users WHERE id = %s", (uid,))["default_project_id"] == p


def test_desfazer_exclusao_de_projeto_nao_troca_o_padrao_escolhido_depois(usuario):
    uid = uid_de(usuario)
    p = usuario.post("/projects", {"name": "Infra"}).json()["id"]
    q = usuario.post("/projects", {"name": "Outro"}).json()["id"]
    usuario.put("/me/default-project", {"project_id": p})
    usuario.delete(f"/projects/{p}")
    usuario.put("/me/default-project", {"project_id": q})
    assert usuario.post(f"/history/{_ultima(usuario, 'project.delete')['id']}/undo").status_code == 200
    assert db.query_one("SELECT default_project_id FROM users WHERE id = %s", (uid,))["default_project_id"] == q


# ------------------------------------------------- apontamentos e cronômetro --
def test_lapide_com_user_id_alheio_restaura_com_o_dono_original(usuario, novo_usuario):
    outro = uid_de(novo_usuario("quem-saiu@example.com"))
    uid = uid_de(usuario)
    tid = usuario.post("/worklog", {"title": "Transferida"}).json()["id"]
    assert usuario.post(f"/worklog/{tid}/time", {"minutes": 30}).status_code == 201
    assert usuario.post(f"/worklog/{tid}/time", {"minutes": 45}).status_code == 201
    assert usuario.delete(f"/worklog/{tid}").status_code == 200
    h = _ultima(usuario, "worklog.delete")
    tempos = db.query_one("SELECT before->'children'->'time' AS t FROM audit_log WHERE id = %s", (h["id"],))["t"]
    alheio = next(i for i, e in enumerate(tempos) if e["minutes"] == 30)
    # A lápide que p03/p08 passam a gravar: `user_id` por apontamento. O de 45 min segue sem o campo (lápide antiga).
    db.execute("UPDATE audit_log SET before = jsonb_set(before, %s, %s::text::jsonb) WHERE id = %s",
               (["children", "time", str(alheio), "user_id"], outro, h["id"]))
    for i, e in enumerate(tempos):
        if i != alheio:
            db.execute("UPDATE audit_log SET before = before #- %s WHERE id = %s", (["children", "time", str(i), "user_id"], h["id"]))

    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    donos = {r["minutes"]: r["user_id"] for r in db.query_all("SELECT minutes, user_id FROM time_entries WHERE task_id = %s", (tid,))}
    assert donos == {30: outro, 45: uid}


def test_lapide_de_conta_que_nao_existe_mais_nao_passa_as_horas_a_quem_desfaz(usuario):
    tid = usuario.post("/worklog", {"title": "Transferida"}).json()["id"]
    usuario.post(f"/worklog/{tid}/time", {"minutes": 30})
    usuario.delete(f"/worklog/{tid}")
    h = _ultima(usuario, "worklog.delete")
    db.execute("UPDATE audit_log SET before = jsonb_set(before, '{children,time,0,user_id}', '999999') WHERE id = %s", (h["id"],))
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert db.query_one("SELECT 1 FROM worklog_tasks WHERE id = %s", (tid,))
    assert not db.query_one("SELECT 1 FROM time_entries WHERE task_id = %s", (tid,))


def test_desfazer_que_volta_a_concluida_para_o_cronometro(usuario):
    uid = uid_de(usuario)
    tid = usuario.post("/worklog", {"title": "Entrega"}).json()["id"]
    usuario.post(f"/worklog/{tid}/finish")
    assert usuario.patch(f"/worklog/{tid}", {"status": "todo"}).status_code == 200  # reabriu
    assert usuario.post("/timer/start", {"task_id": tid}).status_code == 200
    assert db.query_one("SELECT 1 FROM task_timers WHERE user_id = %s", (uid,))
    for _ in range(3):  # desfaz as edições até a tarefa voltar a concluída
        if db.query_one("SELECT status FROM worklog_tasks WHERE id = %s", (tid,))["status"] == "done":
            break
        h = next(x for x in hist(usuario, entity="worklog", entity_id=tid) if x["can_undo"])
        assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert db.query_one("SELECT status FROM worklog_tasks WHERE id = %s", (tid,))["status"] == "done"
    assert not db.query_one("SELECT 1 FROM task_timers WHERE user_id = %s", (uid,))
    assert db.query_one("SELECT 1 FROM time_entries WHERE task_id = %s", (tid,))  # o tempo foi apontado, não perdido


# ------------------------------------------------------------ log de admin --
def test_chave_e_mcp_nao_leem_o_log_de_admin(admin):
    aid = uid_de(admin)
    admin.post("/worklog", {"title": "Tarefa do admin"})
    audit.record({"user_id": aid, "actor": "admin"}, "master.view", "user", 999,
                 after={"what": "quadro", "email": "terceiro@example.com"})
    db.execute("UPDATE audit_log SET created_at = created_at - interval '1 minute'")  # o feed espera 2 s

    # A sessão do próprio admin continua vendo tudo.
    assert any(h["actor"] == "admin" for h in hist(admin, limit=200))
    assert "terceiro@example.com" in admin.get("/history?limit=200").text
    assert any(e["actor"] == "admin" for e in admin.get("/history?after=0&limit=200").json())

    for scope in ("read", "write"):
        chave = Bearer(criar_chave(admin, nome=f"IA {scope}", scope=scope)["token"])
        r = chave.get("/history?limit=200")
        assert r.status_code == 200 and "terceiro@example.com" not in r.text
        assert r.json() and all(h["actor"] != "admin" for h in r.json())
        assert int(r.headers["X-Total-Count"]) == len(r.json())  # o total também não conta o que foi escondido
        feed = chave.get("/history?after=0&limit=200").json()
        assert feed and all(e["actor"] != "admin" for e in feed)
        mcp = chave.rpc("tools/list").json()["result"]["tools"]
        ferramenta = next((t["name"] for t in mcp if "hist" in t["name"]), None)
        if ferramenta:
            assert "terceiro@example.com" not in str(chave.tool(ferramenta, limit=50))


# -------------------------------------------- tabela: alvo apagado = 409 ----
def _tarefa(u):
    return u.post("/worklog", {"title": "Alvo"}).json()["id"]


def _c_worklog_create(u):
    t = _tarefa(u)
    return "worklog.create", ("worklog_tasks", t)


def _c_worklog_update(u):
    t = _tarefa(u)
    u.patch(f"/worklog/{t}", {"title": "Outro"})
    return "worklog.update", ("worklog_tasks", t)


def _c_worklog_finish(u):
    t = _tarefa(u)
    u.post(f"/worklog/{t}/finish")
    return "worklog.finish", ("worklog_tasks", t)


def _c_note_create(u):
    n = u.post(f"/worklog/{_tarefa(u)}/notes", {"body": "nota"}).json()["id"]
    return "note.create", ("task_notes", n)


def _c_note_update(u):
    n = u.post(f"/worklog/{_tarefa(u)}/notes", {"body": "nota"}).json()["id"]
    assert u.patch(f"/notes/{n}", {"body": "outra"}).status_code == 200
    return "note.update", ("task_notes", n)


def _c_note_delete(u):
    t = _tarefa(u)
    n = u.post(f"/worklog/{t}/notes", {"body": "nota"}).json()["id"]
    assert u.delete(f"/notes/{n}").status_code == 200
    return "note.delete", ("worklog_tasks", t)


def _c_checklist_create(u):
    c = u.post(f"/worklog/{_tarefa(u)}/checklist", {"label": "item"}).json()["id"]
    return "checklist.create", ("task_checklist", c)


def _c_checklist_update(u):
    c = u.post(f"/worklog/{_tarefa(u)}/checklist", {"label": "item"}).json()["id"]
    assert u.patch(f"/checklist/{c}", {"done": True}).status_code == 200
    return "checklist.update", ("task_checklist", c)


def _c_checklist_delete(u):
    t = _tarefa(u)
    c = u.post(f"/worklog/{t}/checklist", {"label": "item"}).json()["id"]
    assert u.delete(f"/checklist/{c}").status_code == 200
    return "checklist.delete", ("worklog_tasks", t)


def _c_time_create(u):
    e = u.post(f"/worklog/{_tarefa(u)}/time", {"minutes": 10}).json()["id"]
    return "time.create", ("time_entries", e)


def _c_time_update(u):
    e = u.post(f"/worklog/{_tarefa(u)}/time", {"minutes": 10}).json()["id"]
    assert u.patch(f"/time/{e}", {"minutes": 20}).status_code == 200
    return "time.update", ("time_entries", e)


def _c_time_delete(u):
    t = _tarefa(u)
    e = u.post(f"/worklog/{t}/time", {"minutes": 10}).json()["id"]
    assert u.delete(f"/time/{e}").status_code == 200
    return "time.delete", ("worklog_tasks", t)


def _rotina(u):
    return u.post("/recurring", {"label": "Alvo"}).json()["id"]


def _c_recurring_create(u):
    return "recurring.create", ("recurring_tasks", _rotina(u))


def _c_recurring_update(u):
    r = _rotina(u)
    u.patch(f"/recurring/{r}", {"label": "Outro"})
    return "recurring.update", ("recurring_tasks", r)


def _c_recurring_deactivate(u):
    r = _rotina(u)
    u.delete(f"/recurring/{r}")
    return "recurring.deactivate", ("recurring_tasks", r)


def _c_recurring_toggle(u):
    r = _rotina(u)
    u.post(f"/recurring/{r}/toggle", {"done": True})
    return "recurring.toggle", ("recurring_tasks", r)


def _c_recurring_pause(u):
    r = _rotina(u)
    u.post(f"/recurring/{r}/pause", {"until": (dia_hoje(u) + timedelta(days=3)).isoformat()})
    return "recurring.pause", ("recurring_tasks", r)


def _c_recurring_resume(u):
    r = _rotina(u)
    u.post(f"/recurring/{r}/pause", {"until": (dia_hoje(u) + timedelta(days=3)).isoformat()})
    u.delete(f"/recurring/{r}/pause")
    return "recurring.resume", ("recurring_tasks", r)


def _c_recurring_replace(u):
    r = _rotina(u)
    recuar_criacao(r, 5)
    novo = u.patch(f"/recurring/{r}", {"freq": "weekly", "weekdays": 42}).json()["id"]
    return "recurring.replace", ("recurring_tasks", novo)


def _c_renewal_create(u):
    v = u.post("/renewals", {"label": "Domínio", "expires_on": (dia_hoje(u) + timedelta(days=30)).isoformat()}).json()["id"]
    return "renewal.create", ("renewals", v)


def _c_renewal_update(u):
    v = u.post("/renewals", {"label": "Domínio", "expires_on": (dia_hoje(u) + timedelta(days=30)).isoformat()}).json()["id"]
    assert u.patch(f"/renewals/{v}", {"label": "Domínio novo"}).status_code == 200
    return "renewal.update", ("renewals", v)


def _projeto(u):
    return u.post("/projects", {"name": "Alvo"}).json()["id"]


def _c_project_create(u):
    return "project.create", ("projects", _projeto(u))


def _c_project_update(u):
    p = _projeto(u)
    assert u.patch(f"/projects/{p}", {"name": "Outro nome"}).status_code == 200
    return "project.update", ("projects", p)


def _c_objective_create(u):
    o = u.post(f"/projects/{_projeto(u)}/objectives", {"title": "Meta"}).json()["id"]
    return "objective.create", ("project_objectives", o)


def _c_objective_update(u):
    o = u.post(f"/projects/{_projeto(u)}/objectives", {"title": "Meta"}).json()["id"]
    assert u.patch(f"/objectives/{o}", {"title": "Meta nova"}).status_code == 200
    return "objective.update", ("project_objectives", o)


def _c_objective_delete(u):
    p = _projeto(u)
    o = u.post(f"/projects/{p}/objectives", {"title": "Meta"}).json()["id"]
    assert u.delete(f"/objectives/{o}").status_code == 200
    return "objective.delete", ("projects", p)


CASOS = [_c_worklog_create, _c_worklog_update, _c_worklog_finish,
         _c_note_create, _c_note_update, _c_note_delete,
         _c_checklist_create, _c_checklist_update, _c_checklist_delete,
         _c_time_create, _c_time_update, _c_time_delete,
         _c_recurring_create, _c_recurring_update, _c_recurring_deactivate, _c_recurring_toggle,
         _c_recurring_pause, _c_recurring_resume, _c_recurring_replace,
         _c_renewal_create, _c_renewal_update,
         _c_project_create, _c_project_update,
         _c_objective_create, _c_objective_update, _c_objective_delete]


@pytest.mark.parametrize("caso", CASOS, ids=lambda c: c.__name__[3:])
def test_desfazer_com_o_alvo_apagado_responde_409_e_nao_muda_nada(usuario, caso):
    acao, (tabela, alvo) = caso(usuario)
    h = _ultima(usuario, acao)
    assert h["can_undo"] is True
    db.execute(f"DELETE FROM {tabela} WHERE id = %s", (alvo,))
    tabelas = ("worklog_tasks", "task_notes", "task_checklist", "time_entries", "recurring_tasks", "recurring_completions",
               "recurring_pauses", "renewals", "projects", "project_objectives", "audit_log")
    antes = {t: db.query_all(f"SELECT * FROM {t} ORDER BY id") for t in tabelas}
    r = usuario.post(f"/history/{h['id']}/undo")
    assert r.status_code == 409, (acao, r.status_code, r.text)
    assert {t: db.query_all(f"SELECT * FROM {t} ORDER BY id") for t in tabelas} == antes  # banco intacto


# ------------------------------------------------------- janela de 7 dias ---
@pytest.mark.parametrize("caso", [_c_recurring_deactivate, _c_recurring_replace, _c_recurring_pause, _c_recurring_resume],
                         ids=lambda c: c.__name__[3:])
def test_janela_de_7_dias_do_desfazer(usuario, caso):
    acao, _ = caso(usuario)
    h = _ultima(usuario, acao)
    db.execute("UPDATE audit_log SET created_at = created_at - interval '8 days' WHERE id = %s", (h["id"],))
    r = usuario.post(f"/history/{h['id']}/undo")
    assert r.status_code == 409 and "janela de 7 dias" in r.json()["detail"]
    _intacto(usuario, h["id"])
    # Dentro da janela, o mesmo desfazer vale.
    db.execute("UPDATE audit_log SET created_at = created_at + interval '6 days' WHERE id = %s", (h["id"],))
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200


def test_janela_de_7_dias_da_marcacao(usuario):
    rid = _rotina(usuario)
    recuar_criacao(rid, 20)
    dia = (dia_hoje(usuario) - timedelta(days=3)).isoformat()
    usuario.post(f"/recurring/{rid}/toggle", {"done": True, "day": dia})
    h = _ultima(usuario, "recurring.toggle")
    velho = (dia_hoje(usuario) - timedelta(days=12)).isoformat()
    # A marcação é de um dia que já saiu da janela (o dia vale, não a hora da ação).
    db.execute("""UPDATE audit_log SET before = jsonb_set(before, '{day}', to_jsonb(%s::text)),
                                       after = jsonb_set(after, '{day}', to_jsonb(%s::text)) WHERE id = %s""",
               (velho, velho, h["id"]))
    r = usuario.post(f"/history/{h['id']}/undo")
    assert r.status_code == 409 and "7 dias" in r.json()["detail"]
    assert db.query_one("SELECT 1 FROM recurring_completions WHERE task_id = %s AND completed_date = %s", (rid, dia))
