"""Objetivos do projeto: as demandas principais, em ordem de execução, com as
tarefas vinculadas (também em ordem). A tarefa fica em um objetivo do seu
projeto principal, ou em nenhum ("Sem objetivo"). Progresso e status do
objetivo saem das tarefas: nada a marcar à mão."""
from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db
from ..deps import active_user, active_user_csrf
from ..schemas import ObjectiveIn, ObjectiveUpdate, OrderIn, TaskOrderIn
from ..services import ASSIGNER_NAME, TASK_COUNTS

router = APIRouter(prefix="/api", tags=["objectives"])

COLS = "id, project_id, title, description, due_date, position, created_at"
DONE_SHOWN = 30  # concluídas por bloco (as mais recentes)


def own_project(uid: int, project_id: int) -> dict:
    row = db.query_one("SELECT id, name, color, archived FROM projects WHERE id = %s AND user_id = %s", (project_id, uid))
    if not row:
        raise HTTPException(status_code=404, detail="projeto não encontrado")
    return row


def own_objective(uid: int, objective_id: int) -> dict:
    row = db.query_one(f"SELECT {COLS} FROM project_objectives WHERE id = %s AND user_id = %s", (objective_id, uid))
    if not row:
        raise HTTPException(status_code=404, detail="objetivo não encontrado")
    return row


def check_objective(uid: int, objective_id, project_id) -> None:
    """O objetivo existe, é da pessoa e é do projeto principal da tarefa."""
    if objective_id is None:
        return
    o = db.query_one("SELECT project_id FROM project_objectives WHERE id = %s AND user_id = %s", (objective_id, uid))
    if not o:
        raise HTTPException(status_code=400, detail="objetivo não encontrado")
    if o["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="o objetivo é de outro projeto")


def objective_project(uid: int, objective_id: int):
    o = db.query_one("SELECT project_id FROM project_objectives WHERE id = %s AND user_id = %s", (objective_id, uid))
    if not o:
        raise HTTPException(status_code=400, detail="objetivo não encontrado")
    return o["project_id"]


def next_position(uid: int, project_id, objective_id) -> int | None:
    """Fim da fila do bloco (objetivo, ou "Sem objetivo" do projeto)."""
    if project_id is None:
        return None
    row = db.query_one(
        """SELECT COALESCE(max(exec_position), -1) + 1 AS n FROM worklog_tasks
            WHERE user_id = %s AND project_id = %s AND objective_id IS NOT DISTINCT FROM %s""",
        (uid, project_id, objective_id))
    return row["n"]


def status_of(total: int, done: int, started: bool) -> str:
    if total and done == total:
        return "done"
    return "in_progress" if done or started else "todo"


_TASK_SELECT = """
    SELECT w.id, w.title, w.description, w.status, w.due_date, w.created_at, w.completed_at,
           w.priority, w.project_id, w.ticket, w.after_hours, w.assigned_by, w.blocked_reason, w.blocked_at,
           w.follow_up_on, w.objective_id, w.exec_position,
           p.name AS project_name, p.color AS project_color, """ + ASSIGNER_NAME + ", " + TASK_COUNTS + """
      FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id
     WHERE w.user_id = %s AND w.project_id = %s"""


@router.get("/projects/{project_id}/overview")
def overview(project_id: int, user=Depends(active_user)):
    """A tela do projeto: os objetivos na ordem de execução, cada um com o
    progresso, o status e as tarefas (abertas na ordem; concluídas recentes),
    e o bloco "Sem objetivo"."""
    uid = user["user_id"]
    project = own_project(uid, project_id)
    objectives = db.query_all(
        f"SELECT {COLS} FROM project_objectives WHERE user_id = %s AND project_id = %s ORDER BY position, id",
        (uid, project_id))
    open_tasks = db.query_all(_TASK_SELECT + " AND w.status <> 'done' ORDER BY w.exec_position NULLS LAST, w.created_at",
                              (uid, project_id))
    done_tasks = db.query_all(_TASK_SELECT + " AND w.status = 'done' ORDER BY w.completed_at DESC NULLS LAST",
                              (uid, project_id))

    def block(oid):
        abertas = [t for t in open_tasks if t["objective_id"] == oid]
        feitas = [t for t in done_tasks if t["objective_id"] == oid]
        total = len(abertas) + len(feitas)
        started = any(t["status"] != "todo" for t in abertas)
        return {"total": total, "done": len(feitas), "status": status_of(total, len(feitas), started),
                "tasks": abertas, "done_tasks": feitas[:DONE_SHOWN]}

    out = [{**o, **block(o["id"])} for o in objectives]
    return {
        "project": project,
        "objectives": out,
        "unassigned": block(None),
        "totals": {"total": len(open_tasks) + len(done_tasks), "done": len(done_tasks),
                   "objectives_open": sum(1 for o in out if o["status"] != "done")},
    }


@router.get("/projects/{project_id}/objectives")
def list_objectives(project_id: int, user=Depends(active_user)):
    """Os objetivos do projeto, na ordem (para os seletores)."""
    own_project(user["user_id"], project_id)
    return db.query_all(
        f"SELECT {COLS} FROM project_objectives WHERE user_id = %s AND project_id = %s ORDER BY position, id",
        (user["user_id"], project_id))


@router.post("/projects/{project_id}/objectives", status_code=201)
def create_objective(project_id: int, data: ObjectiveIn, user=Depends(active_user_csrf)):
    uid = user["user_id"]
    own_project(uid, project_id)
    row = db.query_one(
        f"""INSERT INTO project_objectives (user_id, project_id, title, description, due_date, position)
            VALUES (%s, %s, %s, %s, %s,
                    (SELECT COALESCE(max(position), -1) + 1 FROM project_objectives WHERE project_id = %s))
            RETURNING {COLS}""",
        (uid, project_id, data.title.strip(), (data.description or "").strip() or None, data.due_date, project_id))
    audit.record(user, "objective.create", "objective", row["id"], after=row)
    return row


@router.patch("/objectives/{objective_id}")
def update_objective(objective_id: int, data: ObjectiveUpdate, user=Depends(active_user_csrf)):
    uid = user["user_id"]
    before = own_objective(uid, objective_id)
    sent = data.model_fields_set
    new = {
        "title": data.title.strip() if data.title is not None else before["title"],
        "description": ((data.description or "").strip() or None) if "description" in sent else before["description"],
        "due_date": data.due_date if "due_date" in sent else before["due_date"],
    }
    db.execute("""UPDATE project_objectives SET title = %s, description = %s, due_date = %s, updated_at = now()
                   WHERE id = %s AND user_id = %s""",
               (new["title"], new["description"], new["due_date"], objective_id, uid))
    after = own_objective(uid, objective_id)
    audit.record(user, "objective.update", "objective", objective_id, before=before, after=after)
    return after


@router.delete("/objectives/{objective_id}")
def delete_objective(objective_id: int, user=Depends(active_user_csrf)):
    """As tarefas continuam no projeto, em "Sem objetivo" (no fim da fila)."""
    uid = user["user_id"]
    before = own_objective(uid, objective_id)
    tasks = db.query_all(
        "SELECT id, exec_position FROM worklog_tasks WHERE user_id = %s AND objective_id = %s ORDER BY exec_position NULLS LAST, id",
        (uid, objective_id))
    start = next_position(uid, before["project_id"], None)
    for i, t in enumerate(tasks):
        db.execute("UPDATE worklog_tasks SET objective_id = NULL, exec_position = %s WHERE id = %s", (start + i, t["id"]))
    db.execute("DELETE FROM project_objectives WHERE id = %s AND user_id = %s", (objective_id, uid))
    audit.record(user, "objective.delete", "objective", objective_id,
                 before={**before, "tasks": [{"id": t["id"], "exec_position": t["exec_position"]} for t in tasks]})
    return {"ok": True, "tasks": len(tasks)}


@router.post("/projects/{project_id}/objectives/order")
def order_objectives(project_id: int, data: OrderIn, user=Depends(active_user_csrf)):
    """Ordem de execução dos objetivos (a lista inteira, na ordem nova)."""
    uid = user["user_id"]
    own_project(uid, project_id)
    ids = {r["id"] for r in db.query_all("SELECT id FROM project_objectives WHERE user_id = %s AND project_id = %s",
                                         (uid, project_id))}
    if set(data.ids) != ids or len(data.ids) != len(ids):
        raise HTTPException(status_code=400, detail="mande todos os objetivos do projeto, cada um uma vez")
    for i, oid in enumerate(data.ids):
        db.execute("UPDATE project_objectives SET position = %s WHERE id = %s", (i, oid))
    return {"ok": True}


@router.post("/projects/{project_id}/tasks/order")
def order_tasks(project_id: int, data: TaskOrderIn, user=Depends(active_user_csrf)):
    """Ordem de execução das tarefas de um bloco (objetivo ou "Sem objetivo").
    Tarefa que vem de outro bloco muda de objetivo (fica no histórico, com desfazer)."""
    uid = user["user_id"]
    own_project(uid, project_id)
    if data.objective_id is not None:
        check_objective(uid, data.objective_id, project_id)
    if len(set(data.task_ids)) != len(data.task_ids):
        raise HTTPException(status_code=400, detail="tarefa repetida na lista")
    rows = {r["id"]: r for r in db.query_all(
        "SELECT id, objective_id FROM worklog_tasks WHERE user_id = %s AND project_id = %s AND id = ANY(%s)",
        (uid, project_id, data.task_ids))}
    if len(rows) != len(data.task_ids):
        raise HTTPException(status_code=400, detail="tarefa de outro projeto ou inexistente")
    for i, tid in enumerate(data.task_ids):
        moved = rows[tid]["objective_id"] != data.objective_id
        before = audit.worklog_snapshot(tid, uid) if moved else None
        db.execute("UPDATE worklog_tasks SET objective_id = %s, exec_position = %s WHERE id = %s",
                   (data.objective_id, i, tid))
        if moved:
            audit.record(user, "worklog.update", "worklog", tid, before=before, after=audit.worklog_snapshot(tid, uid))
    return {"ok": True}
