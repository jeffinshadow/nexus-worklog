"""Projetos/clientes do usuário: agrupam tarefas pontuais (filtro no quadro,
no relatório e nas ferramentas da IA). Arquivar esconde dos seletores sem
apagar nada; excluir tira o projeto das tarefas (ficam "sem projeto")."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg.errors import UniqueViolation

from .. import audit, db
from ..deps import active_user, active_user_csrf
from ..schemas import ArchiveIn, ProjectIn, ProjectUpdate, WorklogUpdate
from ..services import project_rows
from .worklog import finish, update

router = APIRouter(prefix="/api/projects", tags=["projects"])

COLS = "id, name, color, COALESCE(icon, 'pasta') AS icon, description, archived, external_ref"
PALETA = ["#5294E2", "#81C995", "#FDD663", "#C58AF9", "#F28B82", "#78D9EC", "#F6AE6B", "#A1A1A8"]


@router.get("")
def list_projects(include_archived: bool = False, external_ref: Optional[str] = None, user=Depends(active_user)):
    """Com external_ref: só o projeto com essa chave, arquivado ou não (lista vazia se não houver).
    Números: open_tasks/waiting_tasks/done_tasks/total_tasks (principal e extras), minutes_month
    (tempo apontado no mês corrente), objectives/objectives_done e last_activity."""
    uid = user["user_id"]
    if external_ref is not None:
        found = by_ref(uid, external_ref.strip())
        return project_rows(uid, only_id=found["id"]) if found else []
    return project_rows(uid, include_archived)


def _icon(name):
    """No banco, a pasta (o padrão) fica NULL."""
    return None if name in (None, "pasta") else name


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
            f"""INSERT INTO projects (user_id, name, color, icon, description, external_ref)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING {COLS}""",
            (uid, data.name.strip(), color, _icon(data.icon), (data.description or "").strip() or None,
             data.external_ref),
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
        raise HTTPException(status_code=404, detail="projeto não encontrado (pode ter sido excluído); atualize a tela")
    new = {
        "name": data.name.strip() if data.name is not None else before["name"],
        "color": data.color or before["color"],
        "icon": (data.icon or "pasta") if "icon" in data.model_fields_set else before["icon"],
        "description": ((data.description or "").strip() or None) if "description" in data.model_fields_set
        else before["description"],
        "archived": data.archived if data.archived is not None else before["archived"],
    }
    if same_name(uid, new["name"], other_than=project_id):
        raise HTTPException(status_code=409, detail="já existe um projeto com esse nome")
    try:
        db.execute("UPDATE projects SET name = %s, color = %s, icon = %s, description = %s, archived = %s WHERE id = %s",
                   (new["name"], new["color"], _icon(new["icon"]), new["description"], new["archived"], project_id))
    except UniqueViolation:
        raise HTTPException(status_code=409, detail="já existe um projeto com esse nome") from None
    after = {"id": project_id, **new, "external_ref": before["external_ref"]}
    audit.record(user, "project.update", "project", project_id, before=before, after=after)
    return after


@router.post("/{project_id}/archive")
def archive_project(project_id: int, data: ArchiveIn, user=Depends(active_user_csrf)):
    """Arquiva o projeto e decide o que acontece com as tarefas em aberto que o
    têm como principal: keep (continuam como estão), done (concluídas agora) ou
    move (vão para o projeto move_to, no fim da fila "Sem objetivo"). Cada tarefa
    mexida entra no histórico como se fosse pela tela (dá para desfazer uma a uma).
    Onde o projeto é só um dos extras, a tarefa segue no principal dela."""
    uid = user["user_id"]
    before = db.query_one(f"SELECT {COLS} FROM projects WHERE id = %s AND user_id = %s", (project_id, uid))
    if not before:
        raise HTTPException(status_code=404, detail="projeto não encontrado (pode ter sido excluído); atualize a tela")
    if data.open_tasks == "move":
        alvo = db.query_one("SELECT id, archived FROM projects WHERE id = %s AND user_id = %s", (data.move_to, uid))
        if not alvo or alvo["id"] == project_id:
            raise HTTPException(status_code=400, detail="escolha outro projeto seu para receber as tarefas")
        if alvo["archived"]:
            raise HTTPException(status_code=400, detail="o projeto que recebe as tarefas está arquivado")
    ids = [r["id"] for r in db.query_all(
        """SELECT id FROM worklog_tasks WHERE user_id = %s AND project_id = %s AND status <> 'done'
            ORDER BY objective_id NULLS LAST, exec_position NULLS LAST, created_at""", (uid, project_id))]
    if data.open_tasks == "done":
        for tid in ids:
            finish(tid, None, user=user)
    elif data.open_tasks == "move":
        for tid in ids:
            update(tid, WorklogUpdate(project_id=data.move_to), user=user)
    if not before["archived"]:
        update_project(project_id, ProjectUpdate(archived=True), user=user)
    return {"ok": True, "open_tasks": len(ids), "done": len(ids) if data.open_tasks == "done" else 0,
            "moved": len(ids) if data.open_tasks == "move" else 0,
            "kept": len(ids) if data.open_tasks == "keep" else 0}


@router.delete("/{project_id}")
def delete_project(project_id: int, user=Depends(active_user_csrf)):
    uid = user["user_id"]
    if not db.query_one("SELECT 1 FROM projects WHERE id = %s AND user_id = %s", (project_id, uid)):
        raise HTTPException(status_code=404, detail="projeto não encontrado (pode ter sido excluído); atualize a tela")
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
        raise HTTPException(status_code=404, detail="projeto não encontrado (pode ter sido excluído); atualize a tela")
    # As tarefas ficam sem projeto (FK SET NULL); guardamos quais eram para o desfazer.
    row["task_ids"] = [r["id"] for r in db.query_all(
        "SELECT id FROM worklog_tasks WHERE user_id = %s AND project_id IS NULL AND id = ANY(%s)",
        (user["user_id"], tasks))]
    row["promoted"], row["extra_task_ids"] = promoted, extra_tasks
    row["objectives"] = objectives
    audit.record(user, "project.delete", "project", project_id, before=row)
    return {"ok": True}
