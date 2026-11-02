"""R5-C (integrador, IA e admin): chave "só registrar", prompts MCP do dia,
"o que esta chave fez", avisos de agenda no feed/webhooks e Saúde do Nexus."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import agenda, db, deps, webhooks
from app.config import config
from app.main import app
from conftest import Bearer, criar_chave, dia_hoje, hist, texto, uid_de
from test_api_aberta import Destino, dns  # noqa: F401 — fixture


# ------------------------------------------------------ 1. chave "só registrar" --

def _tarefa(u, **kw):
    r = u.post("/worklog", {"title": "Trocar reator", **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_registrar_cria_anota_aponta_marca_e_conclui(usuario):
    b = Bearer(criar_chave(usuario, nome="Só registra", scope="append")["token"])
    r = b.post("/worklog", {"title": "Pela IA", "external_ref": "ia-1"})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert b.post("/worklog", {"title": "Pela IA", "external_ref": "ia-1"}).json()["existing"]  # repetir não duplica
    assert b.post(f"/worklog/{tid}/notes", {"body": "trocado o reator"}).status_code == 201
    assert b.post(f"/worklog/{tid}/checklist", {"label": "testar"}).status_code == 201
    assert b.post(f"/worklog/{tid}/time", {"minutes": 30}).status_code == 201
    assert b.post("/timer/start", {"task_id": tid}).status_code == 200
    assert b.post("/timer/stop", {}).status_code == 200
    rid = usuario.post("/recurring", {"label": "Conferir nobreak"}).json()["id"]
    assert b.post(f"/recurring/{rid}/toggle", {"done": True, "note": "ok"}).status_code == 200
    assert b.post(f"/worklog/{tid}/finish", {"resolution": "trocado"}).status_code == 200
    assert b.post(f"/worklog/{tid}/duplicate").status_code == 201
    tpl = usuario.post("/templates", {"name": "Preventiva", "title": "Preventiva"}).json()["id"]
    assert b.post(f"/templates/{tpl}/use").status_code == 201
    assert any("Só registra" == (r["token_name"] or "") for r in hist(usuario))


def test_registrar_nao_altera_nem_exclui(usuario):
    b = Bearer(criar_chave(usuario, scope="append")["token"])
    tid = _tarefa(usuario)
    nota = usuario.post(f"/worklog/{tid}/notes", {"body": "a"}).json()["id"]
    item = usuario.post(f"/worklog/{tid}/checklist", {"label": "a"}).json()["id"]
    tempo = usuario.post(f"/worklog/{tid}/time", {"minutes": 5}).json()["id"]
    pid = usuario.post("/projects", {"name": "Prédio A"}).json()["id"]
    rid = usuario.post("/recurring", {"label": "Backup"}).json()["id"]
    usuario.post(f"/recurring/{rid}/toggle", {"done": True, "note": "feito"})
    proibidos = [
        ("patch", f"/worklog/{tid}", {"title": "outro"}), ("delete", f"/worklog/{tid}", None),
        ("patch", f"/notes/{nota}", {"body": "b"}), ("delete", f"/notes/{nota}", None),
        ("patch", f"/checklist/{item}", {"done": True}), ("delete", f"/checklist/{item}", None),
        ("patch", f"/time/{tempo}", {"minutes": 9}), ("delete", f"/time/{tempo}", None),
        ("post", "/projects", {"name": "Novo"}), ("patch", f"/projects/{pid}", {"name": "B"}),
        ("delete", f"/projects/{pid}", None), ("post", "/recurring", {"label": "x"}),
        ("patch", f"/recurring/{rid}", {"label": "y"}), ("delete", f"/recurring/{rid}", None),
        ("post", f"/recurring/{rid}/pause", {"until": "2030-01-01"}),
        ("post", f"/recurring/{rid}/toggle", {"done": False}),  # desmarcar
        ("post", f"/recurring/{rid}/toggle", {"done": True, "note": "troca a evidência"}),
        ("delete", "/timer", None), ("post", "/renewals", {"label": "x", "expires_on": "2030-01-01"}),
    ]
    for verbo, path, body in proibidos:
        r = getattr(b, verbo)(path, body) if body is not None else getattr(b, verbo)(path)
        assert r.status_code == 403, (verbo, path, r.text)
        assert "só registra" in r.json()["detail"], (verbo, path)
    h = hist(usuario)
    assert b.post(f"/history/{h[0]['id']}/undo").status_code == 403
    # Concluída: concluir de novo mudaria a conclusão (data, "como resolveu").
    assert usuario.post(f"/worklog/{tid}/finish").status_code == 200
    assert b.post(f"/worklog/{tid}/finish", {"resolution": "outra"}).status_code == 403
    # Marcar de novo sem mexer na evidência continua valendo (repetição segura).
    assert b.post(f"/recurring/{rid}/toggle", {"done": True}).status_code == 200
    assert db.query_one("SELECT title FROM worklog_tasks WHERE id = %s", (tid,))["title"] == "Trocar reator"


def _rotas():
    """Todas as rotas, já com o prefixo (o FastAPI novo inclui os routers sob demanda)."""
    for r in app.routes:
        if hasattr(r, "effective_route_contexts"):
            yield from r.effective_route_contexts()
        else:
            yield r


def _usa(dep, alvo) -> bool:
    return any(d.call in alvo or _usa(d, alvo) for d in dep.dependencies)


def test_registrar_toda_rota_que_escreve_nasce_negada(usuario):
    """Percorre TODAS as rotas que escrevem com a dependência de escrita: fora da
    lista fechada, a chave "só registrar" recebe 403 antes de qualquer coisa."""
    b = Bearer(criar_chave(usuario, scope="append")["token"])
    alvo = {deps.active_user_csrf, deps.require_assigner_csrf}
    vistas = 0
    for route in _rotas():
        methods = (getattr(route, "methods", None) or set()) & {"POST", "PUT", "PATCH", "DELETE"}
        if not methods or not hasattr(route, "dependant") or not _usa(route.dependant, alvo):
            continue
        path = route.path
        for p in route.param_convertors:
            path = path.replace("{" + p + "}", "1")
        for m in methods:
            if (m, route.path) in deps.APPEND_ROUTES:
                continue
            r = b.c.request(m, path, json={}, headers=b.h)
            assert r.status_code == 403, (m, route.path, r.status_code)
            if not _usa(route.dependant, {deps.require_assigner_csrf}):  # lá o papel é conferido antes
                assert r.json()["detail"] == deps.APPEND_DENIED, (m, route.path)
            vistas += 1
    assert vistas >= 30  # a lista acima realmente percorreu as rotas
    for m, p in deps.APPEND_ROUTES:  # a lista fechada só tem rotas que existem
        assert any(getattr(r, "path", None) == p and m in (getattr(r, "methods", None) or ()) for r in _rotas()), (m, p)


def test_registrar_no_mcp(usuario):
    b = Bearer(criar_chave(usuario, nome="Claude", scope="append")["token"])
    nomes = {t["name"] for t in b.rpc("tools/list").json()["result"]["tools"]}
    assert {"create_task", "complete_task", "add_note", "log_time", "set_recurring", "get_today"} <= nomes
    assert not nomes & {"update_task", "undo", "update_project", "create_project", "update_recurring",
                        "set_checklist_item", "assign_task", "reorder_objectives"}
    res = b.tool("create_task", title="Reator", minutes=20, status="done")
    assert not res["isError"], texto(res)
    tid = int(texto(res).split("#")[1].split()[0])
    r = b.tool("update_task", task_id=tid, title="x")
    assert r["isError"] and "só registra" in texto(r)
    # Concluir de novo uma concluída não muda nada (nem reemite): diz que já estava (R6 ia-api 6).
    r = b.tool("complete_task", task_id=tid)
    assert not r["isError"] and texto(r).startswith("Já estava concluída")
    r = b.tool("complete_task", task_id=tid, completed_at=dia_hoje(usuario).isoformat())
    assert r["isError"] and "só registra" in texto(r)  # mudar a conclusão continua negado
    rid = usuario.post("/recurring", {"label": "Ronda"}).json()["id"]
    assert not b.tool("set_recurring", recurring_id=rid, done=True)["isError"]
    assert b.tool("set_recurring", recurring_id=rid, done=False)["isError"]
    r = b.tool("set_recurring", recurring_id=rid, paused_until="2030-01-01")
    assert r["isError"] and "só registra" in texto(r)
    assert not db.query_one("SELECT 1 FROM recurring_pauses WHERE recurring_id = %s", (rid,))


def test_registrar_aparece_na_lista_de_chaves(usuario):
    criar_chave(usuario, scope="append")
    assert usuario.get("/tokens").json()[0]["scope"] == "append"
    assert usuario.post("/tokens", {"name": "x", "scope": "admin"}).status_code == 422


# ------------------------------------------------------------ 2. prompts MCP --

def test_prompts_do_dia_e_do_projeto(usuario):
    # fechar_dia grava: a chave só de leitura não o recebe (R6); aqui, a de escrita.
    b = Bearer(criar_chave(usuario)["token"])
    nomes = {p["name"] for p in b.rpc("prompts/list").json()["result"]["prompts"]}
    assert {"planejar_dia", "fechar_dia", "resumo_projeto", "daily", "resumo_semanal"} <= nomes
    plano = b.rpc("prompts/get", {"name": "planejar_dia"}).json()["result"]["messages"][0]["content"]["text"]
    assert "get_today" in plano and "NÃO crie" in plano
    hoje = dia_hoje(usuario).isoformat()
    fechar = b.rpc("prompts/get", {"name": "fechar_dia"}).json()["result"]["messages"][0]["content"]["text"]
    assert f"fechar-{hoje}-N" in fechar and "CONFIRMAÇÃO" in fechar
    r = b.rpc("prompts/get", {"name": "resumo_projeto", "arguments": {}}).json()
    assert r["error"]["code"] == -32602 and "projeto" in r["error"]["message"]
    txt = b.rpc("prompts/get", {"name": "resumo_projeto", "arguments": {"projeto": "Prédio  X\n", "periodo": "outubro"}}
                ).json()["result"]["messages"][0]["content"]["text"]
    assert "“Prédio X”" in txt and "outubro" in txt and hoje in txt and "get_period" in txt
    padrao = b.rpc("prompts/get", {"name": "resumo_projeto", "arguments": {"projeto": "A"}}).json()["result"]
    assert "este mês" in padrao["messages"][0]["content"]["text"]


# --------------------------------------------------- 5. o que esta chave fez --

def test_historico_filtrado_pela_chave(usuario, novo_usuario):
    k1, k2 = criar_chave(usuario, nome="Claude"), criar_chave(usuario, nome="n8n")
    Bearer(k1["token"]).post("/worklog", {"title": "pela IA"})
    Bearer(k1["token"]).post("/worklog", {"title": "pela IA 2"})
    Bearer(k2["token"]).post("/worklog", {"title": "pelo n8n"})
    usuario.post("/worklog", {"title": "à mão"})
    r = usuario.get(f"/history?token_id={k1['id']}")
    assert r.status_code == 200 and r.headers["X-Total-Count"] == "2"
    assert {x["token_name"] for x in r.json()} == {"Claude"} and all(x["can_undo"] for x in r.json())
    assert len([x for x in hist(usuario) if x["action"] == "worklog.create"]) == 4
    lista = {t["name"]: t for t in usuario.get("/tokens").json()}
    assert lista["Claude"]["actions_7d"] == 2 and lista["n8n"]["actions_7d"] == 1
    outro = novo_usuario("outro@example.com")
    assert outro.get(f"/history?token_id={k1['id']}").json() == []  # sempre só a própria conta
    assert usuario.get("/history?token_id=0").status_code == 422


# ------------------------------------------------- 4. avisos de agenda (feed) --

TODO_DIA = {"freq": "weekly", "weekdays": 127}  # devida hoje, seja qual for o dia da semana


def _agora():
    return datetime.now(ZoneInfo(config.APP_TZ)).replace(hour=23, minute=59)  # depois da manhã e de qualquer horário


def test_agenda_emite_uma_vez_e_so_no_feed(usuario, novo_usuario):
    criar_chave(usuario)
    hoje = dia_hoje(usuario)
    tid = _tarefa(usuario)
    usuario.patch(f"/worklog/{tid}", {"title": "Trocar reator do 3º"})
    db.execute("UPDATE worklog_tasks SET status = 'blocked', follow_up_on = %s WHERE id = %s", (hoje, tid))
    rid = usuario.post("/recurring", {"label": "Backup das 9h", "remind_at": "00:00", **TODO_DIA}).json()["id"]
    feita = usuario.post("/recurring", {"label": "Já feita", "remind_at": "00:00", **TODO_DIA}).json()["id"]
    usuario.post(f"/recurring/{feita}/toggle", {"done": True})
    ven = usuario.post("/renewals", {"label": "Certificado", "expires_on": (hoje + timedelta(days=3)).isoformat(),
                                      "warn_days": 5}).json()["id"]
    usuario.post("/renewals", {"label": "Longe", "expires_on": (hoje + timedelta(days=200)).isoformat(), "warn_days": 5})
    sem_chave = novo_usuario("sem@example.com")  # sem chave nem webhook: nada a gravar
    _tarefa(sem_chave)

    feitos = agenda.run_once(_agora())
    uid = uid_de(usuario)
    assert sorted(x for u, x in feitos if u == uid) == sorted([f"followup:{tid}", f"recurring:{rid}", f"renewal:{ven}"])
    assert all(u == uid for u, _ in feitos)
    assert agenda.run_once(_agora()) == []  # uma vez por ocorrência

    db.execute("UPDATE audit_log SET created_at = created_at - interval '1 minute'")  # passa do atraso do feed
    feed = usuario.get("/history?after=0").json()
    eventos = {e["action"]: e for e in feed if e["actor"] == "system"}
    assert set(eventos) == {"followup.due", "recurring.due", "renewal.warning"}
    assert eventos["followup.due"]["entity"] == "agenda" and eventos["followup.due"]["entity_id"] == tid
    # Tela de Histórico e MCP não mostram; o desfazer da edição anterior continua valendo.
    tela = hist(usuario, limit=200)
    assert not [x for x in tela if x["actor"] == "system"]
    assert next(x for x in tela if x["action"] == "worklog.update")["can_undo"]


def test_agenda_vai_pelo_webhook_filtrado(usuario, dns):  # noqa: F811
    usuario.post("/webhooks", {"url": "https://hooks.example.com/x", "events": ["followup.*", "renewal.warning"]})
    hoje = dia_hoje(usuario)
    tid = _tarefa(usuario, external_ref="os-9")
    db.execute("UPDATE worklog_tasks SET status = 'blocked', follow_up_on = %s, blocked_reason = 'peça' WHERE id = %s",
               (hoje, tid))
    usuario.post("/recurring", {"label": "Ronda", "remind_at": "00:00", **TODO_DIA})
    agenda.run_once(_agora())
    destino = Destino()
    webhooks.run_once(send=destino)
    corpos = [json.loads(b) for _, _, b in destino.recebidos]
    assert [c["action"] for c in corpos] == ["followup.due"]  # recurring.due não foi pedido
    c = corpos[0]
    assert c["actor"] == "system" and c["external_ref"] == "os-9"
    assert c["data"]["title"] == "Trocar reator" and c["data"]["occurrence"] == hoje.isoformat()
    assert destino.recebidos[0][1]["X-Nexus-Event"] == "followup.due"


def test_agenda_respeita_manha_e_rotina_pausada(usuario):
    criar_chave(usuario)
    hoje = dia_hoje(usuario)
    tid = _tarefa(usuario)
    db.execute("UPDATE worklog_tasks SET status = 'blocked', follow_up_on = %s WHERE id = %s", (hoje, tid))
    rid = usuario.post("/recurring", {"label": "Pausada", "remind_at": "00:00", **TODO_DIA}).json()["id"]
    assert usuario.post(f"/recurring/{rid}/pause", {"until": (hoje + timedelta(days=3)).isoformat()}).status_code == 200
    cedo = datetime.now(ZoneInfo(config.APP_TZ)).replace(hour=5, minute=0)
    assert [x for _, x in agenda.run_once(cedo)] == []  # cobrar só de manhã (8h padrão); pausada não avisa


# ------------------------------------------------------- 6. Saúde do Nexus --

def test_saude_so_admin_e_sem_segredos(admin, usuario, tmp_path, monkeypatch, dns):  # noqa: F811
    assert usuario.get("/admin/health").status_code == 403
    assert Bearer(criar_chave(admin)["token"]).get("/admin/health").status_code == 403
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path / "nao-existe"))
    s = admin.get("/admin/health").json()
    assert s["backup"] is None and s["version"]["commit"] is None and s["version"]["migration"].startswith("0")
    # Com os arquivos do deploy.sh (campos desconhecidos, como um caminho, ficam de fora).
    (tmp_path / "backup.json").write_text(json.dumps({"at": "2026-11-01T03:00:00Z", "size_bytes": 2048, "tables": 30,
                                                      "file": "/srv/backups/x.dump"}))
    (tmp_path / "deploy.json").write_text(json.dumps({"commit": "abc1234", "previous": "0001111", "at": "2026-11-01T03:01:00Z"}))
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path))
    usuario.post("/webhooks", {"url": "https://hooks.example.com/segredo-do-caminho"})
    db.execute("UPDATE webhooks SET disabled_at = now()")
    db.execute("""INSERT INTO notification_log (user_id, kind, ref_date, ok, error)
                  VALUES (%s, 'morning', CURRENT_DATE, false, 'falha no envio: recusado para colega@example.com')""",
               (uid_de(usuario),))
    r = admin.get("/admin/health")
    assert r.status_code == 200
    s = r.json()
    assert s["backup"] == {"at": "2026-11-01T03:00:00Z", "size_bytes": 2048, "tables": 30}
    assert s["version"]["commit"] == "abc1234" and s["webhooks"] == {"total": 1, "disabled": 1}
    assert s["email"]["last_error"] == "falha no envio: recusado para <e-mail>"
    assert s["photos"]["quota_mb"] >= 0 and s["accounts"] == 2 and s["db_bytes"] > 0
    bruto = r.text
    for segredo in ("colega@example.com", "segredo-do-caminho", "hooks.example.com", "/srv/backups", config.SECRET_KEY):
        assert segredo not in bruto
