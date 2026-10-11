"""Busca (tarefas, anotações, checklist, apontamentos, recorrentes, projetos)
e exportação dos dados do usuário em CSV/JSON."""
import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .. import db
from ..deps import active_user
from ..labels import PRIO_PT, STATUS_PT
from ..services import TASK_COUNTS, app_today, app_tz
from ..labels import fold as _fold

router = APIRouter(prefix="/api", tags=["search"])

MAX_HITS = 40
def _snippet(text: str, q: str, width: int = 70) -> str:
    """Trecho de `text` em volta da primeira ocorrência de `q` (sem acento)."""
    i = _fold(text).find(q)
    if i < 0 or len(text) <= width * 2:
        return text if len(text) <= width * 2 else text[: width * 2].rstrip() + "…"
    a, b = max(0, i - width), min(len(text), i + len(q) + width)
    return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")


@router.get("/search")
def search(q: str = Query(..., min_length=2, max_length=100), user=Depends(active_user)):
    uid = user["user_id"]
    fq = _fold(q.strip())
    if len(fq) < 2:
        raise HTTPException(status_code=400, detail="busque ao menos 2 letras")
    like = "%" + fq.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

    tasks: dict[int, dict] = {}

    def task(row):
        t = tasks.get(row["id"])
        if not t:
            t = tasks[row["id"]] = {k: row[k] for k in (
                "id", "title", "status", "priority", "due_date", "completed_at", "created_at",
                "project_name", "project_color")} | {"hits": []}
        return t

    base = """SELECT w.id, w.title, w.description, w.status, w.priority, w.due_date, w.completed_at,
                     w.created_at, p.name AS project_name, p.color AS project_color{extra}
                FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id {join}
               WHERE w.user_id = %(uid)s AND {cond}
               ORDER BY w.created_at DESC LIMIT 200"""
    params = {"uid": uid, "like": like}

    for r in db.query_all(base.format(extra="", join="", cond="(nx_fold(w.title) LIKE %(like)s OR nx_fold(w.description) LIKE %(like)s)"), params):
        t = task(r)
        if fq in _fold(r["title"]):
            t["hits"].append({"kind": "título", "text": r["title"]})
        if r["description"] and fq in _fold(r["description"]):
            t["hits"].append({"kind": "descrição", "text": _snippet(r["description"], fq)})
    for kind, extra, join, cond, field in [
        ("anotação", ", n.body AS hit", "JOIN task_notes n ON n.task_id = w.id", "nx_fold(n.body) LIKE %(like)s", "hit"),
        ("checklist", ", c.label AS hit", "JOIN task_checklist c ON c.task_id = w.id", "nx_fold(c.label) LIKE %(like)s", "hit"),
        ("apontamento", ", e.note AS hit", "JOIN time_entries e ON e.task_id = w.id", "nx_fold(e.note) LIKE %(like)s", "hit"),
    ]:
        for r in db.query_all(base.format(extra=extra, join=join, cond=cond), params):
            t = task(r)
            if sum(1 for h in t["hits"] if h["kind"] == kind) < 3:
                t["hits"].append({"kind": kind, "text": _snippet(r[field], fq)})

    recurring = db.query_all(
        """SELECT id, label, active, freq FROM recurring_tasks
            WHERE user_id = %(uid)s AND nx_fold(label) LIKE %(like)s
            ORDER BY active DESC, position, id LIMIT 20""", params)
    projects = db.query_all(
        """SELECT id, name, color, archived FROM projects
            WHERE user_id = %(uid)s AND nx_fold(name) LIKE %(like)s ORDER BY archived, lower(name) LIMIT 20""", params)

    # Abertas primeiro (mais urgentes), depois concluídas mais recentes.
    ordered = sorted(tasks.values(), key=lambda t: (
        t["status"] == "done", t["priority"] if t["status"] != "done" else 0,
        -(t["completed_at"] or t["created_at"]).timestamp()))
    return {"q": q, "tasks": ordered[:MAX_HITS], "total_tasks": len(ordered),
            "recurring": recurring, "projects": projects}


# --------------------------------------------------------------- exportação --



def _local(ts):
    if ts is None:
        return ""
    return ts.astimezone(app_tz()).strftime("%Y-%m-%d %H:%M")


def _cell(v):
    """Texto que começa como fórmula vira texto no Excel (injeção de CSV)."""
    return "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def _csv(rows: list[list], header: list[str]) -> bytes:
    """CSV no jeito do Excel brasileiro: ';' como separador e BOM UTF-8."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(header)
    w.writerows([_cell(v) for v in r] for r in rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _download(content: bytes, media: str, name: str) -> Response:
    return Response(content=content, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


def _tasks(uid: int) -> list[dict]:
    return db.query_all(
        """SELECT w.id, w.title, w.description, w.status, w.priority, w.due_date, w.created_at, w.completed_at,
                  p.name AS project,
                  """ + TASK_COUNTS + """
             FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id
            WHERE w.user_id = %s ORDER BY w.created_at""", (uid,))


def time_csv(uid: int | None, filename: str) -> Response:
    """Apontamentos em CSV. uid=None = de todos (admin: horas da equipe por
    cliente; o projeto vai por nome, pois cada pessoa tem os seus)."""
    rows = db.query_all(
        """SELECT e.day, e.minutes, w.id AS task_id, w.title, p.name AS project, e.note, e.actor, e.token_name,
                  u.email
             FROM time_entries e JOIN worklog_tasks w ON w.id = e.task_id
             JOIN users u ON u.id = e.user_id
             LEFT JOIN projects p ON p.id = w.project_id
            WHERE (%(uid)s::bigint IS NULL OR e.user_id = %(uid)s) ORDER BY e.day, u.email, e.id""", {"uid": uid})
    header = ["data", "minutos", "horas", "tarefa_id", "tarefa", "projeto", "observacao", "origem"]
    data = [[r["day"], r["minutes"], str(round(r["minutes"] / 60, 2)).replace(".", ","), r["task_id"], r["title"],
             r["project"] or "", r["note"] or "", r["token_name"] or r["actor"]] + ([r["email"]] if uid is None else [])
            for r in rows]
    return _download(_csv(data, header + (["usuario"] if uid is None else [])), "text/csv; charset=utf-8", filename)


@router.get("/export/{kind}")
def export(kind: str, user=Depends(active_user)):
    uid = user["user_id"]
    stamp = app_today().isoformat()
    if kind == "tarefas.csv":
        rows = [[t["id"], t["title"], t["description"] or "", STATUS_PT.get(t["status"], t["status"]), PRIO_PT.get(t["priority"], ""),
                 t["project"] or "", _local(t["created_at"]), t["due_date"] or "", _local(t["completed_at"]),
                 f"{t['check_done']}/{t['check_total']}" if t["check_total"] else "", t["minutes"],
                 str(round(t["minutes"] / 60, 2)).replace(".", ","), t["notes_count"]] for t in _tasks(uid)]
        return _download(_csv(rows, ["id", "titulo", "descricao", "status", "prioridade", "projeto", "criada_em", "prazo",
                                     "concluida_em", "checklist", "minutos", "horas", "anotacoes"]),
                         "text/csv; charset=utf-8", f"nexus-tarefas-{stamp}.csv")
    if kind == "apontamentos.csv":
        return time_csv(uid, f"nexus-apontamentos-{stamp}.csv")
    if kind == "tudo.json":
        tasks = _tasks(uid)
        by_id = {t["id"]: t for t in tasks}
        for t in tasks:
            t["checklist"], t["notes_list"], t["time"] = [], [], []
        for c in db.query_all("SELECT task_id, label, done FROM task_checklist WHERE user_id = %s ORDER BY position, id", (uid,)):
            by_id[c.pop("task_id")]["checklist"].append(c)
        for n in db.query_all("SELECT task_id, body, actor, token_name, created_at FROM task_notes WHERE user_id = %s ORDER BY created_at", (uid,)):
            by_id[n.pop("task_id")]["notes_list"].append(n)
        for e in db.query_all("SELECT task_id, day, minutes, note, actor, token_name FROM time_entries WHERE user_id = %s ORDER BY day, id", (uid,)):
            by_id[e.pop("task_id")]["time"].append(e)
        for t in tasks:
            t["notes"] = t.pop("notes_list")
        recurring = db.query_all(
            """SELECT id, label, active, freq, weekdays, month_day, interval_days, created_at, deactivated_at
                 FROM recurring_tasks WHERE user_id = %s ORDER BY position, id""", (uid,))
        done = {}
        for c in db.query_all("SELECT task_id, completed_date FROM recurring_completions WHERE user_id = %s ORDER BY completed_date", (uid,)):
            done.setdefault(c["task_id"], []).append(c["completed_date"])
        for r in recurring:
            r["completed_dates"] = done.get(r["id"], [])
        payload = {
            "exported_at": datetime.now(app_tz()),
            "user": db.query_one("SELECT email, work_days, created_at FROM users WHERE id = %s", (uid,)),
            "projects": db.query_all("SELECT id, name, color, archived, created_at FROM projects WHERE user_id = %s ORDER BY id", (uid,)),
            "tasks": tasks,
            "recurring": recurring,
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o))
        return _download(body.encode("utf-8"), "application/json", f"nexus-dados-{stamp}.json")
    raise HTTPException(status_code=404, detail="formato desconhecido")
