import os


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Variavel de ambiente obrigatoria ausente: {name}")
    return value


class Config:
    DATABASE_URL = _required("DATABASE_URL")
    SECRET_KEY = _required("SECRET_KEY")

    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL")
    ADMIN_INITIAL_PASSWORD = os.environ.get("ADMIN_INITIAL_PASSWORD")

    SESSION_TTL_DAYS = int(os.environ.get("SESSION_TTL_DAYS", "7"))
    COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
    # Cadastro publico. Padrao: fechado (contas criadas pelo admin, por convite).
    REGISTRATION_OPEN = os.environ.get("REGISTRATION_OPEN", "false").lower() == "true"
    APP_TZ = os.environ.get("APP_TZ", "America/Sao_Paulo")

    SESSION_COOKIE = "session"
    MIN_PASSWORD_LEN = 10
    MAX_PASSWORD_LEN = 128


config = Config()
