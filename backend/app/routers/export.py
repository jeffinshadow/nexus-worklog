"""Exportação dos dados do usuário: apontamentos e tarefas em CSV (Excel BR),
tudo em JSON. O admin reusa time_csv para as horas da equipe."""
import csv
import io
import json
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .. import db, teams
from ..visibility import active_sql, visible_sql
from ..deps import active_user
from ..labels import PRIO_PT, STATUS_PT
from ..services import ASSIGNER_NAME, ENTRY_EXTRA_PROJECTS, IN_PROJECT, TASK_COUNTS, app_today, app_tz, is_due, rotinas, work_mask
from .reports import file_slug

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


# IN_PROJECT (principal ou extra) com parâmetro nomeado, para as consultas daqui.
_IN_PROJECT = IN_PROJECT.replace("%s", "%(proj)s")


def _others(extra) -> str:
    """Coluna outros_projetos: os projetos extras da tarefa (o principal está em `projeto`)."""
    return ", ".join(x["name"] for x in extra or [])


def _project(uid: int, project_id: int | None) -> dict | None:
    """O projeto do filtro `project` (None = sem filtro); inexistente ou de outra pessoa = 404."""
    if project_id is None:
        return None
    row = db.query_one("SELECT id, name FROM projects WHERE id = %s AND user_id = %s", (project_id, uid))
    if not row:
        raise HTTPException(status_code=404, detail="projeto não encontrado")
    return row


def _tasks(uid: int, start: date | None = None, end: date | None = None, project: int | None = None) -> list[dict]:
    """Todas as tarefas; com período, as que estiveram em aberto em algum momento
    dele (criadas até o fim e não concluídas antes do início) ou com tempo apontado
    nele, e period_minutes = o tempo apontado no período. project: só as desse
    projeto (principal ou extra, como no PDF)."""
    period = start is not None and end is not None
    return db.query_all(
        """SELECT w.id, w.title, w.description, w.status, w.priority, w.due_date, w.created_at, w.completed_at,
                  w.ticket, w.after_hours, w.blocked_reason, w.blocked_at, w.follow_up_on, w.resolution, p.name AS project,
                  w.project_id, w.external_ref, w.objective_id,
                  w.remind_at, w.assigned_at, """ + ASSIGNER_NAME.replace("AS assigned_by_name", "AS assigned_by") + """,
                  """ + TASK_COUNTS + """,
                  (SELECT COALESCE(sum(t.minutes), 0) FROM time_entries t
                    WHERE t.task_id = w.id AND t.user_id = w.user_id AND t.day BETWEEN %(s)s AND %(e)s)::int AS period_minutes
             FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id
            WHERE w.user_id = %(uid)s
              AND (NOT %(p)s
                   OR ((w.created_at AT TIME ZONE %(tz)s)::date <= %(e)s
                       AND (w.completed_at IS NULL OR (w.completed_at AT TIME ZONE %(tz)s)::date >= %(s)s))
                   OR EXISTS (SELECT 1 FROM time_entries t WHERE t.task_id = w.id AND t.user_id = w.user_id
                                 AND t.day BETWEEN %(s)s AND %(e)s))
              AND (%(proj)s::bigint IS NULL OR """ + _IN_PROJECT + """)
            ORDER BY w.created_at""",
        {"uid": uid, "p": period, "s": start, "e": end, "tz": app_tz().key, "proj": project})


def _period(start: date | None, end: date | None) -> tuple[date | None, date | None]:
    """Período opcional das exportações: os dois ou nenhum, até 1 ano."""
    if start is None and end is None:
        return None, None
    if start is None or end is None or end < start or (end - start).days > 366:
        raise HTTPException(status_code=400, detail="período inválido: informe start e end (até 1 ano)")
    return start, end


def time_csv(uid: int | None, filename: str, viewer: int | None = None,
             start: date | None = None, end: date | None = None, extra: str = "TRUE",
             project: int | None = None) -> Response:
    """Apontamentos em CSV. uid=None = de todos (visualizador: horas da equipe
    por cliente; o projeto vai por nome, pois cada pessoa tem os seus).
    viewer = só de quem esse visualizador pode ver (visibility.visible_sql;
    `extra`: o recorte do seletor de equipe). start/end: só esse período.
    project: só as tarefas desse projeto (principal ou extra, como no PDF).
    Colunas novas entram sempre no fim (quem lê por posição não quebra)."""
    # NB: tarefas.csv não ganhou outros_projetos: a última coluna dele é contrato de teste antigo.
    # active_sql: como a lista e o painel da Equipe (as horas de uma conta bloqueada entravam só aqui, e a soma não fechava).
    vis = f"{visible_sql('u', int(viewer))} AND {active_sql('u')} AND {extra}" if viewer is not None else "TRUE"
    rows = db.query_all(
        f"""SELECT e.day, e.minutes, w.id AS task_id, w.title, p.name AS project, e.note, e.actor, e.token_name,
                  w.ticket, w.after_hours, u.email, e.started_at, e.ended_at, {ENTRY_EXTRA_PROJECTS}
             FROM time_entries e JOIN worklog_tasks w ON w.id = e.task_id
             JOIN users u ON u.id = e.user_id
             LEFT JOIN projects p ON p.id = w.project_id AND p.user_id = e.user_id
            WHERE (%(uid)s::bigint IS NULL OR e.user_id = %(uid)s) AND {vis}
              AND (%(s)s::date IS NULL OR e.day >= %(s)s) AND (%(e)s::date IS NULL OR e.day <= %(e)s)
              AND (%(proj)s::bigint IS NULL OR {_IN_PROJECT})
            ORDER BY e.day, u.email, e.id""", {"uid": uid, "s": start, "e": end, "proj": project})
    header = ["data", "minutos", "horas", "tarefa_id", "tarefa", "projeto", "observacao", "origem", "chamado", "plantao"]
    data = [[r["day"], r["minutes"], str(round(r["minutes"] / 60, 2)).replace(".", ","), r["task_id"], r["title"],
             r["project"] or "", r["note"] or "", r["token_name"] or r["actor"], r["ticket"] or "",
             "sim" if r["after_hours"] else ""] + ([r["email"]] if uid is None else [])
            # inicio/fim: só no apontamento que veio do cronômetro (o digitado não tem horário).
            # Só no CSV da própria pessoa: no da equipe, `usuario` continua a última coluna.
            + ([_others(r["extra_projects"]), _local(r["started_at"]), _local(r["ended_at"])] if uid is not None else [])
            for r in rows]
    return _download(_csv(data, header + (["usuario"] if uid is None else ["outros_projetos", "inicio", "fim"])),
                     "text/csv; charset=utf-8", filename)


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
             LEFT JOIN time_entries e ON e.task_id = w.id AND e.user_id = w.user_id
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
def export(kind: str, start: Optional[date] = Query(None), end: Optional[date] = Query(None),
           project: Optional[int] = Query(None), user=Depends(active_user)):
    """tarefas.csv e apontamentos.csv aceitam start/end (os dois): só o período;
    e project: só o que é desse projeto (principal ou extra, como no PDF)."""
    uid = user["user_id"]
    stamp = app_today().isoformat()
    if kind in ("tarefas.csv", "apontamentos.csv"):
        start, end = _period(start, end)
        if start:
            stamp = f"{start.isoformat()}-a-{end.isoformat()}"
        proj = _project(uid, project)
        if proj:  # o nome do arquivo diz de que projeto é
            stamp = f"{file_slug(proj['name'], 'projeto')}-{stamp}"
    if kind == "tarefas.csv":
        horas = lambda m: str(round(m / 60, 2)).replace(".", ",")  # noqa: E731
        rows = [[t["id"], t["title"], t["description"] or "", STATUS_PT.get(t["status"], t["status"]), PRIO_PT.get(t["priority"], ""),
                 t["project"] or "", _local(t["created_at"]), t["due_date"] or "", _local(t["completed_at"]),
                 f"{t['check_done']}/{t['check_total']}" if t["check_total"] else "", t["minutes"],
                 horas(t["minutes"]), t["notes_count"],
                 t["ticket"] or "", "sim" if t["after_hours"] else "", t["blocked_reason"] or "", t["resolution"] or ""]
                + ([t["period_minutes"], horas(t["period_minutes"])] if start else [])
                for t in _tasks(uid, start, end, project)]
        return _download(_csv(rows, ["id", "titulo", "descricao", "status", "prioridade", "projeto", "criada_em", "prazo",
                                     "concluida_em", "checklist", "minutos", "horas", "anotacoes", "chamado", "plantao",
                                     "aguardando", "como_resolveu"] + (["minutos_no_periodo", "horas_no_periodo"] if start else [])),
                         "text/csv; charset=utf-8", f"nexus-tarefas-{stamp}.csv")
    if kind == "apontamentos.csv":
        return time_csv(uid, f"nexus-apontamentos-{stamp}.csv", start=start, end=end, project=project)
    if kind == "tudo.json":
        tasks = _tasks(uid)
        by_id = {t["id"]: t for t in tasks}
        for t in tasks:
            t["checklist"], t["notes"], t["time"] = [], [], []
        for c in db.query_all("SELECT task_id, label, done FROM task_checklist WHERE user_id = %s ORDER BY position, id", (uid,)):
            by_id[c.pop("task_id")]["checklist"].append(c)
        for n in db.query_all("SELECT task_id, body, actor, token_name, created_at FROM task_notes WHERE user_id = %s ORDER BY created_at", (uid,)):
            by_id[n.pop("task_id")]["notes"].append(n)
        # Tarefa transferida para outra pessoa (Admin › Contas): o tempo já apontado fica com
        # quem apontou, mas a tarefa não é mais dele. Esse tempo vai à parte, com o título.
        time_elsewhere = []
        for e in db.query_all(
                """SELECT e.task_id, w.title AS task_title, e.day, e.minutes, e.note, e.actor, e.token_name,
                          e.started_at, e.ended_at
                     FROM time_entries e JOIN worklog_tasks w ON w.id = e.task_id
                    WHERE e.user_id = %s ORDER BY e.day, e.id""", (uid,)):
            task = by_id.get(e["task_id"])
            if task is None:
                time_elsewhere.append(e)
                continue
            del e["task_id"], e["task_title"]
            task["time"].append(e)
        recurring = db.query_all(
            """SELECT id, label, active, freq, weekdays, month_day, interval_days, require_note, remind_at, created_at, deactivated_at,
                      steps, after_from
                 FROM recurring_tasks WHERE user_id = %s ORDER BY position, id""", (uid,))
        done, evid = {}, {}
        for c in db.query_all("SELECT task_id, completed_date, note FROM recurring_completions WHERE user_id = %s ORDER BY completed_date", (uid,)):
            done.setdefault(c["task_id"], []).append(c["completed_date"])
            if c["note"]:
                evid.setdefault(c["task_id"], []).append({"date": c["completed_date"], "note": c["note"]})
        for r in recurring:
            r["completed_dates"] = done.get(r["id"], [])
            r["evidence"] = evid.get(r["id"], [])  # o que foi anotado ao marcar
            r["pauses"] = []
        rec_by_id = {r["id"]: r for r in recurring}
        for x in db.query_all(
                """SELECT recurring_id, start_d, end_d, created_at FROM recurring_pauses
                    WHERE recurring_id = ANY(%s) ORDER BY start_d, id""", (list(rec_by_id),)):
            rec_by_id[x.pop("recurring_id")]["pauses"].append(x)
        for x in db.query_all("SELECT task_id, project_id FROM worklog_task_projects WHERE task_id = ANY(%s) ORDER BY project_id",
                              (list(by_id),)):
            by_id[x["task_id"]].setdefault("extra_project_ids", []).append(x["project_id"])
        projects = db.query_all(
            """SELECT id, name, color, COALESCE(icon, 'pasta') AS icon, description, external_ref, archived, created_at
                 FROM projects WHERE user_id = %s ORDER BY id""",
            (uid,))
        objs = {}
        for o in db.query_all(
                """SELECT project_id, id, title, description, due_date, position, external_ref, created_at
                     FROM project_objectives WHERE user_id = %s ORDER BY position, id""", (uid,)):
            objs.setdefault(o.pop("project_id"), []).append(o)
        for p in projects:
            p["objectives"] = objs.get(p["id"], [])

        def prefs(table: str):
            row = db.query_one(f"SELECT * FROM {table} WHERE user_id = %s", (uid,))  # sem linha = os padrões
            return row and {k: v for k, v in row.items() if k not in ("user_id", "updated_at")}

        payload = {
            "exported_at": datetime.now(app_tz()),
            "user": db.query_one("SELECT email, work_days, created_at FROM users WHERE id = %s", (uid,)),
            "profile": db.query_one(
                f"""SELECT display_name, theme, COALESCE((SELECT s.ticket_url FROM app_settings s WHERE s.id = 1 AND {teams.company_sql('users.id')}), ticket_url) AS ticket_url,
                          default_project_id, accepts_assignments_at, viewers_allowed,
                          EXISTS (SELECT 1 FROM user_avatars a WHERE a.user_id = users.id) AS has_avatar
                     FROM users WHERE id = %s""", (uid,)),
            "prefs": {"email": prefs("notification_prefs"), "push": prefs("push_prefs"),
                      "assistant": prefs("assistant_prefs")},
            "projects": projects,
            "templates": db.query_all(
                """SELECT name, title, description, priority, project_id, after_hours, checklist, created_at
                     FROM task_templates WHERE user_id = %s ORDER BY name""", (uid,)),
            # As imagens não cabem aqui: vão no fotos.zip (Relatórios, pelo app).
            "photos": {"count": db.query_one("SELECT count(*) AS n FROM photos WHERE user_id = %s AND deleted_at IS NULL",
                                             (uid,))["n"],
                       "download": "/api/export/fotos.zip"},
            "tasks": tasks,
            # Tempo apontado em tarefas que passaram para outra pessoa (o título é o de hoje).
            "time_on_transferred_tasks": time_elsewhere,
            "recurring": recurring,
            "week_reviews": db.query_all(
                "SELECT week_start, done_at, dismissed_at FROM week_reviews WHERE user_id = %s ORDER BY week_start", (uid,)),
            # Onde a pessoa está: as equipes de que faz parte (só o nome) e os papéis da conta.
            "teams": [r["name"] for r in db.query_all(
                """SELECT t.name FROM team_members m JOIN teams t ON t.id = m.team_id
                    WHERE m.user_id = %s ORDER BY lower(t.name)""", (uid,))],
            "roles": [r["role"] for r in db.query_all("SELECT role FROM user_roles WHERE user_id = %s ORDER BY role", (uid,))],
            "renewals": db.query_all(
                """SELECT r.label, r.expires_on, r.warn_days, r.renew_months, p.name AS project, r.note, r.created_at
                     FROM renewals r LEFT JOIN projects p ON p.id = r.project_id
                    WHERE r.user_id = %s ORDER BY r.expires_on""", (uid,)),
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o))
        return _download(body.encode("utf-8"), "application/json", f"nexus-dados-{stamp}.json")
    raise HTTPException(status_code=404, detail="formato desconhecido")
