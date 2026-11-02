"""Revisão semanal guiada.

Revisão: no último dia útil da semana (domingo a sábado, a mesma do resumo do
Hoje) o assistente convida, uma vez, para três passos curtos: o que fechou, o
que ficou e o que vem. Nada é obrigatório; feita ou dispensada, o convite não
volta naquela semana. O texto final reaproveita o formato da passagem de turno.
"""
from datetime import date, datetime, time, timedelta

from . import db, people
from .services import app_today, app_tz, get_board, is_work_day, week_start, work_mask

NEXT_MAX = 3        # prioridades da próxima semana
DONE_MAX = 100      # concluídas listadas na revisão


def week_bounds(d: date) -> tuple[date, date]:
    ws = week_start(d)
    return ws, ws + timedelta(days=6)


def review_day(d: date, mask: int) -> date | None:
    """Último dia útil da semana de `d` (None: semana sem dia útil)."""
    ws, _ = week_bounds(d)
    for i in range(6, -1, -1):
        x = ws + timedelta(days=i)
        if is_work_day(x, mask):
            return x
    return None


def waiting_days(t: dict, today: date) -> int:
    """Dias de calendário (fuso da app) desde que a tarefa passou a aguardar."""
    ts = t.get("blocked_at")
    return max(0, (today - ts.astimezone(app_tz()).date()).days) if ts else 0


def state(uid: int, ws: date) -> dict:
    r = db.query_one("SELECT done_at, dismissed_at FROM week_reviews WHERE user_id = %s AND week_start = %s", (uid, ws))
    return dict(r) if r else {"done_at": None, "dismissed_at": None}


def mark(uid: int, column: str) -> dict:
    assert column in ("done_at", "dismissed_at")
    ws, _ = week_bounds(app_today())
    db.execute(f"""INSERT INTO week_reviews (user_id, week_start, {column}) VALUES (%s, %s, now())
                   ON CONFLICT (user_id, week_start) DO UPDATE SET {column} = now()""", (uid, ws))
    return state(uid, ws)


def hints(uid: int) -> dict:
    """O que o assistente do Hoje precisa: convidar para a revisão?"""
    today = app_today()
    mask = work_mask(uid)
    ws, _ = week_bounds(today)
    st = state(uid, ws)
    return {"invite": review_day(today, mask) == today and not st["done_at"] and not st["dismissed_at"],
            "reviewed": bool(st["done_at"])}


def _task(t: dict, today: date) -> dict:
    return {"id": t["id"], "title": t["title"], "status": t["status"], "priority": t["priority"],
            "due_date": t["due_date"], "project_name": t.get("project_name"), "ticket": t.get("ticket"),
            "assigned_by_name": t.get("assigned_by_name"), "blocked_reason": t.get("blocked_reason"),
            "follow_up_on": t.get("follow_up_on"),
            "waiting_days": waiting_days(t, today) if t["status"] == "blocked" else None}


def week_review(uid: int) -> dict:
    """A revisão da semana atual: concluídas (com ou sem "como resolveu"), o que
    ficou aberto ou aguardando e até 3 sugestões para a próxima semana (a mesma
    ordem do Hoje: atrasadas, vencem logo, prioridade alta, prazo)."""
    today = app_today()
    mask = work_mask(uid)
    ws, we = week_bounds(today)
    tz = app_tz()
    done = db.query_all(
        """SELECT w.id, w.title, w.resolution, w.completed_at, p.name AS project_name
             FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id
            WHERE w.user_id = %s AND w.status = 'done' AND w.completed_at >= %s AND w.completed_at < %s
            ORDER BY w.completed_at DESC LIMIT %s""",
        (uid, datetime.combine(ws, time(), tz), datetime.combine(we + timedelta(days=1), time(), tz), DONE_MAX))
    abertas = get_board(uid, today)["in_progress"]
    open_ = [_task(t, today) for t in abertas if t["status"] != "blocked"]
    waiting = [_task(t, today) for t in abertas if t["status"] == "blocked"]
    st = state(uid, ws)
    rd = review_day(today, mask)
    return {
        "today": today, "week_start": ws, "week_end": we, "review_day": rd, "is_review_day": rd == today,
        "done_at": st["done_at"], "dismissed_at": st["dismissed_at"],
        "done": [{"id": t["id"], "title": t["title"], "resolution": t["resolution"], "project_name": t["project_name"],
                  "completed_at": t["completed_at"]} for t in done],
        "open": open_, "waiting": waiting,
        "suggestions": [t["id"] for t in open_[:NEXT_MAX]],
    }


def week_text(uid: int, next_ids: list[int] | None = None) -> str:
    """A semana em texto puro, pronto para colar (formato da passagem de turno):
    o que fechou (com como resolveu), o que ficou, o que aguarda e o que vem."""
    from .routers.summary import _titulo  # título de terceiro entre « »
    r = week_review(uid)
    today = r["today"]
    ws, we = r["week_start"], r["week_end"]
    linhas = [f"Semana de {ws:%d/%m} a {we:%d/%m} — {people.profile(uid)['name']}", ""]
    linhas.append(f"O que fechou ({len(r['done'])}):")
    for t in r["done"][:20]:
        extra = f" [{t['project_name']}]" if t["project_name"] else ""
        como = f" — {' '.join(t['resolution'].split())[:160]}" if t["resolution"] else ""
        linhas.append(f"- {t['title']}{extra}{como}")
    if len(r["done"]) > 20:
        linhas.append(f"- e mais {len(r['done']) - 20}")
    if not r["done"]:
        linhas.append("- nada concluído")

    def prazo(t):
        if not t["due_date"]:
            return ""
        return " (atrasada)" if t["due_date"] < today else (" (vence hoje)" if t["due_date"] == today
                                                            else f" (prazo {t['due_date']:%d/%m})")
    linhas += ["", f"O que ficou ({len(r['open'])}):"]
    linhas += [f"- {_titulo(t)}{prazo(t)}" for t in r["open"][:15]] or ["- nada em aberto"]
    if len(r["open"]) > 15:
        linhas.append(f"- e mais {len(r['open']) - 15}")
    linhas += ["", f"Aguardando ({len(r['waiting'])}):"]
    for t in r["waiting"]:
        info = [f"há {t['waiting_days']} d"] if t["waiting_days"] else []
        if t["follow_up_on"]:
            info.append(f"cobrar dia {t['follow_up_on']:%d/%m}")
        motivo = f" — {t['blocked_reason']}" if t["blocked_reason"] else ""
        linhas.append(f"- {_titulo(t)}{motivo}" + (f" ({', '.join(info)})" if info else ""))
    if not r["waiting"]:
        linhas.append("- nada")
    por_id = {t["id"]: t for t in r["open"] + r["waiting"]}
    proximas = [por_id[i] for i in dict.fromkeys(next_ids or []) if i in por_id][:NEXT_MAX]
    if proximas:
        linhas += ["", "O que vem na próxima semana:"]
        for t in proximas:
            info = (["prioridade alta"] if t["priority"] == 1 else []) + (
                [(f"atrasada desde {t['due_date']:%d/%m}" if t["due_date"] < today else f"prazo {t['due_date']:%d/%m}")]
                if t["due_date"] else [])
            linhas.append(f"- {_titulo(t)}" + (f" ({', '.join(info)})" if info else ""))
    return "\n".join(linhas)
