"""Notificações do sistema (Web Push), por aparelho.

Padrão aberto (RFC 8030/8291/8292): o conteúdo vai criptografado de ponta a
ponta para o navegador (http_ece, aes128gcm) e cada envio leva a assinatura
VAPID do servidor (ES256, feita aqui com o cryptography). Sem Firebase nem conta
em serviço de terceiros; o par de chaves é gerado no primeiro uso e fica no
banco (app_secrets), então o backup leva junto.

Disparos agendados (uma passada por minuto, junto do agendador de e-mails):
  rotina    no horário da rotina, +10 e +30 min, até ser marcada ("Adiar" empurra)
  cobrar    de manhã: bloqueadas com o dia de cobrar até hoje
  prazos    de manhã: atrasadas e o que vence hoje
E por evento: tarefa atribuída (routers/assign.py). Cada disparo agendado é
gravado em push_log ANTES de sair: nunca repete, mesmo reiniciando.
"""
import base64
import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import http_ece
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from . import db
from .config import config
from .services import app_today, get_board, is_due, is_work_day, rotinas, work_mask

log = logging.getLogger("uvicorn.error")

# Só os serviços de push dos navegadores (o servidor faz a requisição: um
# endereço qualquer viraria porta para dentro da rede).
ALLOWED_HOSTS = ("fcm.googleapis.com", "updates.push.services.mozilla.com", "push.services.mozilla.com",
                 "web.push.apple.com")
ALLOWED_SUFFIXES = (".push.apple.com", ".notify.windows.com")
STEPS = (0, 10, 30)       # minutos depois do horário da rotina
LATE_MIN = 15             # passou disso do disparo (backend fora do ar): não manda mais
MORNING_CATCH_UP_H = 2    # como nos e-mails: "bom dia" às 15h não serve
DEFAULT_PREFS = {"routine": True, "follow_up": True, "deadline": True, "assigned": True,
                 "morning_hour": 8, "hide_content": False}


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def endpoint_ok(endpoint: str) -> bool:
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (host in ALLOWED_HOSTS or host.endswith(ALLOWED_SUFFIXES))


def keys_ok(p256dh: str, auth: str) -> bool:
    try:
        pub, sec = _unb64u(p256dh), _unb64u(auth)
    except (ValueError, TypeError):
        return False
    return len(pub) == 65 and pub[0] == 4 and len(sec) == 16


# ----------------------------------------------------------------- chaves --

_key_cache: ec.EllipticCurvePrivateKey | None = None


def _private_key() -> ec.EllipticCurvePrivateKey:
    global _key_cache
    if _key_cache is None:
        pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        # Dois backends subindo juntos: o primeiro grava, os dois leem o mesmo.
        db.execute("INSERT INTO app_secrets (name, value) VALUES ('vapid_private_pem', %s) ON CONFLICT DO NOTHING", (pem,))
        stored = db.query_one("SELECT value FROM app_secrets WHERE name = 'vapid_private_pem'")["value"]
        _key_cache = serialization.load_pem_private_key(stored.encode(), password=None)
    return _key_cache


def public_key() -> str:
    """A chave que o navegador usa para aceitar só as nossas notificações."""
    return _b64u(_private_key().public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))


def _vapid_header(endpoint: str) -> str:
    """JWT ES256 (RFC 8292) para o serviço de push do endpoint."""
    parts = urlsplit(endpoint)
    sub = config.APP_URL if config.APP_URL.startswith("https://") else "mailto:nexus@localhost"
    head = _b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = _b64u(json.dumps({"aud": f"{parts.scheme}://{parts.netloc}", "exp": int(time.time()) + 12 * 3600,
                               "sub": sub}, separators=(",", ":")).encode())
    der = _private_key().sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    sig = _b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={head}.{claims}.{sig}, k={public_key()}"


# ----------------------------------------------------------------- envio --

def _http_post(endpoint: str, headers: dict, body: bytes) -> int:
    req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status
    except urllib.error.HTTPError as e:
        return e.code


TRANSPORT = _http_post  # os testes trocam por um que guarda o que sairia


def encrypt(payload: bytes, p256dh: str, auth: str) -> bytes:
    return http_ece.encrypt(payload, salt=os.urandom(16), private_key=ec.generate_private_key(ec.SECP256R1()),
                            dh=_unb64u(p256dh), auth_secret=_unb64u(auth), version="aes128gcm")


def send(uid: int, message: dict, urgency: str = "normal", ttl: int = 3600, only_id: int | None = None) -> int:
    """Manda para os aparelhos da pessoa. Devolve quantos aceitaram. Aparelho que
    o serviço diz não existir mais (404/410) sai da lista."""
    subs = db.query_all("SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = %s"
                        + (" AND id = %s" if only_id else ""), (uid, only_id) if only_id else (uid,))
    body = json.dumps(message, ensure_ascii=False).encode()
    sent = 0
    for s in subs:
        try:
            status = TRANSPORT(s["endpoint"], {
                "TTL": str(ttl), "Urgency": urgency, "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream", "Authorization": _vapid_header(s["endpoint"]),
            }, encrypt(body, s["p256dh"], s["auth"]))
        except Exception as e:  # noqa: BLE001 — rede fora: tenta no próximo disparo
            log.warning("push para o aparelho %s falhou: %s", s["id"], e)
            status = 0
        if status in (404, 410):
            db.execute("DELETE FROM push_subscriptions WHERE id = %s", (s["id"],))
        elif 200 <= status < 300:
            sent += 1
            db.execute("UPDATE push_subscriptions SET last_ok_at = now(), failures = 0 WHERE id = %s", (s["id"],))
        else:
            db.execute("UPDATE push_subscriptions SET failures = LEAST(failures + 1, 999) WHERE id = %s", (s["id"],))
    return sent


def prefs(uid: int) -> dict:
    row = db.query_one("""SELECT routine, follow_up, deadline, assigned, morning_hour, hide_content
                            FROM push_prefs WHERE user_id = %s""", (uid,))
    return dict(row) if row else dict(DEFAULT_PREFS)


# ------------------------------------------------------------- mensagens --

def _msg(title: str, body: str, url: str, tag: str, kind: str, hide: bool, generic: str, **extra) -> dict:
    """Tela bloqueada sem nomes (hide_content): só o tipo do aviso."""
    if hide:
        title, body = generic, "Abra o Nexus para ver."
    return {"title": title, "body": body, "url": url, "tag": tag, "kind": kind, **extra}


def routine_message(r: dict, day, step_label: str, hide: bool) -> dict:
    actions = [] if r["require_note"] else [{"action": "feita", "title": "Marcar feita"}]
    actions.append({"action": "adiar", "title": "Adiar 10 min"})
    return _msg(r["label"], step_label, "/#/hoje", f"rotina-{r['id']}-{day.isoformat()}", "rotina", hide,
                "Rotina na hora", id=r["id"], day=day.isoformat(), actions=actions, require_interaction=True)


def assigned_message(task: dict, by_name: str, hide: bool) -> dict:
    return _msg(f"Nova tarefa de {by_name}", task["title"], f"/#/tarefas?id={task['id']}", f"atribuida-{task['id']}",
                "atribuida", hide, "Nova tarefa atribuída a você")


def notify_assigned(uid: int, task: dict, by_name: str) -> None:
    """Chamado em outra thread pela atribuição (a requisição não espera a rede)."""
    p = prefs(uid)
    if p["assigned"]:
        send(uid, assigned_message(task, by_name, p["hide_content"]), urgency="high", ttl=24 * 3600)


# -------------------------------------------------------------- agendador --

def _claim(uid: int, kind: str, ref: str, day) -> bool:
    return bool(db.query_one("""INSERT INTO push_log (user_id, kind, ref, ref_date) VALUES (%s, %s, %s, %s)
                                ON CONFLICT DO NOTHING RETURNING 1""", (uid, kind, ref, day)))


def _routines(uid: int, p: dict, now: datetime, mask: int) -> list[str]:
    """Rotinas com horário devidas hoje e ainda não marcadas: o disparo da vez."""
    today, done = now.date(), []
    feitas = {r["task_id"] for r in db.query_all(
        "SELECT task_id FROM recurring_completions WHERE user_id = %s AND completed_date = %s", (uid, today))}
    snoozes = {r["recurring_id"]: r["until"] for r in db.query_all(
        "SELECT recurring_id, until FROM push_snooze WHERE user_id = %s AND day = %s", (uid, today))}
    for r in rotinas(uid):
        if not r["remind_at"] or r["id"] in feitas or not (r["start_d"] <= today <= r["end_d"]) or not is_due(r, today, mask):
            continue
        at = datetime.combine(today, r["remind_at"], tzinfo=now.tzinfo)
        until = snoozes.get(r["id"])
        until = until.astimezone(now.tzinfo) if until else None
        # Os disparos da rotina; o adiado entra como mais um. O que cai antes do
        # fim do adiamento não sai.
        moments = [(f"{r['id']}:{s}", at + timedelta(minutes=s)) for s in STEPS]
        if until:
            moments = [m for m in moments if m[1] >= until] + [(f"{r['id']}:a{until:%H%M}", until)]
        due = [m for m in moments if m[1] <= now < m[1] + timedelta(minutes=LATE_MIN)]
        if not due:
            continue
        ref, moment = max(due, key=lambda m: m[1])
        if not _claim(uid, "rotina", ref, today):
            continue
        label = f"Agora, às {r['remind_at']:%H:%M}" if moment == at else f"Era às {r['remind_at']:%H:%M} · ainda não marcada"
        send(uid, routine_message(r, today, label, p["hide_content"]), urgency="high", ttl=LATE_MIN * 60)
        done.append(ref)
    return done


def _morning(uid: int, p: dict, now: datetime, mask: int) -> list[str]:
    today, done = now.date(), []
    if not (p["follow_up"] or p["deadline"]) or now.hour < p["morning_hour"] or now.hour - p["morning_hour"] > MORNING_CATCH_UP_H:
        return done
    if not is_work_day(today, mask):
        return done
    abertas = get_board(uid, today)["in_progress"]
    hide = p["hide_content"]
    if p["deadline"]:
        atrasadas = [t["title"] for t in abertas if t["due_date"] and t["due_date"] < today]
        hoje = [t["title"] for t in abertas if t["due_date"] == today]
        if (atrasadas or hoje) and _claim(uid, "prazos", "manha", today):
            partes = [f"{len(atrasadas)} atrasada{'s' if len(atrasadas) > 1 else ''}" if atrasadas else "",
                      f"{len(hoje)} vence{'m' if len(hoje) > 1 else ''} hoje" if hoje else ""]
            resumo = " · ".join(x for x in partes if x)
            body = resumo + ": " + ", ".join((atrasadas + hoje)[:3]) + ("…" if len(atrasadas + hoje) > 3 else "")
            send(uid, _msg("Prazos de hoje", body, "/#/hoje", f"prazos-{today}", "prazos", hide, "Prazos de hoje"))
            done.append("prazos")
    if p["follow_up"]:
        cobrar = [t["title"] for t in abertas if t["status"] == "blocked" and t.get("follow_up_on") and t["follow_up_on"] <= today]
        if cobrar and _claim(uid, "cobrar", "manha", today):
            body = ", ".join(cobrar[:3]) + ("…" if len(cobrar) > 3 else "")
            title = "Cobrar hoje" if len(cobrar) == 1 else f"Cobrar hoje: {len(cobrar)} tarefas"
            send(uid, _msg(title, body, "/#/tarefas", f"cobrar-{today}", "cobrar", hide, "Cobranças de hoje"))
            done.append("cobrar")
    return done


def run_once(now: datetime) -> list[tuple[int, str]]:
    """Uma passada no horário local `now` (com fuso). Devolve o que disparou."""
    out = []
    users = db.query_all("""SELECT DISTINCT s.user_id FROM push_subscriptions s JOIN users u ON u.id = s.user_id
                             WHERE NOT u.must_change_password""")
    for row in users:
        uid = row["user_id"]
        try:
            p, mask = prefs(uid), work_mask(uid)
            if p["routine"]:
                out += [(uid, ref) for ref in _routines(uid, p, now, mask)]
            out += [(uid, ref) for ref in _morning(uid, p, now, mask)]
        except Exception:  # noqa: BLE001 — uma pessoa com erro não para as outras
            log.exception("notificações do usuário %s falharam nesta passada", uid)
    if now.minute == 0:  # uma vez por hora: o registro antigo não serve para nada
        db.execute("DELETE FROM push_log WHERE ref_date < %s", (now.date() - timedelta(days=30),))
        db.execute("DELETE FROM push_snooze WHERE day < %s", (now.date(),))
    return out


def snooze(uid: int, recurring_id: int, minutes: int) -> datetime:
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    db.execute("""INSERT INTO push_snooze (user_id, recurring_id, day, until) VALUES (%s, %s, %s, %s)
                  ON CONFLICT (user_id, recurring_id, day) DO UPDATE SET until = EXCLUDED.until""",
               (uid, recurring_id, app_today(), until))
    return until
