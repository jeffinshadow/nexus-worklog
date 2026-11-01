import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from psycopg.errors import UniqueViolation

from .. import audit, db
from ..deps import active_user, active_user_csrf
from ..schemas import ChecklistIn, ChecklistUpdate, FinishIn, NoteIn, TimeIn, WorklogIn, WorklogUpdate
from .assign import notify_assigner
from .objectives import check_objective, next_position, objective_project
from ..services import is_work_day, work_mask
from ..services import ASSIGNER_NAME, EXTRA_PROJECTS, app_today, app_tz, default_project, set_extra_projects, task_retro_days

router = APIRouter(prefix="/api/worklog", tags=["worklog"])
items = APIRouter(prefix="/api", tags=["worklog"])  # rotas por id de anotação/item/tempo

TIME_MAX_PAST_DAYS = 366  # apontamento retroativo


def check_day_total(uid: int, day, minutes: int, status: int = 400) -> None:
    """No máximo 24h apontadas por dia (também ao desfazer uma exclusão)."""
    total = db.query_one("SELECT COALESCE(sum(minutes), 0)::int AS m FROM time_entries WHERE user_id = %s AND day = %s",
                         (uid, day))["m"]
    if total + minutes > 1440:
        raise HTTPException(status_code=status, detail="com esse tempo, o dia passaria de 24 h apontadas; confira se o dia ou as horas estão certos")


def _check_project(uid: int, project_id) -> None:
    if project_id is None:
        return
    if not db.query_one("SELECT 1 FROM projects WHERE id = %s AND user_id = %s", (project_id, uid)):
        raise HTTPException(status_code=400, detail="projeto não encontrado")


# ------------------------------------------------- lançamento retroativo --
# Só a data (sem hora): criação às 9h, conclusão às 18h do dia, no fuso da app.
# Conclusão "hoje" sem hora = agora; no mesmo dia da criação, nunca antes dela.
DAY_START, DAY_END = time(9), time(18)
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_when(raw: str, label: str) -> tuple[datetime, bool]:
    """Texto -> (instante com fuso, veio só a data)."""
    raw = raw.strip()
    try:
        if _DATE_ONLY.match(raw):
            return datetime.combine(date.fromisoformat(raw), time(), app_tz()), True
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{label}: use AAAA-MM-DD ou AAAA-MM-DDTHH:MM") from None
    return (when if when.tzinfo else when.replace(tzinfo=app_tz())), False


def _check_window(when: datetime, label: str, now: datetime) -> None:
    if when > now + timedelta(minutes=10):  # folga para o relógio do aparelho (feito sem sinal)
        raise HTTPException(status_code=400, detail=f"{label} no futuro")
    limit = task_retro_days()
    if (app_today() - when.astimezone(app_tz()).date()).days > limit:
        raise HTTPException(status_code=400, detail=f"{label}: até {limit} dias atrás")


def resolve_created(raw: Optional[str], now: datetime) -> datetime:
    if not raw:
        return now
    when, only_date = _parse_when(raw, "data de criação")
    if only_date:
        if when.date() > app_today():
            raise HTTPException(status_code=400, detail="data de criação no futuro")
        when = min(datetime.combine(when.date(), DAY_START, app_tz()), now)
    _check_window(when, "data de criação", now)
    return when


def resolve_completed(raw: Optional[str], created: datetime, now: datetime) -> datetime:
    """Instante da conclusão: nunca no futuro, dentro do limite e não antes da criação."""
    if not raw:
        return max(now, created)
    when, only_date = _parse_when(raw, "data de conclusão")
    if only_date:
        day = when.date()
        if day > app_today():
            raise HTTPException(status_code=400, detail="data de conclusão no futuro")
        when = now if day == app_today() else datetime.combine(day, DAY_END, app_tz())
        if when < created and day == created.astimezone(app_tz()).date():
            when = created
    _check_window(when, "data de conclusão", now)
    if created - timedelta(minutes=1) < when < created:  # hora com minutos (sem segundos) do mesmo minuto
        when = created
    if when < created:
        raise HTTPException(status_code=400, detail="data de conclusão anterior à criação da tarefa")
    return when


def stop_timer_of(user: dict, task_id: int, ended_at: datetime | None = None) -> None:
    """Concluir a tarefa com o cronômetro rodando nela para o cronômetro e aponta o
    tempo. ended_at: a conclusão veio com hora (feita sem sinal): para ali."""
    from .timer import stop_running  # import tardio: timer usa log_time daqui
    stop_running(user, only_task=task_id, ended_at=min(ended_at, datetime.now(timezone.utc)) if ended_at else None)


def _own_task(uid: int, task_id: int) -> dict:
    row = audit.worklog_snapshot(task_id, uid)
    if not row:
        raise HTTPException(status_code=404, detail="não encontrado")
    return row


def safe_notify(task_id: int) -> None:
    """O aviso a quem atribuiu nunca derruba a conclusão (já gravada)."""
    try:
        notify_assigner(task_id)
    except Exception:  # noqa: BLE001
        logging.getLogger("uvicorn.error").exception("aviso de conclusão da tarefa %s falhou", task_id)


def follow_up_day(uid: int, d):
    """Dia para cobrar em dia não útil vai para o dia útil anterior (o lembrete
    só aparece em dia útil), sem passar de hoje. Vale para app, API e MCP."""
    if d is None:
        return None
    mask, today = work_mask(uid), app_today()
    while d > today and not is_work_day(d, mask):
        d -= timedelta(days=1)
    return d


def _reason(text):
    return " ".join((text or "").split()) or None


def _by_ref(uid: int, ref: str):
    return db.query_one("SELECT id FROM worklog_tasks WHERE user_id = %s AND external_ref = %s", (uid, ref))


@router.post("", status_code=201)
def create(data: WorklogIn, response: Response, user=Depends(active_user_csrf)):
    """Cria a tarefa. Com external_ref já usado pela pessoa, devolve a que
    existe (200, existing=true) em vez de duplicar."""
    uid = user["user_id"]
    if data.external_ref and (found := _by_ref(uid, data.external_ref)):
        response.status_code = 200
        return {"id": found["id"], "existing": True}
    # Com objetivo e sem projeto: o projeto do objetivo. Sem projeto informado
    # (nem null): o padrão da pessoa (Configurações > Conta).
    if data.objective_id is not None and "project_id" not in data.model_fields_set:
        project_id = objective_project(uid, data.objective_id)
    else:
        project_id = data.project_id if "project_id" in data.model_fields_set else default_project(uid)
    _check_project(uid, project_id)
    check_objective(uid, data.objective_id, project_id)
    now = datetime.now(timezone.utc)
    created_at = resolve_created(data.created_at, now)
    completed_at = resolve_completed(data.completed_at, created_at, now) if data.status == "done" else None
    try:
        row = db.query_one(
            """
            INSERT INTO worklog_tasks (user_id, title, description, status, due_date, created_at, completed_at,
                                       project_id, priority, ticket, after_hours, external_ref,
                                       blocked_reason, blocked_at, follow_up_on, resolution, objective_id, exec_position)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (uid, data.title, data.description, data.status, data.due_date, created_at, completed_at,
             project_id, data.priority, data.ticket, data.after_hours, data.external_ref,
             _reason(data.blocked_reason) if data.status == "blocked" else None,
             now if data.status == "blocked" else None,
             follow_up_day(uid, data.follow_up_on) if data.status == "blocked" else None,
             ((data.resolution or "").strip() or None) if data.status == "done" else None,
             data.objective_id, next_position(uid, project_id, data.objective_id)),
        )
    except UniqueViolation:  # duas chamadas iguais ao mesmo tempo: a segunda devolve a primeira
        response.status_code = 200
        return {"id": _by_ref(uid, data.external_ref)["id"], "existing": True}
    if data.extra_project_ids:
        set_extra_projects(uid, row["id"], data.extra_project_ids)
    audit.record(user, "worklog.create", "worklog", row["id"],
                 after=audit.worklog_snapshot(row["id"], uid))
    return {"id": row["id"]}


@router.get("")
def list_tasks(
    start: Optional[date] = Query(default=None, alias="from"),
    end: Optional[date] = Query(default=None, alias="to"),
    by: Literal["created", "completed"] = "created",
    status: Literal["open", "done", "all"] = "all",
    limit: int = Query(default=200, ge=1, le=500),
    external_ref: Annotated[Optional[str], Query(min_length=1, max_length=120)] = None,  # Annotated: idem (MCP)
    user=Depends(active_user),
):
    """Tarefas por período (dias inclusivos, fuso da app), pela criação ou
    pela conclusão: para conferir o que já foi lançado sem baixar tudo.
    Com external_ref: só a tarefa com essa chave (lista vazia se não houver)."""
    col = "w.completed_at" if by == "completed" else "w.created_at"
    cond, params = ["w.user_id = %(uid)s"], {"uid": user["user_id"], "tz": app_tz().key, "lim": limit}
    if external_ref is not None:
        found = _by_ref(user["user_id"], external_ref.strip())
        cond.append("w.id = %(ref_id)s")
        params["ref_id"] = found["id"] if found else 0
    if start:
        cond.append(f"({col} AT TIME ZONE %(tz)s)::date >= %(start)s")
        params["start"] = start
    if end:
        cond.append(f"({col} AT TIME ZONE %(tz)s)::date <= %(end)s")
        params["end"] = end
    if by == "completed":
        cond.append("w.completed_at IS NOT NULL")
    if status == "open":
        cond.append("w.status <> 'done'")
    elif status == "done":
        cond.append("w.status = 'done'")
    return db.query_all(
        f"""SELECT w.id, w.title, w.description, w.status, w.due_date, w.created_at, w.completed_at,
                   w.priority, w.project_id, w.ticket, w.after_hours, w.external_ref, w.assigned_by,
                   p.name AS project_name, {ASSIGNER_NAME}
              FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id
             WHERE {' AND '.join(cond)}
             ORDER BY {col} DESC NULLS LAST, w.id DESC
             LIMIT %(lim)s""",
        params,
    )


@router.get("/{task_id}")
def detail(task_id: int, user=Depends(active_user)):
    """Tarefa completa: dados, projeto, checklist, anotações e tempo."""
    uid = user["user_id"]
    task = db.query_one(
        """
        SELECT w.id, w.title, w.description, w.status, w.due_date, w.created_at, w.completed_at,
               w.priority, w.project_id, w.ticket, w.after_hours, w.external_ref, w.assigned_by, w.assigned_at,
               w.blocked_reason, w.blocked_at, w.follow_up_on, w.resolution,
               w.objective_id, (SELECT o.title FROM project_objectives o WHERE o.id = w.objective_id) AS objective_title,
               p.name AS project_name, p.color AS project_color, """ + ASSIGNER_NAME + ", " + EXTRA_PROJECTS + """
          FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id
         WHERE w.id = %s AND w.user_id = %s
        """,
        (task_id, uid),
    )
    if not task:
        raise HTTPException(status_code=404, detail="não encontrado")
    task["checklist"] = db.query_all(
        "SELECT id, label, done, position FROM task_checklist WHERE task_id = %s ORDER BY position, id",
        (task_id,),
    )
    task["notes"] = db.query_all(
        "SELECT id, body, actor, token_name, created_at FROM task_notes WHERE task_id = %s ORDER BY created_at DESC, id DESC",
        (task_id,),
    )
    from .photos import for_task
    task["photos"] = for_task(uid, task_id)
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
    extras = data.extra_project_ids is not None
    # Objetivo: só do projeto principal. Trocar o projeto tira do objetivo que
    # não é dele; a tarefa vai para o fim da fila do bloco novo.
    final_project = data.project_id if "project_id" in sent else before["project_id"]
    if "objective_id" in sent:
        check_objective(user["user_id"], data.objective_id, final_project)
        if data.objective_id != before["objective_id"]:
            fields += ["objective_id = %s", "exec_position = %s"]
            values += [data.objective_id, next_position(user["user_id"], final_project, data.objective_id)]
    elif "project_id" in sent and final_project != before["project_id"]:
        fields += ["objective_id = NULL", "exec_position = %s"]
        values.append(next_position(user["user_id"], final_project, None))
    if data.priority is not None:
        fields.append("priority = %s")
        values.append(data.priority)
    if "ticket" in sent:
        fields.append("ticket = %s")
        values.append(data.ticket)
    if data.after_hours is not None:
        fields.append("after_hours = %s")
        values.append(data.after_hours)
    if "resolution" in sent and (data.status or before["status"]) == "done":  # como o create: só em concluída
        fields.append("resolution = %s")
        values.append((data.resolution or "").strip() or None)
    final_status = data.status or before["status"]
    if data.completed_at and final_status != "done":
        raise HTTPException(status_code=400, detail="data de conclusão só em tarefa concluída")
    if data.status is not None:
        fields.append("status = %s")
        values.append(data.status)
        if data.status != "done":
            fields.append("completed_at = NULL")
    # Impedimento: ao bloquear, desde quando e o que se aguarda; ao sair, limpa.
    if final_status == "blocked":
        if before["status"] != "blocked":
            fields.append("blocked_at = now()")
        if "blocked_reason" in sent or before["status"] != "blocked":
            fields.append("blocked_reason = %s")
            values.append(_reason(data.blocked_reason))
        if "follow_up_on" in sent or before["status"] != "blocked":
            fields.append("follow_up_on = %s")
            values.append(follow_up_day(user["user_id"], data.follow_up_on))
    elif ("blocked_reason" in sent and _reason(data.blocked_reason)) or ("follow_up_on" in sent and data.follow_up_on):
        # Motivo ou cobrança numa tarefa que não fica aguardando: antes era
        # descartado em silêncio. Mudar o status por tabela seria efeito escondido.
        raise HTTPException(status_code=400, detail=(
            "motivo (blocked_reason) e dia de cobrar (follow_up_on) só valem em tarefa aguardando: "
            "mande status \"blocked\" junto para ela passar a aguardar"))
    elif before["status"] == "blocked":
        fields.append("blocked_at = NULL")
        fields.append("blocked_reason = NULL")
        fields.append("follow_up_on = NULL")
    if final_status == "done" and (data.completed_at or before["completed_at"] is None):
        fields.append("completed_at = %s")
        values.append(resolve_completed(data.completed_at, before["created_at"], datetime.now(timezone.utc)))

    if not fields and not extras:
        raise HTTPException(status_code=400, detail="nada para atualizar")
    if data.status == "done":
        stop_timer_of(user, task_id)

    if fields:
        values += [task_id, user["user_id"]]
        db.execute(
            f"UPDATE worklog_tasks SET {', '.join(fields)} WHERE id = %s AND user_id = %s",
            tuple(values),
        )
    # Trocou o principal: os extras se ajustam (sem repetir; sem principal, nenhum).
    if extras or "project_id" in sent:
        set_extra_projects(user["user_id"], task_id,
                           data.extra_project_ids if extras else before["extra_project_ids"])
    audit.record(user, "worklog.update", "worklog", task_id, before=before,
                 after=audit.worklog_snapshot(task_id, user["user_id"]))
    if final_status == "done" and before["status"] != "done":
        safe_notify(task_id)
    return {"ok": True}


@router.post("/{task_id}/finish")
def finish(task_id: int, data: Optional[FinishIn] = None, user=Depends(active_user_csrf)):
    """Conclui agora, ou na data informada (retroativo). Já concluída e sem
    data: mantém a conclusão que tinha."""
    before = _own_task(user["user_id"], task_id)
    raw = data.completed_at if data else None
    when = before["completed_at"] if (before["completed_at"] and not raw) else \
        resolve_completed(raw, before["created_at"], datetime.now(timezone.utc))
    stop_timer_of(user, task_id, when if raw else None)
    resolution = ((data.resolution if data else None) or "").strip() or None  # mantém as quebras de linha (passos)
    db.execute(
        """UPDATE worklog_tasks SET status = 'done', completed_at = %s,
                  blocked_reason = NULL, blocked_at = NULL, follow_up_on = NULL,
                  resolution = COALESCE(%s, resolution)
            WHERE id = %s AND user_id = %s""",
        (when, resolution, task_id, user["user_id"]),
    )
    audit.record(user, "worklog.finish", "worklog", task_id, before=before,
                 after=audit.worklog_snapshot(task_id, user["user_id"]))
    safe_notify(task_id)
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

NOTE_COLS = "id, task_id, body, actor, token_name, created_at, external_ref"
TIME_COLS = "id, task_id, minutes, day, note, actor, token_name, created_at, external_ref"


def _child_by_ref(table: str, cols: str, uid: int, ref):
    """Anotação/apontamento já criado com essa chave externa (idempotência)."""
    return ref and db.query_one(f"SELECT {cols} FROM {table} WHERE user_id = %s AND external_ref = %s", (uid, ref))


@router.post("/{task_id}/notes", status_code=201)
def add_note(task_id: int, data: NoteIn, response: Response = None, user=Depends(active_user_csrf)):
    """Com external_ref já usado, devolve a anotação que existe (200, existing)."""
    task = _own_task(user["user_id"], task_id)
    if found := _child_by_ref("task_notes", NOTE_COLS, user["user_id"], data.external_ref):
        response.status_code = 200
        return {**found, "existing": True}
    try:
        row = db.query_one(
            f"""INSERT INTO task_notes (task_id, user_id, body, actor, token_name, external_ref)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING {NOTE_COLS}""",
            (task_id, user["user_id"], data.body.strip(), user.get("actor", "web"), user.get("token_name"),
             data.external_ref),
        )
    except UniqueViolation:  # duas chamadas iguais ao mesmo tempo: a segunda devolve a primeira
        response.status_code = 200
        return {**_child_by_ref("task_notes", NOTE_COLS, user["user_id"], data.external_ref), "existing": True}
    audit.record(user, "note.create", "note", row["id"],
                 after={"task_id": task_id, "title": task["title"], "body": row["body"][:120],
                        "external_ref": data.external_ref})
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
        raise HTTPException(status_code=404, detail="não encontrado")
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
        raise HTTPException(status_code=404, detail="não encontrado")
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
        raise HTTPException(status_code=404, detail="não encontrado")
    audit.record(user, "checklist.delete", "checklist", item_id, before=row)
    return {"ok": True}


# ------------------------------------------------------------------ tempo --

@router.post("/{task_id}/time", status_code=201)
def log_time(task_id: int, data: TimeIn, response: Response = None, user=Depends(active_user_csrf)):
    """Com external_ref já usado, devolve o apontamento que existe (200, existing)
    sem somar de novo: a automação que repete por timeout não aponta em dobro."""
    task = _own_task(user["user_id"], task_id)
    if found := _child_by_ref("time_entries", TIME_COLS, user["user_id"], data.external_ref):
        response.status_code = 200
        return {**found, "existing": True}
    today = app_today()
    day = data.day or today
    if day > today:
        raise HTTPException(status_code=400, detail="não dá para apontar tempo no futuro")
    if (today - day).days > TIME_MAX_PAST_DAYS:
        raise HTTPException(status_code=400, detail=f"apontamento até {TIME_MAX_PAST_DAYS} dias atrás")
    check_day_total(user["user_id"], day, data.minutes)
    try:
        row = db.query_one(
            f"""INSERT INTO time_entries (task_id, user_id, minutes, day, note, actor, token_name, external_ref)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING {TIME_COLS}""",
            (task_id, user["user_id"], data.minutes, day, (data.note or "").strip() or None,
             user.get("actor", "web"), user.get("token_name"), data.external_ref),
        )
    except UniqueViolation:
        response.status_code = 200
        return {**_child_by_ref("time_entries", TIME_COLS, user["user_id"], data.external_ref), "existing": True}
    audit.record(user, "time.create", "time", row["id"],
                 after={"task_id": task_id, "title": task["title"], "minutes": data.minutes, "day": day,
                        "external_ref": data.external_ref})
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
        raise HTTPException(status_code=404, detail="não encontrado")
    audit.record(user, "time.delete", "time", entry_id, before=row)
    return {"ok": True}
