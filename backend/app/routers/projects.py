"""Projetos/clientes do usuário: agrupam tarefas pontuais (filtro no quadro,
no relatório e nas ferramentas da IA). Arquivar esconde dos seletores sem
apagar nada; excluir tira o projeto das tarefas (ficam "sem projeto")."""
from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg.errors import UniqueViolation

from .. import audit, db
from ..deps import active_user, active_user_csrf
from ..schemas import ProjectIn, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])

COLS = "id, name, color, description, archived, external_ref"
PALETA = ["#5294E2", "#81C995", "#FDD663", "#C58AF9", "#F28B82", "#78D9EC", "#F6AE6B", "#A1A1A8"]


@router.get("")
def list_projects(include_archived: bool = False, user=Depends(active_user)):
    return db.query_all(
        f"""
        SELECT p.id, p.name, p.color, p.description, p.archived, p.created_at,
               count(w.id) FILTER (WHERE w.status <> 'done')::int AS open_tasks,
               count(w.id)::int AS total_tasks,
               count(w.id) FILTER (WHERE w.status = 'done')::int AS done_tasks,
               (SELECT count(*) FROM project_objectives o WHERE o.project_id = p.id)::int AS objectives
          FROM projects p
          LEFT JOIN worklog_tasks w ON w.project_id = p.id
            OR w.id IN (SELECT x.task_id FROM worklog_task_projects x WHERE x.project_id = p.id)
         WHERE p.user_id = %s {'' if include_archived else 'AND NOT p.archived'}
         GROUP BY p.id
         ORDER BY p.archived, lower(p.name)
        """,
        (user["user_id"],),
    )


def same_name(uid: int, name: str, other_than=None):
    """Projeto da pessoa com esse nome, sem diferenciar maiúsculas e acentos (como a busca)."""
    return db.query_one(
        f"""SELECT {COLS} FROM projects WHERE user_id = %s AND nx_fold(name) = nx_fold(%s) AND id IS DISTINCT FROM %s
             ORDER BY (name = %s) DESC LIMIT 1""", (uid, name.strip(), other_than, name.strip()))


def by_ref(uid: int, ref):
    return ref and db.query_one(f"SELECT {COLS} FROM projects WHERE user_id = %s AND external_ref = %s", (uid, ref))


@router.post("", status_code=201)
def create_project(data: ProjectIn, response: Response, user=Depends(active_user_csrf)):
    """Cria o projeto. Com external_ref já usado pela pessoa, devolve o que
    existe (200, existing=true) em vez de duplicar."""
    uid = user["user_id"]
    if found := by_ref(uid, data.external_ref):
        response.status_code = 200
        return {**found, "existing": True}
    if same_name(uid, data.name):
        raise HTTPException(status_code=409, detail="já existe um projeto com esse nome")
    color = data.color
    if not color:
        n = db.query_one("SELECT count(*) AS n FROM projects WHERE user_id = %s", (uid,))["n"]
        color = PALETA[n % len(PALETA)]
    try:
        row = db.query_one(
            f"""INSERT INTO projects (user_id, name, color, description, external_ref) VALUES (%s, %s, %s, %s, %s)
                RETURNING {COLS}""",
            (uid, data.name.strip(), color, (data.description or "").strip() or None, data.external_ref),
        )
    except UniqueViolation:
        if found := by_ref(uid, data.external_ref):  # duas chamadas iguais ao mesmo tempo
            response.status_code = 200
            return {**found, "existing": True}
        raise HTTPException(status_code=409, detail="já existe um projeto com esse nome") from None
    audit.record(user, "project.create", "project", row["id"], after=row)
    return row


@router.patch("/{project_id}")
def update_project(project_id: int, data: ProjectUpdate, user=Depends(active_user_csrf)):
    uid = user["user_id"]
    before = db.query_one(f"SELECT {COLS} FROM projects WHERE id = %s AND user_id = %s", (project_id, uid))
    if not before:
        raise HTTPException(status_code=404, detail="não encontrado")
    new = {
        "name": data.name.strip() if data.name is not None else before["name"],
        "color": data.color or before["color"],
        "description": ((data.description or "").strip() or None) if "description" in data.model_fields_set
        else before["description"],
        "archived": data.archived if data.archived is not None else before["archived"],
    }
    if same_name(uid, new["name"], other_than=project_id):
        raise HTTPException(status_code=409, detail="já existe um projeto com esse nome")
    try:
        db.execute("UPDATE projects SET name = %s, color = %s, description = %s, archived = %s WHERE id = %s",
                   (new["name"], new["color"], new["description"], new["archived"], project_id))
    except UniqueViolation:
        raise HTTPException(status_code=409, detail="já existe um projeto com esse nome") from None
    after = {"id": project_id, **new, "external_ref": before["external_ref"]}
    audit.record(user, "project.update", "project", project_id, before=before, after=after)
    return after


@router.delete("/{project_id}")
def delete_project(project_id: int, user=Depends(active_user_csrf)):
    uid = user["user_id"]
    if not db.query_one("SELECT 1 FROM projects WHERE id = %s AND user_id = %s", (project_id, uid)):
        raise HTTPException(status_code=404, detail="não encontrado")
    # Os objetivos vão junto (CASCADE); guardamos com as tarefas deles para o desfazer.
    objectives = db.query_all(
        "SELECT id, project_id, title, description, due_date, position, created_at, external_ref FROM project_objectives WHERE project_id = %s",
        (project_id,))
    for o in objectives:
        o["tasks"] = db.query_all("SELECT id, exec_position FROM worklog_tasks WHERE objective_id = %s", (o["id"],))
    extra_tasks = [r["task_id"] for r in db.query_all(
        "SELECT task_id FROM worklog_task_projects WHERE project_id = %s", (project_id,))]
    # Tarefa com outros projetos não fica "sem projeto": o primeiro extra vira o principal.
    promoted = db.query_all(
        """UPDATE worklog_tasks w
              SET project_id = (SELECT min(x.project_id) FROM worklog_task_projects x WHERE x.task_id = w.id)
            WHERE w.user_id = %s AND w.project_id = %s
              AND EXISTS (SELECT 1 FROM worklog_task_projects x WHERE x.task_id = w.id)
        RETURNING w.id, w.project_id""", (uid, project_id))
    for t in promoted:
        db.execute("DELETE FROM worklog_task_projects WHERE task_id = %s AND project_id = %s", (t["id"], t["project_id"]))
    tasks = [r["id"] for r in db.query_all(
        "SELECT id FROM worklog_tasks WHERE user_id = %s AND project_id = %s", (uid, project_id))]
    row = db.query_one(
        f"DELETE FROM projects WHERE id = %s AND user_id = %s RETURNING {COLS}",
        (project_id, user["user_id"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="não encontrado")
    # As tarefas ficam sem projeto (FK SET NULL); guardamos quais eram para o desfazer.
    row["task_ids"] = [r["id"] for r in db.query_all(
        "SELECT id FROM worklog_tasks WHERE user_id = %s AND project_id IS NULL AND id = ANY(%s)",
        (user["user_id"], tasks))]
    row["promoted"], row["extra_task_ids"] = promoted, extra_tasks
    row["objectives"] = objectives
    audit.record(user, "project.delete", "project", project_id, before=row)
    return {"ok": True}
