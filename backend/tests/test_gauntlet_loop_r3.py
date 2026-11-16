"""Gauntlet loop, rodada 3: achados do crítico de segurança e do crítico do MCP.

Links de e-mail que sobreviviam à senha nova, convite antigo, papéis do master, aviso
de passkey, e as respostas do MCP que davam erro 500 ou enganavam a IA."""
import re

import pytest

from app import db, mailer
from app.routers import auth as auth_mod
from conftest import Api, Bearer, SENHA_PADRAO, criar_chave, hist, texto, uid_de
from test_passkeys import _cadastrar


class _Agora:
    """threading.Thread que roda na hora (o envio em segundo plano vira síncrono)."""

    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@pytest.fixture
def caixa(monkeypatch):
    from app.routers import passkeys as pk_mod
    enviados = []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None, **kw: enviados.append((to, subject, text)))
    monkeypatch.setattr(auth_mod.threading, "Thread", _Agora)
    monkeypatch.setattr(pk_mod.threading, "Thread", _Agora)
    return enviados


def _token(texto_do_email, chave):
    return re.search(rf"#{chave}=([\w\-]+)", texto_do_email).group(1)


# -------------------------------------------------------------- segurança --

def test_link_de_troca_de_email_morre_com_a_senha_nova(caixa, novo_usuario):
    """Quem tinha a senha antiga pediu a troca de e-mail; a dona troca a senha: o link não vale mais."""
    u = novo_usuario("dona@example.com")
    assert u.post("/me/email", {"new_email": "intruso@example.com", "password": SENHA_PADRAO}).status_code == 200
    tok = _token(caixa[-1][2], "email")
    assert u.post("/auth/change-password", {"current_password": SENHA_PADRAO, "new_password": SENHA_PADRAO + "x"}).status_code == 200
    assert Api().post("/auth/email/confirm", {"token": tok}).status_code == 400
    assert db.query_one("SELECT email FROM users WHERE id = %s", (uid_de(u),))["email"] == "dona@example.com"


def test_convite_antigo_nao_vale_depois_de_redefinir_a_senha(admin, caixa):
    r = admin.post("/admin/users", {"email": "nova@example.com"})
    tok = r.json()["invite_url"].split("#convite=")[1]
    uid = db.query_one("SELECT id FROM users WHERE email = 'nova@example.com'")["id"]
    assert admin.post(f"/admin/users/{uid}/reset-password", {"method": "temp"}).status_code == 200
    assert Api().post("/auth/invite/accept", {"token": tok, "password": SENHA_PADRAO}).status_code == 400
    # E o e-mail corrigido pelo admin cancela o convite mandado ao endereço antigo.
    r = admin.post("/admin/users", {"email": "erado@example.com"})
    tok = r.json()["invite_url"].split("#convite=")[1]
    uid = db.query_one("SELECT id FROM users WHERE email = 'erado@example.com'")["id"]
    assert admin.put(f"/admin/users/{uid}/profile", {"email": "certo@example.com"}).status_code == 200
    assert Api().post("/auth/invite/accept", {"token": tok, "password": SENHA_PADRAO}).status_code == 400


def test_outro_admin_nao_mexe_nos_papeis_do_master(admin, novo_usuario):
    outro = novo_usuario("gestor@example.com")
    assert admin.put(f"/admin/users/{uid_de(outro)}/roles", {"roles": ["user", "admin"]}).status_code == 200
    outro.login("gestor@example.com", SENHA_PADRAO)
    r = outro.put(f"/admin/users/{uid_de(admin)}/roles", {"roles": ["admin"]})  # tirar Vê a equipe e Usuário do master
    assert r.status_code == 400, r.text
    assert set(db.query_one("SELECT array_agg(role) AS r FROM user_roles WHERE user_id = %s", (uid_de(admin),))["r"]) >= {"admin", "user", "viewer"}


def test_passkey_nova_avisa_por_email(caixa, novo_usuario):
    u = novo_usuario("dona@example.com")
    caixa.clear()
    _cadastrar(u, nome="Notebook")
    assert any(to == "dona@example.com" and "passkey" in subj.lower() and "Notebook" in txt for to, subj, txt in caixa)


def test_transferencia_fica_no_historico_de_quem_tinha_as_tarefas(admin, novo_usuario):
    sai, fica = novo_usuario("sai@example.com"), novo_usuario("fica@example.com")
    sai.post("/worklog", {"title": "Chamado aberto"})
    sid = uid_de(sai)
    assert admin.post(f"/admin/users/{sid}/block", {"transfer_to": uid_de(fica)}).status_code == 200
    linha = db.query_one("SELECT after FROM audit_log WHERE user_id = %s AND action = 'user.transfer_tasks'", (sid,))
    assert linha and linha["after"]["to"] == "fica@example.com" and linha["after"]["count"] == 1


def test_sair_apaga_o_cookie_com_os_mesmos_atributos(usuario):
    r = usuario.post("/auth/logout")
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "max-age=0" in cookie


# -------------------------------------------------------------------- MCP --

def test_mcp_cronometro_esquecido_nao_da_erro(usuario):
    ia = Bearer(criar_chave(usuario)["token"])
    t = usuario.post("/worklog", {"title": "Atendimento longo"}).json()
    assert usuario.post("/timer/start", {"task_id": t["id"]}).status_code == 200
    db.execute("UPDATE task_timers SET started_at = now() - interval '20 hours'")
    r = ia.rpc("tools/call", {"name": "stop_timer", "arguments": {}})
    assert r.status_code == 200, r.text
    assert "nada foi apontado" in texto(r.json()["result"])
    # Trocando de tarefa com outro esquecido: também sem erro.
    usuario.post("/timer/start", {"task_id": t["id"]})
    db.execute("UPDATE task_timers SET started_at = now() - interval '20 hours'")
    outra = usuario.post("/worklog", {"title": "Outra"}).json()
    r = ia.rpc("tools/call", {"name": "start_timer", "arguments": {"task_id": outra["id"]}})
    assert r.status_code == 200 and "nada foi apontado" in texto(r.json()["result"])


def test_mcp_titulos_em_branco_e_datas_absurdas_viram_erro_claro(usuario):
    ia = Bearer(criar_chave(usuario)["token"])
    usuario.post("/projects", {"name": "Obra"})
    for nome, args in (("create_objective", {"project": "Obra", "title": "   "}),
                       ("create_project", {"name": "   "}),
                       ("create_task", {"title": "x", "completed_at": "0001-01-01T00:10", "minutes": 30}),
                       ("stop_timer", {"at": "9999-12-31T23:59"})):
        r = ia.rpc("tools/call", {"name": nome, "arguments": args})
        assert r.status_code == 200 and r.json()["result"]["isError"], (nome, r.text)
    assert usuario.post("/projects", {"name": "  "}).status_code == 422
    r = ia.rpc("prompts/get", {"name": "daily", "arguments": [1]})
    assert r.status_code == 200 and r.json()["error"]["code"] == -32602


def test_mcp_ref_repetido_em_outra_tarefa_e_erro(usuario):
    ia = Bearer(criar_chave(usuario)["token"])
    a = usuario.post("/worklog", {"title": "A"}).json()["id"]
    b = usuario.post("/worklog", {"title": "B"}).json()["id"]
    assert not ia.tool("log_time", task_id=a, minutes=30, external_ref="fechar-1")["isError"]
    assert "Já apontado" in texto(ia.tool("log_time", task_id=a, minutes=30, external_ref="fechar-1"))
    r = ia.tool("log_time", task_id=b, minutes=30, external_ref="fechar-1")
    assert r["isError"] and f"#{a}" in texto(r)
    assert not ia.tool("add_note", task_id=a, text="feito", external_ref="nota-1")["isError"]
    r = ia.tool("add_note", task_id=b, text="feito", external_ref="nota-1")
    assert r["isError"] and f"#{a}" in texto(r)


def test_mcp_prefixo_de_outro_tipo_nao_vira_id(usuario):
    ia = Bearer(criar_chave(usuario)["token"])
    t = usuario.post("/worklog", {"title": "Tarefa"}).json()["id"]
    rid = usuario.post("/recurring", {"label": "Ronda"}).json()["id"]
    r = ia.tool("complete_task", task_id=f"R{t}")  # a IA quis a rotina R<n>: não conclui a tarefa de mesmo número
    assert r["isError"]
    assert usuario.get(f"/worklog/{t}").json()["status"] != "done"
    assert not ia.tool("complete_task", task_id=f"#{t}")["isError"]
    assert not ia.tool("set_recurring", recurring_id=f"R{rid}")["isError"]
    assert ia.tool("log_time", task_id=t, minutes="M30")["isError"]


def test_mcp_projeto_com_nome_de_numero_e_lista_all_paginada(usuario):
    ia = Bearer(criar_chave(usuario)["token"])
    usuario.post("/projects", {"name": "2025"})
    r = ia.tool("create_task", title="Inventário", project="2025")
    assert not r["isError"] and "{2025}" in texto(r)
    # status all: as concluídas continuam depois das abertas, página a página.
    for i in range(3):
        usuario.post("/worklog", {"title": f"feita {i}", "status": "done"})
    p1 = texto(ia.tool("list_tasks", status="all", limit=2))
    assert "Inventário" in p1 and "offset=2" in p1
    p2 = texto(ia.tool("list_tasks", status="all", limit=2, offset=2))
    assert p2.count("feita") == 2 and "Inventário" not in p2


def test_mcp_vencimento_de_colega_vai_entre_marcadores(admin, novo_usuario):
    ana, bia = novo_usuario("ana@example.com"), novo_usuario("bia@example.com")
    tid = admin.post("/admin/teams", {"name": "Infra", "member_ids": [uid_de(ana), uid_de(bia)]}).json()["id"]
    ana.post("/renewals", {"label": "Certificado do site", "expires_on": "2030-01-10", "team_id": tid})
    da_bia = texto(Bearer(criar_chave(bia)["token"]).tool("list_renewals"))
    assert "«Certificado do site»" in da_bia
    da_ana = texto(Bearer(criar_chave(ana)["token"]).tool("list_renewals"))
    assert "«" not in da_ana and "Certificado do site" in da_ana
    assert hist(ana) is not None
