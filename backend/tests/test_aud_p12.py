"""Auditoria, pacote p12: agendador (ordem das passadas, nova tentativa do e-mail,
faxina de hora em hora), assunto de e-mail numa linha, pedido de convite (texto
fixo aos admins, decisão e conta na mesma transação), Saúde (versão e última
passada) e ordem alfabética sem jogar os acentos para o fim."""
import asyncio
import smtplib
import threading
from datetime import datetime, timedelta

from app import db, mailer, notify, push, security
from app.config import config
from app.version import VERSION
import pytest

from conftest import ADMIN_EMAIL, ADMIN_PW, SENHA_PADRAO, Api, dia_hoje, ligar_pedido_convite, uid_de

_Thread = threading.Thread  # a de verdade: a fixture `pedidos` troca threading.Thread pela que roda na hora


def _proxima_segunda(d):
    return d + timedelta(days=(0 - d.weekday()) % 7 or 7)


class _Smtp:
    """smtplib.SMTP de mentira: aceita a conexão; `falha` é levantada no send_message."""
    falha = None
    enviados: list = []

    def __init__(self, *a, **k):
        self.sock = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def send_message(self, msg):
        if type(self).falha:
            raise type(self).falha
        type(self).enviados.append(msg)


@pytest.fixture
def smtp_falso(monkeypatch):
    _Smtp.falha, _Smtp.enviados = None, []
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.teste.invalid")
    monkeypatch.setattr(config, "SMTP_PORT", 1025)
    monkeypatch.setattr(config, "SMTP_USER", "")
    monkeypatch.setattr(mailer.smtplib, "SMTP", _Smtp)
    return _Smtp


def _aviso_da_manha(usuario):
    segunda = _proxima_segunda(dia_hoje(usuario))
    usuario.post("/worklog", {"title": "Prazo de segunda", "due_date": segunda.isoformat()})
    usuario.c.put("/api/notifications", json={"morning": True, "morning_hour": 8}, headers=usuario._h())
    return lambda h, m=0: datetime(segunda.year, segunda.month, segunda.day, h, m)


def _reservas(uid):
    return db.query_all("SELECT kind, ok, error FROM notification_log WHERE user_id = %s AND kind = 'morning'", (uid,))


# ------------------------------------------------------------- agendador --

def test_passada_manda_push_e_agenda_antes_do_email(monkeypatch):
    ordem = []
    dub = lambda nome: type("D", (), {"run_once": staticmethod(lambda now: ordem.append(nome))})
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.teste.invalid")
    monkeypatch.setattr(notify, "run_once", lambda now: ordem.append("email"))
    monkeypatch.setattr(notify, "faxina", lambda: ordem.append("faxina"))
    antes = datetime.now().astimezone()
    asyncio.run(notify._pass(datetime(2026, 11, 23, 8, 1), dub("agenda"), dub("push")))
    assert ordem == ["push", "agenda", "email"]          # a faxina é só na hora cheia
    assert notify.last_pass and notify.last_pass >= antes  # a Saúde lê daqui

    ordem.clear()
    monkeypatch.setattr(config, "SMTP_HOST", "")           # sem SMTP: sem e-mail, mas a faxina roda
    asyncio.run(notify._pass(datetime(2026, 11, 23, 9, 0), dub("agenda"), dub("push")))
    assert ordem == ["push", "agenda", "faxina"]


def test_smtp_que_recusa_a_conexao_tenta_de_novo_na_proxima_passada(monkeypatch, usuario):
    uid, em = uid_de(usuario), _aviso_da_manha(usuario)
    monkeypatch.setattr(config, "SMTP_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "SMTP_PORT", 1)            # ninguém escuta: conexão recusada
    monkeypatch.setattr(config, "SMTP_USER", "")
    assert (uid, "morning", "retry") in notify.run_once(em(8, 1))
    assert _reservas(uid) == []                            # a reserva saiu
    assert "falha no envio" in mailer.last["error"]        # e o erro aparece na Saúde

    _Smtp.falha, _Smtp.enviados = None, []
    monkeypatch.setattr(mailer.smtplib, "SMTP", _Smtp)     # o SMTP voltou
    assert (uid, "morning", "sent") in notify.run_once(em(8, 2))
    assert len(_Smtp.enviados) == 1 and _Smtp.enviados[0]["To"] == usuario.me["email"]
    assert notify.run_once(em(8, 3)) == [] and len(_Smtp.enviados) == 1   # não repete


def test_smtp_que_aceita_e_depois_falha_nao_reenvia(usuario, smtp_falso):
    uid, em = uid_de(usuario), _aviso_da_manha(usuario)
    smtp_falso.falha = smtplib.SMTPServerDisconnected("caiu no meio da entrega")
    assert (uid, "morning", "error") in notify.run_once(em(8, 1))
    r = _reservas(uid)
    assert len(r) == 1 and r[0]["ok"] is False and "falha no envio" in r[0]["error"]
    smtp_falso.falha = None
    assert notify.run_once(em(8, 2)) == [] and smtp_falso.enviados == []   # pode ter saído: não manda de novo


def test_mailer_distingue_o_que_nao_saiu(monkeypatch, smtp_falso):
    smtp_falso.falha = smtplib.SMTPDataError(451, b"tente mais tarde")
    with pytest.raises(mailer.MailError) as e:
        mailer.send("a@example.com", "Oi", "texto")
    assert not isinstance(e.value, mailer.MailNotSent)

    def recusa(*a, **k):
        assert k["timeout"] == 5                           # conexão: 5 s, não 20
        raise ConnectionRefusedError("recusada")
    monkeypatch.setattr(mailer.smtplib, "SMTP", recusa)
    with pytest.raises(mailer.MailNotSent):
        mailer.send("a@example.com", "Oi", "texto")

    class SenhaErrada(_Smtp):                              # senha recusada não passa sozinha: sem nova tentativa
        def login(self, *a):
            raise smtplib.SMTPAuthenticationError(535, b"senha incorreta")
    monkeypatch.setattr(mailer.smtplib, "SMTP", SenhaErrada)
    monkeypatch.setattr(config, "SMTP_USER", "nexus")
    with pytest.raises(mailer.MailError) as e:
        mailer.send("a@example.com", "Oi", "texto")
    assert not isinstance(e.value, mailer.MailNotSent)


def test_assunto_com_quebra_de_linha_vira_uma_linha(smtp_falso):
    mailer.send("a@example.com", "Tarefa atribuída:\nlinha dois\r\n  e três", "texto")
    assert smtp_falso.enviados[0]["Subject"] == "Tarefa atribuída: linha dois e três"


def test_faxina_do_agendador_sem_login_nenhum(monkeypatch, usuario):
    uid = uid_de(usuario)
    db.execute("""INSERT INTO audit_log (user_id, actor, action, entity, created_at)
                  VALUES (%s, 'web', 'worklog.create', 'worklog', now() - interval '200 days'),
                         (%s, 'web', 'worklog.create', 'worklog', now() - interval '100 days')""", (uid, uid))
    db.execute("INSERT INTO sessions (user_id, token_hash, csrf_token, expires_at) VALUES (%s, 'velha', 'x', now() - interval '1 hour')", (uid,))
    db.execute("""INSERT INTO auth_links (user_id, kind, token_hash, expires_at, used_at, created_at)
                  VALUES (%s, 'reset', 'usado', now() - interval '30 days', now() - interval '31 days', now() - interval '31 days'),
                         (%s, 'reset', 'novo', now() + interval '1 hour', NULL, now())""", (uid, uid))
    db.execute("""INSERT INTO notification_log (user_id, kind, ref_date, sent_at, ok)
                  VALUES (%s, 'morning', current_date - 31, now() - interval '31 days', true),
                         (%s, 'morning', current_date - 5, now() - interval '5 days', true)""", (uid, uid))
    db.execute("""INSERT INTO invite_requests (name, email, source, reason, status, decided_at, created_at)
                  VALUES ('Velho', 'velho@example.com', 'outro', 'motivo', 'declined', now() - interval '31 days', now() - interval '40 days')""")
    sessoes = db.query_one("SELECT count(*)::int AS n FROM sessions")["n"]

    monkeypatch.setattr(config, "SMTP_HOST", "")           # roda mesmo sem e-mail configurado
    nada = type("D", (), {"run_once": staticmethod(lambda now: None)})
    asyncio.run(notify._pass(datetime(2026, 11, 23, 3, 0), nada, nada))

    idade = db.query_all("SELECT (now() - created_at) > interval '180 days' AS velha FROM audit_log WHERE user_id = %s AND action = 'worklog.create'", (uid,))
    assert [r["velha"] for r in idade] == [False]
    assert db.query_one("SELECT count(*)::int AS n FROM sessions")["n"] == sessoes - 1
    assert [r["token_hash"] for r in db.query_all("SELECT token_hash FROM auth_links WHERE user_id = %s", (uid,))] == ["novo"]
    assert db.query_one("SELECT count(*)::int AS n FROM notification_log WHERE user_id = %s", (uid,))["n"] == 1
    assert not db.query_one("SELECT 1 FROM invite_requests WHERE email = 'velho@example.com'")
    assert usuario.get("/board").status_code == 200        # a sessão viva segue valendo


def test_login_so_faz_faxina_sem_o_agendador(monkeypatch, usuario):
    uid = uid_de(usuario)
    velha = lambda: db.execute("INSERT INTO sessions (user_id, token_hash, csrf_token, expires_at) VALUES (%s, 'velha', 'x', now() - interval '1 hour')", (uid,))
    tem = lambda: bool(db.query_one("SELECT 1 FROM sessions WHERE token_hash = 'velha'"))
    velha()
    monkeypatch.setattr(config, "MAIL_SCHEDULER", True)
    usuario.login(usuario.me["email"], SENHA_PADRAO)
    assert tem()                                           # com o agendador, o login não varre o banco
    monkeypatch.setattr(config, "MAIL_SCHEDULER", False)
    usuario.login(usuario.me["email"], SENHA_PADRAO)
    assert not tem()


# ------------------------------------------------------ pedido de convite --

@pytest.fixture
def pedidos(monkeypatch):
    """Pedido de convite ligado, e-mail 'configurado' e o envio em segundo plano na hora."""
    import app.routers.invite_requests as ir
    ligar_pedido_convite()
    emails, pushes = [], []
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", lambda to, subj, text, html=None, **k: emails.append((to, subj, text, html or "")))
    monkeypatch.setattr(push, "send", lambda uid, msg, **k: pushes.append(msg) or 1)
    monkeypatch.setattr(ir.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda self: target()})())
    return emails, pushes


def _pedir(email, **kw):
    r = Api().post("/auth/invite-request", {"name": "Ana Souza", "email": email, "source": "colega",
                                            "reason": "Quero registrar o suporte da filial.", **kw})
    assert r.status_code == 202, r.text


def test_pedido_de_convite_nao_leva_texto_de_anonimo_aos_admins(pedidos, admin):
    emails, pushes = pedidos
    _pedir("isca@example.org", name="URGENTE: sua conta vence hoje",
           source_note="veja https://golpe.example/nota",
           reason="Confirme a sua senha em https://golpe.example/entrar ainda hoje.")
    aos_admins = [e for e in emails if e[0] == ADMIN_EMAIL]
    assert len(aos_admins) == 1 and aos_admins[0][1] == "Pedido de convite"
    tudo = " ".join(aos_admins[0][1:]) + " ".join(f"{p['title']} {p['body']}" for p in pushes)
    for texto in ("URGENTE", "vence hoje", "golpe.example", "Confirme a sua senha"):
        assert texto not in tudo
    assert "isca@example.org" in aos_admins[0][2] and "Chegou um pedido de convite. Veja em Admin." in aos_admins[0][2]
    assert pushes and pushes[0]["body"] == "Chegou um pedido de convite. Veja em Admin."
    # nome e motivo continuam no app, para o admin decidir
    p = admin.get("/admin/invite-requests").json()[0]
    assert p["name"] == "URGENTE: sua conta vence hoje" and "golpe.example" in p["reason"]


def test_convidar_com_conta_que_ja_existe_desfaz_a_decisao(pedidos, admin):
    _pedir("ana@empresa.com.br")
    rid = admin.get("/admin/invite-requests").json()[0]["id"]
    assert admin.post("/admin/users", {"email": "ana@empresa.com.br"}).status_code == 201   # convidada por fora
    assert admin.post(f"/admin/invite-requests/{rid}/invite").status_code == 409
    assert db.query_one("SELECT status, decided_at FROM invite_requests WHERE id = %s", (rid,)) == {"status": "pending", "decided_at": None}
    assert not db.query_one("SELECT 1 FROM audit_log WHERE action = 'invite_request.invited'")
    assert admin.post(f"/admin/invite-requests/{rid}/decline").status_code == 200           # ainda dá para recusar


def test_dois_admins_no_mesmo_pedido_terminam_coerentes(pedidos, admin):
    outro = Api()
    outro.login(ADMIN_EMAIL, ADMIN_PW)
    for i in range(6):
        email = f"corrida{i}@example.org"
        security.invite_req_limiter._hits.clear()            # o limite por IP (5 por 15 min) não é o assunto aqui
        _pedir(email)
        rid = db.query_one("SELECT id FROM invite_requests WHERE email = %s", (email,))["id"]
        largada, res = threading.Barrier(2), {}

        def ir(quem, api, acao):
            largada.wait()
            res[quem] = api.post(f"/admin/invite-requests/{rid}/{acao}").status_code
        ts = [_Thread(target=ir, args=("convida", admin, "invite")), _Thread(target=ir, args=("recusa", outro, "decline"))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        status = db.query_one("SELECT status FROM invite_requests WHERE id = %s", (rid,))["status"]
        conta = bool(db.query_one("SELECT 1 FROM users WHERE email = %s", (email,)))
        assert sorted(res.values()) == [200, 404], res       # só uma decisão vale
        assert (status, conta) in {("invited", True), ("declined", False)}, (res, status, conta)
        assert (res["convida"] == 200) == conta


# ------------------------------------------------------------------ Saúde --

def test_saude_tem_versao_e_ultima_passada(monkeypatch, admin):
    monkeypatch.setattr(notify, "last_pass", None)
    s = admin.get("/admin/health").json()
    assert s["version"]["number"] == VERSION and s["scheduler_last_pass"] is None
    nada = type("D", (), {"run_once": staticmethod(lambda now: None)})
    monkeypatch.setattr(config, "SMTP_HOST", "")
    asyncio.run(notify._pass(datetime(2026, 11, 23, 8, 1), nada, nada))
    s = admin.get("/admin/health").json()
    assert s["scheduler_last_pass"] and s["scheduler_last_pass"] <= s["now"]


# ------------------------------------------------------ ordem com acentos --

def test_ordem_alfabetica_nao_poe_acento_no_fim(admin, usuario):
    for nome in ("Zeladoria", "almoxarifado", "Água"):
        assert usuario.post("/projects", {"name": nome}).status_code == 201
    nomes = [p["name"] for p in usuario.get("/projects").json() if p["name"] in ("Zeladoria", "almoxarifado", "Água")]
    assert nomes == ["Água", "almoxarifado", "Zeladoria"]
    for nome in ("Zona Sul", "ativos", "Área técnica"):
        assert admin.post("/admin/teams", {"name": nome}).status_code in (200, 201)
    equipes = [t["name"] for t in admin.get("/admin/teams").json()]
    assert equipes == ["Área técnica", "ativos", "Zona Sul"]


def test_codigo_morto_saiu():
    from app import services, teams
    from app.routers import packs
    assert not hasattr(teams, "is_member") and not hasattr(services, "task_retro_days")
    assert not hasattr(packs, "TER") and not hasattr(packs, "QUA")
    assert Api().get("/auth/options").status_code == 200
