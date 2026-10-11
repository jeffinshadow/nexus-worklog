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


def _week_start(d: date) -> date:
    return d - timedelta(days=_sun_index(d))


# Dias úteis do usuário: máscara com domingo = bit 0 (seg–sex = 62). Recorrentes
# só geram "dia devido" em dia útil; conclusão em dia não útil é "extra".
DEFAULT_WORK_DAYS = 62
# Marcação retroativa de recorrentes: até RETRO_DAYS dias antes de hoje.
RETRO_DAYS = 7


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


def board_day_range(today: date) -> tuple[date, date]:
    return today - timedelta(days=RETRO_DAYS), today


# Recorrente vigente no dia %(day)s: criada até o dia e, se desativada, só até o
# dia da desativação (inclusive). Inativa sem data (legado anterior à 002) fica
# de fora, como antes.
_VIGENTE_NO_DIA = """
    (r.created_at AT TIME ZONE %(tz)s)::date <= %(day)s
    AND (r.active OR (r.deactivated_at IS NOT NULL
                      AND (r.deactivated_at AT TIME ZONE %(tz)s)::date >= %(day)s))
"""


def recurring_vigente(task_id: int, user_id: int, day: date) -> bool:
    row = db.query_one(
        "SELECT 1 FROM recurring_tasks r WHERE r.id = %(id)s AND r.user_id = %(uid)s AND"
        + _VIGENTE_NO_DIA,
        {"id": task_id, "uid": user_id, "day": day, "tz": config.APP_TZ},
    )
    return row is not None


def get_board(user_id: int, day: date | None = None, project: int | None = None) -> dict:
    """Quadro do usuário. `day` escolhe o dia das recorrentes (padrão: hoje;
    a rota garante a janela de RETRO_DAYS). As pontuais não dependem do dia;
    `project` filtra as pontuais (0 = sem projeto)."""
    today = app_today()
    day = day or today
    mask = work_mask(user_id)
    # `done_today` = concluída no dia selecionado (nome mantido por compatibilidade).
    # Hoje: só as ativas (removeu, some na hora). Dias passados: as que eram
    # vigentes naquele dia, inclusive as desativadas depois.
    filtro = " r.active" if day == today else _VIGENTE_NO_DIA
    recurring = db.query_all(
        """
        SELECT r.id, r.label, r.position, r.freq, r.weekdays, r.month_day, r.interval_days,
               (r.created_at AT TIME ZONE %(tz)s)::date AS start_d,
               (c.id IS NOT NULL) AS done_today
          FROM recurring_tasks r
          LEFT JOIN recurring_completions c
                 ON c.task_id = r.id AND c.completed_date = %(day)s
         WHERE r.user_id = %(uid)s AND"""
        + filtro
        + """
         ORDER BY r.position, r.id
        """,
        {"uid": user_id, "day": day, "tz": config.APP_TZ},
    )
    filtro_proj, params = "", [user_id]
    if project is not None:
        filtro_proj = " AND w.project_id IS NULL" if project == 0 else " AND w.project_id = %s"
        if project:
            params.append(project)
    cols = """
        SELECT w.id, w.title, w.description, w.status, w.due_date, w.created_at, w.completed_at,
               w.priority, w.project_id, p.name AS project_name, p.color AS project_color,
               (SELECT count(*) FROM task_checklist c WHERE c.task_id = w.id)::int AS check_total,
               (SELECT count(*) FROM task_checklist c WHERE c.task_id = w.id AND c.done)::int AS check_done,
               (SELECT count(*) FROM task_notes n WHERE n.task_id = w.id)::int AS notes_count,
               (SELECT COALESCE(sum(t.minutes), 0) FROM time_entries t WHERE t.task_id = w.id)::int AS minutes
          FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id
         WHERE w.user_id = %s"""
    in_progress = db.query_all(
        cols + " AND w.status <> 'done'" + filtro_proj
        + " ORDER BY w.priority, COALESCE(w.due_date, DATE '9999-12-31'), w.created_at",
        tuple(params),
    )
    done = db.query_all(
        cols + " AND w.status = 'done'" + filtro_proj + " ORDER BY w.completed_at DESC NULLS LAST",
        tuple(params),
    )
    for r in recurring:
        r["due"] = is_due(r, day, mask)
    min_day, _ = board_day_range(today)
    return {
        "recurring": recurring,
        "in_progress": in_progress,
        "done": done,
        "day": day,
        "today": today,
        "min_day": min_day,
        "work_day": is_work_day(day, mask),
    }


# Datas de referência (hoje / início da semana=DOMINGO / início do mês) no fuso
# da aplicação. EXTRACT(DOW) usa domingo=0, então week_start = today - DOW
# (evita o date_trunc('week') do Postgres, que começaria na segunda).
_REF_DATES = """
    WITH p AS (
        SELECT
            d.today,
            d.today - CAST(EXTRACT(DOW FROM d.today) AS int) AS week_start,
            date_trunc('month', d.today)::date               AS month_start
        FROM (SELECT (now() AT TIME ZONE %(tz)s)::date AS today) d
    )
"""

# Grupo A — recorrentes: calculado em Python (_recurring_kpis), junto com os
# gráficos, para que "devido" siga uma regra só (is_due): um slot = (recorrente
# vigente, dia da agenda dela). Conclusão fora da agenda conta como "extra".

# Grupo B — pontuais. Concluído = worklog 'done' com completed_at no período
# (no fuso da app). "Em aberto" = backlog atual (status <> 'done'), igual para
# os três períodos por definição (escolha documentada).
_DASH_PONTUAL_SQL = _REF_DATES + """
    SELECT
        (SELECT count(*) FROM worklog_tasks
          WHERE user_id = %(uid)s AND status <> 'done')::int AS open_now,
        count(*) FILTER (WHERE (w.completed_at AT TIME ZONE %(tz)s)::date =  p.today)::int       AS day_done,
        count(*) FILTER (WHERE (w.completed_at AT TIME ZONE %(tz)s)::date >= p.week_start)::int  AS week_done,
        count(*) FILTER (WHERE (w.completed_at AT TIME ZONE %(tz)s)::date >= p.month_start)::int AS month_done
      FROM p
      LEFT JOIN worklog_tasks w
             ON w.user_id = %(uid)s
            AND w.status = 'done'
            AND w.completed_at IS NOT NULL
            -- LEAST: cobre também a semana atual quando ela começa no mês anterior.
            AND (w.completed_at AT TIME ZONE %(tz)s)::date
                BETWEEN LEAST(p.week_start, p.month_start) AND p.today
"""


def _recurring_tasks_and_completions(user_id: int, since: date, until: date):
    tz = config.APP_TZ
    tasks = db.query_all(
        """
        SELECT r.id, r.label, r.freq, r.weekdays, r.month_day, r.interval_days,
               (r.created_at AT TIME ZONE %s)::date AS start_d,
               COALESCE((r.deactivated_at AT TIME ZONE %s)::date,
                        (now() AT TIME ZONE %s)::date) AS end_d
          FROM recurring_tasks r
         WHERE r.user_id = %s
         ORDER BY r.position, r.id
        """,
        (tz, tz, tz, user_id),
    )
    completions = db.query_all(
        """
        SELECT task_id, completed_date
          FROM recurring_completions
         WHERE user_id = %s AND completed_date BETWEEN %s AND %s
        """,
        (user_id, since, until),
    )
    return tasks, completions


def _recurring_kpis(tasks, completions, mask: int, today: date) -> dict:
    """Dia/semana/mês: done = conclusões em dia útil dentro da vigência;
    open = slots úteis ainda não concluídos; extra = conclusões em dia não útil."""
    by_id = {t["id"]: t for t in tasks}
    periods = {"day": today, "week": _week_start(today), "month": today.replace(day=1)}
    out = {}
    for key, ps in periods.items():
        slots = sum(
            _due_between(t, max(ps, t["start_d"]), min(today, t["end_d"]), mask)
            for t in tasks
        )
        done = extra = 0
        for c in completions:
            t = by_id.get(c["task_id"])
            d = c["completed_date"]
            if not t or not (ps <= d <= today) or not (t["start_d"] <= d <= t["end_d"]):
                continue
            if is_due(t, d, mask):
                done += 1
            else:
                extra += 1
        out[key] = {"done": done, "open": max(slots - done, 0), "extra": extra}
    return out


def get_dashboard(user_id: int) -> dict:
    params = {"uid": user_id, "tz": config.APP_TZ}
    today = app_today()
    mask = work_mask(user_id)
    tasks, completions = _recurring_tasks_and_completions(
        user_id, today - timedelta(days=_STREAK_LOOKBACK), today
    )
    b = db.query_one(_DASH_PONTUAL_SQL, params)
    return {
        "work_days": mask,
        "recurring": _recurring_kpis(tasks, completions, mask, today),
        "pontual": {
            "day":   {"done": b["day_done"],   "open": b["open_now"]},
            "week":  {"done": b["week_done"],  "open": b["open_now"]},
            "month": {"done": b["month_done"], "open": b["open_now"]},
        },
        "analytics": get_dashboard_analytics(user_id, tasks, completions, mask, today),
    }


# Janelas dos gráficos analíticos (em dias / semanas, sempre no fuso do app).
_HEAT_WEEKS = 8          # série diária: calendário mostra 4 sem., tendência 8 sem.
_ADHERENCE_DAYS = 30     # ranking de aderência por tarefa
_THROUGHPUT_WEEKS = 4    # vazão semanal de pontuais
_CYCLE_DAYS = 90         # tempo de ciclo das pontuais
_WEEKDAY_WEEKS = 8       # produtividade por dia da semana
_STREAK_LOOKBACK = 120   # histórico p/ calcular a sequência (streak) atual


def _current_streak(dates: set, today: date, mask: int, t: dict) -> int:
    """Dias ÚTEIS consecutivos concluídos terminando no último dia útil.

    Dias não úteis são pulados (não quebram nem somam). Se hoje é útil e ainda
    não foi concluído, começa do dia útil anterior: o dia em aberto não quebra
    a sequência. Para antes da criação da tarefa ou do limite de histórico."""
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
    só dia útil do dono gera slot; conclusão em dia não útil é "extra" (aparece
    no gráfico por dia da semana, mas não na aderência). Toda data já vem no
    fuso do app; `today` é a referência única.
    """
    tz = config.APP_TZ
    pont = db.query_all(
        """
        SELECT (completed_at AT TIME ZONE %s)::date AS done_d,
               EXTRACT(EPOCH FROM (completed_at - created_at)) / 3600.0 AS hours
          FROM worklog_tasks
         WHERE user_id = %s AND status = 'done' AND completed_at IS NOT NULL
           AND (completed_at AT TIME ZONE %s)::date >= %s
        """,
        (tz, user_id, tz, today - timedelta(days=_CYCLE_DAYS)),
    )
    backlog = db.query_one(
        """
        SELECT
          count(*) FILTER (WHERE status = 'todo')::int        AS todo,
          count(*) FILTER (WHERE status = 'in_progress')::int AS in_progress,
          count(*) FILTER (WHERE status = 'blocked')::int     AS blocked,
          count(*) FILTER (WHERE status <> 'done' AND due_date IS NOT NULL
                             AND due_date < %s)::int           AS overdue,
          count(*) FILTER (WHERE status <> 'done'
                             AND %s - (created_at AT TIME ZONE %s)::date < 7)::int          AS age_new,
          count(*) FILTER (WHERE status <> 'done'
                             AND %s - (created_at AT TIME ZONE %s)::date BETWEEN 7 AND 30)::int AS age_mid,
          count(*) FILTER (WHERE status <> 'done'
                             AND %s - (created_at AT TIME ZONE %s)::date > 30)::int         AS age_old
          FROM worklog_tasks
         WHERE user_id = %s
        """,
        (today, today, tz, today, tz, today, tz, user_id),
    )

    # Índices das completions de recorrentes.
    done_by_date: dict[date, int] = {}   # todas as conclusões (gráfico por dia da semana)
    dates_by_task: dict[int, set] = {}
    for c in completions:
        d = c["completed_date"]
        done_by_date[d] = done_by_date.get(d, 0) + 1
        dates_by_task.setdefault(c["task_id"], set()).add(d)

    # 1) Heatmap: série diária (done, slots) das últimas _HEAT_WEEKS semanas.
    #    _week_start(today) é um domingo, então heat_start também é domingo:
    #    cada coluna do calendário é uma semana começando no domingo.
    heat_start = _week_start(today) - timedelta(days=(_HEAT_WEEKS - 1) * 7)
    heat_days = []
    d = heat_start
    by_id = {t["id"]: t for t in tasks}
    tasks_done_on: dict[date, set] = {}
    for c in completions:
        tasks_done_on.setdefault(c["completed_date"], set()).add(c["task_id"])
    while d <= today:
        due_ids = {t["id"] for t in tasks if t["start_d"] <= d <= t["end_d"] and is_due(t, d, mask)}
        feitos = tasks_done_on.get(d, set())
        # Fora da agenda da tarefa: conta como extra, para não inflar a
        # tendência semanal (done/slots). Dia sem nada devido = quadro vazio.
        heat_days.append({
            "date": d,
            "slots": len(due_ids),
            "done": len(feitos & due_ids),
            "extra": len({i for i in feitos - due_ids if i in by_id}),
        })
        d += timedelta(days=1)

    # 2) Ranking de aderência por tarefa (últimos _ADHERENCE_DAYS) + streak atual.
    win_start = today - timedelta(days=_ADHERENCE_DAYS - 1)
    task_rows = []
    for t in tasks:
        s = max(win_start, t["start_d"])
        e = min(today, t["end_d"])
        slots = _due_between(t, s, e, mask)
        if slots <= 0:
            continue  # nenhum dia devido na janela: fora do ranking
        dts = dates_by_task.get(t["id"], set())
        done = sum(1 for dd in dts if s <= dd <= e and is_due(t, dd, mask))
        task_rows.append({
            "label": t["label"], "slots": slots, "done": done,
            "streak": _current_streak(dts, today, mask, t),
        })
    task_rows.sort(key=lambda r: (r["done"] / r["slots"], r["done"]), reverse=True)

    # 3) Vazão: pontuais concluídas por semana (últimas _THROUGHPUT_WEEKS).
    tp_start = _week_start(today) - timedelta(days=(_THROUGHPUT_WEEKS - 1) * 7)
    week_counts: dict[date, int] = {}
    wk = tp_start
    while wk <= today:
        week_counts[wk] = 0
        wk += timedelta(days=7)
    for p in pont:
        ws = _week_start(p["done_d"])
        if ws in week_counts:
            week_counts[ws] += 1
    throughput = [{"week_start": w, "done": week_counts[w]} for w in sorted(week_counts)]

    # 4) Tempo de ciclo: durações (horas) das pontuais concluídas (_CYCLE_DAYS).
    durations = [
        round(float(p["hours"]), 2)
        for p in pont
        if p["hours"] is not None and p["hours"] >= 0
    ]

    # 5) Produtividade por dia da semana (últimas _WEEKDAY_WEEKS): recorrentes +
    #    pontuais concluídas, somadas por dia da semana (índice domingo=0).
    wd_start = today - timedelta(days=_WEEKDAY_WEEKS * 7 - 1)
    weekday = [0] * 7
    for dd, n in done_by_date.items():
        if wd_start <= dd <= today:
            weekday[_sun_index(dd)] += n
    for p in pont:
        if wd_start <= p["done_d"] <= today:
            weekday[_sun_index(p["done_d"])] += 1

    return {
        "heatmap": {"start": heat_start, "today": today, "days": heat_days},
        "task_adherence": {"window_days": _ADHERENCE_DAYS, "tasks": task_rows},
        "throughput": {"weeks": throughput},
        "cycle_time": {"durations_h": durations},
        "weekday": {"counts": weekday},
        "backlog": {
            "todo": backlog["todo"],
            "in_progress": backlog["in_progress"],
            "blocked": backlog["blocked"],
            "overdue": backlog["overdue"],
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
               (SELECT count(*) FROM task_checklist c WHERE c.task_id = w.id)::int AS check_total,
               (SELECT count(*) FROM task_checklist c WHERE c.task_id = w.id AND c.done)::int AS check_done,
               (SELECT COALESCE(sum(t.minutes), 0) FROM time_entries t WHERE t.task_id = w.id)::int AS minutes
          FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id
         WHERE w.user_id = %s AND w.status = 'done' AND w.completed_at IS NOT NULL
           AND (w.completed_at AT TIME ZONE %s)::date BETWEEN %s AND %s"""
        + filtro + " ORDER BY w.completed_at",
        (tz, user_id, tz, start, end, pid, pid),
    )
    entries = db.query_all(
        """
        SELECT e.day, e.minutes, e.note, w.title, p.name AS project, p.color AS project_color
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
               (SELECT count(*) FROM task_checklist c WHERE c.task_id = w.id)::int AS check_total,
               (SELECT count(*) FROM task_checklist c WHERE c.task_id = w.id AND c.done)::int AS check_done,
               (SELECT COALESCE(sum(t.minutes), 0) FROM time_entries t WHERE t.task_id = w.id)::int AS minutes
          FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id
         WHERE w.user_id = %s AND w.status <> 'done'"""
        + filtro + " ORDER BY w.priority, COALESCE(w.due_date, DATE '9999-12-31'), w.created_at",
        (user_id, pid, pid),
    )

    done_by_date: dict[date, set[int]] = {}
    for c in completions:
        done_by_date.setdefault(c["completed_date"], set()).add(c["task_id"])
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
            if is_due(t, d, mask):
                st["due"] += 1
                st["done"] += feito
                rec.append({"label": t["label"], "done": feito, "extra": False})
            elif feito:
                st["extra"] += 1
                extras.append({"label": t["label"], "done": True, "extra": True})
        n_done = sum(1 for r in rec if r["done"])
        pont = pont_by_date.get(d, [])
        tempo = time_by_date.get(d, [])
        minutes = sum(e["minutes"] for e in tempo)
        series.append({"date": d, "work_day": is_work_day(d, mask), "recurring_done": n_done + len(extras),
                       "recurring_total": len(rec), "pontual": len(pont), "minutes": minutes})
        total_done += n_done
        total_slots += len(rec)
        total_extra += len(extras)
        if done_ids or pont or tempo:
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
            "pontual_done": len(pontuais),
            "active_days": len(days),
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
        "active_days": s["active_days"],
        "deliveries": [{"id": w["id"], "title": w["title"], "project": w["project"],
                        "project_color": w["project_color"], "minutes": w["minutes"]} for w in r["deliveries"]],
        "projects": [p for p in r["projects"] if p["minutes"] or p["done"]],
        "missed": [x["label"] for x in r["recurring_stats"] if x["due"] > x["done"]],
    }


def get_summary(user_id: int) -> dict:
    """Resumos da tela Hoje: o último dia útil e a semana até agora, com a
    mesma parte da semana anterior para comparar (mesmo número de dias)."""
    today = app_today()
    mask = work_mask(user_id)
    last = last_work_day(today, mask)
    ws = _week_start(today)
    prev_s = ws - timedelta(days=7)
    prev_e = prev_s + (today - ws)
    week = _compact(get_report_range(user_id, ws, today))
    prev = _compact(get_report_range(user_id, prev_s, prev_e))
    week["previous"] = {k: prev[k] for k in ("recurring_done", "recurring_total", "pontual_done", "minutes", "start", "end")}
    return {"today": today, "last_day": _compact(get_report_range(user_id, last, last)), "week": week}
