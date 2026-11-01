"""Lote G — API aberta: feed de mudanças, idempotência, webhooks, contrato e dados."""
import hashlib
import hmac
import ipaddress
import json
import os
import pathlib

import pytest

from app import db, webhooks
from app.routers import history
from conftest import Bearer, criar_chave, uid_de


@pytest.fixture(autouse=True)
def _sem_atraso(monkeypatch):
    # O feed esconde os últimos 2 s (ordem dos ids); nos testes, tudo aparece já.
    monkeypatch.setattr(history, "FEED_LAG_SECONDS", 0)


# ---------------------------------------------------------------- feed (F1) --

def test_feed_em_ordem_crescente_com_lapide_e_external_ref(usuario):
    b = Bearer(criar_chave(usuario, scope="read")["token"])
    inicio = b.get("/history?after=0").json()
    cursor = inicio[-1]["id"] if inicio else 0
    t = usuario.post("/worklog", {"title": "Alerta disco", "external_ref": "zbx-1"}).json()["id"]
    usuario.post(f"/worklog/{t}/finish")
    usuario.delete(f"/worklog/{t}")
    itens = b.get(f"/history?after={cursor}").json()
    assert [i["action"] for i in itens] == ["worklog.create", "worklog.finish", "worklog.delete"]
    assert [i["id"] for i in itens] == sorted(i["id"] for i in itens)
    assert all(i["entity"] == "worklog" and i["entity_id"] == t and i["external_ref"] == "zbx-1" for i in itens)
    assert {"id", "at", "actor", "token_name"} <= set(itens[0])
    # O cursor avança: depois do último, nada.
    assert b.get(f"/history?after={itens[-1]['id']}").json() == []
    assert len(b.get(f"/history?after={cursor}&limit=2").json()) == 2


def test_feed_so_da_propria_pessoa(usuario, novo_usuario):
    outro = novo_usuario("outro@example.com")
    outro.post("/worklog", {"title": "Do outro"})
    usuario.post("/worklog", {"title": "Minha"})
    meus = usuario.get("/history?after=0").json()
    ids_outro = {r["id"] for r in db.query_all(
        "SELECT a.id FROM audit_log a JOIN users u ON u.id = a.user_id WHERE u.email = 'outro@example.com'")}
    assert meus and not ({i["id"] for i in meus} & ids_outro)


def test_feed_cursor_alem_da_retencao_410(usuario):
    for n in range(4):
        usuario.post("/worklog", {"title": f"T{n}"})
    ids = [i["id"] for i in usuario.get("/history?after=0").json()]
    db.execute("DELETE FROM audit_log WHERE id <= %s", (ids[2],))  # a faxina de 180 dias levou o começo
    assert usuario.get(f"/history?after={ids[0]}").status_code == 410
    assert usuario.get(f"/history?after={ids[2]}").status_code == 200  # cursor logo antes do que restou: ok
    assert usuario.get("/history?after=0").status_code == 200  # recomeçar do zero sempre vale


# ------------------------------------------------------- idempotência (I1) --

def test_anotacao_e_tempo_com_external_ref_nao_duplicam(usuario):
    b = Bearer(criar_chave(usuario)["token"])
    t = b.post("/worklog", {"title": "Chamado 42"}).json()["id"]
    r1 = b.post(f"/worklog/{t}/notes", {"body": "Reiniciei o serviço", "external_ref": "n8n-1"})
    r2 = b.post(f"/worklog/{t}/notes", {"body": "Reiniciei o serviço", "external_ref": "n8n-1"})
    assert r1.status_code == 201 and r2.status_code == 200
    assert r2.json()["existing"] and r2.json()["id"] == r1.json()["id"]
    r1 = b.post(f"/worklog/{t}/time", {"minutes": 30, "external_ref": "n8n-2"})
    r2 = b.post(f"/worklog/{t}/time", {"minutes": 30, "external_ref": "n8n-2"})
    assert r1.status_code == 201 and r2.status_code == 200 and r2.json()["id"] == r1.json()["id"]
    det = b.get(f"/worklog/{t}").json()
    assert len(det["notes"]) == 1 and det["minutes"] == 30
    # Sem external_ref continua como sempre (duplica de propósito).
    assert b.post(f"/worklog/{t}/notes", {"body": "outra"}).status_code == 201
    assert b.post(f"/worklog/{t}/notes", {"body": "outra"}).status_code == 201


def test_external_ref_e_por_pessoa(usuario, novo_usuario):
    outro = novo_usuario("outro@example.com")
    t1 = usuario.post("/worklog", {"title": "A"}).json()["id"]
    t2 = outro.post("/worklog", {"title": "B"}).json()["id"]
    assert usuario.post(f"/worklog/{t1}/time", {"minutes": 5, "external_ref": "x"}).status_code == 201
    assert outro.post(f"/worklog/{t2}/time", {"minutes": 5, "external_ref": "x"}).status_code == 201


def test_busca_por_external_ref(usuario):
    t = usuario.post("/worklog", {"title": "Alerta", "external_ref": "zbx-9"}).json()["id"]
    usuario.post("/worklog", {"title": "Outra"})
    assert [x["id"] for x in usuario.get("/worklog?external_ref=zbx-9").json()] == [t]
    assert usuario.get("/worklog?external_ref=nao-existe").json() == []
    p = usuario.post("/projects", {"name": "Cliente X", "external_ref": "crm-7"}).json()["id"]
    usuario.patch(f"/projects/{p}", {"archived": True})
    achou = usuario.get("/projects?external_ref=crm-7").json()
    assert [x["id"] for x in achou] == [p] and achou[0]["external_ref"] == "crm-7"
    assert usuario.get("/projects?external_ref=nada").json() == []


# ------------------------------------------------------------ webhooks (W1) --

DNS = {"hooks.example.com": {"93.184.216.34"}, "interno.example.com": {"10.0.0.5"},
       "misto.example.com": {"93.184.216.34", "127.0.0.1"}}


@pytest.fixture
def dns(monkeypatch):
    def _resolve(host, port):
        try:
            return {str(ipaddress.ip_address(host))}  # IP no endereço: o getaddrinfo devolve ele mesmo
        except ValueError:
            pass
        if host not in DNS:
            raise OSError("sem DNS")
        return DNS[host]
    monkeypatch.setattr(webhooks, "resolve", _resolve)
    monkeypatch.setattr(webhooks, "LAG_SECONDS", 0)


class Destino:
    """Faz o papel do sistema que recebe: guarda o que chegou e responde `status`."""

    def __init__(self, status=200):
        self.status, self.recebidos = status, []

    def __call__(self, url, headers, body):
        self.recebidos.append((url, headers, body))
        if isinstance(self.status, Exception):
            raise self.status
        return self.status


def _novo(api, url="https://hooks.example.com/nexus?k=1", events=None):
    return api.post("/webhooks", {"url": url, **({"events": events} if events else {})})


def test_webhook_recusa_endereco_inseguro(usuario, dns):
    for url in ("http://hooks.example.com/x", "https://127.0.0.1/x", "https://[::1]/x", "https://169.254.169.254/",
                "https://interno.example.com/x", "https://misto.example.com/", "https://naoexiste.example.com/",
                "https://u:p@hooks.example.com/", "https://[::ffff:10.0.0.1]/", "https://100.64.0.1/"):
        assert _novo(usuario, url).status_code == 400, url
    assert usuario.get("/webhooks").json() == []


def test_webhook_cria_lista_limite_e_apaga(usuario, novo_usuario, dns):
    r = _novo(usuario)
    assert r.status_code == 201 and r.json()["secret"].startswith("whsec_")
    lista = usuario.get("/webhooks").json()
    assert len(lista) == 1 and "secret" not in lista[0] and lista[0]["active"] and lista[0]["events"] == ["*"]
    assert not db.query_one("SELECT 1 FROM webhooks WHERE secret_salt = %s", (r.json()["secret"],))
    for _ in range(4):
        assert _novo(usuario, events=["worklog.*"]).status_code == 201
    assert _novo(usuario).status_code == 409
    assert _novo(usuario, events=["DROP TABLE"]).status_code == 422
    outro = novo_usuario("outro@example.com")
    assert outro.delete(f"/webhooks/{r.json()['id']}").status_code == 404
    assert usuario.delete(f"/webhooks/{r.json()['id']}").status_code == 200
    # Chave: write cadastra, read só lê.
    assert Bearer(criar_chave(usuario, scope="read")["token"]).post("/webhooks", {"url": "https://hooks.example.com/"}).status_code == 403
    assert Bearer(criar_chave(usuario, nome="w")["token"]).get("/webhooks").status_code == 200
    # cadastrar só pelo app: chave vazada não abre canal permanente para fora
    assert Bearer(criar_chave(usuario, nome="w2")["token"]).post("/webhooks", {"url": "https://hooks.example.com/"}).status_code == 403


def test_webhook_entrega_assinada_em_ordem_e_filtrada(usuario, dns):
    segredo = _novo(usuario, events=["worklog.*"]).json()["secret"]
    t = usuario.post("/worklog", {"title": "Trocar disjuntor", "external_ref": "os-77"}).json()["id"]
    usuario.post(f"/worklog/{t}/notes", {"body": "não entra (note.*)"})
    usuario.post(f"/worklog/{t}/finish")
    destino = Destino()
    assert webhooks.run_once(send=destino)[0][1] == 2
    eventos = [json.loads(b) for _, _, b in destino.recebidos]
    assert [e["action"] for e in eventos] == ["worklog.create", "worklog.finish"]
    assert eventos[0]["external_ref"] == "os-77" and eventos[1]["data"]["status"] == "done"
    url, h, body = destino.recebidos[0]
    assert url.endswith("/nexus?k=1") and h["X-Nexus-Event"] == "worklog.create"
    assert h["X-Nexus-Delivery"] == str(eventos[0]["id"])
    ts, v1 = (p.split("=", 1)[1] for p in h["X-Nexus-Signature"].split(","))
    assert v1 == hmac.new(segredo.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    # Nada novo: nada sai de novo.
    assert webhooks.run_once(send=destino) == [] and len(destino.recebidos) == 2
    usuario.delete(f"/worklog/{t}")
    webhooks.run_once(send=destino)
    lapide = json.loads(destino.recebidos[-1][2])
    assert lapide["action"] == "worklog.delete" and lapide["data"] is None


def test_webhook_reentrega_com_espera_e_desliga_apos_5_falhas(usuario, dns):
    hid = _novo(usuario).json()["id"]
    usuario.post("/worklog", {"title": "A"})
    fora = Destino(status=500)
    for n in range(1, 6):
        res = webhooks.run_once(send=fora)
        assert res and res[0][2] == "o destino respondeu HTTP 500"
        w = db.query_one("SELECT failures, next_attempt_at > now() AS espera, disabled_at FROM webhooks WHERE id = %s", (hid,))
        assert w["failures"] == n and w["espera"]
        assert webhooks.run_once(send=fora) == []  # ainda esperando: não tenta
        db.execute("UPDATE webhooks SET next_attempt_at = now() WHERE id = %s", (hid,))
    assert len(fora.recebidos) == 5
    lista = usuario.get("/webhooks").json()[0]
    assert not lista["active"] and lista["disabled_at"] and "500" in lista["last_error"]
    # Religar: continua do mesmo evento (que não foi entregue).
    assert usuario.post(f"/webhooks/{hid}/enable").status_code == 200
    ok = Destino()
    webhooks.run_once(send=ok)
    assert [json.loads(b)["action"] for _, _, b in ok.recebidos] == ["worklog.create", "webhook.enable"]
    assert usuario.get("/webhooks").json()[0]["failures"] == 0


def test_webhook_falha_de_rede_e_troca_de_senha(usuario, dns):
    from conftest import SENHA_PADRAO
    hid = _novo(usuario).json()["id"]
    usuario.post("/worklog", {"title": "A"})
    res = webhooks.run_once(send=Destino(status=TimeoutError("lento")))
    assert "falha de conexão" in res[0][2]
    r = usuario.post("/auth/change-password", {"current_password": SENHA_PADRAO, "new_password": "Outra-Senha-Forte-2"})
    assert r.status_code == 200
    w = db.query_one("SELECT disabled_at, last_error FROM webhooks WHERE id = %s", (hid,))
    assert w["disabled_at"] and "senha" in w["last_error"]


def test_webhook_so_eventos_do_dono_e_sem_fotos(usuario, novo_usuario, dns):
    _novo(usuario)
    outro = novo_usuario("outro@example.com")
    outro.post("/worklog", {"title": "Do outro"})
    destino = Destino()
    webhooks.run_once(send=destino)
    assert destino.recebidos == []
    assert webhooks.payload({"id": 1, "created_at": None, "actor": "web", "token_name": None, "action": "photo.create",
                             "entity": "photo", "entity_id": 3, "before": None,
                             "after": {"task_id": 1, "image": "base64..."}})["data"] is None


# ------------------------------------------------------------------- dados --

def test_exportacao_json_completa(usuario):
    p = usuario.post("/projects", {"name": "Cliente X", "description": "contrato 2026", "external_ref": "crm-1"}).json()["id"]
    usuario.post(f"/projects/{p}/objectives", {"title": "Migrar e-mail"})
    usuario.post("/worklog", {"title": "Alerta", "external_ref": "zbx-1", "project_id": p})
    usuario.post("/templates", {"name": "Troca de toner", "title": "Trocar toner", "checklist": ["retirar", "instalar"]})
    usuario.put("/me/profile", {"display_name": "Marina"})
    dados = usuario.get("/export/tudo.json").json()
    assert {"profile", "prefs", "templates", "photos", "projects", "tasks"} <= set(dados)
    proj = dados["projects"][0]
    assert proj["description"] == "contrato 2026" and proj["external_ref"] == "crm-1"
    assert [o["title"] for o in proj["objectives"]] == ["Migrar e-mail"]
    assert dados["tasks"][0]["external_ref"] == "zbx-1"
    assert dados["templates"][0]["checklist"] == ["retirar", "instalar"]
    assert dados["profile"]["display_name"] == "Marina" and dados["profile"]["has_avatar"] is False
    assert dados["photos"] == {"count": 0, "download": "/api/export/fotos.zip"}
    assert set(dados["prefs"]) == {"email", "push", "assistant"}


def test_faxina_dos_pedidos_de_convite(usuario):
    from conftest import SENHA_PADRAO
    ins = """INSERT INTO invite_requests (name, email, source, reason, status, created_at, decided_at)
             VALUES ('X', %s, 'site', 'motivo', %s, now() - make_interval(days => %s), %s)"""
    db.execute(ins, ("velho-decidido@ex.com", "declined", 40, db.query_one("SELECT now() - interval '31 days' AS t")["t"]))
    db.execute(ins, ("novo-decidido@ex.com", "invited", 40, db.query_one("SELECT now() - interval '5 days' AS t")["t"]))
    db.execute(ins, ("pendente-velho@ex.com", "pending", 181, None))
    db.execute(ins, ("pendente-novo@ex.com", "pending", 100, None))
    try:
        usuario.login(usuario.me["email"], SENHA_PADRAO)  # a faxina roda no login
        restam = {r["email"] for r in db.query_all("SELECT email FROM invite_requests WHERE email LIKE '%%@ex.com'")}
        assert restam == {"novo-decidido@ex.com", "pendente-novo@ex.com"}
    finally:
        db.execute("DELETE FROM invite_requests WHERE email LIKE '%%@ex.com'")


def test_quem_pode_ver_meu_registro(admin, usuario, novo_usuario):
    from app import roles
    vis = novo_usuario("visual@example.com")
    roles.grant(uid_de(vis), ["viewer"])
    lista = usuario.get("/me/visibility").json()
    assert {(p["name"], tuple(p["roles"])) for p in lista} == {("Admin", ("admin", "viewer")), ("Visual", ("viewer",))}
    assert all("email" not in p for p in lista)
    assert Bearer(criar_chave(usuario)["token"]).get("/me/visibility").status_code == 403  # só pelo app


# ------------------------------------------------------------ contrato (D1) --

def test_openapi_em_dia():
    """docs/openapi.json versionado = o que o app gera (rode tools/openapi.py)."""
    from app.main import app
    path = pathlib.Path(os.environ.get("OPENAPI_FILE") or pathlib.Path(__file__).parents[2] / "docs" / "openapi.json")
    assert path.exists(), "falta docs/openapi.json: rode tools/openapi.py"
    atual = json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"
    assert path.read_text(encoding="utf-8") == atual, "docs/openapi.json desatualizado: rode tools/openapi.py"
    assert "/api/history" in app.openapi()["paths"] and "/api/webhooks" in app.openapi()["paths"]


def test_retry_after_no_429_e_503(usuario):
    import asyncio
    from app import main, security
    b = Bearer(criar_chave(usuario)["token"])
    security.token_limiter._hits.clear()
    try:
        for _ in range(security.token_limiter.max):
            b.get("/timer")
        r = b.get("/timer")
        assert r.status_code == 429 and r.headers["Retry-After"] == "60"
    finally:
        security.token_limiter._hits.clear()
    r = asyncio.run(main._busy(None, security.Busy()))
    assert r.status_code == 503 and r.headers["Retry-After"] == "5"
    # Os outros erros seguem sem o header e com o detail de sempre.
    r = usuario.get("/worklog/999999")
    assert r.status_code == 404 and "Retry-After" not in r.headers and r.json() == {"detail": "não encontrado"}


def test_webhook_de_grupo_recebe_o_desfazer():
    from app.webhooks import matches
    assert matches(["worklog.*"], "undo", "worklog") and not matches(["recurring.*"], "undo", "worklog")
    assert matches(["worklog.*"], "worklog.finish", "worklog") and matches(["*"], "undo", "worklog")


def test_webhook_recusa_caracteres_de_controle():
    from app.webhooks import Refused, check_url
    import pytest
    for url in ("https://hooks.example.com/a%0d%0aX-Evil: 1", "https://hooks.example.com/a b"):
        with pytest.raises(Refused):
            check_url(url)
