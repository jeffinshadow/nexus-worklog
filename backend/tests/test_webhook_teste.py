"""Testar webhook (ping): envio na hora, assinado, pelo mesmo caminho (SSRF, prazo),
só pelo app, com limite, sem contar como falha."""
import hashlib
import hmac
import json
import ssl

from app import db, security, webhooks
from conftest import Bearer, criar_chave
from test_api_aberta import DNS, Destino, _novo, dns  # noqa: F401 — dns é fixture


def _sig_ok(segredo, headers, body):
    ts, v1 = (p.split("=", 1)[1] for p in headers["X-Nexus-Signature"].split(","))
    return v1 == hmac.new(segredo.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()


def test_ping_assinado_e_marcado_como_teste(usuario, dns, monkeypatch):
    r = _novo(usuario).json()
    destino = Destino(status=204)
    monkeypatch.setattr(webhooks, "post", destino)
    res = usuario.post(f"/webhooks/{r['id']}/test")
    assert res.status_code == 200
    out = res.json()
    assert out["ok"] and out["status"] == 204 and out["error"] is None and isinstance(out["ms"], int)
    url, h, body = destino.recebidos[0]
    assert url == "https://hooks.example.com/nexus?k=1"
    assert h["X-Nexus-Event"] == "ping" and h["X-Nexus-Delivery"].startswith("test-")
    assert _sig_ok(r["secret"], h, body)
    corpo = json.loads(body)
    assert corpo["action"] == "ping" and corpo["test"] is True and corpo["entity_id"] == r["id"]
    # Não entra na fila: a passada seguinte não manda nada (o teste não vira evento).
    assert webhooks.run_once(send=destino) == [] and len(destino.recebidos) == 1


def test_ping_que_falha_nao_conta_nem_desliga(usuario, dns, monkeypatch):
    hid = _novo(usuario).json()["id"]
    monkeypatch.setattr(webhooks, "post", Destino(status=500))
    for _ in range(5):
        out = usuario.post(f"/webhooks/{hid}/test").json()
        assert not out["ok"] and out["status"] == 500 and "HTTP 500" in out["error"]
    w = db.query_one("SELECT failures, disabled_at, last_error, next_attempt_at FROM webhooks WHERE id = %s", (hid,))
    assert w == {"failures": 0, "disabled_at": None, "last_error": None, "next_attempt_at": None}


def test_ping_explica_erros_em_linguagem_comum(usuario, dns, monkeypatch):
    hid = _novo(usuario).json()["id"]
    casos = [(ssl.SSLCertVerificationError("self-signed"), "certificado"), (TimeoutError(), "não respondeu a tempo"),
             (ConnectionRefusedError(), "recusou a conexão"), (302, "redirecionamento"), (401, "segredo"),
             (404, "caminho")]
    for falha, trecho in casos:
        security.webhook_test_limiter._hits.clear()
        monkeypatch.setattr(webhooks, "post", Destino(status=falha))
        out = usuario.post(f"/webhooks/{hid}/test").json()
        assert not out["ok"] and trecho in out["error"], (falha, out)


def test_ping_recusa_rede_interna(usuario, dns, monkeypatch):
    """O DNS passou a apontar para a rede interna depois do cadastro: o teste não sai."""
    hid = _novo(usuario).json()["id"]
    monkeypatch.setitem(DNS, "hooks.example.com", {"10.0.0.5"})
    out = usuario.post(f"/webhooks/{hid}/test").json()  # post de verdade: check_url recusa antes de conectar
    assert not out["ok"] and out["status"] is None and "rede interna" in out["error"]
    assert db.query_one("SELECT failures FROM webhooks WHERE id = %s", (hid,))["failures"] == 0


def test_ping_limite_so_pelo_app_e_so_do_dono(usuario, novo_usuario, dns, monkeypatch):
    hid = _novo(usuario).json()["id"]
    monkeypatch.setattr(webhooks, "post", Destino())
    # Chave de API (mesmo write) não testa: só pelo app.
    assert Bearer(criar_chave(usuario)["token"]).post(f"/webhooks/{hid}/test").status_code == 403
    # Sem o CSRF certo: recusado.
    assert usuario.post(f"/webhooks/{hid}/test", headers={"X-CSRF-Token": "errado"}).status_code == 403
    # De outra pessoa: 404 (nem diz que existe).
    outro = novo_usuario("outro@example.com")
    assert outro.post(f"/webhooks/{hid}/test").status_code == 404
    assert usuario.post("/webhooks/999/test").status_code == 404
    for _ in range(5):
        assert usuario.post(f"/webhooks/{hid}/test").status_code == 200
    r = usuario.post(f"/webhooks/{hid}/test")
    assert r.status_code == 429 and "aguarde" in r.json()["detail"]
