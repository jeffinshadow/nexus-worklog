"""Auditoria, pacote p03: tarefas e cronômetro no servidor (horas que somem,
conclusão idempotente e corridas)."""
import threading
from datetime import datetime, timedelta, timezone

from app import db
from conftest import Bearer, criar_chave, hist, uid_de


def _tarefa(u, titulo="Trocar o switch", **kw):
    r = u.post("/worklog", {"title": titulo, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _linhas(tid, acao="worklog.finish"):
    return db.query_one("SELECT count(*)::int AS n FROM audit_log WHERE entity = 'worklog' AND entity_id = %s"
                        " AND action = %s", (tid, acao))["n"]


def _tempo_de_outra_pessoa(tid, outra, minutos=90):
    """Como fica depois da transferência: o apontamento continua de quem saiu."""
    return db.query_one("INSERT INTO time_entries (task_id, user_id, minutes, day) VALUES (%s, %s, %s, current_date)"
                        " RETURNING id", (tid, uid_de(outra), minutos))["id"]


# ---- excluir: horas de quem passou a tarefa, lápide com user_id, cronômetro rodando

def test_excluir_tarefa_com_horas_de_outra_pessoa_da_409_e_nada_some(usuario, novo_usuario):
    outra = novo_usuario("saiu@example.com")
    tid = _tarefa(usuario)
    usuario.post(f"/worklog/{tid}/time", {"minutes": 30})
    _tempo_de_outra_pessoa(tid, outra)
    r = usuario.delete(f"/worklog/{tid}")
    assert r.status_code == 409 and "conclua em vez de excluir" in r.json()["detail"]
    assert usuario.get(f"/worklog/{tid}").status_code == 200
    assert db.query_one("SELECT count(*)::int AS n, sum(minutes)::int AS m FROM time_entries WHERE task_id = %s",
                        (tid,)) == {"n": 2, "m": 120}
    assert _linhas(tid, "worklog.delete") == 0
    assert usuario.post(f"/worklog/{tid}/finish").status_code == 200  # o caminho que a mensagem indica


def test_excluir_tarefa_propria_segue_igual_e_a_lapide_traz_user_id(usuario):
    tid = _tarefa(usuario)
    usuario.post(f"/worklog/{tid}/time", {"minutes": 45})
    assert usuario.delete(f"/worklog/{tid}").status_code == 200
    antes = db.query_one("SELECT before FROM audit_log WHERE entity = 'worklog' AND entity_id = %s"
                         " AND action = 'worklog.delete'", (tid,))["before"]
    tempos = antes["children"]["time"]
    assert [(t["minutes"], t["user_id"]) for t in tempos] == [(45, uid_de(usuario))]


def test_excluir_com_cronometro_rodando_aponta_antes_e_o_tempo_vai_na_lapide(usuario):
    tid = _tarefa(usuario)
    usuario.post("/timer/start", {"task_id": tid})
    db.execute("UPDATE task_timers SET started_at = now() - interval '40 minutes' WHERE task_id = %s", (tid,))
    assert usuario.delete(f"/worklog/{tid}").status_code == 200
    assert usuario.get("/timer").json()["timer"] is None
    antes = db.query_one("SELECT before FROM audit_log WHERE entity = 'worklog' AND entity_id = %s"
                         " AND action = 'worklog.delete'", (tid,))["before"]
    assert [t["minutes"] for t in antes["children"]["time"]] == [40]
    assert antes["children"]["time"][0]["started_at"]


def test_excluir_recusado_nao_para_o_cronometro(usuario, novo_usuario):
    tid = _tarefa(usuario)
    _tempo_de_outra_pessoa(tid, novo_usuario("saiu@example.com"))
    usuario.post("/timer/start", {"task_id": tid})
    assert usuario.delete(f"/worklog/{tid}").status_code == 409
    assert usuario.get("/timer").json()["timer"]["task_id"] == tid


# ---- concluir com cronômetro: a resposta traz o `stopped` de /timer/stop

def test_finish_com_cronometro_esquecido_devolve_needs_review(usuario):
    tid = _tarefa(usuario, "Ronda")
    usuario.post("/timer/start", {"task_id": tid})
    db.execute("UPDATE task_timers SET started_at = now() - interval '13 hours' WHERE task_id = %s", (tid,))
    r = usuario.post(f"/worklog/{tid}/finish")
    st = r.json()["stopped"]
    assert r.status_code == 200 and st["needs_review"] is True and st["minutes"] == 0
    assert st["task_id"] == tid and st["title"] == "Ronda" and st["started_at"]
    t = usuario.get(f"/worklog/{tid}").json()
    assert t["status"] == "done" and t["minutes"] == 0


def test_finish_e_patch_done_devolvem_o_apontamento_do_cronometro(usuario):
    a, b, c = _tarefa(usuario, "A"), _tarefa(usuario, "B"), _tarefa(usuario, "C")
    usuario.post("/timer/start", {"task_id": a})
    db.execute("UPDATE task_timers SET started_at = now() - interval '20 minutes' WHERE task_id = %s", (a,))
    st = usuario.post(f"/worklog/{a}/finish").json()["stopped"]
    assert st["minutes"] == 20 and st["task_id"] == a and "needs_review" not in st
    usuario.post("/timer/start", {"task_id": b})
    db.execute("UPDATE task_timers SET started_at = now() - interval '13 hours' WHERE task_id = %s", (b,))
    r = usuario.patch(f"/worklog/{b}", {"status": "done"})
    assert r.status_code == 200 and r.json()["stopped"]["needs_review"] is True
    assert usuario.post(f"/worklog/{c}/finish").json() == {"ok": True, "stopped": None}  # sem cronômetro
    assert usuario.patch(f"/worklog/{c}", {"title": "C2"}).json() == {"ok": True, "stopped": None}


# ---- finish idempotente

def test_tres_finish_iguais_uma_linha_e_um_aviso(usuario, monkeypatch):
    from app.routers import worklog
    avisos = []
    monkeypatch.setattr(worklog, "safe_notify", avisos.append)
    tid = _tarefa(usuario)
    corpo = {"resolution": "Troquei a fonte", "completed_at": datetime.now(timezone.utc).isoformat()}
    r1 = usuario.post(f"/worklog/{tid}/finish", corpo)
    r2 = usuario.post(f"/worklog/{tid}/finish", corpo)
    r3 = usuario.post(f"/worklog/{tid}/finish", {"resolution": "Troquei a fonte"})
    assert [r.status_code for r in (r1, r2, r3)] == [200, 200, 200]
    assert "existing" not in r1.json() and r2.json()["existing"] is True and r3.json()["existing"] is True
    assert _linhas(tid) == 1 and avisos == [tid]
    assert len([h for h in hist(usuario, entity="worklog") if h["action"] == "worklog.finish"]) == 1


def test_finish_repetido_por_chave_append_da_200_existing(usuario):
    tid = _tarefa(usuario)
    chave = Bearer(criar_chave(usuario, scope="append")["token"])
    corpo = {"resolution": "Reiniciei o serviço"}
    assert chave.post(f"/worklog/{tid}/finish", corpo).status_code == 200
    r = chave.post(f"/worklog/{tid}/finish", corpo)
    assert r.status_code == 200 and r.json()["existing"] is True
    assert _linhas(tid) == 1
    # mudar a conclusão continua fora do "só registrar"; para a chave write é edição válida
    assert chave.post(f"/worklog/{tid}/finish", {"resolution": "Outra coisa"}).status_code == 403
    escreve = Bearer(criar_chave(usuario, nome="escreve")["token"])
    r = escreve.post(f"/worklog/{tid}/finish", {"resolution": "Outra coisa"})
    assert r.status_code == 200 and "existing" not in r.json()
    assert usuario.get(f"/worklog/{tid}").json()["resolution"] == "Outra coisa" and _linhas(tid) == 2


def test_dez_finish_simultaneos_uma_linha(usuario):
    tid = _tarefa(usuario)
    barreira, saidas = threading.Barrier(10), []

    def concluir():
        barreira.wait()
        saidas.append(usuario.post(f"/worklog/{tid}/finish", {"resolution": "feito"}))

    fios = [threading.Thread(target=concluir) for _ in range(10)]
    [f.start() for f in fios]
    [f.join() for f in fios]
    assert [r.status_code for r in saidas] == [200] * 10
    assert sum(1 for r in saidas if not r.json().get("existing")) == 1
    assert _linhas(tid) == 1


# ---- cronômetro

def test_start_em_tarefa_concluida_recusado_e_nao_muda_o_status(usuario):
    tid = _tarefa(usuario)
    usuario.post(f"/worklog/{tid}/finish")
    r = usuario.post("/timer/start", {"task_id": tid})
    assert r.status_code == 400 and "concluída" in r.json()["detail"]
    assert usuario.get("/timer").json()["timer"] is None
    t = usuario.get(f"/worklog/{tid}").json()
    assert t["status"] == "done" and t["completed_at"]


def test_start_que_perde_a_corrida_para_o_finish_nao_reabre(usuario, monkeypatch):
    """O finish entra entre a leitura e a gravação do start (a janela da corrida)."""
    from app.routers import timer
    tid = _tarefa(usuario)
    original = timer.client_time

    def conclui_no_meio(at):
        db.execute("UPDATE worklog_tasks SET status = 'done', completed_at = now() WHERE id = %s", (tid,))
        return original(at)

    monkeypatch.setattr(timer, "client_time", conclui_no_meio)
    assert usuario.post("/timer/start", {"task_id": tid}).status_code == 400
    assert db.query_one("SELECT status FROM worklog_tasks WHERE id = %s", (tid,))["status"] == "done"
    assert db.query_one("SELECT count(*)::int AS n FROM task_timers")["n"] == 0


def test_arredondamento_de_meio_minuto_sobe(usuario):
    tid = _tarefa(usuario)
    usuario.post("/timer/start", {"task_id": tid})
    inicio = (datetime.now(timezone.utc) - timedelta(minutes=10)).replace(microsecond=0)
    db.execute("UPDATE task_timers SET started_at = %s WHERE task_id = %s", (inicio, tid))
    r = usuario.post("/timer/stop", {"at": (inicio + timedelta(seconds=150)).isoformat()})
    assert r.status_code == 200 and r.json()["stopped"]["minutes"] == 3  # 150,0 s: era 2 (meio para o par)


def test_chave_append_nao_para_nem_inicia_com_at_retroativo(usuario):
    a, b = _tarefa(usuario, "A"), _tarefa(usuario, "B")
    chave = Bearer(criar_chave(usuario, scope="append")["token"])
    usuario.post("/timer/start", {"task_id": a})
    inicio = datetime.now(timezone.utc) - timedelta(hours=3)
    db.execute("UPDATE task_timers SET started_at = %s WHERE task_id = %s", (inicio, a))
    velho = (inicio + timedelta(seconds=1)).isoformat()
    assert chave.post("/timer/stop", {"at": velho}).status_code == 403
    assert chave.post("/timer/start", {"task_id": b, "at": velho}).status_code == 403
    assert usuario.get("/timer").json()["timer"]["task_id"] == a  # nada mudou
    recente = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    r = chave.post("/timer/stop", {"at": recente})
    assert r.status_code == 200 and r.json()["stopped"]["minutes"] == 179
    # pelo app (fila sem sinal) o at antigo continua valendo
    usuario.post("/timer/start", {"task_id": b})
    db.execute("UPDATE task_timers SET started_at = now() - interval '2 hours' WHERE task_id = %s", (b,))
    antigo = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    assert usuario.post("/timer/stop", {"at": antigo}).json()["stopped"]["minutes"] == 90


# ---- edição simultânea: o "antes" do histórico é o estado encontrado

def test_duas_edicoes_simultaneas_gravam_antes_e_depois_em_cadeia(usuario):
    tid = _tarefa(usuario, "Original")
    barreira = threading.Barrier(2)

    def editar(campo, valor):
        barreira.wait()
        assert usuario.patch(f"/worklog/{tid}", {campo: valor}).status_code == 200

    fios = [threading.Thread(target=editar, args=a) for a in (("title", "Novo título"), ("description", "Sala 2"))]
    [f.start() for f in fios]
    [f.join() for f in fios]
    linhas = db.query_all("SELECT before, after FROM audit_log WHERE entity = 'worklog' AND entity_id = %s"
                          " AND action = 'worklog.update' ORDER BY id", (tid,))
    assert len(linhas) == 2
    assert linhas[1]["before"] == linhas[0]["after"]  # a segunda parte de onde a primeira chegou
    assert (linhas[1]["after"]["title"], linhas[1]["after"]["description"]) == ("Novo título", "Sala 2")


# ---- datas

def test_ano_1_com_fuso_da_400(usuario):
    r = usuario.post("/worklog", {"title": "x", "created_at": "0001-01-01T00:00+14:00"})
    assert r.status_code == 400 and "dias atrás" in r.json()["detail"]
    tid = _tarefa(usuario)
    r = usuario.post(f"/worklog/{tid}/finish", {"completed_at": "0001-01-01T00:00+14:00"})
    assert r.status_code == 400
    assert usuario.post("/worklog", {"title": "x", "created_at": "0001-01-01"}).status_code == 400
    r = usuario.post("/worklog", {"title": "x", "created_at": "9999-12-31T23:59-14:00"})
    assert r.status_code == 400 and "futuro" in r.json()["detail"]


def test_mensagem_do_limite_diz_o_caminho(usuario):
    velho = (datetime.now(timezone.utc) - timedelta(days=90)).date().isoformat()
    r = usuario.post("/worklog", {"title": "x", "created_at": velho})
    assert r.status_code == 400
    assert r.json()["detail"] == ("data de criação: até 60 dias atrás; para trabalho mais antigo, "
                                  "crie a tarefa com a data de hoje e aponte o tempo no dia certo")
    tid = _tarefa(usuario)  # na conclusão a frase segue curta
    r = usuario.post(f"/worklog/{tid}/finish", {"completed_at": velho})
    assert r.status_code == 400 and "aponte o tempo" not in r.json()["detail"]


# ---- external_ref repetido: status da existente; status done conclui

def test_external_ref_repetido_devolve_status_e_conclui_com_done(usuario):
    chave = Bearer(criar_chave(usuario, scope="append")["token"])
    r1 = chave.post("/worklog", {"title": "Link caiu", "external_ref": "kuma-7"})
    assert r1.status_code == 201
    tid = r1.json()["id"]
    r2 = chave.post("/worklog", {"title": "Link caiu", "external_ref": "kuma-7"})
    assert r2.status_code == 200 and r2.json() == {"id": tid, "existing": True, "status": "todo"}
    assert _linhas(tid) == 0  # sem status no corpo, nada muda
    usuario.post("/timer/start", {"task_id": tid})
    r3 = chave.post("/worklog", {"title": "Link voltou", "external_ref": "kuma-7", "status": "done",
                                 "resolution": "Normalizou sozinho"})
    assert r3.status_code == 200, r3.text
    j = r3.json()
    assert (j["id"], j["existing"], j["status"]) == (tid, True, "done") and j["stopped"]["minutes"] == 1
    t = usuario.get(f"/worklog/{tid}").json()
    assert t["status"] == "done" and t["resolution"] == "Normalizou sozinho" and t["title"] == "Link caiu"
    assert _linhas(tid) == 1
    # de novo: já concluída, nada muda (sem reabrir, sem outro evento)
    r4 = chave.post("/worklog", {"title": "Link voltou", "external_ref": "kuma-7", "status": "done"})
    assert r4.status_code == 200 and r4.json() == {"id": tid, "existing": True, "status": "done"}
    r5 = chave.post("/worklog", {"title": "Link caiu", "external_ref": "kuma-7"})
    assert r5.json()["status"] == "done" and _linhas(tid) == 1
