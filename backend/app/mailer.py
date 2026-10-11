"""Envio de e-mail por SMTP (biblioteca padrão; sem SDK de terceiros).

Resend em produção (smtp.resend.com:465, TLS direto). Sem rastreamento: o
e-mail é texto + HTML simples, sem imagens remotas nem links redirecionados.
"""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

from .config import config


class MailError(Exception):
    pass


def configured() -> bool:
    return bool(config.SMTP_HOST)


def send(to: str, subject: str, text: str, html: str | None = None) -> None:
    if not configured():
        raise MailError("e-mail não configurado no servidor (SMTP_HOST)")
    msg = EmailMessage()
    msg["From"] = config.MAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    domain = parseaddr(config.MAIL_FROM)[1].rpartition("@")[2] or "localhost"
    msg["Message-ID"] = make_msgid(domain=domain)
    # Aviso automático: sem resposta automática de férias de volta.
    msg["Auto-Submitted"] = "auto-generated"
    msg["X-Auto-Response-Suppress"] = "All"
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        if config.SMTP_PORT == 465:
            smtp = smtplib.SMTP_SSL(config.SMTP_HOST, 465, timeout=20, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20)
            if config.SMTP_PORT == 587:
                smtp.starttls(context=ssl.create_default_context())
        with smtp:
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        # Mensagem curta para o usuário/log; nunca inclui a senha.
        raise MailError(f"falha no envio: {type(e).__name__}: {str(e)[:160]}") from e
