"""Integração com o GLPI (app/glpi.py, sql/060): chamado -> tarefa, tarefa concluída -> solução.

O GLPI aqui é falso (FakeGlpi), no lugar de glpi.request: responde como a API
legada do GLPI 11/12 respondeu no laboratório (códigos e formatos conferidos lá).
"""
import ipaddress
import logging
import re
from urllib.parse import parse_qs, urlsplit

import pytest

from app import db, glpi, security, webhooks
from app.config import config
from app.routers import history
from conftest import Bearer, criar_chave, hist, uid_de

URL = "http://glpi.example.com"
APP = "app-token-da-instancia-0123456789"
TOK_A = "token-pessoal-da-ana-0123456789abcdef"
TOK_B = "token-pessoal-do-beto-0123456789abcde"


class FakeGlpi:
    def __init__(self):
        self.version = "11.0.13"
        self.app_token = APP
        self.users = {TOK_A: {"id": 7, "first": "Ana", "last": "Souza"}, TOK_B: {"id": 8, "first": "Beto", "last": "Lima"}}
        self.tickets = {}  # id -> {name, content, priority, ttr, status, tech}
        self.solutions = []  # (ticket, autor, conteúdo)
        self.sessions = {}
        self.calls = []
        self.fail = None  # exceção (GLPI fora do ar) ou status (ex.: 503)
        self.off = None  # "api" = API desligada no GLPI; "token" = login por token desligado
        self.lose_answer = False  # a solução entra, mas a resposta se perde

    def add(self, tid, tech, name="Impressora não imprime", content="<p>Sem papel</p>", priority=3, ttr=None, status=2):
        self.tickets[tid] = {"name": name, "content": content, "priority": priority, "ttr": ttr, "status": status,
                             "tech": tech}

    def __call__(self, base, method, path, headers, body=None):
        assert base == URL
        self.calls.append((method, path.split("?")[0]))
        if isinstance(self.fail, Exception):
            raise self.fail
        if self.fail:
            return self.fail, None
        parts = urlsplit(path)
        if parts.path == "/initSession":
            if self.off:
                return 400, ["ERROR", "API disabled"] if self.off == "api" else [
                    "ERROR_LOGIN_WITH_TOKEN_DISABLED", "usage of initSession resource with user token is disabled"]
            if self.app_token and "App-Token" not in headers:
                return 400, ["ERROR_APP_TOKEN_PARAMETERS_MISSING", "missing parameter app_token"]
            if self.app_token and headers["App-Token"] != self.app_token:
                return 400, ["ERROR_WRONG_APP_TOKEN_PARAMETER", "parameter app_token seems wrong"]
            if "Authorization" not in headers:
                return 400, ["ERROR_LOGIN_PARAMETERS_MISSING", "parameter(s) login, password or user_token are missing"]
            u = self.users.get(headers["Authorization"].removeprefix("user_token "))
            if not u:
                return 401, ["ERROR_GLPI_LOGIN_USER_TOKEN", "parameter user_token seems invalid"]
            st = f"sessao-{len(self.calls)}"
            self.sessions[st] = u
            return 200, {"session_token": st, "session": {"glpiID": u["id"], "glpiname": "login", "glpifirstname": u["first"],
                                                           "glpirealname": u["last"]}}
        u = self.sessions.get(headers.get("Session-Token"))
        if not u:
            return 401, ["ERROR_SESSION_TOKEN_INVALID", "session_token seems invalid"]
        if parts.path == "/killSession":
            del self.sessions[headers["Session-Token"]]
            return 200, True
        if parts.path == "/getGlpiConfig":
            return 200, {"cfg_glpi": {"version": self.version}}
        if parts.path == "/search/Ticket":
            q = parse_qs(parts.query)
            assert q["criteria[0][value]"] == ["myself"] and q["criteria[1][value]"] == ["notold"]
            rows = [{"2": i, "1": t["name"], "21": t["content"], "3": t["priority"], "18": t["ttr"]}
                    for i, t in sorted(self.tickets.items()) if t["tech"] == u["id"] and t["status"] < 5]
            out = {"totalcount": len(rows), "count": len(rows)}
            return 200, {**out, "data": rows} if rows else out  # sem resultado, o GLPI não manda "data"
        if m := re.fullmatch(r"/Ticket/(\d+)", parts.path):
            t = self.tickets.get(int(m[1]))
            return (200, {"id": int(m[1]), "status": t["status"]}) if t else (404, ["ERROR_ITEM_NOT_FOUND", "Item not found"])
        if parts.path == "/ITILSolution" and method == "POST":
            i = body["input"]
            t = self.tickets.get(i["items_id"])
            if not t or t["status"] >= 5:
                return 400, ["ERROR_GLPI_ADD", "The item is already solved"]
            t["status"] = 5
            self.solutions.append((i["items_id"], u["id"], i["content"]))
            if self.lose_answer:
                raise TimeoutError("resposta perdida")
            return 201, {"id": len(self.solutions)}
        return 404, None


@pytest.fixture
def fake(monkeypatch):
    f = FakeGlpi()
    monkeypatch.setattr(glpi, "request", f)

    def _resolve(host, port):
        try:
            return {str(ipaddress.ip_address(host))}
        except ValueError:
            pass
        if not host.endswith("example.com"):
            raise OSError("sem DNS")
        return {"10.0.0.5"}  # rede interna: aceita de propósito
    monkeypatch.setattr(webhooks, "resolve", _resolve)
    monkeypatch.setattr(security.webhook_test_limiter, "allow", lambda key: True)  # o limite tem o seu teste
    return f


@pytest.fixture
def instancia(admin, fake):
    r = admin.put("/admin/org", {"glpi_url": URL + "/apirest.php/", "glpi_app_token": APP})
    assert r.status_code == 200, r.text
    assert r.json()["glpi_url"] == URL  # guardado sem o /apirest.php
    return admin


@pytest.fixture
def ana(instancia, novo_usuario, fake):
    u = novo_usuario("ana@example.com")
    r = u.put("/me/glpi", {"token": TOK_A})
    assert r.status_code == 200, r.text
    return u


def passada(u):
    """Uma passada do agendador para esta pessoa, como se os 5 minutos tivessem passado."""
    db.execute("UPDATE glpi_accounts SET last_sync_at = now() - interval '6 minutes' WHERE user_id = %s", (uid_de(u),))
    return glpi.run_once()


def envelhecer(tid):
    db.execute("UPDATE worklog_tasks SET completed_at = completed_at - interval '3 minutes' WHERE id = %s", (tid,))


def tarefas(u):
    return [t for t in u.get("/worklog?limit=500").json() if (t.get("external_ref") or "").startswith("glpi:")]


# ---------------------------------------------------------- cifra e textos --

def test_cifra_ida_e_volta_e_falha_limpa_com_outra_chave(monkeypatch):
    selado = glpi.seal(TOK_A)
    assert TOK_A not in selado and glpi.unseal(selado) == TOK_A
    monkeypatch.setattr(config, "SECRET_KEY", "outra-chave-0123456789-abcdefghijklmnopqrstuvwxyz")
    with pytest.raises(glpi.GlpiError) as e:
        glpi.unseal(selado)
    assert e.value.auth and "conecte de novo" in str(e.value)


def test_html_do_glpi_vira_texto_e_texto_do_nexus_vai_escapado():
    assert glpi.plain("<p>Acesso remoto.</p><ul><li>Maria</li><li>Jo&atilde;o &amp; filhos</li></ul>") == \
        "Acesso remoto.\nMaria\nJoão & filhos"
    assert glpi.plain("a<SCRIPT>alert(1)</SCRIPT>b<style>x{}</style>") == "ab"
    assert glpi.plain("&#60;p&#62;escapado&#60;/p&#62;") == "escapado"  # a busca às vezes devolve assim
    assert glpi.plain(None) == ""
    h = glpi.to_html("Troquei o cabo <script>alert(1)</script> & testei em \\\\srv\nlinha 2\n\nFim")
    assert h == "<p>Troquei o cabo &lt;script&gt;alert(1)&lt;/script&gt; &amp; testei em \\\\srv<br>linha 2</p><p>Fim</p>"


def test_endereco_do_glpi_tem_checagem_propria(fake):
    assert glpi.check_base("http://glpi.example.com:8080/glpi/")[:4] == ("http", "glpi.example.com", 8080, "/glpi")
    for ruim in ("ftp://glpi.example.com", "http://user:senha@glpi.example.com", "http://127.0.0.1", "http://localhost.sem-dns",
                 "http://169.254.169.254", "http://[::1]", "http://glpi.example.com/?x=1", "http://glpi.example.com/a\tb"):
        with pytest.raises(webhooks.Refused):
            glpi.check_base(ruim)


# -------------------------------------------------------------------- admin --

def test_admin_configura_testa_e_o_app_token_nunca_volta(admin, usuario, fake):
    assert usuario.put("/admin/org", {"glpi_url": URL}).status_code == 403
    assert usuario.post("/admin/glpi/test").status_code == 403
    assert admin.post("/admin/glpi/test").status_code == 400  # nada salvo ainda
    assert admin.put("/admin/org", {"glpi_url": "http://127.0.0.1:8300"}).status_code == 400
    r = admin.put("/admin/org", {"glpi_url": URL, "glpi_app_token": APP})
    assert r.json()["glpi_url"] == URL and r.json()["glpi_app_token_set"] is True
    assert APP not in r.text and APP not in admin.get("/admin/org").text
    guardado = db.query_one("SELECT glpi_app_token FROM app_settings WHERE id = 1")["glpi_app_token"]
    assert APP not in guardado and glpi.unseal(guardado) == APP
    assert APP not in str(hist(admin, limit=50))
    assert admin.post("/admin/glpi/test").json() == {"ok": True, "error": None}
    # App-Token errado (ou IP fora da faixa: o GLPI responde igual), faltando, GLPI fora do ar, endereço errado.
    fake.app_token = "outro"
    assert "IP do Nexus" in admin.post("/admin/glpi/test").json()["error"]
    admin.put("/admin/org", {"glpi_app_token": ""})
    assert admin.get("/admin/org").json()["glpi_app_token_set"] is False
    assert "exige um App-Token" in admin.post("/admin/glpi/test").json()["error"]
    fake.fail = TimeoutError("lento")
    assert "não respondeu a tempo" in admin.post("/admin/glpi/test").json()["error"]
    fake.fail = 404
    assert "não respondeu como um GLPI" in admin.post("/admin/glpi/test").json()["error"]


def test_trocar_o_endereco_desconecta_todos(ana, instancia):
    assert ana.get("/me/glpi").json()["connected"] is True
    instancia.put("/admin/org", {"glpi_url": URL})  # o mesmo: nada muda
    assert ana.get("/me/glpi").json()["connected"] is True
    instancia.put("/admin/org", {"glpi_url": "http://outro.example.com"})
    assert ana.get("/me/glpi").json() == {"available": True, "connected": False}
    instancia.put("/admin/org", {"glpi_url": ""})
    assert ana.get("/me/glpi").json() == {"available": False, "connected": False}


def test_endereco_do_chamado_vem_do_glpi_quando_ninguem_definiu(instancia, novo_usuario):
    u = novo_usuario("ana@example.com")
    assert u.get("/auth/me").json()["ticket_url"] == URL + "/front/ticket.form.php?id={id}"
    assert u.get("/auth/me").json()["ticket_url_managed"] is False
    u.put("/me/tickets", {"ticket_url": "https://os.example.com/{id}"})  # o da pessoa vem antes
    assert u.get("/auth/me").json()["ticket_url"] == "https://os.example.com/{id}"


# ------------------------------------------------------------------ conectar --

def test_conectar_confere_o_token_e_nunca_o_devolve(instancia, novo_usuario, fake, caplog):
    u = novo_usuario("ana@example.com")
    assert u.get("/me/glpi").json() == {"available": True, "connected": False}
    r = u.put("/me/glpi", {"token": "token-que-nao-existe-no-glpi"})
    assert r.status_code == 400 and "recusou o seu token" in r.json()["detail"]
    assert not db.query_one("SELECT 1 FROM glpi_accounts")
    with caplog.at_level(logging.DEBUG):
        r = u.put("/me/glpi", {"token": TOK_A})
        fake.fail = ConnectionRefusedError()
        passada(u)
    fake.fail = None
    assert r.status_code == 200 and r.json()["connected"] and r.json()["name"] == "Ana Souza"
    guardado = db.query_one("SELECT token FROM glpi_accounts")["token"]
    assert TOK_A not in guardado and glpi.unseal(guardado) == TOK_A
    # Em lugar nenhum: resposta, estado, sessão, histórico, exportação, log.
    for texto in (r.text, u.get("/me/glpi").text, u.get("/auth/me").text, str(hist(u, limit=50)),
                  u.get("/export/json").text, caplog.text):
        assert TOK_A not in texto and guardado not in texto and APP not in texto
    assert fake.sessions == {}  # toda sessão aberta no GLPI foi encerrada
    assert u.delete("/me/glpi").json() == {"available": True, "connected": False}
    assert not db.query_one("SELECT 1 FROM glpi_accounts")


def test_api_desligada_e_glpi_anterior_ao_11_sao_recusados(instancia, novo_usuario, fake):
    u = novo_usuario("ana@example.com")
    fake.off = "api"
    assert "API está ligada" in instancia.post("/admin/glpi/test").json()["error"]
    fake.off = "token"
    assert "login por token está desligado" in u.put("/me/glpi", {"token": TOK_A}).json()["detail"]
    fake.off = None
    fake.version = "10.0.18"
    r = u.put("/me/glpi", {"token": TOK_A})
    assert r.status_code == 400 and "10.0.18" in r.json()["detail"] and "11 ou superior" in r.json()["detail"]
    assert not db.query_one("SELECT 1 FROM glpi_accounts") and fake.sessions == {}
    fake.version = "12.0.2"
    assert u.put("/me/glpi", {"token": TOK_A}).status_code == 200


def test_sem_glpi_configurado_e_rotas_so_do_app(admin, usuario, fake):
    assert usuario.get("/me/glpi").json() == {"available": False, "connected": False}
    assert usuario.put("/me/glpi", {"token": TOK_A}).status_code == 400
    for scope in ("write", "append", "read"):
        b = Bearer(criar_chave(usuario, nome=scope, scope=scope)["token"])
        assert b.get("/me/glpi").status_code == 403
        assert b.post("/me/glpi/sync").status_code == 403
        assert b.c.put("/api/me/glpi", json={"token": TOK_A}, headers=b.h).status_code == 403
        assert b.delete("/me/glpi").status_code == 403
        assert b.post("/admin/glpi/test").status_code == 403
    assert usuario.c.put("/api/me/glpi", json={"token": TOK_A}).status_code == 403  # sem CSRF


# ---------------------------------------------------------- chamado -> tarefa --

def test_chamado_no_meu_nome_vira_tarefa_uma_vez_so(instancia, novo_usuario, fake, monkeypatch):
    monkeypatch.setattr(history, "FEED_LAG_SECONDS", 0)  # o feed esconde os últimos 2 s
    fake.add(1, 7, name="Impressora da recep&ccedil;&atilde;o", content="<p>Luz laranja.<br>Papel preso &amp; toner</p>",
             priority=5, ttr="2026-12-01 18:00:00")
    fake.add(2, 7, name="x" * 300, content="<p>" + "y" * 400 + "</p>", priority=1)
    fake.add(3, 8, name="Chamado do Beto")
    fake.add(4, 7, name="Já solucionado", status=5)
    u = novo_usuario("ana@example.com")
    assert u.put("/me/glpi", {"token": TOK_A}).json()["open"] == 2  # a 1ª passada vem junto
    a, b = sorted(tarefas(u), key=lambda t: t["id"])
    assert (a["title"], a["description"], a["priority"], a["due_date"], a["ticket"], a["external_ref"], a["status"]) == \
        ("Impressora da recepção", "Luz laranja.\nPapel preso & toner", 1, "2026-12-01", "1", "glpi:1", "todo")
    assert len(b["title"]) == 200 and len(b["description"]) == 300 and b["description"].endswith("…") and b["priority"] == 3
    # Repetir (agendador e botão) não duplica; o que a pessoa mudou na tarefa fica.
    u.patch(f"/worklog/{a['id']}", {"title": "Do meu jeito"})
    passada(u)
    assert u.post("/me/glpi/sync").json()["open"] == 2
    assert [t["title"] for t in sorted(tarefas(u), key=lambda t: t["id"])][0] == "Do meu jeito" and len(tarefas(u)) == 2
    # A criação entra no feed (e nos webhooks), assinada pelo GLPI.
    feed = u.get("/history?after=0").json()
    assert [(e["actor"], e["token_name"]) for e in feed if e["action"] == "worklog.create"] == [("system", "GLPI")] * 2
    assert fake.sessions == {}


def test_tarefa_excluida_nao_volta_e_isolamento_entre_pessoas(ana, novo_usuario, fake):
    fake.add(1, 7)
    fake.add(3, 8, name="Chamado do Beto")
    ana.post("/me/glpi/sync")
    beto = novo_usuario("beto@example.com")
    beto.put("/me/glpi", {"token": TOK_B})
    assert [t["title"] for t in tarefas(beto)] == ["Chamado do Beto"]
    assert [t["ticket"] for t in tarefas(ana)] == ["1"]
    assert beto.get("/me/glpi").json()["name"] == "Beto Lima" and ana.get("/me/glpi").json()["name"] == "Ana Souza"
    assert ana.delete(f"/worklog/{tarefas(ana)[0]['id']}").status_code == 200
    ana.post("/me/glpi/sync")
    assert tarefas(ana) == []  # a pessoa excluiu: o Nexus não briga com ela


# ----------------------------------------------------- tarefa -> solução --

def test_concluir_a_tarefa_soluciona_o_chamado_com_o_registro(ana, fake):
    fake.add(9, 7, name="Configurar VPN")
    ana.post("/me/glpi/sync")
    t = tarefas(ana)[0]
    ana.post(f"/worklog/{t['id']}/time", {"minutes": 50})
    ana.post(f"/worklog/{t['id']}/notes", {"body": "anotação minha, não vai para o requerente"})
    assert ana.post(f"/worklog/{t['id']}/finish",
                    {"resolution": "VPN liberada <b>ok</b>.\nTestado em \\\\srv & fiscal"}).status_code == 200
    # O agendador espera dois minutos (desfazer, escrever o "Como resolveu?"); depois, envia.
    passada(ana)
    assert fake.solutions == [] and ana.get("/me/glpi").json()["pending"] == 1
    envelhecer(t["id"])
    assert passada(ana) == [(uid_de(ana), None)]
    assert fake.tickets[9]["status"] == 5
    assert fake.solutions == [(9, 7, "<p>VPN liberada &lt;b&gt;ok&lt;/b&gt;.<br>Testado em \\\\srv &amp; fiscal</p>"
                                     "<p>Tempo registrado: 0 h 50 min</p><p>Registrado pelo Nexus Worklog.</p>")]
    # Idempotente: outras passadas não mandam de novo.
    passada(ana)
    ana.post("/me/glpi/sync")
    assert len(fake.solutions) == 1 and ana.get("/me/glpi").json()["pending"] == 0
    assert fake.calls.count(("POST", "/ITILSolution")) == 1


def test_atualizar_agora_envia_na_hora_e_sem_texto_vai_concluido(ana, fake):
    fake.add(5, 7)
    ana.post("/me/glpi/sync")
    ana.post(f"/worklog/{tarefas(ana)[0]['id']}/finish")
    assert ana.post("/me/glpi/sync").json()["pending"] == 0
    assert fake.solutions == [(5, 7, "<p>Concluído.</p><p>Registrado pelo Nexus Worklog.</p>")]


def test_tarefa_forjada_por_chave_de_api_nao_escreve_no_glpi(ana, fake):
    """external_ref "glpi:N" escolhido por quem tem uma chave não é vínculo: só o da sincronização vale."""
    b = Bearer(criar_chave(ana, scope="append")["token"])
    for tid in (10, 11):  # o 10 é do Beto; o 11 vai aparecer no nome da Ana depois
        r = b.post("/worklog", {"title": "forjada", "external_ref": f"glpi:{tid}", "ticket": str(tid), "status": "done",
                                "resolution": "texto de quem tem a chave"})
        assert r.status_code == 201
        envelhecer(r.json()["id"])
    fake.add(10, 8, name="Chamado do Beto")
    fake.add(11, 7, name="Chamado da Ana")
    passada(ana)
    ana.post("/me/glpi/sync")
    assert fake.solutions == [] and fake.tickets[10]["status"] == 2 and fake.tickets[11]["status"] == 2
    assert not [c for c in fake.calls if c[1] in ("/ITILSolution", "/Ticket/10", "/Ticket/11")]
    assert len(tarefas(ana)) == 2  # nem duplicou a do chamado 11


def test_chamado_ja_solucionado_por_outro_e_resposta_perdida(ana, fake):
    fake.add(1, 7)
    fake.add(2, 7)
    ana.post("/me/glpi/sync")
    um, dois = sorted(tarefas(ana), key=lambda t: t["ticket"])
    fake.tickets[1]["status"] = 5  # outra pessoa solucionou no GLPI
    ana.post("/me/glpi/sync")  # a tarefa ainda aberta ganha UMA anotação; o Nexus não conclui sozinho
    ana.post("/me/glpi/sync")
    notas = ana.get(f"/worklog/{um['id']}").json()["notes"]
    assert [n["body"] for n in notas] == [glpi.GONE] and ana.get(f"/worklog/{um['id']}").json()["status"] == "todo"
    ana.post(f"/worklog/{um['id']}/finish", {"resolution": "já estava feito"})
    ana.post("/me/glpi/sync")
    assert fake.solutions == []  # nada enviado: já estava solucionado lá
    # A solução entra no GLPI mas a resposta se perde: conta como falha; na repetição, nada é reenviado.
    ana.post(f"/worklog/{dois['id']}/finish", {"resolution": "feito"})
    fake.lose_answer = True
    st = ana.post("/me/glpi/sync").json()
    assert "não respondeu a tempo" in st["error"] and st["pending"] == 1
    fake.lose_answer = False
    st = ana.post("/me/glpi/sync").json()
    assert st["error"] is None and st["pending"] == 0 and len(fake.solutions) == 1


def test_solucao_recusada_reabre_a_tarefa_com_anotacao(ana, fake):
    fake.add(1, 7)
    ana.post("/me/glpi/sync")
    t = tarefas(ana)[0]
    ana.post(f"/worklog/{t['id']}/finish", {"resolution": "primeira"})
    ana.post("/me/glpi/sync")
    fake.tickets[1]["status"] = 2  # o requerente recusou: o chamado volta para a lista de abertos
    ana.post("/me/glpi/sync")
    ana.post("/me/glpi/sync")
    d = ana.get(f"/worklog/{t['id']}").json()
    assert d["status"] == "todo" and d["completed_at"] is None and [n["body"] for n in d["notes"]] == [glpi.REOPENED]
    ana.post(f"/worklog/{t['id']}/finish", {"resolution": "segunda"})
    ana.post("/me/glpi/sync")
    assert [s[2].split("</p>")[0] for s in fake.solutions] == ["<p>primeira", "<p>segunda"]


def test_o_glpi_recusa_a_solucao_e_a_tela_mostra(ana, fake):
    fake.add(1, 7)
    ana.post("/me/glpi/sync")
    t = tarefas(ana)[0]
    ana.post(f"/worklog/{t['id']}/finish")
    del fake.tickets[1]  # chamado excluído no GLPI
    st = ana.post("/me/glpi/sync").json()
    assert st["error"] is None and st["pending"] == 0
    assert [(f["ticket_id"], f["task_id"]) for f in st["failed"]] == [(1, t["id"])] and "recusou a solução" in st["failed"][0]["error"]
    for _ in range(6):  # o agendador desiste depois de 5 tentativas
        envelhecer(t["id"])
        passada(ana)
    assert db.query_one("SELECT tries FROM glpi_tickets")["tries"] == glpi.MAX_FAILURES
    assert ana.get(f"/worklog/{t['id']}").json()["status"] == "done"


def test_tarefa_transferida_para_outra_pessoa_nao_manda_solucao(ana, novo_usuario, fake):
    """Bloquear/excluir com transferência muda o dono da tarefa: o vínculo de quem saiu não vale mais."""
    fake.add(1, 7)
    ana.post("/me/glpi/sync")
    t = tarefas(ana)[0]
    beto = novo_usuario("beto@example.com")
    db.execute("UPDATE worklog_tasks SET user_id = %s, external_ref = NULL WHERE id = %s", (uid_de(beto), t["id"]))
    assert beto.post(f"/worklog/{t['id']}/finish", {"resolution": "feito pelo Beto"}).status_code == 200
    st = ana.post("/me/glpi/sync").json()
    assert fake.solutions == [] and (st["open"], st["pending"]) == (0, 0)


# ------------------------------------------------------------------ falhas --

def test_glpi_fora_do_ar_nao_trava_o_nexus_e_tenta_de_novo(ana, novo_usuario, fake):
    fake.add(1, 7)
    ana.post("/me/glpi/sync")
    t = tarefas(ana)[0]
    beto = novo_usuario("beto@example.com")
    beto.put("/me/glpi", {"token": TOK_B})
    fake.fail = ConnectionRefusedError()
    assert ana.post(f"/worklog/{t['id']}/finish", {"resolution": "feito"}).status_code == 200  # o Nexus segue
    envelhecer(t["id"])
    db.execute("UPDATE glpi_accounts SET last_sync_at = now() - interval '6 minutes'")
    n = len(fake.calls)
    res = glpi.run_once()
    assert len(res) == 1 and "recusou a conexão" in res[0][1] and len(fake.calls) == n + 1  # fora do ar: não insiste com os outros
    conta = db.query_one("SELECT failures, next_attempt_at > now() AS espera FROM glpi_accounts WHERE user_id = %s", (res[0][0],))
    assert conta == {"failures": 1, "espera": True}
    st = ana.post("/me/glpi/sync").json()  # o botão responde com o motivo, sem 500
    assert st["connected"] and "recusou a conexão" in st["error"] and st["pending"] == 1
    fake.fail = 503
    assert "HTTP 503" in ana.post("/me/glpi/sync").json()["error"]
    # 5 falhas seguidas pausam; o agendador não tenta mais até a pessoa pedir.
    db.execute("UPDATE glpi_accounts SET failures = 4, next_attempt_at = NULL WHERE user_id = %s", (uid_de(ana),))
    db.execute("UPDATE glpi_accounts SET next_attempt_at = now() + interval '1 hour' WHERE user_id <> %s", (uid_de(ana),))
    passada(ana)
    assert ana.get("/me/glpi").json()["paused"] is True
    db.execute("UPDATE glpi_accounts SET next_attempt_at = NULL WHERE user_id = %s", (uid_de(ana),))
    assert uid_de(ana) not in [r[0] for r in passada(ana)]
    fake.fail = None
    st = ana.post("/me/glpi/sync").json()
    assert (st["paused"], st["error"], st["pending"]) == (False, None, 0) and fake.tickets[1]["status"] == 5


def test_token_revogado_pausa_na_hora_e_reconectar_resolve(ana, fake):
    fake.add(1, 7)
    del fake.users[TOK_A]
    st = ana.post("/me/glpi/sync").json()
    assert st["paused"] is True and "recusou o seu token" in st["error"] and tarefas(ana) == []
    assert passada(ana) == []
    fake.users["token-novo-da-ana-0123456789"] = {"id": 7, "first": "Ana", "last": "Souza"}
    st = ana.put("/me/glpi", {"token": "token-novo-da-ana-0123456789"}).json()
    assert (st["paused"], st["error"], st["open"]) == (False, None, 1)


def test_agendador_respeita_o_intervalo_e_pula_conta_bloqueada(ana, instancia, fake):
    assert glpi.run_once() == []  # acabou de sincronizar (ao conectar): só daqui a 5 minutos
    assert passada(ana) == [(uid_de(ana), None)]
    assert instancia.post(f"/admin/users/{uid_de(ana)}/block").status_code == 200
    assert passada(ana) == []


def test_limite_de_chamadas_ao_glpi_por_pessoa(ana, monkeypatch):
    monkeypatch.undo()  # o limite de verdade (5 por minuto)
    security.webhook_test_limiter._hits.clear()
    codigos = [ana.delete("/me/glpi").status_code] + [ana.put("/me/glpi", {"token": "token-qualquer-0123"}).status_code
                                                      for _ in range(6)]
    assert codigos[0] == 200 and codigos[-1] == 429
