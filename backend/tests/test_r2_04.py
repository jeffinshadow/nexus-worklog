"""Rodada 2, pacote 04: pontos abertos da integração com o GLPI (papel no sincronizar,
troca de endereço limpa vínculos e App-Token, Host com IPv6)."""
from app import db, glpi
from conftest import hist, papeis, uid_de
from test_glpi import APP, URL, ana, fake, instancia, tarefas  # noqa: F401 — fixtures e o GLPI falso

OUTRO = "http://outro.example.com"


def _app_token():
    return db.query_one("SELECT glpi_app_token FROM app_settings WHERE id = 1")["glpi_app_token"]


def _contagens():
    return (db.query_one("SELECT count(*) AS n FROM glpi_accounts")["n"],
            db.query_one("SELECT count(*) AS n FROM glpi_tickets")["n"])


def test_sincronizar_exige_o_papel_usuario(ana, instancia, fake):
    papeis(instancia, ana, ["viewer"])
    antes = len(fake.calls)
    r = ana.post("/me/glpi/sync")
    assert r.status_code == 403 and r.json()["detail"] == "esta conta não tem registro próprio"
    assert len(fake.calls) == antes  # nem chegou a falar com o GLPI


def test_trocar_o_endereco_apaga_contas_vinculos_e_app_token(ana, instancia, fake):
    fake.add(9, 7, name="Configurar VPN")
    ana.post("/me/glpi/sync")
    t = tarefas(ana)[0]
    assert _contagens() == (1, 1) and _app_token()
    r = instancia.put("/admin/org", {"glpi_url": OUTRO})
    assert r.status_code == 200 and r.json()["glpi_url"] == OUTRO and r.json()["glpi_app_token_set"] is False
    assert _contagens() == (0, 0) and _app_token() is None
    # A tarefa fica, sem a chave do chamado antigo (o chamado 9 do GLPI novo pode ser importado).
    fica = ana.get(f"/worklog/{t['id']}").json()
    assert fica["title"] == "Configurar VPN" and fica["external_ref"] is None
    h = db.query_all("SELECT action, after FROM audit_log WHERE action LIKE 'app.glpi%%' ORDER BY id DESC LIMIT 2")
    assert {x["action"]: x["after"] for x in h} == {
        "app.glpi_url": {"glpi_url": OUTRO, "links": 1, "by": instancia.me["email"]},
        "app.glpi_app_token": {"set": False, "by": instancia.me["email"]}}
    assert APP not in str(hist(instancia, limit=50))


def test_desligar_tambem_apaga_vinculos_e_app_token(ana, instancia, fake):
    fake.add(9, 7)
    ana.post("/me/glpi/sync")
    assert instancia.put("/admin/org", {"glpi_url": ""}).json()["glpi_app_token_set"] is False
    assert _contagens() == (0, 0) and _app_token() is None


def test_chamado_de_mesmo_numero_no_glpi_novo_e_importado(ana, instancia, fake, monkeypatch):
    fake.add(9, 7, name="Chamado do GLPI antigo")
    ana.post("/me/glpi/sync")
    instancia.put("/admin/org", {"glpi_url": OUTRO, "glpi_app_token": APP})
    novo = type(fake)()
    novo.add(9, 7, name="Chamado do GLPI novo")
    monkeypatch.setattr(glpi, "request", lambda base, *a, **k: novo(URL, *a, **k) if base == OUTRO else None)
    assert ana.put("/me/glpi", {"token": "token-pessoal-da-ana-0123456789abcdef"}).status_code == 200
    assert [t["title"] for t in tarefas(ana)] == ["Chamado do GLPI novo"]
    assert db.query_one("SELECT count(*) AS n FROM worklog_tasks WHERE user_id = %s", (uid_de(ana),))["n"] == 2


def test_anotacao_de_chamado_que_saiu_vale_de_novo_no_glpi_novo(ana, instancia, fake, monkeypatch):
    fake.add(9, 7)
    ana.post("/me/glpi/sync")
    fake.tickets[9]["status"] = 5
    ana.post("/me/glpi/sync")  # a tarefa do GLPI antigo ganha a anotação "saiu da lista"
    instancia.put("/admin/org", {"glpi_url": OUTRO, "glpi_app_token": APP})
    novo = type(fake)()
    novo.add(9, 7)
    monkeypatch.setattr(glpi, "request", lambda base, *a, **k: novo(URL, *a, **k) if base == OUTRO else None)
    assert ana.put("/me/glpi", {"token": "token-pessoal-da-ana-0123456789abcdef"}).status_code == 200
    novo.tickets[9]["status"] = 5
    ana.post("/me/glpi/sync")
    t = tarefas(ana)[0]
    assert [n["body"] for n in ana.get(f"/worklog/{t['id']}").json()["notes"]] == [glpi.GONE]


def test_trocar_o_endereco_com_app_token_novo_guarda_o_novo(ana, instancia):
    r = instancia.put("/admin/org", {"glpi_url": OUTRO, "glpi_app_token": "app-token-do-glpi-novo-0123456789"})
    assert r.json()["glpi_app_token_set"] is True
    assert glpi.unseal(_app_token()) == "app-token-do-glpi-novo-0123456789"


def test_salvar_o_mesmo_endereco_nao_apaga_nada(ana, instancia, fake):
    fake.add(9, 7)
    ana.post("/me/glpi/sync")
    for igual in (URL, URL + "/", URL + "/apirest.php"):
        assert instancia.put("/admin/org", {"glpi_url": igual}).status_code == 200
    assert _contagens() == (1, 1) and glpi.unseal(_app_token()) == APP
    assert tarefas(ana)[0]["external_ref"] == "glpi:9"


def test_host_com_ipv6_vai_entre_colchetes(monkeypatch):
    assert glpi.host_header("2001:db8::5", 80) == "[2001:db8::5]"
    assert glpi.host_header("2001:db8::5", 8080) == "[2001:db8::5]:8080"
    assert glpi.host_header("glpi.example.com", 443) == "glpi.example.com"
    assert glpi.host_header("glpi.example.com", 8080) == "glpi.example.com:8080"
    # E é esse o cabeçalho que a chamada manda.
    enviado = {}

    class Conn:
        sock = None

        def __init__(self, *a, **k):
            pass

        def request(self, method, path, body=None, headers=None):
            enviado.update(headers)

        def getresponse(self):
            return type("R", (), {"status": 200, "read": lambda self, n: b"{}"})()

        def close(self):
            pass
    monkeypatch.setattr(glpi.webhooks, "resolve", lambda host, port: {host})
    monkeypatch.setattr(glpi.http.client, "HTTPConnection", Conn)
    assert glpi.request("http://[2001:db8::5]:8080", "GET", "/x", {}) == (200, {})
    assert enviado["Host"] == "[2001:db8::5]:8080"
