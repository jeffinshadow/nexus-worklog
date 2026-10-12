import os


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Variavel de ambiente obrigatoria ausente: {name}")
    return value


class Config:
    DATABASE_URL = _required("DATABASE_URL")
    SECRET_KEY = _required("SECRET_KEY")
    if len(SECRET_KEY) < 32:  # pepper dos HMAC de sessão, chaves e calendário
        raise RuntimeError("SECRET_KEY curta demais: use 32+ caracteres aleatórios")

    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL")
    ADMIN_INITIAL_PASSWORD = os.environ.get("ADMIN_INITIAL_PASSWORD")

    SESSION_TTL_DAYS = int(os.environ.get("SESSION_TTL_DAYS", "7"))
    COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
    # Cadastro publico. Padrao: fechado (contas criadas pelo admin, por convite).
    REGISTRATION_OPEN = os.environ.get("REGISTRATION_OPEN", "false").lower() == "true"
    APP_TZ = os.environ.get("APP_TZ", "America/Sao_Paulo")

    # E-mail (avisos). Sem SMTP_HOST, os avisos ficam desligados no servidor.
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    # 465 = TLS direto; 587 = STARTTLS; outra porta (ex.: 1025 do Mailpit) = sem TLS.
    MAIL_FROM = os.environ.get("MAIL_FROM", "Nexus Worklog <nexus@localhost>")
    APP_URL = os.environ.get("APP_URL", "https://nexus.shadow.tec.br").rstrip("/")
    # O agendador roda só se houver SMTP e não estiver desligado (testes).
    MAIL_SCHEDULER = os.environ.get("MAIL_SCHEDULER", "true").lower() == "true"

    SESSION_COOKIE = "session"
    MIN_PASSWORD_LEN = 10
    MAX_PASSWORD_LEN = 128


config = Config()
