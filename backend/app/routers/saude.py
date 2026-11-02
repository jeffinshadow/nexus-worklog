"""Saúde do Nexus (Admin > Geral): um retrato só de leitura do servidor.

Versão (o commit que o deploy.sh gravou), última migração, último backup (o
deploy.sh grava estado/backup.json depois do pg_dump; o backend lê a pasta só
leitura e nunca vê o dump), e-mail e notificações (configurados? último erro),
espaço das fotos, webhooks desligados por falha, pedidos de convite.

Só contagens e datas: nada de dados de pessoas, endereço de webhook, caminho
de arquivo ou segredo — o admin cola isto num chamado ("Copiar diagnóstico").
Sem os arquivos do deploy (rodou sem o deploy.sh, ou antes desta versão), o
campo vem null: "sem informação", não erro.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends

from .. import db, mailer
from ..config import config
from ..deps import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])

STARTED_AT = datetime.now(timezone.utc)
SQL_DIR = Path(__file__).resolve().parent.parent.parent / "sql"
NEAR_QUOTA = 0.8  # pessoas com 80%+ do espaço de fotos
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


def _state(name: str, keys: tuple) -> dict | None:
    """Um JSON do deploy.sh, só com os campos conhecidos (nada de caminho)."""
    try:
        raw = json.loads((Path(config.STATE_DIR) / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    out = {k: raw.get(k) for k in keys}
    return out if any(v is not None for v in out.values()) else None


def _clean(text: str | None) -> str | None:
    """Mensagem de erro sem e-mails (de quem recebia) e curta."""
    if not text:
        return None
    return _EMAIL.sub("<e-mail>", " ".join(text.split()))[:200]


def _latest(*pairs):
    """O par (quando, o quê) mais recente, ignorando os vazios."""
    found = [p for p in pairs if p and p[0]]
    return max(found, key=lambda p: p[0]) if found else None


@router.get("/health")
def admin_health(admin=Depends(require_admin)):
    migrations = sorted(p.stem for p in SQL_DIR.glob("*.sql"))
    deploy = _state("deploy.json", ("commit", "previous", "at"))
    backup = _state("backup.json", ("at", "size_bytes", "tables"))

    mail_err = db.query_one(
        """SELECT sent_at, error FROM notification_log WHERE ok = false ORDER BY sent_at DESC LIMIT 1""")
    mail_ok = db.query_one("SELECT max(sent_at) AS at FROM notification_log WHERE ok")["at"]
    err = _latest((mail_err["sent_at"], mail_err["error"]) if mail_err else None,
                  (mailer.last["error_at"], mailer.last["error"]))
    ok_at = max([t for t in (mail_ok, mailer.last["ok_at"]) if t], default=None)

    push = db.query_one(
        """SELECT count(*)::int AS devices, count(*) FILTER (WHERE failures > 0)::int AS failing,
                  max(last_ok_at) AS last_ok_at FROM push_subscriptions""")
    vapid = bool(db.query_one("SELECT 1 FROM app_secrets WHERE name = 'vapid_private_pem'"))

    quota_mb = config.PHOTO_QUOTA_MB
    photos = db.query_one(
        """SELECT COALESCE(sum(n), 0)::bigint AS used, COALESCE(max(n), 0)::bigint AS top,
                  count(*) FILTER (WHERE %s > 0 AND n >= %s)::int AS near
             FROM (SELECT sum(bytes) AS n FROM photos WHERE deleted_at IS NULL GROUP BY user_id) x""",
        (quota_mb, quota_mb * 1024 * 1024 * NEAR_QUOTA))
    hooks = db.query_one(
        """SELECT count(*)::int AS total, count(*) FILTER (WHERE disabled_at IS NOT NULL)::int AS disabled
             FROM webhooks""")
    counts = db.query_one(
        """SELECT (SELECT count(*)::int FROM users) AS accounts,
                  (SELECT count(*)::int FROM invite_requests WHERE status = 'pending') AS invite_requests,
                  (SELECT count(*)::int FROM api_tokens WHERE revoked_at IS NULL
                      AND (expires_at IS NULL OR expires_at > now())) AS api_tokens,
                  pg_database_size(current_database())::bigint AS db_bytes""")

    return {
        "now": datetime.now(timezone.utc),
        "version": {"commit": (deploy or {}).get("commit"), "deployed_at": (deploy or {}).get("at"),
                    "migration": migrations[-1] if migrations else None, "started_at": STARTED_AT},
        "backup": backup,
        "email": {"configured": mailer.configured(), "scheduler": config.MAIL_SCHEDULER, "last_ok_at": ok_at,
                  "last_error_at": err[0] if err else None, "last_error": _clean(err[1]) if err else None},
        "push": {"keys_ok": vapid, "devices": push["devices"], "failing": push["failing"],
                 "last_ok_at": push["last_ok_at"]},
        "photos": {"quota_mb": quota_mb, "used_bytes": photos["used"], "top_bytes": photos["top"],
                   "near_quota": photos["near"]},
        "webhooks": {"total": hooks["total"], "disabled": hooks["disabled"]},
        "accounts": counts["accounts"], "invite_requests": counts["invite_requests"],
        "api_tokens": counts["api_tokens"], "db_bytes": counts["db_bytes"],
    }
