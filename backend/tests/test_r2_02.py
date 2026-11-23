"""Rodada 2, pacote 02: JSON aninhado demais sem 500, busca com NUL, minutos do webhook só do dono
e logo WebP de formato desconhecido."""
import json

import pytest

from app import db, webhooks
from conftest import uid_de
from test_api_aberta import DNS, Destino, _novo, dns  # noqa: F401 — dns é fixture


# ------------------------------------------------------------ JSON aninhado --

def _aninhado(n):
    return ("[" * n + "]" * n).encode()


@pytest.mark.parametrize("niveis", [900, 1100, 2000, 5000, 20000])
def test_json_aninhado_nunca_da_500(usuario, niveis):
    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app, base_url="http://testserver")
    json_h = {"Content-Type": "application/json"}
    respostas = [anon.post("/api/auth/login", content=_aninhado(niveis), headers=json_h),
                 usuario.c.post("/api/worklog", content=_aninhado(niveis), headers=usuario._h(json_h))]
    for r in respostas:
        assert r.status_code == (422 if niveis == 900 else 400), r.text[:200]
        assert "detail" in r.json()
        if 1000 < niveis <= 5000:
            assert r.json() == {"detail": "JSON aninhado demais"}


def test_json_aninhado_dentro_de_campo_valido(usuario):
    corpo = '{"title":"x","description":' + '{"a":' * 3000 + "1" + "}" * 3000 + "}"
    r = usuario.c.post("/api/worklog", content=corpo.encode(), headers=usuario._h({"Content-Type": "application/json"}))
    assert r.status_code == 400 and r.json() == {"detail": "JSON aninhado demais"}
    # O 422 comum segue igual (lista de erros com o valor recusado).
    r = usuario.post("/worklog", {"title": [[1]]})
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)


# ------------------------------------------------------------- NUL na busca --

def test_busca_com_nul_nao_da_500(usuario):
    usuario.post("/worklog", {"title": "Backup do ERP"})
    r = usuario.get("/search?q=backup%00erp")
    assert r.status_code == 400 and "caractere inválido" in r.json()["detail"]
    assert usuario.get("/search/similar?title=backup%00erp").status_code == 200
    assert usuario.get("/search?q=backup").json()["total_tasks"] == 1  # a busca comum segue


# ------------------------------------------------- minutos do webhook: dono --

def test_webhook_de_tarefa_transferida_traz_so_os_minutos_do_dono(usuario, novo_usuario, dns):
    saiu = novo_usuario("saiu@example.com")
    assert _novo(usuario, events=["worklog.*"]).status_code == 201
    tid = usuario.post("/worklog", {"title": "Trocar o switch"}).json()["id"]
    # Como depois de uma transferência pelo admin: a tarefa guarda horas de quem a tinha.
    db.execute("INSERT INTO time_entries (task_id, user_id, minutes, day) VALUES (%s, %s, 90, current_date)",
               (tid, uid_de(saiu)))
    assert usuario.post(f"/worklog/{tid}/time", {"minutes": 30}).status_code == 201
    assert usuario.post(f"/worklog/{tid}/finish", {}).status_code == 200
    # Direto no corpo do evento...
    row = db.query_one("SELECT * FROM audit_log WHERE user_id = %s AND action = 'worklog.finish'", (uid_de(usuario),))
    assert webhooks.payload(row)["data"]["minutes"] == 30
    # ...e pelo caminho da entrega (a passada do agendador).
    destino = Destino()
    webhooks.run_once(send=destino)
    fim = [json.loads(b) for _, h, b in destino.recebidos if h["X-Nexus-Event"] == "worklog.finish"]
    assert len(fim) == 1 and fim[0]["data"]["minutes"] == 30 and fim[0]["entity_id"] == tid


# ---------------------------------------------------------------- logo WebP --

def test_logo_webp_de_formato_desconhecido_e_recusado(admin):
    envia = lambda data: admin.c.post("/api/admin/branding/logo", content=data,  # noqa: E731
                                      headers=admin._h({"Content-Type": "image/webp"}))
    riff = lambda corpo: b"RIFF" + (len(corpo) + 4).to_bytes(4, "little") + b"WEBP" + corpo  # noqa: E731
    for ruim in (riff(b"XXXX" + b"\x00" * 40), riff(b"ANIM" + b"\x00" * 40), riff(b"")):
        r = envia(ruim)
        assert r.status_code == 400 and "WebP" in r.json()["detail"], ruim[:20]
    assert admin.get("/branding").json()["logo"] is None
    vp8x = riff(b"VP8X" + (10).to_bytes(4, "little") + b"\x00" * 4 + (599).to_bytes(3, "little")
                + (199).to_bytes(3, "little") + b"\x00" * 8)
    assert envia(vp8x).status_code == 200
    # PNG sem IHDR e SVG seguem como antes.
    assert envia(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).status_code == 200
    assert envia(b'<svg xmlns="http://www.w3.org/2000/svg" width="99999" height="99999"></svg>').status_code == 200
