from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db
from ..deps import active_user_csrf
from ..schemas import RecurringIn, RecurringUpdate, ToggleIn
from ..services import app_today, app_tz, recurring_vigente
from .board import check_board_day

router = APIRouter(prefix="/api/recurring", tags=["recurring"])


@router.post("", status_code=201)
def create(data: RecurringIn, user=Depends(active_user_csrf)):
    row = db.query_one(
        """
        INSERT INTO recurring_tasks (user_id, label, position, freq, weekdays, month_day, interval_days)
        VALUES (%(uid)s, %(label)s,
                (SELECT COALESCE(MAX(position), 0) + 1
                   FROM recurring_tasks WHERE user_id = %(uid)s),
                %(freq)s, %(weekdays)s, %(month_day)s, %(interval_days)s)
        RETURNING id, label, position, active, freq, weekdays, month_day, interval_days
        """,
        {"uid": user["user_id"], "label": data.label,
         **(data.agenda() if data.freq else {"freq": "daily", "weekdays": None, "month_day": None, "interval_days": None})},
    )
    audit.record(user, "recurring.create", "recurring", row["id"],
                 after=audit.recurring_snapshot(row["id"], user["user_id"]))
    return row


def replace_routine(user: dict, before: dict, new: dict, freeze: dict | None = None) -> int:
    """Encerra a rotina `before` hoje e cria outra (mesma posição) a partir de
    hoje com `new` (label + agenda): o passado da antiga não muda. `freeze`
    regrava a agenda da antiga (ex.: dias úteis antigos, congelados como
    semanal). A marcação de hoje passa para a nova. UMA ação no histórico
    ("recurring.replace", na nova), desfeita por inteiro."""
    uid, old_id = user["user_id"], before["id"]
    sets = ["active = false", "deactivated_at = now()"] + [f"{k} = %s" for k in (freeze or {})]
    db.execute(f"UPDATE recurring_tasks SET {', '.join(sets)} WHERE id = %s AND user_id = %s",
               tuple((freeze or {}).values()) + (old_id, uid))
    row = db.query_one(
        """INSERT INTO recurring_tasks (user_id, label, position, freq, weekdays, month_day, interval_days)
           VALUES (%(uid)s, %(label)s, %(position)s, %(freq)s, %(weekdays)s, %(month_day)s, %(interval_days)s)
           RETURNING id""",
        {"uid": uid, "position": before["position"], "weekdays": None, "month_day": None, "interval_days": None, **new})
    db.execute("UPDATE recurring_completions SET task_id = %s WHERE task_id = %s AND user_id = %s AND completed_date = %s",
               (row["id"], old_id, uid, app_today()))
    audit.record(user, "recurring.replace", "recurring", row["id"], before=before,
                 after={"replaced": old_id, **audit.recurring_snapshot(row["id"], uid)})
    return row["id"]


@router.patch("/{task_id}")
def update(task_id: int, data: RecurringUpdate, user=Depends(active_user_csrf)):
    """Nome e agenda. Trocar a agenda de uma rotina que já tem passado NÃO
    reescreve o passado: a atual é encerrada hoje e uma nova (mesmo nome e
    posição) começa hoje. A marcação de hoje, se houver, passa para a nova."""
    uid = user["user_id"]
    before = audit.recurring_snapshot(task_id, uid)
    if not before or not before["active"]:
        raise HTTPException(status_code=404, detail="não encontrado")
    agenda = data.agenda() if data.freq is not None else {}
    if data.label is None and not agenda:
        raise HTTPException(status_code=400, detail="nada para atualizar")
    today = app_today()
    muda_agenda = any(before[k] != v for k, v in agenda.items())
    tem_passado = before["created_at"].astimezone(app_tz()).date() < today

    if muda_agenda and tem_passado:
        new_id = replace_routine(user, before, {"label": data.label or before["label"], **agenda})
        return {"ok": True, "id": new_id, "replaced": task_id}

    fields, values = [], []
    if data.label is not None:
        fields.append("label = %s")
        values.append(data.label)
    for col, val in agenda.items():  # rotina criada hoje: ainda sem passado
        fields.append(f"{col} = %s")
        values.append(val)
    db.execute(f"UPDATE recurring_tasks SET {', '.join(fields)} WHERE id = %s AND user_id = %s",
               tuple(values) + (task_id, uid))
    audit.record(user, "recurring.update", "recurring", task_id, before=before,
                 after=audit.recurring_snapshot(task_id, uid))
    return {"ok": True, "id": task_id}


@router.delete("/{task_id}")
def deactivate(task_id: int, user=Depends(active_user_csrf)):
    # Soft-delete = desativar: preserva o historico em recurring_completions e
    # marca deactivated_at (so na transicao ativa->inativa).
    before = audit.recurring_snapshot(task_id, user["user_id"])
    updated = db.execute(
        """UPDATE recurring_tasks
              SET active = false,
                  deactivated_at = CASE WHEN active THEN now() ELSE deactivated_at END
            WHERE id = %s AND user_id = %s""",
        (task_id, user["user_id"]),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="não encontrado")
    audit.record(user, "recurring.deactivate", "recurring", task_id, before=before,
                 after=audit.recurring_snapshot(task_id, user["user_id"]))
    return {"ok": True}


@router.post("/{task_id}/toggle")
def toggle(task_id: int, data: ToggleIn, user=Depends(active_user_csrf)):
    owns = db.query_one(
        "SELECT 1 FROM recurring_tasks WHERE id = %s AND user_id = %s",
        (task_id, user["user_id"]),
    )
    if not owns:
        raise HTTPException(status_code=404, detail="não encontrado")

    # Marcação retroativa: hoje ou até RETRO_DAYS dias atrás (mesma janela do
    # quadro), e só em dia em que a rotina estava vigente.
    today = check_board_day(data.day) or app_today()
    if not recurring_vigente(task_id, user["user_id"], today):
        raise HTTPException(status_code=400, detail="a rotina não existia nesse dia")
    prev = db.query_one(
        "SELECT note FROM recurring_completions WHERE task_id = %s AND user_id = %s AND completed_date = %s",
        (task_id, user["user_id"], today),
    )
    was, old_note = prev is not None, (prev or {}).get("note")
    note = " ".join((data.note or "").split()) or None
    if data.done:
        # Remarcar sem nota mantém a evidência que já havia; com nota, troca.
        db.execute(
            """INSERT INTO recurring_completions (task_id, user_id, completed_date, note)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (task_id, completed_date) DO UPDATE
                  SET note = COALESCE(EXCLUDED.note, recurring_completions.note)""",
            (task_id, user["user_id"], today, note),
        )
    else:
        db.execute(
            "DELETE FROM recurring_completions WHERE task_id = %s AND user_id = %s AND completed_date = %s",
            (task_id, user["user_id"], today),
        )
    new_note = (note or old_note) if data.done else None
    if was != data.done or (data.done and new_note != old_note):
        audit.record(user, "recurring.toggle", "recurring", task_id,
                     before={"day": today, "done": was, "note": old_note},
                     after={"day": today, "done": data.done, "note": new_note})
    return {"ok": True, "done": data.done, "day": today, "note": new_note}
