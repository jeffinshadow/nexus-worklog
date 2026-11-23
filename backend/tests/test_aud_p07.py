"""Auditoria (testes-qualidade #7 e #9): defesas que existiam no código e nunca rodavam na suíte.

- webhooks.post: a conexão presa ao IP validado por check_url (defesa contra troca de DNS entre a checagem e o envio);
- notify._passes: o laço do agendador, que isola a falha de cada serviço;
- mailer.send: STARTTLS e login do SMTP nas portas 587 e 25;
- os parâmetros de produção do Argon2 (a suíte roda com um barato, trocado no conftest)."""
import asyncio
import io
import smtplib
import socket
import ssl
import types
from datetime import datetime

import pytest

from app import mailer, notify, security, webhooks
from app.config import config
from tests.conftest import PH_PRODUCAO

# ------------------------------------------------------ webhook preso ao IP validado --

IP_PUBLICO = "93.184.216.34"


class _Soquete:
    """Soquete falso: guarda o que foi enviado e responde um HTTP 204."""

    def __init__(self):
        self.enviado = b""

    def sendall(self, data):
        self.enviado += data

    def makefile(self, *a, **k):
        return io.BytesIO(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n")

    def shutdown(self, *a):
        pass

    def close(self):
        pass


@pytest.fixture
def rede(monkeypatch):
    """Troca só a rede (DNS, TCP e TLS); check_url, _Pinned e post rodam de verdade."""
    visto = types.SimpleNamespace(dns=[], tcp=[], tls=[], soquete=_Soquete(), ips={IP_PUBLICO})

    def resolve(host, port):
        visto.dns.append((host, port))
        return set(visto.ips)

    def create_connection(addr, timeout=None, *a, **k):
        visto.tcp.append(addr)
        return object()  # o soquete cru: só é entregue ao TLS

    def wrap_socket(self, sock, server_hostname=None, **k):
        visto.tls.append({"host": server_hostname, "verify": self.verify_mode, "check_hostname": self.check_hostname})
        return visto.soquete

    def sem_dns(*a, **k):
        raise AssertionError("resolveu o nome de novo: a conexão tem de usar o IP já validado")

    monkeypatch.setattr(webhooks, "resolve", resolve)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", sem_dns)
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", wrap_socket)
    return visto


def test_webhook_conecta_no_ip_validado_e_confere_o_certificado_pelo_nome(rede):
    status = webhooks.post("https://hooks.example.com:8443/entrada?x=1", {"Content-Type": "application/json"}, b'{"a":1}')
    assert status == 204
    # O nome é resolvido uma vez só (na checagem) e o TCP vai para aquele IP, não para o nome.
    assert rede.dns == [("hooks.example.com", 8443)]
    assert rede.tcp == [(IP_PUBLICO, 8443)]
    # O TLS confere o certificado pelo NOME (SNI e verificação ligados), mesmo conectando por IP.
    assert rede.tls == [{"host": "hooks.example.com", "verify": ssl.CERT_REQUIRED, "check_hostname": True}]
    pedido = rede.soquete.enviado
    assert pedido.startswith(b"POST /entrada?x=1 HTTP/1.1\r\n")
    assert b"\r\nHost: hooks.example.com:8443\r\n" in pedido and pedido.endswith(b'{"a":1}')


def test_webhook_com_varios_ips_usa_um_dos_validados(rede):
    rede.ips = {"93.184.216.35", IP_PUBLICO}
    assert webhooks.post("https://hooks.example.com/x", {}, b"{}") == 204
    assert rede.tcp == [(IP_PUBLICO, 443)]  # o menor da lista, o mesmo que check_url devolve


def test_webhook_com_um_ip_interno_na_resposta_do_dns_nao_conecta(rede):
    rede.ips = {IP_PUBLICO, "10.0.0.5"}
    with pytest.raises(webhooks.Refused):
        webhooks.post("https://hooks.example.com/x", {}, b"{}")
    assert rede.tcp == [] and rede.tls == []


def test_webhook_que_redireciona_nao_e_seguido(rede, monkeypatch):
    monkeypatch.setattr(rede.soquete, "makefile", lambda *a, **k: io.BytesIO(
        b"HTTP/1.1 302 Found\r\nLocation: https://10.0.0.5/\r\nContent-Length: 0\r\n\r\n"))
    assert webhooks.post("https://hooks.example.com/x", {}, b"{}") == 302
    assert rede.tcp == [(IP_PUBLICO, 443)]  # uma conexão só: o 3xx volta como está (conta como falha)


# ------------------------------------------------------------ laço do agendador --

class _Fim(Exception):
    """Encerra o laço infinito de _passes no fim da 1ª passada."""


SERVICOS = ("email", "push", "agenda", "fotos")


def _uma_passada(monkeypatch, quebra=None, smtp="smtp.example.com", minuto=0):
    """Roda uma passada de notify._passes; devolve os serviços chamados. `quebra`: o serviço que levanta erro."""
    from app.routers import photos
    chamados = []

    def servico(nome):
        def roda(*a, **k):
            chamados.append(nome)
            if nome == quebra:
                raise RuntimeError(f"{nome} fora do ar")
            return []
        return roda

    class _Relogio(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 23, 9, minuto, 30, tzinfo=tz)

    async def dormir(segundos):
        raise _Fim

    monkeypatch.setattr(config, "SMTP_HOST", smtp)
    monkeypatch.setattr(notify, "run_once", servico("email"))
    monkeypatch.setattr(photos, "cleanup", servico("fotos"))
    monkeypatch.setattr(notify, "datetime", _Relogio)
    monkeypatch.setattr(asyncio, "sleep", dormir)
    agenda = types.SimpleNamespace(run_once=servico("agenda"))
    push = types.SimpleNamespace(run_once=servico("push"))
    # Só _Fim pode sair do laço: erro de serviço que escapasse derrubaria o agendador inteiro.
    with pytest.raises(_Fim):
        asyncio.run(notify._passes(notify.ZoneInfo(config.APP_TZ), agenda, push))
    return chamados


@pytest.mark.parametrize("quebra", SERVICOS)
def test_agendador_um_servico_falha_e_os_outros_rodam(monkeypatch, quebra):
    """Confere 'um falha, os outros rodam na mesma passada', sem depender da ORDEM dos serviços."""
    chamados = _uma_passada(monkeypatch, quebra=quebra)
    assert sorted(chamados) == sorted(SERVICOS), f"com {quebra} em erro rodaram só {chamados}"


def test_agendador_sem_smtp_nao_tenta_email_e_faxina_so_na_hora_cheia(monkeypatch):
    assert sorted(_uma_passada(monkeypatch, smtp="")) == ["agenda", "fotos", "push"]
    assert sorted(_uma_passada(monkeypatch, minuto=17)) == ["agenda", "email", "push"]


# ----------------------------------------------------------------- SMTP falso --

class _Smtp:
    """smtplib.SMTP falso: registra, na ordem, o que o mailer fez com a conexão."""
    passos = []
    erro_no_login = None

    def __init__(self, host, port, timeout=None, context=None):
        type(self).passos.append((type(self).__name__, host, port, context is not None))

    def starttls(self, context=None):
        self.passos.append(("starttls", context.verify_mode, context.check_hostname))

    def login(self, user, password):
        self.passos.append(("login", user, password))
        if self.erro_no_login:
            raise self.erro_no_login

    def send_message(self, msg):
        self.passos.append(("envio", msg["To"], msg["Subject"]))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.passos.append(("fim",))


class _SmtpSsl(_Smtp):
    pass


@pytest.fixture
def smtp(monkeypatch):
    _Smtp.passos, _Smtp.erro_no_login = [], None
    monkeypatch.setattr(smtplib, "SMTP", _Smtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _SmtpSsl)
    monkeypatch.setattr(mailer, "last", {"ok_at": None, "error_at": None, "error": None})
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(config, "SMTP_USER", "nexus")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "segredo-do-smtp")
    monkeypatch.setattr(config, "MAIL_FROM", "Nexus <nexus@example.com>")

    def porta(n):
        monkeypatch.setattr(config, "SMTP_PORT", n)
        return _Smtp.passos
    return porta


def test_smtp_587_sobe_tls_conferindo_o_certificado_antes_do_login(smtp):
    passos = smtp(587)
    mailer.send("ana@example.com", "Assunto", "texto")
    assert passos == [("_Smtp", "smtp.example.com", 587, False), ("starttls", ssl.CERT_REQUIRED, True),
                      ("login", "nexus", "segredo-do-smtp"), ("envio", "ana@example.com", "Assunto"), ("fim",)]
    assert mailer.last["ok_at"] and not mailer.last["error"]


def test_smtp_25_envia_sem_tls_e_sem_usuario_nao_faz_login(smtp, monkeypatch):
    passos = smtp(25)
    monkeypatch.setattr(config, "SMTP_USER", "")
    mailer.send("ana@example.com", "Assunto", "texto", html="<p>texto</p>", cc="chefe@example.com")
    assert passos == [("_Smtp", "smtp.example.com", 25, False), ("envio", "ana@example.com", "Assunto"), ("fim",)]


def test_smtp_465_usa_tls_direto(smtp):
    passos = smtp(465)
    mailer.send("ana@example.com", "Assunto", "texto")
    assert passos[0] == ("_SmtpSsl", "smtp.example.com", 465, True) and ("starttls",) not in [p[:1] for p in passos]
    assert ("login", "nexus", "segredo-do-smtp") in passos


def test_smtp_falha_vira_mailerror_curto_e_fica_na_saude(smtp):
    passos = smtp(587)
    _Smtp.erro_no_login = smtplib.SMTPAuthenticationError(535, b"credenciais recusadas")
    with pytest.raises(mailer.MailError) as e:
        mailer.send("ana@example.com", "Assunto", "texto")
    assert "SMTPAuthenticationError" in str(e.value) and "segredo-do-smtp" not in str(e.value)
    assert ("envio", "ana@example.com", "Assunto") not in passos
    assert mailer.last["error"] == str(e.value) and mailer.last["error_at"] and mailer.last["ok_at"] is None


# ------------------------------------------------- Argon2: parâmetros de produção --

def test_argon2_de_producao_segue_o_minimo_recomendado():
    """O conftest troca security._ph por um barato; o ORIGINAL (o de produção) fica em PH_PRODUCAO.
    19 MiB, 2 passadas, 1 thread: o mínimo do OWASP para Argon2id. Baixar isso tem de ser decisão à vista."""
    assert security._ph is not PH_PRODUCAO  # a suíte roda mesmo com o barato
    assert (PH_PRODUCAO.time_cost, PH_PRODUCAO.memory_cost, PH_PRODUCAO.parallelism) == (2, 19456, 1)
    h = PH_PRODUCAO.hash("Senha-Do-Usuario-1")
    assert h.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    # Hash de produção continua sendo aceito pelo verificador (os parâmetros vêm no próprio hash).
    assert security.verify_password(h, "Senha-Do-Usuario-1") and not security.verify_password(h, "outra")
