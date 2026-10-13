"""Quem é a pessoa na interface: nome de exibição, foto e preferências do assistente.

O nome é escolhido pelo próprio usuário (Configurações > Conta). Sem nome, o
app deriva um do e-mail ("jefferson.oliveira@..." -> "Jefferson"), para o
"Bom dia, ..." nunca sair vazio. Usado pela API, pelo PDF e pelos e-mails.
"""
import re

from . import db

# Ações que contam como "registrar algo no worklog" para o lembrete de
# inatividade (configurações, chaves e avisos não contam).
WORK_ACTIONS = ("worklog.%", "recurring.toggle", "note.%", "checklist.%", "time.%", "timer.start")

ASSISTANT_DEFAULTS = {"enabled": True, "idle_on": True, "idle_minutes": 30, "idle_start": 480, "idle_end": 1080,
                      "reopen_on": True, "reopen_minutes": 10}


def name_from_email(email: str) -> str:
    local = (email or "").split("@")[0]
    first = re.split(r"[._\-+0-9]+", local)[0] or local
    return first[:1].upper() + first[1:].lower() if first else "você"


def profile(user_id: int) -> dict:
    r = db.query_one(
        """SELECT u.email, u.display_name, extract(epoch FROM a.updated_at)::bigint AS av
             FROM users u LEFT JOIN user_avatars a ON a.user_id = u.id
            WHERE u.id = %s""",
        (user_id,),
    )
    if not r:
        return {"display_name": None, "name": "você", "avatar": None}
    return {
        "display_name": r["display_name"],
        "name": r["display_name"] or name_from_email(r["email"]),
        # URL versionada: trocar a foto muda a URL e o cache não segura a antiga.
        "avatar": f"/api/me/avatar/{user_id}?v={r['av']}" if r["av"] else None,
    }


def label(user_id: int, email: str) -> str:
    """"Nome · e-mail" (PDF), ou só o e-mail quando o nome é o derivado dele."""
    p = profile(user_id)
    return f"{p['display_name']} · {email}" if p["display_name"] else email


def assistant_prefs(user_id: int) -> dict:
    r = db.query_one(
        """SELECT enabled, idle_on, idle_minutes, idle_start, idle_end, reopen_on, reopen_minutes
             FROM assistant_prefs WHERE user_id = %s""",
        (user_id,),
    )
    return dict(r) if r else dict(ASSISTANT_DEFAULTS)


def last_activity(user_id: int):
    """Quando a pessoa registrou algo pela última vez (qualquer origem: app,
    chave de API ou IA). None = nunca."""
    r = db.query_one(
        "SELECT max(created_at) AS at FROM audit_log WHERE user_id = %s AND action LIKE ANY(%s)",
        (user_id, list(WORK_ACTIONS)),
    )
    return r["at"] if r else None
