"""Visualizador de tarefas: vê, sem editar, o registro de cada pessoa
(quadro, retrospectiva, relatório em PDF) e baixa as horas da equipe.

Só pelo app (nunca por chave de API), como o admin. Quem pode ser visto é
decidido num lugar só, app/visibility.py (papel Usuário e o aceite em
Configurações > Conta, users.viewers_allowed, ou todos com a instância em
"Visível para quem gerencia", Admin › Para empresas): quem não pode responde 404, como
quem não existe, e não entra em nenhum número do painel da Equipe (/team).
"""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db, people
from ..config import config
from ..deps import require_viewer
from ..visibility import active_sql, visible_sql
from .dashboard import MONTH, parse_month
from ..services import (TREND_MONTHS, _add_months, _month_end, app_today, app_tz, get_board, get_dashboard,
                        get_report_range, team_report_inputs)
from .board import check_board_day
from .export import time_csv
from .reports import build_pdf_response

router = APIRouter(prefix="/api/viewer", tags=["viewer"])


def _ensure_user(user_id: int) -> dict:
    row = db.query_one(f"SELECT u.id, u.email FROM users u WHERE u.id = %s AND {visible_sql('u')}", (user_id,))
    if not row:
        raise HTTPException(status_code=404, detail="usuário não encontrado")
    return row


@router.get("/users")
def list_users(viewer=Depends(require_viewer)):
    # Só quem já entrou e segue com acesso (convite pendente ou conta bloqueada
    # não têm o que mostrar), em ordem de nome, como aparecem no seletor.
    rows = db.query_all(f"SELECT u.id, u.email FROM users u WHERE {visible_sql('u')} AND {active_sql('u')}")
    return sorted(({**r, **people.profile(r["id"])} for r in rows), key=lambda x: (x["name"].lower(), x["email"]))


@router.get("/users/{user_id}/board")
def user_board(user_id: int, day: Optional[date] = Query(default=None), viewer=Depends(require_viewer)):
    _ensure_user(user_id)
    return get_board(user_id, check_board_day(day))


@router.get("/users/{user_id}/dashboard")
def user_dashboard(user_id: int, month: Optional[str] = MONTH, viewer=Depends(require_viewer)):
    _ensure_user(user_id)
    out = get_dashboard(user_id, parse_month(month))
    if out.get("overview"):
        # Quem acompanha vê o mês (como no PDF), sem placar: nem o ranking por
        # rotina, nem a tendência dos meses, nem a comparação com a média da pessoa.
        out["overview"].update(behind=[], trend=[], average=None, compare=None, previous=None)
    return out


@router.get("/users/{user_id}/projects")
def user_projects(user_id: int, viewer=Depends(require_viewer)):
    """Projetos da pessoa (para tirar o relatório de um cliente dela)."""
    _ensure_user(user_id)
    return db.query_all("SELECT id, name, archived FROM projects WHERE user_id = %s ORDER BY archived, lower(name)", (user_id,))


@router.get("/users/{user_id}/reports/export")
def user_report_export(
    user_id: int,
    start: date | None = Query(None),
    end: date | None = Query(None),
    project: int | None = Query(None),
    viewer=Depends(require_viewer),
):
    target = _ensure_user(user_id)
    return build_pdf_response(target["email"], user_id, start, end, project)


@router.get("/export/apontamentos.csv")
def team_time_csv(start: Optional[date] = Query(default=None), end: Optional[date] = Query(default=None),
                  viewer=Depends(require_viewer)):
    """Apontamentos de quem aceitou o visualizador (some por cliente/projeto na
    planilha), do período start..end (padrão: o mês corrente; até 1 ano)."""
    today = app_today()
    start = start or today.replace(day=1)
    end = min(end or today, today)
    if end < start or (end - start).days > 366:
        raise HTTPException(status_code=400, detail="período inválido (até 1 ano)")
    return time_csv(None, f"nexus-apontamentos-equipe-{start.isoformat()}-a-{end.isoformat()}.csv",
                    viewable_only=True, start=start, end=end)


# ------------------------------------------------------- painel da Equipe --
# Para COORDENAR, não para comparar: números da equipe SOMADOS (nada por pessoa
# além de "em aberto", "aguardando" e a última atividade nos cartões), sem
# média, sem tendência individual, sem ranking. Só quem pode ser visto
# (visibility.visible_sql) e está com a conta em uso; o resto não entra em
# nenhuma soma, cartão ou item.

ATTENTION_MAX = 6      # itens em "Precisa de atenção"
DUE_SOON_DAYS = 7      # vencimentos dos próximos 7 dias (e os que já passaram)
ASSIGNED_STALE = 5     # atribuída por mim, "a fazer" e sem nada registrado há 5 dias


def _team_people(viewer_id: int) -> tuple[list[dict], int]:
    """Cartões (em ordem alfabética de nome) e quantas contas com registro
    próprio NÃO compartilham (sem nomes; quem acompanha não conta a si mesmo)."""
    rows = db.query_all(
        f"""SELECT u.id, u.email, u.display_name, extract(epoch FROM a.updated_at)::bigint AS av,
                   COALESCE(t.open, 0) AS open, COALESCE(t.waiting, 0) AS waiting, la.at AS last_activity
              FROM users u
              LEFT JOIN user_avatars a ON a.user_id = u.id
              LEFT JOIN (SELECT user_id, count(*)::int AS open, count(*) FILTER (WHERE status = 'blocked')::int AS waiting
                           FROM worklog_tasks WHERE status <> 'done' GROUP BY user_id) t ON t.user_id = u.id
              LEFT JOIN LATERAL (SELECT max(l.created_at) AS at FROM audit_log l
                                  WHERE l.user_id = u.id AND l.action LIKE ANY(%(acts)s)) la ON true
             WHERE {visible_sql('u')} AND {active_sql('u')}""",
        {"acts": list(people.WORK_ACTIONS)})
    out = [{"id": r["id"], "email": r["email"], "display_name": r["display_name"],
            "name": r["display_name"] or people.name_from_email(r["email"]),
            "avatar": f"/api/me/avatar/{r['id']}?v={r['av']}" if r["av"] else None,
            "open": r["open"], "waiting": r["waiting"], "last_activity": r["last_activity"]} for r in rows]
    out.sort(key=lambda p: (p["name"].lower(), p["email"]))
    hidden = db.query_one(
        f"""SELECT count(*)::int AS n FROM users u
             WHERE u.id <> %s AND {active_sql('u')} AND NOT {visible_sql('u')}
               AND EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'user')""",
        (viewer_id,))["n"]
    return out, hidden


def _team_first_day(uids: list[int]) -> date:
    """Primeiro dia com algo de alguém da equipe (o seletor de mês não passa dele)."""
    if not uids:
        return app_today()
    return db.query_one(
        """SELECT LEAST((SELECT min((created_at AT TIME ZONE %(tz)s)::date) FROM users WHERE id = ANY(%(u)s)),
                        (SELECT min((created_at AT TIME ZONE %(tz)s)::date) FROM worklog_tasks WHERE user_id = ANY(%(u)s)),
                        (SELECT min(completed_date) FROM recurring_completions WHERE user_id = ANY(%(u)s)),
                        (SELECT min(day) FROM time_entries WHERE user_id = ANY(%(u)s))) AS d""",
        {"tz": config.APP_TZ, "u": uids})["d"] or app_today()


def _attention(uids: list[int], viewer_id: int, names: dict[int, str]) -> list[dict]:
    """O que destrava trabalho, agora: tarefas que EU atribuí e foram
    devolvidas (até eu decidir), estão aguardando ou paradas (a fazer, sem nada
    registrado há ASSIGNED_STALE dias), o que aguarda há mais tempo e os
    vencimentos próximos. Até ATTENTION_MAX, alternando os tipos (cada um
    aparece). As devolvidas são minhas (estão na minha lista de atribuídas):
    entram mesmo de quem não compartilha o dia a dia."""
    from .assign import open_returns
    today = app_today()
    tz = app_tz()
    returned = [{"kind": "returned", "task_id": r["id"], "title": r["title"], "user_id": r["to_id"],
                 "name": r["to_name"], "status": "returned", "due_date": None, "blocked_reason": None,
                 "follow_up_on": None, "reason": r["reason"],
                 "days": (today - r["at"].astimezone(tz).date()).days} for r in open_returns(viewer_id)]
    if not uids:
        return returned[:ATTENTION_MAX]
    rows = db.query_all(
        """SELECT w.id, w.user_id, w.title, w.status, w.due_date, w.blocked_at, w.blocked_reason, w.follow_up_on,
                  w.assigned_at, (w.assigned_by IS NOT DISTINCT FROM %(me)s) AS mine,
                  NOT EXISTS (SELECT 1 FROM time_entries x WHERE x.task_id = w.id
                              UNION ALL SELECT 1 FROM task_notes x WHERE x.task_id = w.id
                              UNION ALL SELECT 1 FROM task_checklist x WHERE x.task_id = w.id AND x.done) AS untouched
             FROM worklog_tasks w
            WHERE w.user_id = ANY(%(u)s) AND w.status <> 'done'
              AND (w.status = 'blocked'
                   OR (w.due_date IS NOT NULL AND w.due_date <= %(soon)s)
                   OR (w.assigned_by = %(me)s AND w.status = 'todo'
                       AND w.assigned_at < now() - make_interval(days => %(stale)s)))""",
        {"me": viewer_id, "u": uids, "soon": today + timedelta(days=DUE_SOON_DAYS), "stale": ASSIGNED_STALE})
    # Dias desde ts (None: sem a data, como aguardando antes da sql/012; a tela não diz "há quanto").
    since = lambda ts: (today - ts.astimezone(tz).date()).days if ts else None  # noqa: E731

    def item(r, kind, days):
        return {"kind": kind, "task_id": r["id"], "title": r["title"], "user_id": r["user_id"],
                "name": names.get(r["user_id"]), "status": r["status"], "due_date": r["due_date"],
                "blocked_reason": r["blocked_reason"], "follow_up_on": r["follow_up_on"], "days": days}

    mine = sorted((item(r, "assigned", since(r["blocked_at"] if r["status"] == "blocked" else r["assigned_at"]))
                   for r in rows if r["mine"] and (r["status"] == "blocked" or (
                       r["status"] == "todo" and r["untouched"] and r["assigned_at"] is not None
                       and since(r["assigned_at"]) >= ASSIGNED_STALE))),
                  key=lambda x: -(x["days"] or 0))
    waiting = sorted((item(r, "waiting", since(r["blocked_at"])) for r in rows if r["status"] == "blocked"),
                     key=lambda x: -(x["days"] or 0))
    due = sorted((item(r, "due", (r["due_date"] - today).days) for r in rows
                  if r["due_date"] and r["due_date"] <= today + timedelta(days=DUE_SOON_DAYS)),
                 key=lambda x: (x["due_date"], x["task_id"]))
    out, seen, groups = [], set(), [returned, mine, waiting, due]
    while len(out) < ATTENTION_MAX and any(groups):
        for g in groups:
            while g and g[0]["task_id"] in seen:
                g.pop(0)
            if g and len(out) < ATTENTION_MAX:
                x = g.pop(0)
                seen.add(x["task_id"])
                out.append(x)
    order = {"returned": 0, "assigned": 1, "waiting": 2, "due": 3}
    return sorted(out, key=lambda x: order[x["kind"]])  # estável: dentro do tipo, a ordem da escolha


@router.get("/team")
def team_panel(month: Optional[str] = MONTH, viewer=Depends(require_viewer)):
    """Painel da Equipe de um mês (padrão: o corrente, até hoje). Tudo SOMADO de
    quem pode ser visto: rotinas em dia, concluídas e horas do mês (a mesma conta
    do PDF e de Meu mês de cada pessoa) com os últimos 6 meses da equipe, as
    tarefas aguardando agora, "Precisa de atenção", o tempo por projeto (por
    nome, como no CSV) e os cartões das pessoas, em ordem alfabética."""
    today = app_today()
    m = parse_month(month) or today.replace(day=1)
    end = min(_month_end(m), today)
    folks, hidden = _team_people(viewer["user_id"])
    uids = [p["id"] for p in folks]
    first_month = _team_first_day(uids).replace(day=1)

    months, x = [], today.replace(day=1)
    while x >= min(first_month, m):
        months.append(x.strftime("%Y-%m"))
        x = _add_months(x, -1)

    # Os 6 meses que terminam no escolhido, a partir do primeiro com registro da equipe.
    trend_start = max(_add_months(m, 1 - TREND_MONTHS), min(first_month, m))
    inputs = team_report_inputs(uids, trend_start, end)  # uma leitura para os 6 meses de todos
    trend, projects, multi = [], {}, False
    x = trend_start
    while x <= m:
        last = end if x == m else _month_end(x)
        tot = {"recurring_done": 0, "recurring_total": 0, "pontual_done": 0, "minutes": 0}
        for uid in uids:
            r = get_report_range(uid, x, last, inputs=inputs[uid], with_open=False)
            for k in tot:
                tot[k] += r["summary"][k]
            if x == m:
                multi = multi or r["multi_project"]
                for p in r["projects"]:
                    if p["minutes"]:
                        acc = projects.setdefault(p["name"] or "", {"name": p["name"], "color": p["color"],
                                                                     "icon": p["icon"], "minutes": 0})
                        acc["minutes"] += p["minutes"]
        trend.append({"month": x.strftime("%Y-%m"), "start": x, "end": last, **tot,
                      **({"now": last == today} if x == m else {})})
        x = _add_months(x, 1)
    cur = trend[-1]

    return {
        "period": {"month": m.strftime("%Y-%m"), "start": m, "end": end, "now": end == today},
        "months": months,  # do corrente ao primeiro com registro da equipe
        "people_count": len(folks),
        "hidden_count": hidden,
        "month": {k: cur[k] for k in ("start", "end", "recurring_done", "recurring_total", "pontual_done", "minutes")}
                 | {"now": end == today},
        "waiting": sum(p["waiting"] for p in folks),  # agora (não é do mês)
        "open": sum(p["open"] for p in folks),
        "trend": trend,
        "attention": _attention(uids, viewer["user_id"], {p["id"]: p["name"] for p in folks}),
        "projects": sorted(projects.values(), key=lambda p: -p["minutes"]),
        "multi_project": multi,
        "people": folks,
        "can_assign": "assigner" in (viewer.get("roles") or []),
    }
