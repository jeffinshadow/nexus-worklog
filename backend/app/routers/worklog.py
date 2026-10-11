from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db
from ..deps import active_user_csrf
from ..schemas import WorklogIn, WorklogUpdate

router = APIRouter(prefix="/api/worklog", tags=["worklog"])


@router.post("", status_code=201)
def create(data: WorklogIn, user=Depends(active_user_csrf)):
    completed_at = datetime.now(timezone.utc) if data.status == "done" else None
    row = db.query_one(
        """
        INSERT INTO worklog_tasks (user_id, title, description, status, due_date, completed_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (user["user_id"], data.title, data.description, data.status, data.due_date, completed_at),
    )
    audit.record(user, "worklog.create", "worklog", row["id"],
                 after=audit.worklog_snapshot(row["id"], user["user_id"]))
    return {"id": row["id"]}


@router.patch("/{task_id}")
def update(task_id: int, data: WorklogUpdate, user=Depends(active_user_csrf)):
    before = audit.worklog_snapshot(task_id, user["user_id"])
    if not before:
        raise HTTPException(status_code=404, detail="nao encontrado")

    fields, values = [], []
    if data.title is not None:
        fields.append("title = %s")
        values.append(data.title)
    # description e due_date podem ser apagados: enviados como null (ou vazio)
    # = limpar o campo; ausentes no corpo = não mexer. Antes, null era
    # ignorado e o formulário não conseguia remover previsão nem descrição.
    sent = data.model_fields_set
    if "description" in sent:
        fields.append("description = %s")
        values.append(data.description or None)
    if "due_date" in sent:
        fields.append("due_date = %s")
        values.append(data.due_date)
    if data.status is not None:
        fields.append("status = %s")
        values.append(data.status)
        if data.status == "done" and before["completed_at"] is None:
            fields.append("completed_at = %s")
            values.append(datetime.now(timezone.utc))
        elif data.status != "done":
            fields.append("completed_at = NULL")

    if not fields:
        raise HTTPException(status_code=400, detail="nada para atualizar")

    values += [task_id, user["user_id"]]
    db.execute(
        f"UPDATE worklog_tasks SET {', '.join(fields)} WHERE id = %s AND user_id = %s",
        tuple(values),
    )
    audit.record(user, "worklog.update", "worklog", task_id, before=before,
                 after=audit.worklog_snapshot(task_id, user["user_id"]))
    return {"ok": True}


@router.post("/{task_id}/finish")
def finish(task_id: int, user=Depends(active_user_csrf)):
    before = audit.worklog_snapshot(task_id, user["user_id"])
    if not before:
        raise HTTPException(status_code=404, detail="nao encontrado")
    db.execute(
        """UPDATE worklog_tasks
              SET status = 'done', completed_at = COALESCE(completed_at, now())
            WHERE id = %s AND user_id = %s""",
        (task_id, user["user_id"]),
    )
    audit.record(user, "worklog.finish", "worklog", task_id, before=before,
                 after=audit.worklog_snapshot(task_id, user["user_id"]))
    return {"ok": True}


@router.delete("/{task_id}")
def delete(task_id: int, user=Depends(active_user_csrf)):
    before = audit.worklog_snapshot(task_id, user["user_id"])
    if not before:
        raise HTTPException(status_code=404, detail="nao encontrado")
    db.execute("DELETE FROM worklog_tasks WHERE id = %s AND user_id = %s", (task_id, user["user_id"]))
    audit.record(user, "worklog.delete", "worklog", task_id, before=before)
    return {"ok": True}
