"""Vencimentos: certificados, licenças, domínios, garantias e contratos que
vencem numa data. Avisam com antecedência no Hoje, no e-mail da manhã e no
calendário — sem consultar nada de fora (a data é a que a pessoa informou).
"""
from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db
from ..deps import active_user, active_user_csrf
from ..schemas import RenewalIn, RenewalUpdate
from datetime import timedelta

from ..services import app_today, is_work_day, work_mask

router = APIRouter(prefix="/api/renewals", tags=["renewals"])

COLS = "r.id, r.label, r.expires_on, r.warn_days, r.project_id, r.note, p.name AS project_name"


def warn_start(expires_on, warn_days: int, mask: int):
    """Primeiro dia do aviso; caindo em dia não útil, antecipa para o último dia útil
    (um aviso curto não some no fim de semana)."""
    d = expires_on - timedelta(days=warn_days)
    for _ in range(7):
        if is_work_day(d, mask):
            return d
        d -= timedelta(days=1)
    return d


def list_for(uid: int) -> list[dict]:
    """Todos, do que vence primeiro ao último, com dias até vencer e se já está no aviso."""
    today = app_today()
    mask = work_mask(uid)
    rows = db.query_all(
        f"""SELECT {COLS} FROM renewals r LEFT JOIN projects p ON p.id = r.project_id
             WHERE r.user_id = %s ORDER BY r.expires_on, r.id""", (uid,))
    for r in rows:
        r["days_left"] = (r["expires_on"] - today).days
        r["warn_from"] = warn_start(r["expires_on"], r["warn_days"], mask)
        r["warning"] = today >= r["warn_from"]
    return rows


def _check_project(uid: int, project_id) -> None:
    if project_id is not None and not db.query_one(
            "SELECT 1 FROM projects WHERE id = %s AND user_id = %s", (project_id, uid)):
        raise HTTPException(status_code=400, detail="projeto não encontrado")


def _snap(rid: int, uid: int):
    return db.query_one("SELECT id, label, expires_on, warn_days, project_id, note FROM renewals WHERE id = %s AND user_id = %s",
                        (rid, uid))


@router.get("")
def list_renewals(user=Depends(active_user)):
    return list_for(user["user_id"])


@router.post("", status_code=201)
def create(data: RenewalIn, user=Depends(active_user_csrf)):
    uid = user["user_id"]
    _check_project(uid, data.project_id)
    row = db.query_one(
        """INSERT INTO renewals (user_id, label, expires_on, warn_days, project_id, note)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (uid, data.label.strip(), data.expires_on, data.warn_days, data.project_id, (data.note or "").strip() or None))
    audit.record(user, "renewal.create", "renewal", row["id"], after=_snap(row["id"], uid))
    return {"id": row["id"]}


@router.patch("/{rid}")
def update(rid: int, data: RenewalUpdate, user=Depends(active_user_csrf)):
    """Editar ou renovar (nova data de vencimento)."""
    uid = user["user_id"]
    before = _snap(rid, uid)
    if not before:
        raise HTTPException(status_code=404, detail="não encontrado")
    sent = data.model_fields_set
    fields, values = [], []
    for col in ("label", "expires_on", "warn_days"):
        if getattr(data, col) is not None:
            fields.append(f"{col} = %s")
            values.append(getattr(data, col).strip() if col == "label" else getattr(data, col))
    if "project_id" in sent:
        _check_project(uid, data.project_id)
        fields.append("project_id = %s")
        values.append(data.project_id)
    if "note" in sent:
        fields.append("note = %s")
        values.append((data.note or "").strip() or None)
    if not fields:
        raise HTTPException(status_code=400, detail="nada para atualizar")
    db.execute(f"UPDATE renewals SET {', '.join(fields)} WHERE id = %s AND user_id = %s", (*values, rid, uid))
    after = _snap(rid, uid)
    action = "renewal.renew" if after["expires_on"] != before["expires_on"] else "renewal.update"
    audit.record(user, action, "renewal", rid, before=before, after=after)
    return {"ok": True}


@router.delete("/{rid}")
def delete(rid: int, user=Depends(active_user_csrf)):
    before = _snap(rid, user["user_id"])
    if not before:
        raise HTTPException(status_code=404, detail="não encontrado")
    db.execute("DELETE FROM renewals WHERE id = %s AND user_id = %s", (rid, user["user_id"]))
    audit.record(user, "renewal.delete", "renewal", rid, before=before)
    return {"ok": True}
