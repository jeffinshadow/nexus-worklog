import hashlib
import hmac
import math
import secrets
import threading
from contextlib import contextmanager
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from . import db
from .config import config

# Perfil OWASP (19 MiB, 2 passadas): seguro e cabível numa VM de 1 GB. O
# semáforo limita a 2 hashes simultâneos — sem ele, 10 logins ao mesmo tempo
# pediriam centenas de MB. Hashes antigos (64 MiB) migram no próximo login
# (needs_rehash).
_ph = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
_hash_slots = threading.BoundedSemaphore(2)


class Busy(Exception):
    """Sem vaga para calcular hash agora (servidor sob carga)."""


@contextmanager
def _slot():
    # Espera no máximo 1 s: sob ataque, falha rápido (503) em vez de prender
    # as threads do servidor esperando a vez.
    if not _hash_slots.acquire(timeout=1):
        raise Busy()
    try:
        yield
    finally:
        _hash_slots.release()


def hash_password(password: str) -> str:
    with _slot():
        return _ph.hash(password)


# Hash de uma senha aleatoria, usado quando o e-mail nao existe: o login gasta
# o mesmo tempo (um Argon2 completo) com ou sem conta, e o tempo de resposta
# deixa de revelar quais e-mails estao cadastrados.
_DUMMY_HASH = _ph.hash(secrets.token_urlsafe(32))


def burn_password_check(password: str) -> None:
    verify_password(_DUMMY_HASH, password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        with _slot():
            _ph.verify(stored_hash, password)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _ph.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True


def new_token() -> str:
    return secrets.token_urlsafe(32)


# Chave de API pessoal: "nxs_" + 43 caracteres. O prefixo deixa a chave
# reconhecível (e fácil de achar se vazar num repositório).
API_TOKEN_PREFIX = "nxs_"


def new_api_token() -> tuple[str, str]:
    """Devolve (chave completa, trecho de exibição). Só o HMAC vai ao banco."""
    raw = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[: len(API_TOKEN_PREFIX) + 6]


# Alfabeto sem caracteres ambiguos (0/O/1/I/l) para uma senha temporaria que o
# admin repassa e o usuario digita. 12 chars * ~31 simbolos = ~59 bits: forte o
# suficiente para uma senha de uso unico (o usuario troca no proximo login).
_TEMP_PW_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"


def generate_temp_password(length: int = 12) -> str:
    return "".join(secrets.choice(_TEMP_PW_ALPHABET) for _ in range(length))


def token_hash(token: str) -> str:
    # HMAC-SHA256 com SECRET_KEY como pepper (o token vive em claro no cookie).
    return hmac.new(
        config.SECRET_KEY.encode(), token.encode(), hashlib.sha256
    ).hexdigest()


class RateLimiter:
    """Janela fixa em memoria. Backend roda em um unico worker."""

    _PRUNE_AT = 10_000  # chaves guardadas antes de varrer as janelas vencidas

    def __init__(self, max_hits: int, window_seconds: int):
        self.max = max_hits
        self.window = window_seconds
        self._hits: dict[str, tuple[float, int]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        if len(self._hits) >= self._PRUNE_AT:
            self._hits = {
                k: v for k, v in self._hits.items() if now - v[0] < self.window
            }
            if len(self._hits) >= self._PRUNE_AT:
                # Cheio de chaves vivas (ataque): ficam as que já estouraram (o bloqueio continua
                # valendo) e a de quem chama; as demais saem. Recusar as chaves novas, como antes,
                # deixava 10 mil pedidos trancarem o login de todo mundo por uma janela inteira.
                self._hits = {k: v for k, v in self._hits.items() if v[1] >= self.max or k == key}
        start, count = self._hits.get(key, (now, 0))
        if now - start >= self.window:
            start, count = now, 0
        count += 1
        self._hits[key] = (start, count)
        return count <= self.max

    def blocked(self, key: str) -> bool:
        """Já estourou a janela? (consulta sem contar)"""
        return self.retry_after(key) > 0

    def retry_after(self, key: str) -> int:
        """Segundos até a chave voltar a passar (0 se não está bloqueada)."""
        start, count = self._hits.get(key, (0.0, 0))
        left = self.window - (time.monotonic() - start)
        return math.ceil(left) if left > 0 and count >= self.max else 0


# Login: ate 10 FALHAS por IP a cada 5 minutos (entrar certo nao gasta: um
# escritorio atras de um IP so nao se tranca). Falhas contam tambem por
# e-mail+IP (quem erra e bloqueado, nao a dona da conta) e, com teto bem maior,
# por e-mail (freia tentativa distribuida sem trancar a pessoa por 10 erros).
login_limiter = RateLimiter(max_hits=10, window_seconds=300)
# Abrir a tela de login pede o desafio da passkey: limite próprio e folgado,
# fora da conta das tentativas de entrar.
passkey_options_limiter = RateLimiter(max_hits=60, window_seconds=300)
# Links de convite/troca de senha: limite próprio (escritório atrás de um IP só não
# trava o convite de quem chega por causa do login de outros).
link_limiter = RateLimiter(max_hits=30, window_seconds=300)
login_email_limiter = RateLimiter(max_hits=100, window_seconds=300)
# "Esqueci a senha": poucos pedidos por IP e por e-mail (não vira canal de spam).
reset_limiter = RateLimiter(max_hits=5, window_seconds=900)
reset_email_limiter = RateLimiter(max_hits=3, window_seconds=3600)
# Pedido de convite (público): poucos por IP e por e-mail.
invite_req_limiter = RateLimiter(max_hits=5, window_seconds=3600)
invite_req_email_limiter = RateLimiter(max_hits=2, window_seconds=86400)
# PDF: gerar e pesado (CPU, um processo so). Ate 6 por usuario por minuto.
pdf_limiter = RateLimiter(max_hits=6, window_seconds=60)
# Testar webhook: cada teste é um POST para fora (até 15 s); 5 por minuto por pessoa.
webhook_test_limiter = RateLimiter(max_hits=5, window_seconds=60)
# Erros do navegador mandados ao log: poucos por pessoa (não vira canal de spam no log).
client_error_limiter = RateLimiter(max_hits=10, window_seconds=300)

# Chaves de API: ate 240 requisicoes por pessoa por minuto (IA em laço).
token_limiter = RateLimiter(max_hits=240, window_seconds=60)


def revoke_access(user_id: int) -> None:
    """Corta o que nao depende da senha: chaves de API, link do calendario e as
    notificacoes nos aparelhos.
    Usado na troca de senha e no reset pelo admin ("senha nova = acessos novos")."""
    db.execute("UPDATE api_tokens SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL", (user_id,))
    # Links de e-mail ainda abertos (confirmar e-mail novo, nova senha, convite): quem tinha a senha
    # antiga podia ter pedido a troca de e-mail e, depois da senha trocada, confirmar o link e ficar
    # com a conta. Quem chama emite o link novo, se for o caso, DEPOIS daqui.
    db.execute("""UPDATE auth_links SET used_at = now()
                   WHERE user_id = %s AND kind IN ('email', 'reset', 'invite') AND used_at IS NULL""", (user_id,))
    db.execute("DELETE FROM calendar_feeds WHERE user_id = %s", (user_id,))
    db.execute("DELETE FROM push_subscriptions WHERE user_id = %s", (user_id,))  # aparelho talvez perdido
    # Webhook é um canal de saída dos dados: desliga (aparece na lista; religar é um clique).
    db.execute("""UPDATE webhooks SET disabled_at = now(), last_error = 'desligado na troca de senha'
                   WHERE user_id = %s AND disabled_at IS NULL""", (user_id,))


WEAK_PASSWORD = "Essa senha é fácil de adivinhar."


def weak_password(password: str, email: str = "") -> bool:
    """Senha trivial: igual ao e-mail da conta, um caractere só repetido, só
    dígitos em sequência ou repetição óbvia (1234567890, 0000000000, 1212121212)
    ou só "nexus" repetido. Sem lista de senhas comuns (decisão do dono)."""
    p = password.strip().lower()
    if not p or (email and p == email.strip().lower()) or len(set(p)) == 1:
        return True
    if p.replace("nexus", "") == "":
        return True
    if p.isascii() and p.isdigit():
        steps = {(int(b) - int(a)) % 10 for a, b in zip(p, p[1:])}
        if steps in ({1}, {9}):  # 1234567890..., 9876543210...
            return True
        if any(p == (p[:n] * len(p))[:len(p)] for n in (2, 3)):  # 1212121212, 123123123123
            return True
    return False
