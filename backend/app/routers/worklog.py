from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db
from ..deps import active_user, active_user_csrf
from ..schemas import ChecklistIn, ChecklistUpdate, NoteIn, TimeIn, WorklogIn, WorklogUpdate
from ..services import app_today

router = APIRouter(prefix="/api/worklog", tags=["worklog"])
items = APIRouter(prefix="/api", tags=["worklog"])  # rotas por id de anotação/item/tempo

TIME_MAX_PAST_DAYS = 366  # apontamento retroativo (também limita o "projeto inteiro")


def _check_project(uid: int, project_id) -> None:
    if project_id is None:
        return
    if not db.query_one("SELECT 1 FROM projects WHERE id = %s AND user_id = %s", (project_id, uid)):
        raise HTTPException(status_code=400, detail="projeto não encontrado")


def _own_task(uid: int, task_id: int) -> dict:
    row = audit.worklog_snapshot(task_id, uid)
    if not row:
        raise HTTPException(status_code=404, detail="nao encontrado")
    return row


@router.post("", status_code=201)
def create(data: WorklogIn, user=Depends(active_user_csrf)):
    _check_project(user["user_id"], data.project_id)
    completed_at = datetime.now(timezone.utc) if data.status == "done" else None
    row = db.query_one(
        """
        INSERT INTO worklog_tasks (user_id, title, description, status, due_date, completed_at,
                                   project_id, priority)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (user["user_id"], data.title, data.description, data.status, data.due_date, completed_at,
         data.project_id, data.priority),
    )
    audit.record(user, "worklog.create", "worklog", row["id"],
                 after=audit.worklog_snapshot(row["id"], user["user_id"]))
    return {"id": row["id"]}


@router.get("/{task_id}")
def detail(task_id: int, user=Depends(active_user)):
    """Tarefa completa: dados, projeto, checklist, anotações e tempo."""
    uid = user["user_id"]
    task = db.query_one(
        """
        SELECT w.id, w.title, w.description, w.status, w.due_date, w.created_at, w.completed_at,
               w.priority, w.project_id, p.name AS project_name, p.color AS project_color
          FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id
         WHERE w.id = %s AND w.user_id = %s
        """,
        (task_id, uid),
    )
    if not task:
        raise HTTPException(status_code=404, detail="nao encontrado")
    task["checklist"] = db.query_all(
        "SELECT id, label, done, position FROM task_checklist WHERE task_id = %s ORDER BY position, id",
        (task_id,),
    )
    task["notes"] = db.query_all(
        "SELECT id, body, actor, token_name, created_at FROM task_notes WHERE task_id = %s ORDER BY created_at DESC, id DESC",
        (task_id,),
    )
    task["time"] = db.query_all(
        "SELECT id, minutes, day, note, actor, token_name, created_at FROM time_entries WHERE task_id = %s ORDER BY day DESC, id DESC",
        (task_id,),
    )
    task["minutes"] = sum(t["minutes"] for t in task["time"])
    task["today"] = app_today()  # o detalhe não precisa buscar o quadro só para saber o dia
    return task


@router.patch("/{task_id}")
def update(task_id: int, data: WorklogUpdate, user=Depends(active_user_csrf)):
    before = _own_task(user["user_id"], task_id)

    fields, values = [], []
    if data.title is not None:
        fields.append("title = %s")
        values.append(data.title)
    # description, due_date e project_id podem ser apagados: enviados como null
    # (ou vazio) = limpar; ausentes no corpo = não mexer.
    sent = data.model_fields_set
    if "description" in sent:
        fields.append("description = %s")
        values.append(data.description or None)
    if "due_date" in sent:
        fields.append("due_date = %s")
        values.append(data.due_date)
    if "project_id" in sent:
        _check_project(user["user_id"], data.project_id)
        fields.append("project_id = %s")
        values.append(data.project_id)
    if data.priority is not None:
        fields.append("priority = %s")
        values.append(data.priority)
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
    before = _own_task(user["user_id"], task_id)
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
    before = _own_task(user["user_id"], task_id)
    # Anotações, checklist e tempo vão junto (CASCADE): ficam no histórico para o desfazer.
    before["children"] = {
        "notes": db.query_all("SELECT id, body, actor, token_name, created_at FROM task_notes WHERE task_id = %s", (task_id,)),
        "checklist": db.query_all("SELECT id, label, done, position FROM task_checklist WHERE task_id = %s", (task_id,)),
        "time": db.query_all("SELECT id, minutes, day, note, actor, token_name, created_at FROM time_entries WHERE task_id = %s", (task_id,)),
    }
    db.execute("DELETE FROM worklog_tasks WHERE id = %s AND user_id = %s", (task_id, user["user_id"]))
    audit.record(user, "worklog.delete", "worklog", task_id, before=before)
    return {"ok": True}


# ------------------------------------------------------------- anotações --

@router.post("/{task_id}/notes", status_code=201)
def add_note(task_id: int, data: NoteIn, user=Depends(active_user_csrf)):
    task = _own_task(user["user_id"], task_id)
    row = db.query_one(
        """INSERT INTO task_notes (task_id, user_id, body, actor, token_name)
           VALUES (%s, %s, %s, %s, %s) RETURNING id, body, actor, token_name, created_at""",
        (task_id, user["user_id"], data.body.strip(), user.get("actor", "web"), user.get("token_name")),
    )
    audit.record(user, "note.create", "note", row["id"],
                 after={"task_id": task_id, "title": task["title"], "body": row["body"][:120]})
    return row


@items.delete("/notes/{note_id}")
def delete_note(note_id: int, user=Depends(active_user_csrf)):
    row = db.query_one(
        """DELETE FROM task_notes n USING worklog_tasks w
            WHERE n.id = %s AND n.user_id = %s AND w.id = n.task_id
        RETURNING n.id, n.task_id, n.body, n.actor, n.token_name, n.created_at, w.title""",
        (note_id, user["user_id"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="nao encontrado")
    audit.record(user, "note.delete", "note", note_id, before=row)
    return {"ok": True}


# ------------------------------------------------------------- checklist --

@router.post("/{task_id}/checklist", status_code=201)
def add_item(task_id: int, data: ChecklistIn, user=Depends(active_user_csrf)):
    task = _own_task(user["user_id"], task_id)
    row = db.query_one(
        """INSERT INTO task_checklist (task_id, user_id, label, position)
           VALUES (%s, %s, %s, (SELECT COALESCE(MAX(position), 0) + 1 FROM task_checklist WHERE task_id = %s))
        RETURNING id, label, done, position""",
        (task_id, user["user_id"], data.label.strip(), task_id),
    )
    audit.record(user, "checklist.create", "checklist", row["id"],
                 after={"task_id": task_id, "title": task["title"], "label": row["label"], "done": False})
    return row


@items.patch("/checklist/{item_id}")
def update_item(item_id: int, data: ChecklistUpdate, user=Depends(active_user_csrf)):
    before = db.query_one(
        """SELECT c.id, c.task_id, c.label, c.done, w.title FROM task_checklist c
             JOIN worklog_tasks w ON w.id = c.task_id
            WHERE c.id = %s AND c.user_id = %s""",
        (item_id, user["user_id"]),
    )
    if not before:
        raise HTTPException(status_code=404, detail="nao encontrado")
    label = data.label.strip() if data.label is not None else before["label"]
    done = data.done if data.done is not None else before["done"]
    db.execute("UPDATE task_checklist SET label = %s, done = %s WHERE id = %s", (label, done, item_id))
    audit.record(user, "checklist.update", "checklist", item_id, before=before,
                 after={**before, "label": label, "done": done})
    return {"id": item_id, "label": label, "done": done}


@items.delete("/checklist/{item_id}")
def delete_item(item_id: int, user=Depends(active_user_csrf)):
    row = db.query_one(
        """DELETE FROM task_checklist c USING worklog_tasks w
            WHERE c.id = %s AND c.user_id = %s AND w.id = c.task_id
        RETURNING c.id, c.task_id, c.label, c.done, c.position, w.title""",
        (item_id, user["user_id"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="nao encontrado")
    audit.record(user, "checklist.delete", "checklist", item_id, before=row)
    return {"ok": True}


# ------------------------------------------------------------------ tempo --

@router.post("/{task_id}/time", status_code=201)
def log_time(task_id: int, data: TimeIn, user=Depends(active_user_csrf)):
    task = _own_task(user["user_id"], task_id)
    today = app_today()
    day = data.day or today
    if day > today:
        raise HTTPException(status_code=400, detail="não dá para apontar tempo no futuro")
    if (today - day).days > TIME_MAX_PAST_DAYS:
        raise HTTPException(status_code=400, detail=f"apontamento até {TIME_MAX_PAST_DAYS} dias atrás")
    total = db.query_one("SELECT COALESCE(sum(minutes), 0)::int AS m FROM time_entries WHERE user_id = %s AND day = %s",
                         (user["user_id"], day))["m"]
    if total + data.minutes > 1440:
        raise HTTPException(status_code=400, detail="passaria de 24h apontadas nesse dia")
    row = db.query_one(
        """INSERT INTO time_entries (task_id, user_id, minutes, day, note, actor, token_name)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id, minutes, day, note, actor, token_name, created_at""",
        (task_id, user["user_id"], data.minutes, day, (data.note or "").strip() or None,
         user.get("actor", "web"), user.get("token_name")),
    )
    audit.record(user, "time.create", "time", row["id"],
                 after={"task_id": task_id, "title": task["title"], "minutes": data.minutes, "day": day})
    return row


@items.delete("/time/{entry_id}")
def delete_time(entry_id: int, user=Depends(active_user_csrf)):
    row = db.query_one(
        """DELETE FROM time_entries t USING worklog_tasks w
            WHERE t.id = %s AND t.user_id = %s AND w.id = t.task_id
        RETURNING t.id, t.task_id, t.minutes, t.day, t.note, t.actor, t.token_name, t.created_at, w.title""",
        (entry_id, user["user_id"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="nao encontrado")
    audit.record(user, "time.delete", "time", entry_id, before=row)
    return {"ok": True}
