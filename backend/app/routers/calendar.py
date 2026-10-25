"""Feed de calendário (ICS): prazos das tarefas abertas e as recorrentes como
eventos repetidos. Assinado por link secreto (um por usuário, revogável); só o
HMAC do token fica no banco, como nas chaves de API."""
import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response

from .. import audit, db
from ..config import config
from ..deps import web_active, web_active_csrf
from ..labels import PRIO_PT, STATUS_PT
from ..schemas import FeedIn
from .branding import branding
from ..security import token_hash, token_limiter
from ..services import app_today, is_due, work_mask

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

PREFIX = "nxc_"
_DAYS = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]  # bit 0 = domingo


# ------------------------------------------------------------- gerenciamento --

def _status(uid: int) -> dict:
    row = db.query_one(
        "SELECT prefix, include_recurring, created_at, last_used_at FROM calendar_feeds WHERE user_id = %s", (uid,))
    return {"active": bool(row), **(row or {})}


@router.get("")
def feed_status(user=Depends(web_active)):
    return _status(user["user_id"])


@router.post("", status_code=201)
def create_feed(data: FeedIn, user=Depends(web_active_csrf)):
    """Cria (ou troca) o link. O link antigo para de funcionar na hora."""
    raw = PREFIX + secrets.token_urlsafe(24)
    db.execute(
        """INSERT INTO calendar_feeds (user_id, token_hash, prefix, include_recurring)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (user_id) DO UPDATE
              SET token_hash = EXCLUDED.token_hash, prefix = EXCLUDED.prefix,
                  include_recurring = EXCLUDED.include_recurring, created_at = now(), last_used_at = NULL""",
        (user["user_id"], token_hash(raw), raw[: len(PREFIX) + 6], data.include_recurring),
    )
    audit.record(user, "calendar.create", "calendar", user["user_id"], after={"prefix": raw[: len(PREFIX) + 6]})
    return {**_status(user["user_id"]), "path": f"/api/calendar/{raw}.ics"}


@router.patch("")
def update_feed(data: FeedIn, user=Depends(web_active_csrf)):
    if not db.execute("UPDATE calendar_feeds SET include_recurring = %s WHERE user_id = %s",
                      (data.include_recurring, user["user_id"])):
        raise HTTPException(status_code=404, detail="nenhum link de calendário ativo")
    return _status(user["user_id"])


@router.delete("")
def revoke_feed(user=Depends(web_active_csrf)):
    if db.execute("DELETE FROM calendar_feeds WHERE user_id = %s", (user["user_id"],)):
        audit.record(user, "calendar.revoke", "calendar", user["user_id"])
    return {"active": False}


# ---------------------------------------------------------------------- ICS --

def _esc(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold_line(line: str) -> str:
    """Quebra em 75 octetos (RFC 5545), sem partir caracteres UTF-8."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > (75 if not out else 74):
            out.append(cur)
            cur, size = "", 0
        cur += ch
        size += n
    out.append(cur)
    return "\r\n ".join(out)


def _d(d: date) -> str:
    return d.strftime("%Y%m%d")


def _rrule(r: dict, mask: int) -> str | None:
    f = r["freq"] or "daily"
    if f in ("daily", "weekly"):
        bits = mask if f == "daily" else (r["weekdays"] or 0)
        days = [_DAYS[i] for i in range(7) if (bits >> i) & 1]
        return f"FREQ=WEEKLY;BYDAY={','.join(days)}" if days else None
    if f == "monthly":
        n = r["month_day"] or 1
        if n >= 31:
            return "FREQ=MONTHLY;BYMONTHDAY=-1"
        if n >= 29:  # dia 29/30 ou o último, nos meses mais curtos (igual ao app)
            return f"FREQ=MONTHLY;BYMONTHDAY={','.join(str(x) for x in range(28, n + 1))};BYSETPOS=-1"
        return f"FREQ=MONTHLY;BYMONTHDAY={n}"
    if f == "interval":
        return f"FREQ=DAILY;INTERVAL={r['interval_days']}"
    return None


def build_ics(uid: int, include_recurring: bool, cal_name: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    today = app_today()
    mask = work_mask(uid)
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ShadowTec//Nexus Worklog//PT-BR",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(cal_name)}",
        f"X-WR-TIMEZONE:{config.APP_TZ}", "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H",
    ]

    def event(uid_: str, start: date, summary: str, desc: str, extra: list[str] = ()):
        lines.extend(["BEGIN:VEVENT", f"UID:{uid_}@nexus-worklog", f"DTSTAMP:{now}",
                      f"DTSTART;VALUE=DATE:{_d(start)}", f"DTEND;VALUE=DATE:{_d(start + timedelta(days=1))}",
                      f"SUMMARY:{_esc(summary)}", f"DESCRIPTION:{_esc(desc)}", "TRANSP:TRANSPARENT", *extra,
                      "END:VEVENT"])

    for t in db.query_all(
        """SELECT w.id, w.title, w.description, w.status, w.priority, w.due_date, p.name AS project
             FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id
            WHERE w.user_id = %s AND w.status <> 'done' AND w.due_date IS NOT NULL""", (uid,)):
        summary = f"Prazo: {t['title']}" + (f" [{t['project']}]" if t["project"] else "")
        desc = f"Status: {STATUS_PT.get(t['status'], t['status'])} · prioridade {PRIO_PT.get(t['priority'], 'normal')}"
        # Sem a descrição: o feed vai para Google/Apple/Microsoft — só o necessário.
        extra = [f"CATEGORIES:{_esc(t['project'])}"] if t["project"] else []
        extra.append(f"URL:{config.APP_URL}/index.html#/tarefas?id={t['id']}")  # abre a tarefa no app
        if t["priority"] == 1:
            extra.append("PRIORITY:1")
        event(f"task-{t['id']}", t["due_date"], summary, desc, extra)

    # Impedimento com dia combinado para cobrar ("o fornecedor retorna na quinta").
    for t in db.query_all(
        """SELECT id, title, blocked_reason, follow_up_on FROM worklog_tasks
            WHERE user_id = %s AND status = 'blocked' AND follow_up_on IS NOT NULL""", (uid,)):
        quem = f"{t['blocked_reason']} — " if t["blocked_reason"] else ""
        event(f"followup-{t['id']}", t["follow_up_on"], f"Cobrar: {quem}{t['title']}",
              "Tarefa bloqueada com dia combinado para cobrar.",
              [f"URL:{config.APP_URL}/index.html#/tarefas?id={t['id']}"])

    if include_recurring:
        for r in db.query_all(
            """SELECT id, label, freq, weekdays, month_day, interval_days,
                      (created_at AT TIME ZONE %s)::date AS start_d
                 FROM recurring_tasks WHERE user_id = %s AND active ORDER BY position, id""", (config.APP_TZ, uid)):
            rule = _rrule(r, mask)
            if not rule:
                continue
            # DTSTART = primeira ocorrência real (a RFC conta o DTSTART como uma).
            first = next((r["start_d"] + timedelta(days=i) for i in range(0, 400)
                          if is_due(r, r["start_d"] + timedelta(days=i), mask)), None)
            if not first:
                continue
            event(f"recurring-{r['id']}", first, f"Rotina: {r['label']}",
                  "Recorrente do Nexus Worklog. Marque como feita no app.", [f"RRULE:{rule}"])

    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold_line(x) for x in lines) + "\r\n"


@router.get("/{token}.ics")
def feed(token: str):
    if not token.startswith(PREFIX) or len(token) > 80:
        raise HTTPException(status_code=404, detail="calendário não encontrado")
    row = db.query_one(
        """SELECT f.user_id, f.include_recurring, f.last_used_at FROM calendar_feeds f
            WHERE f.token_hash = %s""", (token_hash(token),))
    if not row:
        raise HTTPException(status_code=404, detail="calendário não encontrado")
    if not token_limiter.allow(f"cal:{row['user_id']}"):
        raise HTTPException(status_code=429, detail="muitas requisições, aguarde um minuto")
    now = datetime.now(timezone.utc)
    if row["last_used_at"] is None or now - row["last_used_at"] > timedelta(minutes=10):
        db.execute("UPDATE calendar_feeds SET last_used_at = now() WHERE user_id = %s", (row["user_id"],))
    brand = branding()
    name = f"{brand['line1']} {brand['line2']}".strip().title()
    return Response(
        content=build_ics(row["user_id"], row["include_recurring"], name),
        media_type="text/calendar; charset=utf-8",
        headers={"Cache-Control": "private, max-age=300", "Content-Disposition": 'inline; filename="nexus.ics"',
                 "X-Robots-Tag": "noindex"},
    )
