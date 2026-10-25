"""Exportação dos dados do usuário: apontamentos e tarefas em CSV (Excel BR),
tudo em JSON. O admin reusa time_csv para as horas da equipe."""
import csv
import io
import json
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .. import db
from ..deps import active_user
from ..labels import PRIO_PT, STATUS_PT
from ..services import TASK_COUNTS, app_today, app_tz, is_due, rotinas, work_mask

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
                  w.ticket, w.after_hours, w.blocked_reason, w.blocked_at, w.follow_up_on, w.resolution, p.name AS project,
                  """ + TASK_COUNTS + """
             FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id
            WHERE w.user_id = %s ORDER BY w.created_at""", (uid,))


def time_csv(uid: int | None, filename: str) -> Response:
    """Apontamentos em CSV. uid=None = de todos (admin: horas da equipe por
    cliente; o projeto vai por nome, pois cada pessoa tem os seus)."""
    rows = db.query_all(
        """SELECT e.day, e.minutes, w.id AS task_id, w.title, p.name AS project, e.note, e.actor, e.token_name,
                  w.ticket, w.after_hours, u.email
             FROM time_entries e JOIN worklog_tasks w ON w.id = e.task_id
             JOIN users u ON u.id = e.user_id
             LEFT JOIN projects p ON p.id = w.project_id
            WHERE (%(uid)s::bigint IS NULL OR e.user_id = %(uid)s) ORDER BY e.day, u.email, e.id""", {"uid": uid})
    header = ["data", "minutos", "horas", "tarefa_id", "tarefa", "projeto", "observacao", "origem", "chamado", "plantao"]
    data = [[r["day"], r["minutes"], str(round(r["minutes"] / 60, 2)).replace(".", ","), r["task_id"], r["title"],
             r["project"] or "", r["note"] or "", r["token_name"] or r["actor"], r["ticket"] or "",
             "sim" if r["after_hours"] else ""] + ([r["email"]] if uid is None else [])
            for r in rows]
    return _download(_csv(data, header + (["usuario"] if uid is None else [])), "text/csv; charset=utf-8", filename)


@router.get("/export/plantao.csv")
def plantao_csv(start: Optional[date] = Query(None), end: Optional[date] = Query(None), user=Depends(active_user)):
    """Plantão do período (padrão: o mês atual): cada atendimento fora do horário,
    com o tempo apontado por dia — pra fechar sobreaviso/banco de horas."""
    today = app_today()
    start = start or today.replace(day=1)
    end = min(end or today, today)
    if end < start or (end - start).days > 366:
        raise HTTPException(status_code=400, detail="período inválido (até 1 ano)")
    rows = db.query_all(
        """SELECT COALESCE(e.day, (w.completed_at AT TIME ZONE %(tz)s)::date) AS dia, w.id, w.title, w.ticket,
                  p.name AS project, COALESCE(e.minutes, 0) AS minutes, e.note
             FROM worklog_tasks w
             LEFT JOIN time_entries e ON e.task_id = w.id
             LEFT JOIN projects p ON p.id = w.project_id
            WHERE w.user_id = %(uid)s AND w.after_hours
              AND COALESCE(e.day, (w.completed_at AT TIME ZONE %(tz)s)::date) BETWEEN %(s)s AND %(e)s
            ORDER BY dia, w.id""",
        {"uid": user["user_id"], "tz": app_tz().key, "s": start, "e": end})
    total = sum(r["minutes"] for r in rows)
    data = [[r["dia"], r["id"], r["title"], r["ticket"] or "", r["project"] or "", r["minutes"],
             str(round(r["minutes"] / 60, 2)).replace(".", ","), r["note"] or ""] for r in rows]
    data.append(["total", "", "", "", "", total, str(round(total / 60, 2)).replace(".", ","), ""])
    return _download(_csv(data, ["data", "tarefa_id", "tarefa", "chamado", "projeto", "minutos", "horas", "observacao"]),
                     "text/csv; charset=utf-8", f"nexus-plantao-{start.isoformat()}-a-{end.isoformat()}.csv")


@router.get("/export/rotinas.csv")
def rotinas_csv(start: Optional[date] = Query(None), end: Optional[date] = Query(None), user=Depends(active_user)):
    """Trilha de auditoria das rotinas (padrão: o mês atual): uma linha por rotina
    em cada dia — prevista ou extra, feita ou não e a evidência anotada."""
    today = app_today()
    start = start or today.replace(day=1)
    end = min(end or today, today)
    if end < start or (end - start).days > 366:
        raise HTTPException(status_code=400, detail="período inválido (até 1 ano)")
    uid = user["user_id"]
    mask = work_mask(uid)
    feitas = {(c["task_id"], c["completed_date"]): c["note"] for c in db.query_all(
        "SELECT task_id, completed_date, note FROM recurring_completions WHERE user_id = %s AND completed_date BETWEEN %s AND %s",
        (uid, start, end))}
    data, d = [], start
    tasks = rotinas(uid)
    while d <= end:  # todo dia do período: o dia em que nada foi feito também aparece (é a falta)
        for t in tasks:
            if not (t["start_d"] <= d <= t["end_d"]):
                continue
            devida, feita = is_due(t, d, mask), (t["id"], d) in feitas
            if devida or feita:
                situacao = "sim" if feita else ("pendente" if d == today else "não")
                data.append([d, t["label"], "prevista" if devida else "extra", situacao, feitas.get((t["id"], d)) or ""])
        d += timedelta(days=1)
    return _download(_csv(data, ["data", "rotina", "agenda", "feita", "evidencia"]),
                     "text/csv; charset=utf-8", f"nexus-rotinas-{start.isoformat()}-a-{end.isoformat()}.csv")


@router.get("/export/{kind}")
def export(kind: str, user=Depends(active_user)):
    uid = user["user_id"]
    stamp = app_today().isoformat()
    if kind == "tarefas.csv":
        rows = [[t["id"], t["title"], t["description"] or "", STATUS_PT.get(t["status"], t["status"]), PRIO_PT.get(t["priority"], ""),
                 t["project"] or "", _local(t["created_at"]), t["due_date"] or "", _local(t["completed_at"]),
                 f"{t['check_done']}/{t['check_total']}" if t["check_total"] else "", t["minutes"],
                 str(round(t["minutes"] / 60, 2)).replace(".", ","), t["notes_count"],
                 t["ticket"] or "", "sim" if t["after_hours"] else "", t["blocked_reason"] or "", t["resolution"] or ""] for t in _tasks(uid)]
        return _download(_csv(rows, ["id", "titulo", "descricao", "status", "prioridade", "projeto", "criada_em", "prazo",
                                     "concluida_em", "checklist", "minutos", "horas", "anotacoes", "chamado", "plantao",
                                     "aguardando", "como_resolveu"]),
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
            """SELECT id, label, active, freq, weekdays, month_day, interval_days, require_note, created_at, deactivated_at
                 FROM recurring_tasks WHERE user_id = %s ORDER BY position, id""", (uid,))
        done, evid = {}, {}
        for c in db.query_all("SELECT task_id, completed_date, note FROM recurring_completions WHERE user_id = %s ORDER BY completed_date", (uid,)):
            done.setdefault(c["task_id"], []).append(c["completed_date"])
            if c["note"]:
                evid.setdefault(c["task_id"], []).append({"date": c["completed_date"], "note": c["note"]})
        for r in recurring:
            r["completed_dates"] = done.get(r["id"], [])
            r["evidence"] = evid.get(r["id"], [])  # o que foi anotado ao marcar
        payload = {
            "exported_at": datetime.now(app_tz()),
            "user": db.query_one("SELECT email, work_days, created_at FROM users WHERE id = %s", (uid,)),
            "projects": db.query_all("SELECT id, name, color, archived, created_at FROM projects WHERE user_id = %s ORDER BY id", (uid,)),
            "tasks": tasks,
            "recurring": recurring,
            "renewals": db.query_all(
                """SELECT r.label, r.expires_on, r.warn_days, r.renew_months, p.name AS project, r.note, r.created_at
                     FROM renewals r LEFT JOIN projects p ON p.id = r.project_id
                    WHERE r.user_id = %s ORDER BY r.expires_on""", (uid,)),
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o))
        return _download(body.encode("utf-8"), "application/json", f"nexus-dados-{stamp}.json")
    raise HTTPException(status_code=404, detail="formato desconhecido")
