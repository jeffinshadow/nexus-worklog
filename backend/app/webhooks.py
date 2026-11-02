"""Webhooks de saída: o Nexus avisa outro sistema quando algo muda.

Cada webhook lê o histórico da pessoa (audit_log) a partir do último evento
entregue e manda um POST por evento, em ordem, assinado com HMAC-SHA256
(X-Nexus-Signature: t=<unix>,v1=<hex>). Roda no agendador (notify.scheduler),
uma passada por minuto. Falha → tenta de novo em 1, 5, 30 min, 2 h e 12 h;
5 falhas seguidas desligam o webhook (aparece na listagem). O botão "Testar"
(ping) manda um evento de teste na hora, sem mexer na fila nem nas falhas.

O segredo não vai ao banco: é derivado do SECRET_KEY com um sal aleatório
(o vazamento só do banco não permite forjar assinaturas).
"""
import base64
import hashlib
import hmac
import http.client
import ipaddress
import json
import logging
import secrets
import re
import socket
import ssl
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from . import audit, db
from .config import config

log = logging.getLogger("uvicorn.error")

MAX_PER_USER = 5
TIMEOUT = 5  # segundos, por conexão/leitura
DEADLINE = 15  # segundos, o envio inteiro (destino que responde aos pinguinhos não prende a fila)
BACKOFF_MIN = (1, 5, 30, 120, 720)  # espera depois da 1ª, 2ª... falha seguida
MAX_FAILURES = 5
BATCH = 20  # eventos por webhook em cada passada
LAG_SECONDS = 2  # como o feed: gravações simultâneas podem terminar fora de ordem
# Entidades cujo estado (o "depois" do histórico) vai no corpo; o resto vai só
# com o evento. Fotos nunca vão (o corpo leva no máximo quantas há).
DATA_ENTITIES = {"worklog", "note", "checklist", "time", "recurring", "project", "objective", "renewal",
                 "agenda"}  # agenda: followup.due, recurring.due, renewal.warning (app/agenda.py)


class Refused(ValueError):
    """Endereço recusado (não https, interno, sem DNS...)."""


# ------------------------------------------------------------------ segredo --

def new_salt() -> str:
    return secrets.token_urlsafe(16)


def secret_for(salt: str) -> str:
    raw = hmac.new(config.SECRET_KEY.encode(), f"webhook:{salt}".encode(), hashlib.sha256).digest()
    return "whsec_" + base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def signature(secret: str, t: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


# --------------------------------------------------------------------- SSRF --

def _ip_ok(raw: str) -> bool:
    ip = ipaddress.ip_address(raw.split("%")[0])
    if ip.version == 6 and ip.ipv4_mapped:  # ::ffff:127.0.0.1
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def resolve(host: str, port: int) -> set[str]:
    return {ai[4][0] for ai in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}


def check_url(url: str) -> tuple[str, int, str, str]:
    """Valida e resolve: (host, porta, caminho, IP). Recusa o que não for https
    público — resolve o DNS e todo endereço precisa ser global (nada de rede
    interna, loopback, link-local ou reservado). A conexão usa esse mesmo IP
    (o DNS não troca de endereço entre a checagem e o envio)."""
    if re.search(r"[\x00-\x20\x7f]|%0[0-9a-f]|%1[0-9a-f]|%7f", url.strip(), re.I):  # controle, cru ou codificado
        raise Refused("o endereço tem caracteres inválidos")
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or not parts.hostname:
        raise Refused("use um endereço https://")
    if parts.username or parts.password:
        raise Refused("sem usuário e senha no endereço; use um segredo no caminho ou confira a assinatura")
    try:
        port = parts.port or 443
    except ValueError:
        raise Refused("porta inválida") from None
    try:
        ips = resolve(parts.hostname, port)
    except (OSError, UnicodeError):
        raise Refused("endereço não encontrado (DNS)") from None
    if not ips or not all(_ip_ok(ip) for ip in ips):
        raise Refused("endereço de rede interna ou reservado não é aceito")
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return parts.hostname, port, path, sorted(ips)[0]


class _Pinned(http.client.HTTPSConnection):
    """HTTPS para o IP já checado, com o certificado conferido pelo nome."""

    def __init__(self, host: str, port: int, ip: str):
        super().__init__(host, port, timeout=TIMEOUT, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def post(url: str, headers: dict, body: bytes) -> int:
    """Um POST, sem seguir redirecionamento (3xx conta como falha)."""
    host, port, path, ip = check_url(url)
    conn = _Pinned(host, port, ip)

    def cut():  # prazo total: o timeout do socket vale por operação; isto corta o envio inteiro
        try:
            if conn.sock:
                conn.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    timer = threading.Timer(DEADLINE, cut)
    timer.start()
    try:
        conn.request("POST", path, body=body, headers=headers)
        res = conn.getresponse()
        res.read(4096)  # a resposta não interessa; só não deixa a conexão pendurada
        return res.status
    finally:
        timer.cancel()
        conn.close()


# ------------------------------------------------------------------ entrega --

def matches(events: list[str], action: str, entity: str = "") -> bool:
    """["*"], a ação exata ("worklog.finish") ou o grupo ("worklog.*"). Desfazer
    ("undo") entra no grupo da entidade desfeita: quem ouve tarefas fica sabendo."""
    group = entity + "." if action == "undo" else action
    return any(e == "*" or e == action or (e.endswith(".*") and group.startswith(e[:-1])) for e in events)


def payload(row: dict) -> dict:
    from .routers.history import feed_item  # import tardio: history importa os routers
    item = feed_item(row)
    deleted = row["action"].endswith(".delete")
    item["data"] = row["after"] if row["entity"] in DATA_ENTITIES and not deleted else None
    return audit._jsonable(item)


def _deliver(hook: dict, send) -> tuple[int, str | None]:
    """Entrega os eventos pendentes de um webhook, em ordem; para na 1ª falha.
    Devolve (quantos entregou, erro ou None)."""
    rows = db.query_all(
        """SELECT id, created_at, actor, token_name, action, entity, entity_id, before, after
             FROM audit_log
            WHERE user_id = %s AND id > %s AND created_at <= now() - make_interval(secs => %s)
            ORDER BY id LIMIT %s""",
        (hook["user_id"], hook["last_event_id"], LAG_SECONDS, BATCH),
    )
    secret, last, sent, error = secret_for(hook["secret_salt"]), hook["last_event_id"], 0, None
    for r in rows:
        if not matches(hook["events"], r["action"], r["entity"]):
            last = r["id"]
            continue
        body = json.dumps(payload(r), ensure_ascii=False, separators=(",", ":")).encode()
        t = int(time.time())
        headers = {"Content-Type": "application/json", "User-Agent": "Nexus-Worklog-Webhook/1",
                   "X-Nexus-Event": r["action"], "X-Nexus-Delivery": str(r["id"]),
                   "X-Nexus-Signature": signature(secret, t, body)}
        try:
            status = send(hook["url"], headers, body)
            error = None if 200 <= status < 300 else f"o destino respondeu HTTP {status}"
        except Refused as e:
            error = str(e)
        except Exception as e:  # noqa: BLE001 — rede, TLS, timeout: conta como falha e tenta depois
            error = f"falha de conexão ({e.__class__.__name__})"
        if error:
            break
        last, sent = r["id"], sent + 1
    if error:
        step = BACKOFF_MIN[min(hook["failures"], len(BACKOFF_MIN) - 1)]
        db.execute(
            """UPDATE webhooks SET last_event_id = %s, failures = failures + 1, last_error = %s,
                      next_attempt_at = now() + make_interval(mins => %s),
                      disabled_at = CASE WHEN failures + 1 >= %s THEN now() END
                WHERE id = %s""",
            (last, error[:200], step, MAX_FAILURES, hook["id"]),
        )
    elif last != hook["last_event_id"]:
        db.execute(
            f"""UPDATE webhooks SET last_event_id = %s, failures = 0, next_attempt_at = NULL, last_error = NULL
                      {', last_delivered_at = now()' if sent else ''}
                WHERE id = %s""",
            (last, hook["id"]),
        )
    return sent, error


def run_once(send=None) -> list[tuple[int, int, str | None]]:
    """Uma passada do agendador: (webhook, entregues, erro) de cada um que tinha o que mandar."""
    hooks = db.query_all(
        """SELECT id, user_id, url, events, secret_salt, last_event_id, failures FROM webhooks
            WHERE disabled_at IS NULL AND (next_attempt_at IS NULL OR next_attempt_at <= now())
            ORDER BY id""")
    done = []
    for h in hooks:
        try:
            sent, error = _deliver(h, send or post)
        except Exception:  # noqa: BLE001 — um webhook com problema não para os outros
            log.exception("webhook %s falhou nesta passada", h["id"])
            continue
        if sent or error:
            done.append((h["id"], sent, error))
    return done


# -------------------------------------------------------------------- teste --

def _explain(e: Exception) -> str:
    """A falha de um envio em linguagem comum (o teste mostra isto na tela)."""
    if isinstance(e, Refused):
        return str(e)
    if isinstance(e, ssl.SSLCertVerificationError):
        return "o certificado https do destino não é válido (autoassinado, vencido ou de outro nome)"
    if isinstance(e, ssl.SSLError):
        return "a conexão segura (https) com o destino falhou"
    if isinstance(e, (TimeoutError, socket.timeout)):
        return f"o destino não respondeu a tempo (mais de {TIMEOUT} s)"
    if isinstance(e, ConnectionRefusedError):
        return "o destino recusou a conexão (nada atendendo nesse endereço e porta)"
    if isinstance(e, (ConnectionResetError, BrokenPipeError, http.client.RemoteDisconnected)):
        return "o destino fechou a conexão sem responder"
    return f"falha de conexão ({e.__class__.__name__})"


def _status_text(status: int) -> str | None:
    if 200 <= status < 300:
        return None
    if 300 <= status < 400:
        return f"o destino respondeu HTTP {status} (redirecionamento não é seguido; use o endereço final)"
    if status in (401, 403):
        return f"o destino respondeu HTTP {status} (recusou: confira o segredo ou a senha no caminho do endereço)"
    if status == 404:
        return "o destino respondeu HTTP 404 (o caminho do endereço não existe lá)"
    return f"o destino respondeu HTTP {status}"


def ping(hook: dict, send=None) -> dict:
    """Envia AGORA um evento de teste (X-Nexus-Event: ping), assinado como os
    outros, pelo mesmo caminho (SSRF, prazo). Não mexe na fila nem nas falhas:
    um teste mal sucedido não desliga o webhook."""
    body = json.dumps({
        "id": 0, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "action": "ping", "entity": "webhook", "entity_id": hook["id"], "actor": "web", "token_name": None,
        "test": True, "data": {"message": "Teste do Nexus Worklog: se chegou, o webhook está ligado certo."},
    }, ensure_ascii=False, separators=(",", ":")).encode()
    t = int(time.time())
    headers = {"Content-Type": "application/json", "User-Agent": "Nexus-Worklog-Webhook/1",
               "X-Nexus-Event": "ping", "X-Nexus-Delivery": "test-" + secrets.token_hex(6),
               "X-Nexus-Signature": signature(secret_for(hook["secret_salt"]), t, body)}
    start = time.monotonic()
    status, error = None, None
    try:
        status = (send or post)(hook["url"], headers, body)
        error = _status_text(status)
    except Exception as e:  # noqa: BLE001 — qualquer falha vira explicação, nunca 500
        error = _explain(e)
    return {"ok": error is None, "status": status, "ms": round((time.monotonic() - start) * 1000), "error": error}
