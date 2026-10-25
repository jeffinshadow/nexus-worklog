"""Leituras agregadas (board, dashboard, relatorios).

Todas as funcoes recebem um user_id EXPLICITO. Quem decide qual user_id passar
sao as rotas (proprio usuario, ou alvo validado por require_admin). Assim a
mesma logica serve tanto o usuario comum quanto a visao de admin.
"""

import calendar
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import db
from .config import config


def app_tz() -> ZoneInfo:
    return ZoneInfo(config.APP_TZ)


def app_today() -> date:
    return datetime.now(app_tz()).date()


# Semana começa no DOMINGO (padrão do app). date.weekday(): seg=0..dom=6;
# (weekday()+1) % 7 -> dom=0, seg=1, ..., sáb=6, que é o "índice de domingo".
def _sun_index(d: date) -> int:
    return (d.weekday() + 1) % 7


def week_start(d: date) -> date:
    return d - timedelta(days=_sun_index(d))


# Dias úteis do usuário: máscara com domingo = bit 0 (seg–sex = 62). Usados pelas
# rotinas "nos dias úteis" (freq daily); as outras seguem a própria agenda (is_due).
DEFAULT_WORK_DAYS = 62
# Marcação retroativa de recorrentes: até RETRO_DAYS dias antes de hoje.
RETRO_DAYS = 7


def task_retro_days() -> int:
    """Até quantos dias para trás uma tarefa pode ser criada ou concluída
    (configurável pelo admin; a linha id=1 sempre existe: sql/010)."""
    row = db.query_one("SELECT retro_days FROM app_settings WHERE id = 1")
    return row["retro_days"] if row else 60


def work_mask(user_id: int) -> int:
    row = db.query_one("SELECT work_days FROM users WHERE id = %s", (user_id,))
    return row["work_days"] if row else DEFAULT_WORK_DAYS


def is_work_day(d: date, mask: int) -> bool:
    return bool((mask >> _sun_index(d)) & 1)


def is_due(t: dict, d: date, mask: int) -> bool:
    """A recorrente `t` é devida no dia `d`? Uma regra só para tudo
    (indicadores, gráficos, quadro, PDF). Fora da agenda = extra.

    daily: dias úteis do dono | weekly: dias marcados em `weekdays` |
    monthly: `month_day` (31 = último dia; meses curtos usam o último) |
    interval: a cada `interval_days` dias, contando da criação (start_d).
    """
    freq = t.get("freq") or "daily"
    if freq == "weekly":
        return bool(((t.get("weekdays") or 0) >> _sun_index(d)) & 1)
    if freq == "monthly":
        last = calendar.monthrange(d.year, d.month)[1]
        return d.day == min(t.get("month_day") or 1, last)
    if freq == "interval":
        n = t.get("interval_days") or 1
        return (d - t["start_d"]).days % n == 0
    return is_work_day(d, mask)


def _due_between(t: dict, start: date, end: date, mask: int) -> int:
    """Quantos dias devidos de `t` em [start, end] (inclusive)."""
    n = 0
    d = start
    while d <= end:
        if is_due(t, d, mask):
            n += 1
        d += timedelta(days=1)
    return n


# Contadores de uma tarefa `w` (checklist, anotações, tempo): um lugar só para
# o quadro, o relatório e a exportação.
TASK_COUNTS = """
    (SELECT count(*) FROM task_checklist c WHERE c.task_id = w.id)::int AS check_total,
    (SELECT count(*) FROM task_checklist c WHERE c.task_id = w.id AND c.done)::int AS check_done,
    (SELECT count(*) FROM task_notes n WHERE n.task_id = w.id)::int AS notes_count,
    (SELECT COALESCE(sum(t.minutes), 0) FROM time_entries t WHERE t.task_id = w.id)::int AS minutes"""

# Quem atribuiu a tarefa (nome de exibição ou e-mail); NULL se foi a própria pessoa.
ASSIGNER_NAME = """(SELECT COALESCE(a.display_name, a.email) FROM users a WHERE a.id = w.assigned_by) AS assigned_by_name"""

# Último movimento de uma tarefa aberta (edição, anotação, item, tempo): o
# assistente usa para "bloqueada/parada há N dias".
TOUCHED = """,
    GREATEST(w.created_at,
      (SELECT max(a.created_at) FROM audit_log a
        WHERE a.user_id = w.user_id AND a.entity = 'worklog' AND a.entity_id = w.id),
      (SELECT max(n.created_at) FROM task_notes n WHERE n.task_id = w.id),
      (SELECT max(c.created_at) FROM task_checklist c WHERE c.task_id = w.id),
      (SELECT max(t.created_at) FROM time_entries t WHERE t.task_id = w.id)) AS touched_at"""


def running_timer(user_id: int):
    """O cronômetro rodando (tarefa e início) ou None."""
    return db.query_one(
        """SELECT t.task_id, w.title, t.started_at FROM task_timers t
             JOIN worklog_tasks w ON w.id = t.task_id WHERE t.user_id = %s""", (user_id,))


def board_day_range(today: date) -> tuple[date, date]:
    return today - timedelta(days=RETRO_DAYS), today


# Vigência de cada rotina = [start_d, end_d], no fuso da app. start_d = criação.
# Ativa: sem fim. Removida: até a véspera da remoção — o próprio dia da
# remoção só conta se ela foi feita nele (removeu sem fazer = não era mais para
# fazer). Inativa sem data (legado anterior à 002) fica de fora. UMA regra para
# quadro, marcação, indicadores, relatório e resumos: o filtro é em Python.
_ROTINAS_SQL = """
    SELECT r.id, r.label, r.position, r.freq, r.weekdays, r.month_day, r.interval_days, r.require_note,
           (r.created_at AT TIME ZONE %(tz)s)::date AS start_d,
           CASE WHEN r.deactivated_at IS NULL THEN DATE '9999-12-31'  -- ativa: sem fim
                WHEN EXISTS (SELECT 1 FROM recurring_completions x WHERE x.task_id = r.id
                                AND x.completed_date = (r.deactivated_at AT TIME ZONE %(tz)s)::date)
                     THEN (r.deactivated_at AT TIME ZONE %(tz)s)::date
                ELSE (r.deactivated_at AT TIME ZONE %(tz)s)::date - 1 END AS end_d
      FROM recurring_tasks r
     WHERE r.user_id = %(uid)s AND (r.active OR r.deactivated_at IS NOT NULL)"""


def rotinas(user_id: int, task_id: int | None = None) -> list[dict]:
    extra = " AND r.id = %(id)s" if task_id is not None else ""
    return db.query_all(_ROTINAS_SQL + extra + " ORDER BY r.position, r.id",
                        {"tz": config.APP_TZ, "uid": user_id, "id": task_id})


def recurring_vigente(task_id: int, user_id: int, day: date) -> bool:
    return any(r["start_d"] <= day <= r["end_d"] for r in rotinas(user_id, task_id))


# Concluídas no quadro: as mais recentes (o resto fica no relatório/exportação).
BOARD_DONE_LIMIT = 200


def get_board(user_id: int, day: date | None = None, project: int | None = None) -> dict:
    """Quadro do usuário. `day` escolhe o dia das rotinas (padrão: hoje; a rota
    garante a janela de RETRO_DAYS): as vigentes naquele dia, com `due` (agenda)
    e `done_today` (feita no dia escolhido; nome mantido por compatibilidade).
    `in_progress` = tarefas abertas (a fazer, em andamento, bloqueadas), na
    ordem: atrasadas, vencem hoje, prioridade, prazo. `project` filtra as
    tarefas (0 = sem projeto)."""
    today = app_today()
    day = day or today
    mask = work_mask(user_id)
    feitas = {r["task_id"]: r["note"] for r in db.query_all(
        "SELECT task_id, note FROM recurring_completions WHERE user_id = %s AND completed_date = %s", (user_id, day))}
    recurring = [r for r in rotinas(user_id) if r["start_d"] <= day <= r["end_d"]]
    for r in recurring:
        r["done_today"] = r["id"] in feitas
        r["note"] = feitas.get(r["id"])  # evidência da marcação nesse dia
    filtro_proj, params = "", [user_id]
    if project is not None:
        filtro_proj = " AND w.project_id IS NULL" if project == 0 else " AND w.project_id = %s"
        if project:
            params.append(project)
    def cols(extra=""):
        return """
        SELECT w.id, w.title, w.description, w.status, w.due_date, w.created_at, w.completed_at,
               w.priority, w.project_id, w.ticket, w.after_hours, w.assigned_by, w.blocked_reason, w.blocked_at, w.follow_up_on,
               p.name AS project_name, p.color AS project_color, """ + ASSIGNER_NAME + """,
               """ + TASK_COUNTS + extra + """
          FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id
         WHERE w.user_id = %s"""
    in_progress = db.query_all(
        cols(TOUCHED) + " AND w.status <> 'done'" + filtro_proj
        + """ ORDER BY COALESCE(w.due_date < %s, false) DESC, COALESCE(w.due_date = %s, false) DESC,
                       w.priority, COALESCE(w.due_date, DATE '9999-12-31'), w.created_at""",
        tuple(params) + (today, today),
    )
    done = db.query_all(
        cols() + " AND w.status = 'done'" + filtro_proj + f" ORDER BY w.completed_at DESC NULLS LAST LIMIT {BOARD_DONE_LIMIT}",
        tuple(params),
    )
    for r in recurring:
        r["due"] = is_due(r, day, mask)
    min_day, _ = board_day_range(today)
    return {
        "timer": running_timer(user_id),
        "recurring": recurring,
        "in_progress": in_progress,
        "done": done,
        "day": day,
        "today": today,
        "min_day": min_day,
        "work_day": is_work_day(day, mask),
    }


def _recurring_tasks_and_completions(user_id: int, since: date, until: date):
    tasks = rotinas(user_id)
    completions = db.query_all(
        """
        SELECT task_id, completed_date, note
          FROM recurring_completions
         WHERE user_id = %s AND completed_date BETWEEN %s AND %s
        """,
        (user_id, since, until),
    )
    return tasks, completions


def get_dashboard(user_id: int) -> dict:
    """Dashboard: a retrospectiva (o "hoje" fica na tela Hoje e no resumo)."""
    today = app_today()
    mask = work_mask(user_id)
    tasks, completions = _recurring_tasks_and_completions(
        user_id, today - timedelta(days=_STREAK_LOOKBACK), today
    )
    return get_dashboard_analytics(user_id, tasks, completions, mask, today)


# Janelas dos gráficos analíticos (em dias / semanas, sempre no fuso do app).
_HEAT_WEEKS = 4          # calendário de aderência
_ADHERENCE_DAYS = 30     # ranking de aderência por tarefa
_THROUGHPUT_WEEKS = 4    # vazão semanal de tarefas
_PROJECT_DAYS = 30       # tempo por projeto
_STREAK_LOOKBACK = 120   # histórico p/ calcular a sequência (streak) atual


def _current_streak(dates: set, today: date, mask: int, t: dict) -> int:
    """Dias da agenda (is_due) consecutivos feitos, terminando no último devido.

    Dias fora da agenda são pulados (não quebram nem somam). Se hoje é devido e
    ainda não foi feito, começa do devido anterior: o dia em aberto não quebra
    a sequência. Para antes da criação da rotina ou do limite de histórico."""
    floor = max(t["start_d"], today - timedelta(days=_STREAK_LOOKBACK))
    d = today
    if is_due(t, d, mask) and d not in dates:
        d -= timedelta(days=1)
    streak = 0
    while d >= floor:
        if is_due(t, d, mask):
            if d not in dates:
                break
            streak += 1
        d -= timedelta(days=1)
    return streak


def get_dashboard_analytics(user_id: int, tasks, completions, mask: int, today: date) -> dict:
    """Séries e recortes analíticos do dashboard.

    Recebe as recorrentes e as conclusões já lidas por get_dashboard e deriva
    TODOS os gráficos em Python. "Devido" segue a mesma regra dos indicadores:
    só dia da agenda (is_due) gera slot; feito fora da agenda é "extra" (não
    entra na aderência). Toda data já vem no
    fuso do app; `today` é a referência única.
    """
    tz = config.APP_TZ
    tp_start = week_start(today) - timedelta(days=(_THROUGHPUT_WEEKS - 1) * 7)
    pont = db.query_all(
        """
        SELECT (completed_at AT TIME ZONE %s)::date AS done_d
          FROM worklog_tasks
         WHERE user_id = %s AND status = 'done' AND completed_at IS NOT NULL
           AND (completed_at AT TIME ZONE %s)::date >= %s
        """,
        (tz, user_id, tz, tp_start),
    )
    projects = db.query_all(
        """
        SELECT p.name, p.color, sum(e.minutes)::int AS minutes
          FROM time_entries e JOIN worklog_tasks w ON w.id = e.task_id
          LEFT JOIN projects p ON p.id = w.project_id
         WHERE e.user_id = %s AND e.day > %s
         GROUP BY p.name, p.color ORDER BY minutes DESC
        """,
        (user_id, today - timedelta(days=_PROJECT_DAYS)),
    )
    backlog = db.query_one(
        """
        SELECT
          count(*) FILTER (WHERE status = 'todo')::int        AS todo,
          count(*) FILTER (WHERE status = 'in_progress')::int AS in_progress,
          count(*) FILTER (WHERE status = 'blocked')::int     AS blocked,
          count(*) FILTER (WHERE status <> 'done'
                             AND %s - (created_at AT TIME ZONE %s)::date < 7)::int          AS age_new,
          count(*) FILTER (WHERE status <> 'done'
                             AND %s - (created_at AT TIME ZONE %s)::date BETWEEN 7 AND 30)::int AS age_mid,
          count(*) FILTER (WHERE status <> 'done'
                             AND %s - (created_at AT TIME ZONE %s)::date > 30)::int         AS age_old
          FROM worklog_tasks
         WHERE user_id = %s
        """,
        (today, tz, today, tz, today, tz, user_id),
    )

    # Índices das completions de recorrentes.
    dates_by_task: dict[int, set] = {}
    for c in completions:
        dates_by_task.setdefault(c["task_id"], set()).add(c["completed_date"])

    # 1) Heatmap: série diária (done, slots) das últimas _HEAT_WEEKS semanas.
    #    week_start(today) é um domingo, então heat_start também é domingo:
    #    cada coluna do calendário é uma semana começando no domingo.
    heat_start = week_start(today) - timedelta(days=(_HEAT_WEEKS - 1) * 7)
    heat_days = []
    d = heat_start
    tasks_done_on: dict[date, set] = {}
    for c in completions:
        tasks_done_on.setdefault(c["completed_date"], set()).add(c["task_id"])
    while d <= today:
        due_ids = {t["id"] for t in tasks if t["start_d"] <= d <= t["end_d"] and is_due(t, d, mask)}
        feitos = tasks_done_on.get(d, set())
        # Feito fora da agenda não entra (é extra). Dia sem nada devido = quadro vazio.
        heat_days.append({"date": d, "slots": len(due_ids), "done": len(feitos & due_ids)})
        d += timedelta(days=1)

    # 2) Ranking de aderência por tarefa (últimos _ADHERENCE_DAYS) + streak atual.
    win_start = today - timedelta(days=_ADHERENCE_DAYS - 1)
    task_rows = []
    for t in tasks:
        s = max(win_start, t["start_d"])
        e = min(today, t["end_d"])
        dts = dates_by_task.get(t["id"], set())
        slots = _due_between(t, s, e, mask)
        if e == today and is_due(t, today, mask) and today not in dts:
            slots -= 1  # hoje ainda dá tempo: pendente não é falta
        if slots <= 0:
            continue  # nenhum dia devido na janela: fora do ranking
        done = sum(1 for dd in dts if s <= dd <= e and is_due(t, dd, mask))
        task_rows.append({
            "label": t["label"], "slots": slots, "done": done,
            "streak": _current_streak(dts, today, mask, t),
        })
    task_rows.sort(key=lambda r: (r["done"] / r["slots"], r["done"]))  # a mais pulada primeiro (retro)

    # 3) Vazão: tarefas concluídas por semana (últimas _THROUGHPUT_WEEKS).
    week_counts: dict[date, int] = {}
    wk = tp_start
    while wk <= today:
        week_counts[wk] = 0
        wk += timedelta(days=7)
    for p in pont:
        ws = week_start(p["done_d"])
        if ws in week_counts:
            week_counts[ws] += 1
    throughput = [{"week_start": w, "done": week_counts[w]} for w in sorted(week_counts)]

    return {
        "heatmap": {"days": heat_days},
        "task_adherence": {"tasks": task_rows},
        "throughput": {"weeks": throughput},
        "projects": {"items": projects},
        "backlog": {
            "todo": backlog["todo"],
            "in_progress": backlog["in_progress"],
            "blocked": backlog["blocked"],
            "aging": {
                "new": backlog["age_new"],
                "mid": backlog["age_mid"],
                "old": backlog["age_old"],
            },
        },
    }


def get_report_range(user_id: int, start: date, end: date, project: dict | None = None) -> dict:
    """Dados do relatório em PDF do período [start, end] ('end' já limitado a
    hoje pela rota).

    Dias com atividade = alguma recorrente ou pontual concluída, ou tempo
    apontado. Em cada um: as recorrentes devidas (feitas e não feitas) e as
    extras, as pontuais concluídas e os apontamentos de tempo. Além disso:
    série diária (gráfico), cumprimento por recorrente, tempo por projeto,
    entregas detalhadas e o que está em aberto agora.

    Com 'project' ({id, name}) o relatório é do projeto: só pontuais, tempo e
    abertas dele; recorrentes não têm projeto e ficam de fora.
    """
    tz = config.APP_TZ
    hoje = app_today()
    mask = work_mask(user_id)
    if project:
        tasks, completions = [], []
    else:
        tasks, completions = _recurring_tasks_and_completions(user_id, start, end)
    pid = project["id"] if project else None
    filtro = " AND (%s::bigint IS NULL OR w.project_id = %s)"

    pontuais = db.query_all(
        """
        SELECT w.id, w.title, w.description, w.priority, w.created_at, w.completed_at,
               p.name AS project, p.color AS project_color,
               (w.completed_at AT TIME ZONE %s)::date AS done_date,
               """ + TASK_COUNTS + """
          FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id
         WHERE w.user_id = %s AND w.status = 'done' AND w.completed_at IS NOT NULL
           AND (w.completed_at AT TIME ZONE %s)::date BETWEEN %s AND %s"""
        + filtro + " ORDER BY w.completed_at",
        (tz, user_id, tz, start, end, pid, pid),
    )
    entries = db.query_all(
        """
        SELECT e.day, e.minutes, e.note, w.title, w.after_hours, p.name AS project, p.color AS project_color
          FROM time_entries e
          JOIN worklog_tasks w ON w.id = e.task_id
          LEFT JOIN projects p ON p.id = w.project_id
         WHERE e.user_id = %s AND e.day BETWEEN %s AND %s"""
        + filtro + " ORDER BY e.day, e.created_at",
        (user_id, start, end, pid, pid),
    )
    abertas = db.query_all(
        """
        SELECT w.title, w.status, w.priority, w.due_date, p.name AS project, p.color AS project_color,
               """ + TASK_COUNTS + """
          FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id
         WHERE w.user_id = %s AND w.status <> 'done'"""
        + filtro + " ORDER BY w.priority, COALESCE(w.due_date, DATE '9999-12-31'), w.created_at",
        (user_id, pid, pid),
    )

    done_by_date: dict[date, set[int]] = {}
    notes: dict[tuple, str] = {}  # (dia, rotina) -> evidência
    for c in completions:
        done_by_date.setdefault(c["completed_date"], set()).add(c["task_id"])
        if c.get("note"):
            notes[(c["completed_date"], c["task_id"])] = c["note"]
    pont_by_date: dict[date, list] = {}
    for w in pontuais:
        pont_by_date.setdefault(w["done_date"], []).append(w)
    time_by_date: dict[date, list] = {}
    for e in entries:
        time_by_date.setdefault(e["day"], []).append(e)

    # Cumprimento por recorrente no período (devidas x feitas, + extras).
    per_rec = {t["id"]: {"label": t["label"], "freq": t["freq"], "weekdays": t["weekdays"],
                         "month_day": t["month_day"], "interval_days": t["interval_days"],
                         "due": 0, "done": 0, "extra": 0} for t in tasks}

    series, days = [], []
    total_done = total_slots = total_extra = 0
    d = start
    while d <= end:
        done_ids = done_by_date.get(d, set())
        vigentes = [t for t in tasks if t["start_d"] <= d <= t["end_d"]]
        rec, extras = [], []
        for t in vigentes:
            st = per_rec[t["id"]]
            feito = t["id"] in done_ids
            if d == hoje and not feito:
                continue  # hoje ainda dá tempo: pendente não é falta
            if is_due(t, d, mask):
                st["due"] += 1
                st["done"] += feito
                rec.append({"label": t["label"], "done": feito, "extra": False, "note": notes.get((d, t["id"]))})
            elif feito:
                st["extra"] += 1
                extras.append({"label": t["label"], "done": True, "extra": True, "note": notes.get((d, t["id"]))})
        n_done = sum(1 for r in rec if r["done"])
        pont = pont_by_date.get(d, [])
        tempo = time_by_date.get(d, [])
        minutes = sum(e["minutes"] for e in tempo)
        series.append({"date": d, "work_day": is_work_day(d, mask), "recurring_done": n_done + len(extras),
                       "recurring_total": len(rec), "pontual": len(pont), "minutes": minutes})
        total_done += n_done
        total_slots += len(rec)
        total_extra += len(extras)
        if done_ids & {t["id"] for t in vigentes} or pont or tempo:
            days.append({
                "date": d,
                "work_day": is_work_day(d, mask),
                "recurring": rec + extras,
                "recurring_done": n_done,
                "recurring_total": len(rec),
                "recurring_extra": len(extras),
                "pontual": pont,
                "time": tempo,
                "minutes": minutes,
            })
        d += timedelta(days=1)

    # Tempo e entregas por projeto.
    by_project: dict[str, dict] = {}
    for e in entries:
        k = e["project"] or ""
        p = by_project.setdefault(k, {"name": e["project"], "color": e["project_color"], "minutes": 0, "done": 0})
        p["minutes"] += e["minutes"]
    for w in pontuais:
        k = w["project"] or ""
        p = by_project.setdefault(k, {"name": w["project"], "color": w["project_color"], "minutes": 0, "done": 0})
        p["done"] += 1

    return {
        "start": start,
        "end": end,
        "today": app_today(),
        "generated_at": datetime.now(ZoneInfo(tz)),
        "project": project["name"] if project else None,
        "whole_project": bool(project and project.get("whole")),
        "project_truncated": bool(project and project.get("truncated")),
        "days": days,
        "series": series,
        "recurring_stats": sorted(per_rec.values(), key=lambda r: (-(r["due"] or 0), r["label"].lower())),
        "projects": sorted(by_project.values(), key=lambda p: (-p["minutes"], -p["done"])),
        "deliveries": pontuais,
        "open": abertas,
        "summary": {
            "recurring_done": total_done,
            "recurring_total": total_slots,
            "recurring_extra": total_extra,
            "minutes": sum(e["minutes"] for e in entries),
            "minutes_after_hours": sum(e["minutes"] for e in entries if e["after_hours"]),
            "pontual_done": len(pontuais),
            "active_days": len(days),
            "time_days": len({e["day"] for e in entries}),  # dias com tempo apontado (base da média)
            "period_days": (end - start).days + 1,
            "open": len(abertas),
            "overdue": sum(1 for a in abertas if a["due_date"] and a["due_date"] < app_today()),
        },
    }


# ------------------------------------------------------------------ resumos --

def last_work_day(today: date, mask: int) -> date:
    """Último dia útil antes de hoje (até uma semana para trás; senão, ontem)."""
    for i in range(1, 8):
        d = today - timedelta(days=i)
        if is_work_day(d, mask):
            return d
    return today - timedelta(days=1)


def _compact(r: dict) -> dict:
    s = r["summary"]
    return {
        "start": r["start"],
        "end": r["end"],
        "recurring_done": s["recurring_done"],
        "recurring_total": s["recurring_total"],
        "recurring_extra": s["recurring_extra"],
        "pontual_done": s["pontual_done"],
        "minutes": s["minutes"],
        "minutes_after_hours": s["minutes_after_hours"],
        "active_days": s["active_days"],
        "deliveries": [{"id": w["id"], "title": w["title"], "project": w["project"],
                        "project_color": w["project_color"], "minutes": w["minutes"]} for w in r["deliveries"]],
        "projects": [p for p in r["projects"] if p["minutes"] or p["done"]],
        "missed": [x["label"] for x in r["recurring_stats"] if x["due"] > x["done"]],
    }


def get_summary(user_id: int) -> dict:
    """Resumos da tela Hoje: desde o último dia útil até ontem (na segunda,
    sexta a domingo — o plantão do fim de semana entra) e a semana até agora,
    com a mesma parte da semana anterior para comparar (mesmo número de dias)."""
    today = app_today()
    mask = work_mask(user_id)
    last = last_work_day(today, mask)
    ws = week_start(today)
    prev_s = ws - timedelta(days=7)
    prev_e = prev_s + (today - ws)
    week = _compact(get_report_range(user_id, ws, today))
    prev = _compact(get_report_range(user_id, prev_s, prev_e))
    week["previous"] = {k: prev[k] for k in ("recurring_done", "recurring_total", "pontual_done", "minutes", "start", "end")}
    return {"today": today, "last_day": _compact(get_report_range(user_id, last, today - timedelta(days=1))), "week": week,
            "today_stats": _compact(get_report_range(user_id, today, today))}  # fechamento do dia
