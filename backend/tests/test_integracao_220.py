"""Integração da 2.2.0: contratos entre os pacotes da auditoria que só existem
depois de juntar os branches."""
from app import db
from conftest import Bearer, criar_chave, texto


def _tarefa(u, titulo):
    r = u.post("/worklog", {"title": titulo})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _esquecido(u, tid):
    assert u.post("/timer/start", {"task_id": tid}).status_code == 200
    db.execute("UPDATE task_timers SET started_at = now() - interval '13 hours' WHERE task_id = %s", (tid,))


def test_mcp_avisa_do_cronometro_esquecido_ao_concluir(usuario):
    """p03 devolve `stopped.needs_review` no concluir; o MCP (p10) repassa à IA."""
    b = Bearer(criar_chave(usuario)["token"])
    a, c, d = _tarefa(usuario, "Ronda"), _tarefa(usuario, "Backup"), _tarefa(usuario, "Sem relógio")
    _esquecido(usuario, a)
    out = texto(b.tool("complete_task", task_id=a))
    assert out.startswith("Concluída") and "parou sem apontar" in out and "log_time" in out
    _esquecido(usuario, c)
    out = texto(b.tool("update_task", task_id=c, status="done"))
    assert out.startswith("Atualizada") and "parou sem apontar" in out
    out = texto(b.tool("complete_task", task_id=d))  # sem cronômetro: nada a avisar
    assert out.startswith("Concluída") and "ATENÇÃO" not in out


def test_lapide_da_exclusao_e_da_devolucao_guardam_de_quem_e_o_tempo(usuario):
    """p03 grava `user_id` em cada apontamento da lápide; o desfazer (p09) devolve ao dono."""
    tid = _tarefa(usuario, "Trocar o nobreak")
    assert usuario.post(f"/worklog/{tid}/time", {"minutes": 30}).status_code in (200, 201)
    dono = db.query_one("SELECT user_id FROM time_entries WHERE task_id = %s", (tid,))["user_id"]
    assert usuario.delete(f"/worklog/{tid}").status_code == 200
    lapide = db.query_one("SELECT id, before FROM audit_log WHERE action = 'worklog.delete' AND entity_id = %s", (tid,))
    assert [e["user_id"] for e in lapide["before"]["children"]["time"]] == [dono]
    assert usuario.post(f"/history/{lapide['id']}/undo").status_code == 200
    assert db.query_one("SELECT user_id, minutes FROM time_entries WHERE task_id = %s", (tid,)) == {"user_id": dono, "minutes": 30}
