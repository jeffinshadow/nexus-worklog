from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db
from ..deps import active_user_csrf
from ..schemas import RecurringIn, RecurringUpdate, ToggleIn
from ..services import app_today, board_day_range, recurring_vigente

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


@router.patch("/{task_id}")
def update(task_id: int, data: RecurringUpdate, user=Depends(active_user_csrf)):
    before = audit.recurring_snapshot(task_id, user["user_id"])
    fields, values = [], []
    if data.label is not None:
        fields.append("label = %s")
        values.append(data.label)
    if data.active is not None:
        if data.active:
            # Reativar: a vigência RECOMEÇA agora. created_at avança para now()
            # (só na transição inativa->ativa) para que os dias em que ficou
            # desativada não voltem a gerar slots retroativos no dashboard.
            fields.append("active = true")
            fields.append("deactivated_at = NULL")
            fields.append("created_at = CASE WHEN active THEN created_at ELSE now() END")
        else:
            # Desativar: grava a data só na transição ativa->inativa (preserva a
            # data original se já estava inativa).
            fields.append("active = false")
            fields.append("deactivated_at = CASE WHEN active THEN now() ELSE deactivated_at END")
    if data.position is not None:
        fields.append("position = %s")
        values.append(data.position)
    if data.freq is not None:
        for col, val in data.agenda().items():
            fields.append(f"{col} = %s")
            values.append(val)
    if not fields:
        raise HTTPException(status_code=400, detail="nada para atualizar")

    values += [task_id, user["user_id"]]
    updated = db.execute(
        f"UPDATE recurring_tasks SET {', '.join(fields)} WHERE id = %s AND user_id = %s",
        tuple(values),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="nao encontrado")
    audit.record(user, "recurring.update", "recurring", task_id, before=before,
                 after=audit.recurring_snapshot(task_id, user["user_id"]))
    return {"ok": True}


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
        raise HTTPException(status_code=404, detail="nao encontrado")
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
        raise HTTPException(status_code=404, detail="nao encontrado")

    # Marcação retroativa: hoje ou até RETRO_DAYS dias atrás, e só em dia em
    # que a recorrente existia (criada e ainda não desativada).
    min_day, today_ = board_day_range(app_today())
    today = data.day or today_
    if not (min_day <= today <= today_):
        raise HTTPException(status_code=400, detail="dia fora da janela de edição")
    if not recurring_vigente(task_id, user["user_id"], today):
        raise HTTPException(status_code=400, detail="a recorrente não existia nesse dia")
    was = db.query_one(
        "SELECT 1 FROM recurring_completions WHERE task_id = %s AND completed_date = %s",
        (task_id, today),
    ) is not None
    if data.done:
        db.execute(
            """INSERT INTO recurring_completions (task_id, user_id, completed_date)
               VALUES (%s, %s, %s)
               ON CONFLICT (task_id, completed_date) DO NOTHING""",
            (task_id, user["user_id"], today),
        )
    else:
        db.execute(
            "DELETE FROM recurring_completions WHERE task_id = %s AND completed_date = %s",
            (task_id, today),
        )
    if was != data.done:
        audit.record(user, "recurring.toggle", "recurring", task_id,
                     before={"day": today, "done": was}, after={"day": today, "done": data.done})
    return {"ok": True, "done": data.done, "day": today}
