"""Projetos/clientes do usuário: agrupam tarefas pontuais (filtro no quadro,
no relatório e nas ferramentas da IA). Arquivar esconde dos seletores sem
apagar nada; excluir tira o projeto das tarefas (ficam "sem projeto")."""
from fastapi import APIRouter, Depends, HTTPException
from psycopg.errors import UniqueViolation

from .. import audit, db
from ..deps import active_user, active_user_csrf
from ..schemas import ProjectIn, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])

PALETA = ["#5294E2", "#81C995", "#FDD663", "#C58AF9", "#F28B82", "#78D9EC", "#F6AE6B", "#A1A1A8"]


@router.get("")
def list_projects(include_archived: bool = False, user=Depends(active_user)):
    return db.query_all(
        f"""
        SELECT p.id, p.name, p.color, p.archived, p.created_at,
               count(w.id) FILTER (WHERE w.status <> 'done')::int AS open_tasks,
               count(w.id)::int AS total_tasks
          FROM projects p LEFT JOIN worklog_tasks w ON w.project_id = p.id
         WHERE p.user_id = %s {'' if include_archived else 'AND NOT p.archived'}
         GROUP BY p.id
         ORDER BY p.archived, lower(p.name)
        """,
        (user["user_id"],),
    )


@router.post("", status_code=201)
def create_project(data: ProjectIn, user=Depends(active_user_csrf)):
    uid = user["user_id"]
    color = data.color
    if not color:
        n = db.query_one("SELECT count(*) AS n FROM projects WHERE user_id = %s", (uid,))["n"]
        color = PALETA[n % len(PALETA)]
    try:
        row = db.query_one(
            "INSERT INTO projects (user_id, name, color) VALUES (%s, %s, %s) RETURNING id, name, color, archived",
            (uid, data.name.strip(), color),
        )
    except UniqueViolation:
        raise HTTPException(status_code=409, detail="já existe um projeto com esse nome") from None
    audit.record(user, "project.create", "project", row["id"], after=row)
    return row


@router.patch("/{project_id}")
def update_project(project_id: int, data: ProjectUpdate, user=Depends(active_user_csrf)):
    uid = user["user_id"]
    before = db.query_one("SELECT id, name, color, archived FROM projects WHERE id = %s AND user_id = %s", (project_id, uid))
    if not before:
        raise HTTPException(status_code=404, detail="nao encontrado")
    new = {
        "name": data.name.strip() if data.name is not None else before["name"],
        "color": data.color or before["color"],
        "archived": data.archived if data.archived is not None else before["archived"],
    }
    try:
        db.execute("UPDATE projects SET name = %s, color = %s, archived = %s WHERE id = %s",
                   (new["name"], new["color"], new["archived"], project_id))
    except UniqueViolation:
        raise HTTPException(status_code=409, detail="já existe um projeto com esse nome") from None
    audit.record(user, "project.update", "project", project_id, before=before, after={"id": project_id, **new})
    return {"id": project_id, **new}


@router.delete("/{project_id}")
def delete_project(project_id: int, user=Depends(active_user_csrf)):
    row = db.query_one(
        "DELETE FROM projects WHERE id = %s AND user_id = %s RETURNING id, name, color, archived",
        (project_id, user["user_id"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="nao encontrado")
    audit.record(user, "project.delete", "project", project_id, before=row)
    return {"ok": True}
