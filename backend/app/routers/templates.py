"""Modelos de tarefa: procedimentos que se repetem (onboarding de usuário, troca
de equipamento, servidor novo) com título, prioridade, projeto e checklist.
Usar um modelo cria uma tarefa comum, com os itens do checklist.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg.types.json import Jsonb

from .. import audit, db
from ..deps import active_user, active_user_csrf
from ..schemas import ChecklistIn, TemplateIn, WorklogIn
from .worklog import _check_project, add_item, create

router = APIRouter(prefix="/api/templates", tags=["templates"])

MAX_TEMPLATES = 50
_COLS = "id, name, title, description, priority, project_id, after_hours, checklist, created_at, updated_at"


def _own(uid: int, tid: int) -> dict:
    row = db.query_one(f"SELECT {_COLS} FROM task_templates WHERE id = %s AND user_id = %s", (tid, uid))
    if not row:
        raise HTTPException(status_code=404, detail="modelo não encontrado")
    return row


def _name_free(uid: int, name: str, except_id: int | None = None) -> None:
    if db.query_one("SELECT 1 FROM task_templates WHERE user_id = %s AND lower(name) = lower(%s) AND id <> %s",
                    (uid, name, except_id or 0)):
        raise HTTPException(status_code=409, detail="já existe um modelo com esse nome")


@router.get("")
def list_templates(user=Depends(active_user)):
    return db.query_all(f"SELECT {_COLS} FROM task_templates WHERE user_id = %s ORDER BY lower(name)", (user["user_id"],))


@router.post("", status_code=201)
def create_template(data: TemplateIn, user=Depends(active_user_csrf)):
    uid = user["user_id"]
    if db.query_one("SELECT count(*)::int AS n FROM task_templates WHERE user_id = %s", (uid,))["n"] >= MAX_TEMPLATES:
        raise HTTPException(status_code=400, detail=f"até {MAX_TEMPLATES} modelos")
    _check_project(uid, data.project_id)
    _name_free(uid, data.name)
    row = db.query_one(
        f"""INSERT INTO task_templates (user_id, name, title, description, priority, project_id, after_hours, checklist)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_COLS}""",
        (uid, data.name, data.title, data.description or None, data.priority, data.project_id,
         data.after_hours, Jsonb(data.checklist)),
    )
    audit.record(user, "template.create", "template", row["id"], after={"name": row["name"]})
    return row


@router.put("/{tid}")
def update_template(tid: int, data: TemplateIn, user=Depends(active_user_csrf)):
    uid = user["user_id"]
    before = _own(uid, tid)
    _check_project(uid, data.project_id)
    _name_free(uid, data.name, tid)
    row = db.query_one(
        f"""UPDATE task_templates SET name = %s, title = %s, description = %s, priority = %s, project_id = %s,
                   after_hours = %s, checklist = %s, updated_at = now()
             WHERE id = %s AND user_id = %s RETURNING {_COLS}""",
        (data.name, data.title, data.description or None, data.priority, data.project_id,
         data.after_hours, Jsonb(data.checklist), tid, uid),
    )
    audit.record(user, "template.update", "template", tid, before={"name": before["name"]}, after={"name": row["name"]})
    return row


@router.delete("/{tid}")
def delete_template(tid: int, user=Depends(active_user_csrf)):
    before = _own(user["user_id"], tid)
    db.execute("DELETE FROM task_templates WHERE id = %s AND user_id = %s", (tid, user["user_id"]))
    audit.record(user, "template.delete", "template", tid, before={"name": before["name"]})
    return {"ok": True}


@router.post("/{tid}/use", status_code=201)
def use_template(tid: int, user=Depends(active_user_csrf)):
    """Cria a tarefa do modelo (e o checklist). Projeto arquivado/excluído: sai sem projeto."""
    t = _own(user["user_id"], tid)
    project = t["project_id"]
    if project and not db.query_one("SELECT 1 FROM projects WHERE id = %s AND NOT archived", (project,)):
        project = None
    res = create(WorklogIn(title=t["title"], description=t["description"], priority=t["priority"],
                           project_id=project, after_hours=t["after_hours"]), Response(), user=user)
    for label in t["checklist"]:
        add_item(res["id"], ChecklistIn(label=label), user=user)
    return {"id": res["id"], "checklist": len(t["checklist"])}
