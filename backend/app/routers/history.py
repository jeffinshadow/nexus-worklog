"""Histórico de ações do próprio usuário e "desfazer".

Desfazer só vale para a alteração MAIS RECENTE de cada item (tarefa,
recorrente, configuração): desfazer uma alteração antiga por cima de mudanças
posteriores apagaria trabalho sem aviso. O próprio desfazer fica registrado
(ação "undo") e não pode ser desfeito de novo.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import audit, db
from ..deps import active_user, active_user_csrf

router = APIRouter(prefix="/api/history", tags=["history"])

UNDOABLE = {
    "worklog.create", "worklog.update", "worklog.finish", "worklog.delete",
    "recurring.create", "recurring.update", "recurring.deactivate", "recurring.toggle",
    "settings.update",
    "note.create", "note.delete", "checklist.create", "checklist.update", "checklist.delete",
    "time.create", "time.delete", "project.create", "project.update", "project.delete",
}

ACTION_LABELS = {
    "worklog.create": "criou a tarefa",
    "worklog.update": "editou a tarefa",
    "worklog.finish": "concluiu a tarefa",
    "worklog.delete": "excluiu a tarefa",
    "recurring.create": "criou a recorrente",
    "recurring.update": "editou a recorrente",
    "recurring.deactivate": "removeu a recorrente",
    "recurring.toggle": "marcou a recorrente",
    "settings.update": "alterou os dias úteis",
    "note.create": "anotou na tarefa",
    "note.delete": "apagou uma anotação da tarefa",
    "checklist.create": "adicionou o item",
    "checklist.update": "editou o item",
    "checklist.delete": "removeu o item",
    "time.create": "apontou tempo em",
    "time.delete": "apagou um apontamento de",
    "project.create": "criou o projeto",
    "project.update": "editou o projeto",
    "project.delete": "excluiu o projeto",
    "token.create": "criou a chave de API",
    "token.revoke": "revogou a chave de API",
    "user.invite": "criou a conta (convite)",
    "user.reset_password": "redefiniu a senha",
    "branding.update": "alterou os textos da identidade visual",
    "branding.logo": "enviou um novo logo",
    "branding.logo_reset": "restaurou o logo padrão",
    "undo": "desfez uma ação",
}


def _label(row) -> str:
    snap = row["after"] or row["before"] or {}
    name = snap.get("title") or snap.get("label") or snap.get("name") or ""
    if row["action"] == "undo":
        return "desfez uma ação"
    if row["action"].startswith("checklist."):
        item = snap.get("label") or ""
        if row["action"] == "checklist.update" and row["after"] and row["before"]:
            if row["after"].get("done") != row["before"].get("done"):
                verbo = "concluiu o item" if row["after"].get("done") else "reabriu o item"
                return f"{verbo} “{item}” em “{snap.get('title', '')}”"
        return f"{ACTION_LABELS[row['action']]} “{item}” em “{snap.get('title', '')}”"
    if row["action"] in ("time.create", "time.delete"):
        m = snap.get("minutes") or 0
        dur = f"{m // 60}h{m % 60:02d}" if m >= 60 else f"{m} min"
        return f"{ACTION_LABELS[row['action']]} “{snap.get('title', '')}” ({dur})"
    text = ACTION_LABELS.get(row["action"], row["action"])
    if row["action"] == "recurring.toggle" and row["after"]:
        text = ("marcou" if row["after"]["done"] else "desmarcou") + " a recorrente"
        name = f"{name} em {row['after']['day']}" if name else row["after"]["day"]
    return f"{text} “{name}”" if name else text


def _latest_ids(user_id: int) -> set[int]:
    """Última ação (não desfeita, não-undo) de cada item."""
    rows = db.query_all(
        """
        SELECT DISTINCT ON (entity, entity_id) id
          FROM audit_log
         WHERE user_id = %s AND action <> 'undo' AND undone_at IS NULL
         ORDER BY entity, entity_id, id DESC
        """,
        (user_id,),
    )
    return {r["id"] for r in rows}


def _with_names(user_id: int, rows: list) -> list:
    # Para toggles, o snapshot só tem dia/feito: busca o rótulo da recorrente.
    ids = {r["entity_id"] for r in rows if r["action"] == "recurring.toggle"}
    labels = {}
    if ids:
        for r in db.query_all(
            "SELECT id, label FROM recurring_tasks WHERE user_id = %s AND id = ANY(%s)",
            (user_id, list(ids)),
        ):
            labels[r["id"]] = r["label"]
    for r in rows:
        if r["action"] == "recurring.toggle" and r["after"] is not None:
            r["after"] = {**r["after"], "label": labels.get(r["entity_id"], "")}
    return rows


@router.get("")
def list_history(
    limit: int = Query(default=50, ge=1, le=200),
    entity: Optional[str] = None,
    entity_id: Optional[int] = None,
    user=Depends(active_user),
):
    cond, params = ["user_id = %s"], [user["user_id"]]
    if entity:
        cond.append("entity = %s")
        params.append(entity)
    if entity_id is not None:
        cond.append("entity_id = %s")
        params.append(entity_id)
    rows = db.query_all(
        f"""
        SELECT id, created_at, actor, token_name, action, entity, entity_id,
               before, after, undone_at
          FROM audit_log
         WHERE {' AND '.join(cond)}
         ORDER BY id DESC
         LIMIT %s
        """,
        (*params, limit),
    )
    rows = _with_names(user["user_id"], rows)
    latest = _latest_ids(user["user_id"])
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "created_at": r["created_at"],
            "actor": r["actor"],
            "token_name": r["token_name"],
            "action": r["action"],
            "entity": r["entity"],
            "entity_id": r["entity_id"],
            "summary": _label(r),
            "undone": r["undone_at"] is not None,
            "can_undo": r["action"] in UNDOABLE and r["undone_at"] is None and r["id"] in latest,
        })
    return out


def _projeto_existente(uid: int, project_id):
    """Ao desfazer, o projeto antigo pode ter sido excluído: volta sem projeto."""
    if project_id is None:
        return None
    ok = db.query_one("SELECT 1 FROM projects WHERE id = %s AND user_id = %s", (project_id, uid))
    return project_id if ok else None


def _restore_worklog(uid: int, snap: dict) -> None:
    db.execute(
        """UPDATE worklog_tasks
              SET title = %s, description = %s, status = %s, due_date = %s, completed_at = %s,
                  project_id = %s, priority = %s
            WHERE id = %s AND user_id = %s""",
        (snap["title"], snap["description"], snap["status"], snap["due_date"],
         snap["completed_at"], _projeto_existente(uid, snap.get("project_id")),
         snap.get("priority") or 2, snap["id"], uid),
    )


def _restore_recurring(uid: int, snap: dict) -> None:
    db.execute(
        """UPDATE recurring_tasks
              SET label = %s, position = %s, active = %s, created_at = %s, deactivated_at = %s,
                  freq = %s, weekdays = %s, month_day = %s, interval_days = %s
            WHERE id = %s AND user_id = %s""",
        (snap["label"], snap["position"], snap["active"], snap["created_at"],
         snap["deactivated_at"], snap.get("freq") or "daily", snap.get("weekdays"),
         snap.get("month_day"), snap.get("interval_days"), snap["id"], uid),
    )


def _need_task(uid: int, task_id: int) -> None:
    if not audit.worklog_snapshot(task_id, uid):
        raise HTTPException(status_code=409, detail="a tarefa não existe mais")


@router.post("/{history_id}/undo")
def undo(history_id: int, user=Depends(active_user_csrf)):
    uid = user["user_id"]
    row = db.query_one(
        "SELECT * FROM audit_log WHERE id = %s AND user_id = %s", (history_id, uid)
    )
    if not row:
        raise HTTPException(status_code=404, detail="nao encontrado")
    if row["action"] not in UNDOABLE:
        raise HTTPException(status_code=400, detail="esta ação não pode ser desfeita")
    if row["undone_at"] is not None:
        raise HTTPException(status_code=409, detail="esta ação já foi desfeita")
    if history_id not in _latest_ids(uid):
        raise HTTPException(status_code=409, detail="houve alterações depois desta; desfaça as mais recentes primeiro")

    a, before, after, eid = row["action"], row["before"], row["after"], row["entity_id"]
    if a == "worklog.create":
        db.execute("DELETE FROM worklog_tasks WHERE id = %s AND user_id = %s", (eid, uid))
    elif a in ("worklog.update", "worklog.finish"):
        if not audit.worklog_snapshot(eid, uid):
            raise HTTPException(status_code=409, detail="a tarefa não existe mais")
        _restore_worklog(uid, before)
    elif a == "worklog.delete":
        if audit.worklog_snapshot(eid, uid) or db.query_one("SELECT 1 FROM worklog_tasks WHERE id = %s", (eid,)):
            raise HTTPException(status_code=409, detail="a tarefa já existe")
        db.execute(
            """INSERT INTO worklog_tasks (id, user_id, title, description, status, due_date,
                                          created_at, completed_at, project_id, priority)
               OVERRIDING SYSTEM VALUE
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (eid, uid, before["title"], before["description"], before["status"],
             before["due_date"], before["created_at"], before["completed_at"],
             _projeto_existente(uid, before.get("project_id")), before.get("priority") or 2),
        )
    elif a == "recurring.create":
        has_done = db.query_one("SELECT 1 FROM recurring_completions WHERE task_id = %s LIMIT 1", (eid,))
        if has_done:
            db.execute(
                """UPDATE recurring_tasks SET active = false,
                          deactivated_at = COALESCE(deactivated_at, now())
                    WHERE id = %s AND user_id = %s""", (eid, uid))
        else:
            db.execute("DELETE FROM recurring_tasks WHERE id = %s AND user_id = %s", (eid, uid))
    elif a in ("recurring.update", "recurring.deactivate"):
        _restore_recurring(uid, before)
    elif a == "recurring.toggle":
        day = date.fromisoformat(before["day"])
        if before["done"]:
            db.execute(
                """INSERT INTO recurring_completions (task_id, user_id, completed_date)
                   VALUES (%s, %s, %s) ON CONFLICT (task_id, completed_date) DO NOTHING""",
                (eid, uid, day))
        else:
            db.execute(
                "DELETE FROM recurring_completions WHERE task_id = %s AND completed_date = %s",
                (eid, day))
    elif a == "settings.update":
        db.execute("UPDATE users SET work_days = %s WHERE id = %s", (before["work_days"], uid))
    elif a == "note.create":
        db.execute("DELETE FROM task_notes WHERE id = %s AND user_id = %s", (eid, uid))
    elif a == "note.delete":
        _need_task(uid, before["task_id"])
        db.execute(
            """INSERT INTO task_notes (id, task_id, user_id, body, actor, token_name, created_at)
               OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (eid, before["task_id"], uid, before["body"], before["actor"], before["token_name"], before["created_at"]))
    elif a == "checklist.create":
        db.execute("DELETE FROM task_checklist WHERE id = %s AND user_id = %s", (eid, uid))
    elif a == "checklist.update":
        db.execute("UPDATE task_checklist SET label = %s, done = %s WHERE id = %s AND user_id = %s",
                   (before["label"], before["done"], eid, uid))
    elif a == "checklist.delete":
        _need_task(uid, before["task_id"])
        db.execute(
            """INSERT INTO task_checklist (id, task_id, user_id, label, done, position)
               OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s, %s)""",
            (eid, before["task_id"], uid, before["label"], before["done"], before["position"]))
    elif a == "time.create":
        db.execute("DELETE FROM time_entries WHERE id = %s AND user_id = %s", (eid, uid))
    elif a == "time.delete":
        _need_task(uid, before["task_id"])
        db.execute(
            """INSERT INTO time_entries (id, task_id, user_id, minutes, day, note, actor, token_name, created_at)
               OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (eid, before["task_id"], uid, before["minutes"], before["day"], before["note"],
             before["actor"], before["token_name"], before["created_at"]))
    elif a == "project.create":
        # Com tarefas no projeto, arquiva em vez de apagar (não tira de ninguém).
        if db.query_one("SELECT 1 FROM worklog_tasks WHERE project_id = %s LIMIT 1", (eid,)):
            db.execute("UPDATE projects SET archived = true WHERE id = %s AND user_id = %s", (eid, uid))
        else:
            db.execute("DELETE FROM projects WHERE id = %s AND user_id = %s", (eid, uid))
    elif a == "project.update":
        db.execute("UPDATE projects SET name = %s, color = %s, archived = %s WHERE id = %s AND user_id = %s",
                   (before["name"], before["color"], before["archived"], eid, uid))
    elif a == "project.delete":
        if db.query_one("SELECT 1 FROM projects WHERE user_id = %s AND name = %s", (uid, before["name"])):
            raise HTTPException(status_code=409, detail="já existe um projeto com esse nome")
        db.execute(
            """INSERT INTO projects (id, user_id, name, color, archived)
               OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s)""",
            (eid, uid, before["name"], before["color"], before["archived"]))

    db.execute("UPDATE audit_log SET undone_at = now() WHERE id = %s", (history_id,))
    audit.record(user, "undo", row["entity"], eid, before=after, after={"undid": history_id, "action": a})
    return {"ok": True, "undid": history_id, "action": a}
