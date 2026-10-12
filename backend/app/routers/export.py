"""Exportação dos dados do usuário: apontamentos e tarefas em CSV (Excel BR),
tudo em JSON. O admin reusa time_csv para as horas da equipe."""
import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response

from .. import db
from ..deps import active_user
from ..labels import PRIO_PT, STATUS_PT
from ..services import TASK_COUNTS, app_today, app_tz

router = APIRouter(prefix="/api", tags=["export"])


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
            t["checklist"], t["notes"], t["time"] = [], [], []
        for c in db.query_all("SELECT task_id, label, done FROM task_checklist WHERE user_id = %s ORDER BY position, id", (uid,)):
            by_id[c.pop("task_id")]["checklist"].append(c)
        for n in db.query_all("SELECT task_id, body, actor, token_name, created_at FROM task_notes WHERE user_id = %s ORDER BY created_at", (uid,)):
            by_id[n.pop("task_id")]["notes"].append(n)
        for e in db.query_all("SELECT task_id, day, minutes, note, actor, token_name FROM time_entries WHERE user_id = %s ORDER BY day, id", (uid,)):
            by_id[e.pop("task_id")]["time"].append(e)
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
