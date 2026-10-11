from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import audit, db, mailer, notify
from ..deps import web_active, web_active_csrf
from ..security import RateLimiter
from ..services import app_today

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

test_limiter = RateLimiter(max_hits=3, window_seconds=600)


class PrefsIn(BaseModel):
    morning: bool = False
    morning_hour: int = Field(default=8, ge=0, le=23)
    evening: bool = False
    evening_hour: int = Field(default=17, ge=0, le=23)
    weekly: bool = False
    weekly_hour: int = Field(default=8, ge=0, le=23)
    show_titles: bool = True


def _out(uid: int, email: str) -> dict:
    last = db.query_all(
        """SELECT kind, ref_date, sent_at, ok, error FROM notification_log
            WHERE user_id = %s ORDER BY sent_at DESC LIMIT 5""", (uid,))
    return {**notify.get_prefs(uid), "email": email, "mail_configured": mailer.configured(), "recent": last}


@router.get("")
def get_prefs(user=Depends(web_active)):
    return _out(user["user_id"], user["email"])


@router.put("")
def put_prefs(data: PrefsIn, user=Depends(web_active_csrf)):
    uid = user["user_id"]
    before = notify.get_prefs(uid)
    db.execute(
        """INSERT INTO notification_prefs (user_id, morning, morning_hour, evening, evening_hour, weekly, weekly_hour, show_titles)
           VALUES (%(uid)s, %(morning)s, %(morning_hour)s, %(evening)s, %(evening_hour)s, %(weekly)s, %(weekly_hour)s, %(show_titles)s)
           ON CONFLICT (user_id) DO UPDATE SET
             morning = EXCLUDED.morning, morning_hour = EXCLUDED.morning_hour,
             evening = EXCLUDED.evening, evening_hour = EXCLUDED.evening_hour,
             weekly = EXCLUDED.weekly, weekly_hour = EXCLUDED.weekly_hour,
             show_titles = EXCLUDED.show_titles, updated_at = now()""",
        {"uid": uid, **data.model_dump()},
    )
    audit.record(user, "notifications.update", "user", uid, before=before, after=data.model_dump())
    return _out(uid, user["email"])


@router.post("/test")
def send_test(user=Depends(web_active_csrf)):
    if not mailer.configured():
        raise HTTPException(status_code=503, detail="o envio de e-mail não está configurado no servidor")
    if not test_limiter.allow(f"mailtest:{user['user_id']}"):
        raise HTTPException(status_code=429, detail="aguarde alguns minutos antes de outro teste")
    prefs = notify.get_prefs(user["user_id"])
    mail = notify.build_test(user["user_id"], app_today(), prefs["show_titles"])
    try:
        mailer.send(user["email"], mail.subject, mail.text(), mail.html())
    except mailer.MailError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"ok": True, "to": user["email"]}
