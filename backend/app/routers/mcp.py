"""Servidor MCP (Model Context Protocol) do Nexus: ferramentas para uma IA
registrar e consultar o dia de trabalho em nome do usuário.

Transporte "Streamable HTTP" em modo simples: o cliente faz POST /mcp com
JSON-RPC 2.0 e recebe a resposta em JSON (sem stream SSE, sem sessão). Sem
SDK: o protocolo cabe neste arquivo.

Autenticação: só chave de API (Authorization: Bearer nxs_...). As ferramentas
chamam as mesmas funções das rotas REST, então herdam validação, isolamento
por usuário e histórico (registrado com actor="mcp" e o nome da chave).
Chave "read" só enxerga as ferramentas de leitura. A IA não exclui tarefas.
"""
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from .. import db, deps, services
from ..config import config
from ..labels import PRIO_PT, STATUS_PT
from ..labels import dur as _dur
from ..schemas import (AssignIn, ChecklistIn, ChecklistUpdate, FinishIn, NoteIn, TimeIn, TimerIn, ToggleIn, WorklogIn,
                       WorklogUpdate)
from . import assign as assign_routes
from . import history as history_routes
from . import projects as project_routes
from . import renewals as renewal_routes
from . import search as search_routes
from . import summary as summary_routes
from . import recurring as recurring_routes
from . import templates as template_routes
from . import timer as timer_routes
from . import worklog as worklog_routes
from .board import check_board_day

router = APIRouter(tags=["mcp"])

SUPPORTED_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26"]
SERVER_INFO = {"name": "nexus-worklog", "title": "Nexus Worklog", "version": "2.0.0"}
INSTRUCTIONS = (
    "Nexus Worklog: o registro do dia de trabalho do usuário. Use get_today para "
    "ver o dia (rotinas e tarefas abertas), get_summary para a daily/retro (ontem e a "
    "semana, com tempo por projeto) e get_week para semanas passadas. Registre o que o usuário contar com "
    "create_task/update_task/complete_task, log_time e add_note; marque rotinas com "
    "set_recurring (com note = evidência); get_handoff dá a passagem de turno. Para medir o tempo enquanto o usuário trabalha, use start_timer/stop_timer; "
    "procedimentos repetidos têm modelos (list_templates, create_from_template). "
    "Datas no formato AAAA-MM-DD, no fuso " + config.APP_TZ + ". Rotinas "
    "aceitam até 7 dias para trás; marcar uma rotina fora da agenda dela conta como extra. "
    "Para lançar algo que já aconteceu, informe created_at/completed_at (data ou data e hora) "
    "e um external_ref seu (ex.: o id da sessão) para não duplicar; confira com list_tasks from/to. "
    "Tudo fica no histórico do usuário; use undo para corrigir um engano seu."
)

STATUS = list(STATUS_PT)
PRIO = {nome: n for n, nome in PRIO_PT.items()}  # "alta" -> 1
DATE = {"type": "string", "format": "date", "description": "Data AAAA-MM-DD"}
EXTRA_PROJECTS = {"type": "array", "items": {"type": "string"}, "maxItems": 10,
                  "description": "Outros projetos além do principal (a tarefa atende mais de uma frente); a lista substitui a anterior"}
WHEN = {"type": "string", "description": "Data (AAAA-MM-DD) ou data e hora (AAAA-MM-DDTHH:MM), fuso " + config.APP_TZ + ". Nunca no futuro; até o limite retroativo da conta"}


class ToolError(Exception):
    """Erro que vira resultado com isError=true (a IA lê e pode corrigir)."""


# ------------------------------------------------------------------ helpers --

def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except HTTPException as e:
        raise ToolError(str(e.detail)) from None
    except ValidationError as e:
        msgs = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
        raise ToolError(f"parâmetros inválidos: {msgs}") from None


def _task_line(t: dict, today: date) -> str:
    parts = [f"#{t['id']} {t['title']}", f"[{STATUS_PT.get(t['status'], t['status'])}]"]
    if t.get("assigned_by_name"):
        parts.append(f"(atribuída por {t['assigned_by_name']})")
    if t.get("external_ref"):
        parts.append(f"(ref {t['external_ref']})")
    if t.get("status") == "blocked" and t.get("blocked_reason"):
        parts.append(f"(aguardando {t['blocked_reason']})")
    if t.get("status") == "blocked" and t.get("follow_up_on"):
        parts.append(f"(cobrar em {t['follow_up_on'].isoformat()})")
    if t.get("ticket"):
        parts.append(f"(chamado {t['ticket']})")
    if t.get("after_hours"):
        parts.append("(plantão)")
    if t.get("priority") == 1:
        parts.append("(prioridade alta)")
    if t.get("project_name"):
        nomes = [t["project_name"]] + [x["name"] for x in t.get("extra_projects") or []]
        parts.append("{" + " + ".join(nomes) + "}")
    if t.get("due_date") and t["status"] != "done":
        due = t["due_date"]
        parts.append(f"prazo {due.isoformat()}" + (" (ATRASADA)" if due < today else ""))
    if t.get("completed_at"):
        parts.append(f"concluída em {t['completed_at'].astimezone(services.app_tz()).date().isoformat()}")
    if t.get("check_total"):
        parts.append(f"checklist {t['check_done']}/{t['check_total']}")
    if t.get("minutes"):
        parts.append(f"tempo {_dur(t['minutes'])}")
    if t.get("description"):
        parts.append(f"— {t['description']}")
    return " ".join(parts)


def _resolve_project(uid: int, value):
    """Projeto por id ou nome (sem diferenciar maiúsculas). None = sem projeto."""
    if value is None or value == "":
        return None
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        row = db.query_one("SELECT id FROM projects WHERE id = %s AND user_id = %s", (int(value), uid))
    else:
        row = db.query_one("SELECT id FROM projects WHERE user_id = %s AND lower(name) = lower(%s)", (uid, str(value).strip()))
    if not row:
        nomes = [p["name"] for p in db.query_all("SELECT name FROM projects WHERE user_id = %s AND NOT archived ORDER BY name", (uid,))]
        raise ToolError(f"projeto “{value}” não existe. Projetos: {', '.join(nomes) or '(nenhum)'}")
    return row["id"]


def _prio(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    p = PRIO.get(str(value).lower())
    if not p:
        raise ToolError("prioridade deve ser alta, normal ou baixa")
    return p


def _task_args(uid: int, args: dict) -> dict:
    """Converte project (nome/id) e priority (alta/normal/baixa) dos argumentos."""
    args = dict(args)
    if "project" in args:
        args["project_id"] = _resolve_project(uid, args.pop("project"))
    if "extra_projects" in args:
        args["extra_project_ids"] = [_resolve_project(uid, v) for v in args.pop("extra_projects") or [] if v not in (None, "")]
    if "priority" in args:
        args["priority"] = _prio(args["priority"])
    return args


def _find_task(uid: int, task_id: int) -> dict:
    t = db.query_one(
        """SELECT w.id, w.title, w.description, w.status, w.due_date, w.completed_at, w.priority,
                  w.ticket, w.after_hours, w.external_ref, w.blocked_reason, w.follow_up_on, p.name AS project_name,
                  """ + services.ASSIGNER_NAME + ", " + services.TASK_COUNTS + """
             FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id
            WHERE w.id = %s AND w.user_id = %s""", (task_id, uid))
    if not t:
        raise ToolError(f"tarefa #{task_id} não encontrada")
    return t


# ------------------------------------------------------------------- tools --

def t_get_today(ctx, args):
    uid = ctx["user_id"]
    b = services.get_board(uid)
    today = b["today"]
    lines = [f"Hoje: {today.isoformat()} ({'dia útil' if b['work_day'] else 'dia NÃO útil'})", ""]
    if b.get("timer"):
        tm = b["timer"]
        mins = int((datetime.now(timezone.utc) - tm["started_at"]).total_seconds() // 60)
        lines += [f"Cronômetro rodando em #{tm['task_id']} {tm['title']} há {_dur(max(mins, 1))}.", ""]
    rec = [r for r in b["recurring"] if r["due"]]
    lines.append(f"Rotinas de hoje ({sum(r['done_today'] for r in rec)}/{len(rec)} feitas):")
    lines += _recurring_rows(rec) or ["  (nenhuma)"]
    extra = [r for r in b["recurring"] if not r["due"] and r["done_today"]]
    if extra:
        lines += [f"  [x] R{r['id']} {r['label']} (extra: fora da agenda)" for r in extra]
    lines.append("")
    open_ = b["in_progress"]
    lines.append(f"Tarefas abertas ({len(open_)}):")
    lines += [f"  {_task_line(t, today)}" for t in open_] or ["  (nenhuma)"]
    done_today = [t for t in b["done"] if t["completed_at"] and t["completed_at"].astimezone(services.app_tz()).date() == today]
    lines.append("")
    lines.append(f"Concluídas hoje ({len(done_today)}):")
    lines += [f"  #{t['id']} {t['title']}" for t in done_today] or ["  (nenhuma)"]
    return "\n".join(lines)


def _created(t: dict) -> str:
    return t["created_at"].astimezone(services.app_tz()).strftime("%Y-%m-%d %H:%M")


def t_list_tasks(ctx, args):
    status = args.get("status", "open")
    limit = int(args.get("limit", 50))
    if args.get("from") or args.get("to") or args.get("by"):
        rows = _call(worklog_routes.list_tasks, start=_day(args.get("from")), end=_day(args.get("to")),
                     by=args.get("by") or "created", status=args.get("status", "all"),
                     limit=max(1, min(limit, 500)), user=ctx)
        today = services.app_today()
        return "\n".join(f"criada {_created(t)} · {_task_line(t, today)}" for t in rows) or "(nenhuma tarefa no período)"
    b = services.get_board(ctx["user_id"])
    items = {"open": b["in_progress"], "done": b["done"], "all": b["in_progress"] + b["done"]}.get(status)
    if items is None:
        raise ToolError("status deve ser open, done ou all")
    items = items[: max(1, min(limit, 200))]
    return "\n".join(_task_line(t, b["today"]) for t in items) or "(nenhuma tarefa)"


def _day(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ToolError(f"data inválida: {value} (use AAAA-MM-DD)") from None


def t_create_task(ctx, args):
    data = _call(WorklogIn, **_task_args(ctx["user_id"], args))
    res = _call(worklog_routes.create, data, Response(), user=ctx)
    verbo = "Já existia (external_ref repetido), nada duplicado" if res.get("existing") else "Criada"
    return f"{verbo}: " + _task_line(_find_task(ctx["user_id"], res["id"]), services.app_today())


def t_update_task(ctx, args):
    args = dict(args)
    task_id = args.pop("task_id", None)
    if task_id is None:
        raise ToolError("informe task_id")
    data = _call(WorklogUpdate, **_task_args(ctx["user_id"], args))
    _call(worklog_routes.update, int(task_id), data, user=ctx)
    return "Atualizada: " + _task_line(_find_task(ctx["user_id"], int(task_id)), services.app_today())


def t_complete_task(ctx, args):
    task_id = int(args["task_id"])
    data = _call(FinishIn, completed_at=args.get("completed_at"), resolution=args.get("resolution"))
    _call(worklog_routes.finish, task_id, data, user=ctx)
    return "Concluída: " + _task_line(_find_task(ctx["user_id"], task_id), services.app_today())


def t_get_task(ctx, args):
    t = _call(worklog_routes.detail, int(args["task_id"]), user=ctx)
    t["check_total"] = len(t["checklist"])
    t["check_done"] = sum(1 for c in t["checklist"] if c["done"])
    lines = [_task_line(t, services.app_today())]
    if t["checklist"]:
        lines += ["", "Checklist:"] + [f"  [{'x' if c['done'] else ' '}] item #{c['id']} {c['label']}" for c in t["checklist"]]
    if t["notes"]:
        lines += ["", "Anotações (mais recentes primeiro):"]
        lines += [f"  {n['created_at'].astimezone(services.app_tz()):%d/%m %H:%M} — {n['body']}" for n in t["notes"][:10]]
    if t.get("resolution"):
        lines += ["", "Como resolveu:", t["resolution"]]
    if t["time"]:
        lines += ["", f"Tempo apontado: {_dur(t['minutes'])}"]
        lines += [f"  {e['day']:%d/%m} {_dur(e['minutes'])}" + (f" — {e['note']}" if e["note"] else "") for e in t["time"][:10]]
    return "\n".join(lines)


def t_search(ctx, args):
    r = _call(search_routes.search, str(args.get("query", "")), user=ctx)
    today = services.app_today()
    lines = []
    for t in r["tasks"]:
        t.setdefault("check_total", 0)
        lines.append(_task_line(t | {"description": None, "project_name": t["project_name"]}, today))
        lines += [f"    {h['kind']}: {h['text']}" for h in t["hits"] if h["kind"] != "título"][:3]
    if r["recurring"]:
        lines += ["", "Rotinas:"] + [f"  R{x['id']} {x['label']}" + ("" if x["active"] else " (removida)") for x in r["recurring"]]
    if r["projects"]:
        lines += ["", "Projetos:"] + [f"  #{x['id']} {x['name']}" for x in r["projects"]]
    return "\n".join(lines) or "Nada encontrado."


def t_add_note(ctx, args):
    data = _call(NoteIn, body=args.get("text", ""))
    _call(worklog_routes.add_note, int(args["task_id"]), data, user=ctx)
    return f"Anotado na tarefa #{args['task_id']}."


def t_add_checklist_item(ctx, args):
    data = _call(ChecklistIn, label=args.get("label", ""))
    row = _call(worklog_routes.add_item, int(args["task_id"]), data, user=ctx)
    return f"Item #{row['id']} adicionado: {row['label']}"


def t_set_checklist_item(ctx, args):
    data = _call(ChecklistUpdate, done=args.get("done", True))
    row = _call(worklog_routes.update_item, int(args["item_id"]), data, user=ctx)
    return f"Item #{row['id']} {'concluído' if row['done'] else 'reaberto'}: {row['label']}"


def t_log_time(ctx, args):
    data = _call(TimeIn, minutes=args.get("minutes"), day=args.get("day"), note=args.get("note"))
    row = _call(worklog_routes.log_time, int(args["task_id"]), data, user=ctx)
    return f"Apontado {_dur(row['minutes'])} em {row['day'].isoformat()} na tarefa #{args['task_id']}."


def t_list_projects(ctx, args):
    rows = project_routes.list_projects(include_archived=False, user=ctx)
    return "\n".join(f"#{p['id']} {p['name']} ({p['open_tasks']} abertas)" for p in rows) or "(nenhum projeto)"


def t_list_recurring(ctx, args):
    day = _call(check_board_day, date.fromisoformat(args["day"])) if args.get("day") else None
    b = services.get_board(ctx["user_id"], day)
    head = f"Rotinas de {b['day'].isoformat()} ({'dia útil' if b['work_day'] else 'dia não útil'}; marcar fora da agenda conta como extra):"
    rows = _recurring_rows(b["recurring"])
    return "\n".join([head, *(rows or ["  (nenhuma)"])])


def _recurring_rows(rows: list) -> list[str]:
    return [f"  [{'x' if r['done_today'] else ' '}] R{r['id']} {r['label']}" + ("" if r["due"] else " (fora da agenda)")
            for r in rows]


def _summary_block(title, x, prev=None, prev_label="mesma parte da semana passada"):
    out = [title]
    rec = f"{x['recurring_done']}/{x['recurring_total']}" if x["recurring_total"] else "nenhuma devida"
    out.append(f"  rotinas {rec}" + (f" (+{x['recurring_extra']} extra)" if x["recurring_extra"] else "")
               + f" · {x['pontual_done']} tarefa(s) concluída(s) · {_dur(x['minutes']) if x['minutes'] else 'nada'} apontado")
    if prev:
        out.append(f"  {prev_label}: {prev['pontual_done']} concluída(s), {_dur(prev['minutes'])} apontado")
    out += [f"  - {d['title']}" + (f" {{{d['project']}}}" if d["project"] else "") for d in x["deliveries"][:15]]
    out += [f"  tempo em {p['name'] or 'sem projeto'}: {_dur(p['minutes'])}" for p in x["projects"] if p["minutes"]]
    if x["missed"]:
        out.append("  rotinas que ficaram para trás: " + ", ".join(x["missed"]))
    return out


def t_get_summary(ctx, args):
    s = services.get_summary(ctx["user_id"])
    last = s["last_day"]
    return "\n".join(_summary_block(f"Desde o último dia útil ({last['start'].isoformat()} a {last['end'].isoformat()}):", last)
                     + [""] + _summary_block(f"Semana até hoje (desde {s['week']['start'].isoformat()}):", s["week"], s["week"]["previous"]))


def t_get_week(ctx, args):
    back = int(args.get("weeks_ago", 1))
    if not 0 <= back <= services.WEEKS_BACK_MAX:
        raise ToolError(f"weeks_ago vai de 0 (esta semana) a {services.WEEKS_BACK_MAX}")
    r = services.get_week_summary(ctx["user_id"], back)
    w = r["week"]
    if back > r["oldest"]:
        return f"Não há registros tão antigos: o primeiro é de {r['oldest']} semana(s) atrás."
    titulo = ("Semana até hoje" if back == 0 else f"Semana de {w['start'].isoformat()} a {w['end'].isoformat()}")
    return "\n".join(_summary_block(titulo + ":", w, w["previous"],
                                     "mesma parte da semana passada" if back == 0 else "semana anterior"))


def t_start_timer(ctx, args):
    res = _call(timer_routes.start, TimerIn(task_id=int(args["task_id"])), user=ctx)
    prev = res["stopped"]
    extra = f" (o anterior parou e apontou {_dur(prev['minutes'])} em #{prev['task_id']})" if prev else ""
    return f"Cronômetro iniciado em #{res['timer']['task_id']} {res['timer']['title']}{extra}."


def t_stop_timer(ctx, args):
    res = _call(timer_routes.stop, user=ctx)
    st = res["stopped"]
    if not st:  # o dia do cronômetro já tinha 24h apontadas: parou, mas nada foi somado
        return "Cronômetro parado. O dia dele já tinha 24h apontadas; nada foi somado."
    return f"Cronômetro parado: {_dur(st['minutes'])} apontados em #{st['task_id']} ({st['day'].isoformat()})."


def t_list_templates(ctx, args):
    rows = template_routes.list_templates(user=ctx)
    return "\n".join(f"M{t['id']} {t['name']}: “{t['title']}”" + (f" · checklist de {len(t['checklist'])} itens" if t["checklist"] else "")
                     for t in rows) or "(nenhum modelo; o usuário cria em Configurações > Modelos)"


def t_create_from_template(ctx, args):
    value = str(args.get("template", "")).strip().lstrip("Mm")
    rows = template_routes.list_templates(user=ctx)
    t = next((r for r in rows if str(r["id"]) == value), None) or next(
        (r for r in rows if r["name"].lower() == str(args.get("template", "")).strip().lower()), None)
    if not t:
        raise ToolError("modelo não encontrado (veja list_templates)")
    res = _call(template_routes.use_template, t["id"], user=ctx)
    return "Criada pelo modelo: " + _task_line(_find_task(ctx["user_id"], res["id"]), services.app_today())


def t_set_recurring(ctx, args):
    extra = {"note": args["note"]} if "note" in args else {}  # sem note: mantém a evidência
    data = _call(ToggleIn, done=args.get("done", True), day=args.get("day"), **extra)
    rid = args.get("recurring_id")
    if rid is None:
        raise ToolError("informe recurring_id (veja list_recurring)")
    res = _call(recurring_routes.toggle, int(rid), data, user=ctx)
    nota = f" Evidência: {res['note']}." if res.get("note") else ""
    return f"Rotina R{rid} {'marcada' if res['done'] else 'desmarcada'} em {res['day'].isoformat()}.{nota}"


# Atribuição (só para quem tem o papel Atribuidor de tarefas).
def _assignable(ctx) -> list:
    return [p for p in _call(assign_routes.list_people, user=ctx) if p["accepts"] and p["id"] != ctx["user_id"]]


def _person(ctx, value) -> dict:
    """Pessoa que aceita tarefas, por U<id>, id, e-mail ou nome (sem diferenciar maiúsculas)."""
    gente = _assignable(ctx)
    v = str(value).strip().lower().removeprefix("u")
    v = v if v.isdigit() else str(value).strip().lower()
    achados = [p for p in gente if str(p["id"]) == v or p["email"].lower() == v or p["name"].lower() == v]
    if len(achados) != 1:
        nomes = ", ".join(f"{p['name']} <{p['email']}>" for p in gente) or "(ninguém aceitou ainda)"
        raise ToolError(f"pessoa “{value}” não encontrada (ou ambígua) entre quem aceita tarefas: {nomes}")
    return achados[0]


def t_list_assignable(ctx, args):
    gente = _assignable(ctx)
    return "\n".join(f"U{p['id']} {p['name']} <{p['email']}>" for p in gente) or "(ninguém aceitou receber tarefas ainda)"


def t_assign_task(ctx, args):
    args = dict(args)
    alvo = _person(ctx, args.pop("to", ""))
    if "priority" in args:
        args["priority"] = _prio(args["priority"])
    data = _call(AssignIn, user_id=alvo["id"], **args)
    res = _call(assign_routes.assign, data, user=ctx)
    aviso = " (e-mail enviado)" if res["emailed"] else ""
    return f"Atribuída a {res['to']}: #{res['id']} {data.title}{aviso}"


def t_list_assigned(ctx, args):
    rows = _call(assign_routes.sent, user=ctx)
    linhas = []
    for r in rows:
        st = STATUS_PT.get(r["status"], r["status"])
        fim = f", concluída em {r['completed_at'].astimezone(services.app_tz()).date().isoformat()}" if r["completed_at"] else ""
        atraso = " (ATRASADA)" if r["late"] else ""
        linhas.append(f"#{r['id']} {r['title']} → {r['to_name']} [{st}]{fim}{atraso}")
    return "\n".join(linhas) or "(você ainda não atribuiu tarefas)"


def t_list_renewals(ctx, args):
    rows = renewal_routes.list_for(ctx["user_id"])
    out = []
    for r in rows:
        quando = "VENCIDO" if r["days_left"] < 0 else ("vence hoje" if r["days_left"] == 0 else f"vence em {r['days_left']} d")
        out.append(f"V{r['id']} {r['label']} — {r['expires_on'].isoformat()} ({quando})" + (" [AVISO]" if r["warning"] else ""))
    return "\n".join(out) or "(nenhum vencimento cadastrado)"


def t_find_similar(ctx, args):
    rows = search_routes.find_similar(ctx["user_id"], str(args.get("title", "")))
    return "\n\n".join(f"#{r['id']} {r['title']}\nComo resolveu: {r['resolution']}" for r in rows) \
        or "(nada parecido resolvido antes)"


def t_get_handoff(ctx, args):
    return summary_routes.handoff_text(ctx["user_id"])


def t_get_history(ctx, args):
    rows = history_routes.list_history(limit=int(args.get("limit", 20)), entity=None, entity_id=None, user=ctx)
    out = []
    for r in rows:
        who = {"web": "app", "api": f"API ({r['token_name']})", "mcp": f"IA ({r['token_name']})",
               "admin": "admin"}.get(r["actor"], r["actor"])
        flags = " [desfeita]" if r["undone"] else (" [pode desfazer]" if r["can_undo"] else "")
        out.append(f"#{r['id']} {r['created_at'].astimezone(services.app_tz()):%d/%m %H:%M} {who}: {r['summary']}{flags}")
    return "\n".join(out) or "(sem histórico)"


def t_undo(ctx, args):
    # A IA só desfaz o que ela mesma (esta chave) fez — nunca o trabalho do usuário.
    hid = int(args["history_id"])
    row = db.query_one("SELECT token_id FROM audit_log WHERE id = %s AND user_id = %s", (hid, ctx["user_id"]))
    if not row or row["token_id"] != ctx.get("token_id"):
        raise ToolError("só dá para desfazer ações feitas por esta chave")
    res = _call(history_routes.undo, hid, user=ctx)
    return f"Desfeito: ação #{res['undid']} ({res['action']})."


# nome -> (função, escreve?, descrição, inputSchema)
TOOLS = {
    "get_today": (t_get_today, False,
                  "Resumo de hoje: rotinas (feitas ou não), tarefas abertas com prazos/atrasos e o que foi concluído hoje.",
                  {"type": "object", "properties": {}}),
    "list_tasks": (t_list_tasks, False,
                   "Lista tarefas pontuais do usuário. Com from/to (e by), filtra por período de criação ou de "
                   "conclusão e mostra a data de criação e o external_ref: use para conferir duplicidade.",
                   {"type": "object", "properties": {
                       "status": {"type": "string", "enum": ["open", "done", "all"], "default": "open",
                                  "description": "Padrão open; com período, padrão all"},
                       "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
                       "from": {**DATE, "description": "Primeiro dia do período (inclusive)"},
                       "to": {**DATE, "description": "Último dia do período (inclusive)"},
                       "by": {"type": "string", "enum": ["created", "completed"], "default": "created",
                              "description": "O período vale para a criação ou para a conclusão"}}}),
    "create_task": (t_create_task, True, "Cria uma tarefa (também retroativa, com created_at/completed_at).",
                    {"type": "object", "required": ["title"], "properties": {
                        "title": {"type": "string", "maxLength": 200},
                        "description": {"type": ["string", "null"], "maxLength": 300},
                        "status": {"type": "string", "enum": STATUS, "default": "todo"},
                        "due_date": {**DATE, "type": ["string", "null"], "description": "Previsão de conclusão (AAAA-MM-DD)"},
                        "project": {"type": ["string", "null"],
                                    "description": "Nome do projeto/cliente (veja list_projects). Omitido: o projeto padrão da pessoa, se houver"},
                        "extra_projects": EXTRA_PROJECTS,
                        "priority": {"type": "string", "enum": ["alta", "normal", "baixa"], "default": "normal"},
                        "ticket": {"type": ["string", "null"], "maxLength": 40, "description": "Número do chamado (GLPI, TomTicket...)"},
                        "after_hours": {"type": "boolean", "default": False, "description": "Plantão / fora do horário"},
                        "created_at": {**WHEN, "description": "Quando a tarefa começou (retroativo; padrão: agora). " + WHEN["description"]},
                        "completed_at": {**WHEN, "description": "Quando foi concluída (implica status done; padrão: agora). " + WHEN["description"]},
                        "blocked_reason": {"type": ["string", "null"], "maxLength": 120,
                                           "description": "Com status blocked: o que se está aguardando"},
                        "follow_up_on": {**DATE, "type": ["string", "null"], "description": "Com status blocked: dia combinado para cobrar"},
                        "resolution": {"type": "string", "maxLength": 1000, "description": "Com status done: como foi resolvido (entra na busca)"},
                        "external_ref": {"type": "string", "maxLength": 120,
                                         "description": "Chave sua para não duplicar: repetida, devolve a tarefa que já existe"}}}),
    "update_task": (t_update_task, True,
                    "Edita uma tarefa. Envie só os campos a mudar; description, due_date ou project = null apagam o campo.",
                    {"type": "object", "required": ["task_id"], "properties": {
                        "task_id": {"type": "integer"},
                        "title": {"type": "string", "maxLength": 200},
                        "description": {"type": ["string", "null"], "maxLength": 300},
                        "status": {"type": "string", "enum": STATUS},
                        "due_date": {**DATE, "type": ["string", "null"]},
                        "project": {"type": ["string", "null"]},
                        "extra_projects": EXTRA_PROJECTS,
                        "priority": {"type": "string", "enum": ["alta", "normal", "baixa"]},
                        "ticket": {"type": ["string", "null"], "maxLength": 40},
                        "after_hours": {"type": "boolean"},
                        "completed_at": {**WHEN, "description": "Corrige a data de conclusão (tarefa concluída). " + WHEN["description"]},
                        "blocked_reason": {"type": ["string", "null"], "maxLength": 120,
                                           "description": "Com status blocked: o que se está aguardando (fornecedor, cliente, aprovação...)"},
                        "follow_up_on": {**DATE, "type": ["string", "null"], "description": "Com status blocked: dia combinado para cobrar (AAAA-MM-DD)"},
                        "resolution": {"type": ["string", "null"], "maxLength": 1000,
                                       "description": "Como foi resolvido (tarefa concluída; null apaga)"}}}),
    "get_summary": (t_get_summary, False, "Resumo para a daily/retro: o último dia útil e a semana até hoje (rotinas, tarefas concluídas, tempo por projeto, o que ficou para trás).",
                    {"type": "object", "properties": {}}),
    "get_week": (t_get_week, False, "Resumo de uma semana passada (domingo a sábado), comparada com a anterior: "
                 "rotinas, tarefas concluídas, tempo por projeto. weeks_ago=1 é a semana passada.",
                 {"type": "object", "properties": {"weeks_ago": {"type": "integer", "minimum": 0, "default": 1,
                                                                 "description": "Quantas semanas atrás (0 = esta)"}}}),
    "get_task": (t_get_task, False, "Tarefa completa: checklist, anotações e tempo apontado.",
                 {"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "integer"}}}),
    "search": (t_search, False, "Busca em tarefas (título, descrição, anotações, checklist, apontamentos), rotinas e projetos. Ignora acentos.",
               {"type": "object", "required": ["query"], "properties": {"query": {"type": "string", "minLength": 2, "maxLength": 100}}}),
    "add_note": (t_add_note, True, "Anota um progresso na tarefa (o que foi feito, decisão, pendência).",
                 {"type": "object", "required": ["task_id", "text"], "properties": {
                     "task_id": {"type": "integer"}, "text": {"type": "string", "maxLength": 2000}}}),
    "add_checklist_item": (t_add_checklist_item, True, "Adiciona um item (subtarefa) ao checklist da tarefa.",
                           {"type": "object", "required": ["task_id", "label"], "properties": {
                               "task_id": {"type": "integer"}, "label": {"type": "string", "maxLength": 200}}}),
    "set_checklist_item": (t_set_checklist_item, True, "Marca (done=true) ou reabre um item do checklist (ids em get_task).",
                           {"type": "object", "required": ["item_id"], "properties": {
                               "item_id": {"type": "integer"}, "done": {"type": "boolean", "default": True}}}),
    "log_time": (t_log_time, True, "Aponta tempo gasto numa tarefa (minutos; dia padrão hoje, nunca no futuro).",
                 {"type": "object", "required": ["task_id", "minutes"], "properties": {
                     "task_id": {"type": "integer"},
                     "minutes": {"type": "integer", "minimum": 1, "maximum": 1440},
                     "day": DATE, "note": {"type": "string", "maxLength": 200}}}),
    "list_projects": (t_list_projects, False, "Lista os projetos/clientes do usuário.",
                      {"type": "object", "properties": {}}),
    "complete_task": (t_complete_task, True, "Marca uma tarefa como concluída (agora, ou na data informada).",
                      {"type": "object", "required": ["task_id"], "properties": {
                          "task_id": {"type": "integer"},
                          "completed_at": {**WHEN, "description": "Quando foi concluída (padrão: agora). " + WHEN["description"]},
                          "resolution": {"type": "string", "maxLength": 1000,
                                         "description": "Como foi resolvido (vira base de conhecimento: entra na busca)"}}}),
    "list_recurring": (t_list_recurring, False, "Rotinas de um dia (padrão: hoje; até 7 dias atrás) e se foram feitas.",
                       {"type": "object", "properties": {"day": DATE}}),
    "set_recurring": (t_set_recurring, True, "Marca (done=true) ou desmarca uma rotina num dia (padrão hoje; até 7 dias atrás).",
                      {"type": "object", "required": ["recurring_id"], "properties": {
                          "recurring_id": {"type": "integer", "description": "id da rotina (R<n> em get_today/list_recurring), não de tarefa"},
                          "done": {"type": "boolean", "default": True},
                          "day": DATE,
                          "note": {"type": "string", "maxLength": 200, "description": "Evidência curta da verificação (ex.: backup OK, 2,1 TB)"}}}),
    "start_timer": (t_start_timer, True, "Inicia o cronômetro numa tarefa aberta (se outro estiver rodando, ele para e aponta o tempo).",
                    {"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "integer"}}}),
    "stop_timer": (t_stop_timer, True, "Para o cronômetro e aponta o tempo na tarefa.",
                   {"type": "object", "properties": {}}),
    "list_templates": (t_list_templates, False, "Lista os modelos de tarefa do usuário (procedimentos com checklist pronto).",
                       {"type": "object", "properties": {}}),
    "create_from_template": (t_create_from_template, True, "Cria uma tarefa a partir de um modelo (com o checklist dele).",
                             {"type": "object", "required": ["template"], "properties": {
                                 "template": {"type": "string", "description": "Nome do modelo ou M<id> (veja list_templates)"}}}),
    "list_renewals": (t_list_renewals, False,
                      "Vencimentos cadastrados (certificados, licenças, domínios, garantias), do mais próximo ao mais longe; [AVISO] = dentro da antecedência.",
                      {"type": "object", "properties": {}}),
    "find_similar": (t_find_similar, False,
                     "Já resolvi isso antes? Tarefas concluídas com título parecido e como foram resolvidas. "
                     "Use antes de abrir uma tarefa de problema repetido (impressora, VPN, AD...).",
                     {"type": "object", "required": ["title"], "properties": {"title": {"type": "string", "minLength": 3, "maxLength": 200}}}),
    "get_handoff": (t_get_handoff, False,
                    "Passagem de turno/plantão: em aberto, bloqueadas com o motivo e há quantos dias, concluídas nas "
                    "últimas 12 h, rotinas pendentes e vencimentos no aviso, em texto pronto pra colar no chat da equipe.",
                    {"type": "object", "properties": {}}),
    "list_assignable": (t_list_assignable, False, "Atribuidor: pessoas que aceitam receber tarefas atribuídas.",
                        {"type": "object", "properties": {}}),
    "assign_task": (t_assign_task, True,
                    "Atribuidor: manda uma tarefa para outra pessoa (que aceitou receber). Ela vira dona da "
                    "tarefa e recebe um e-mail.",
                    {"type": "object", "required": ["to", "title"], "properties": {
                        "to": {"type": "string", "description": "Pessoa: U<id>, e-mail ou nome (veja list_assignable)"},
                        "title": {"type": "string", "maxLength": 200},
                        "description": {"type": ["string", "null"], "maxLength": 300},
                        "due_date": {**DATE, "type": ["string", "null"], "description": "Prazo (AAAA-MM-DD)"},
                        "priority": {"type": "string", "enum": ["alta", "normal", "baixa"], "default": "normal"},
                        "ticket": {"type": ["string", "null"], "maxLength": 40},
                        "after_hours": {"type": "boolean", "default": False}}}),
    "list_assigned": (t_list_assigned, False, "Atribuidor: tarefas que você atribuiu, com o status atual.",
                      {"type": "object", "properties": {}}),
    "get_history": (t_get_history, False, "Últimas ações na conta (app, API ou IA), com o que pode ser desfeito.",
                    {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20}}}),
    "undo": (t_undo, True, "Desfaz uma ação do histórico (só a mais recente de cada item).",
             {"type": "object", "required": ["history_id"], "properties": {"history_id": {"type": "integer"}}}),
}

PROMPTS = {
    "resumo_semanal": {
        "title": "Resumo da semana",
        "description": "Resumo da semana de trabalho para mandar a alguém (gestor, time, cliente).",
        "arguments": [{"name": "para", "description": "Para quem é o resumo (padrão: gestor)", "required": False}],
        "text": ("Use a ferramenta get_summary do Nexus e escreva um resumo da minha semana para {para}, em português, "
                 "curto e objetivo: o que foi entregue (agrupe por projeto/cliente), o tempo por projeto, o que ficou "
                 "em andamento e qualquer impedimento (tarefas bloqueadas, via get_today). Não invente nada que não "
                 "esteja nos dados; se algo estiver vazio, diga que não houve registro."),
    },
    "daily": {
        "title": "Daily",
        "description": "Texto da daily: ontem, hoje e impedimentos.",
        "arguments": [],
        "text": ("Use get_summary e get_today do Nexus e monte minha daily em três tópicos curtos: Ontem (o que concluí "
                 "desde o último dia útil), Hoje (o que está em andamento, atrasado ou vence hoje) e Impedimentos "
                 "(tarefas bloqueadas; se não houver, \"nenhum\"). Só com o que está registrado."),
    },
}


def _prompt_list() -> list:
    return [{"name": n, "title": p["title"], "description": p["description"], "arguments": p["arguments"]}
            for n, p in PROMPTS.items()]


def _prompt_get(name: str, args: dict) -> dict:
    p = PROMPTS[name]
    text = p["text"].format(para=(args.get("para") or "o meu gestor").strip()[:80])
    return {"description": p["description"], "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}


ASSIGNER_TOOLS = {"list_assignable", "assign_task", "list_assigned"}


def _allowed(ctx, name: str) -> bool:
    return name not in ASSIGNER_TOOLS or "assigner" in (ctx.get("roles") or [])


def _tool_list(ctx) -> list:
    out = []
    for name, (_, writes, desc, schema) in TOOLS.items():
        if (writes and ctx.get("scope") != "write") or not _allowed(ctx, name):
            continue
        out.append({
            "name": name,
            "description": desc,
            "inputSchema": schema,
            "annotations": {"readOnlyHint": not writes, "destructiveHint": False},
        })
    return out


# --------------------------------------------------------------- JSON-RPC --

def _rpc_error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _handle(ctx, msg):
    """Processa uma mensagem JSON-RPC; devolve a resposta ou None (notificação)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _rpc_error(msg.get("id") if isinstance(msg, dict) else None, -32600, "requisição inválida")
    rid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
    if rid is None:  # notificação (ex.: notifications/initialized): sem resposta
        return None

    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        result = {"protocolVersion": version,
                  "capabilities": {"tools": {"listChanged": False}, "prompts": {"listChanged": False}},
                  "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": _tool_list(ctx)}
    elif method == "prompts/list":
        result = {"prompts": _prompt_list()}
    elif method == "prompts/get":
        if params.get("name") not in PROMPTS:
            return _rpc_error(rid, -32602, f"prompt desconhecido: {params.get('name')}")
        result = _prompt_get(params["name"], params.get("arguments") or {})
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        spec = TOOLS.get(name) if _allowed(ctx, name) else None
        if not spec:
            return _rpc_error(rid, -32602, f"ferramenta desconhecida: {name}")
        fn, writes = spec[0], spec[1]
        try:
            if writes and ctx.get("scope") != "write":
                raise ToolError("esta chave de API é só de leitura")
            text, is_error = fn(ctx, args), False
        except ToolError as e:
            text, is_error = str(e), True
        except (KeyError, ValueError, TypeError) as e:
            text, is_error = f"parâmetros inválidos: {e}", True
        result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    else:
        return _rpc_error(rid, -32601, f"método não suportado: {method}")
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _origin_ok(request: Request) -> bool:
    """Proteção contra DNS rebinding (exigida pela especificação): se o
    navegador mandou Origin, ele precisa ser o próprio host."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    return urlsplit(origin).netloc == request.headers.get("host")


@router.post("/mcp")
async def mcp_post(request: Request):
    if not _origin_ok(request):
        return JSONResponse(_rpc_error(None, -32600, "origem não permitida"), status_code=403)
    try:
        ctx = await run_in_threadpool(deps.active_user, request)
    except HTTPException as e:
        return JSONResponse(_rpc_error(None, -32001, str(e.detail)), status_code=e.status_code,
                            headers=e.headers or {"WWW-Authenticate": "Bearer"})
    if ctx.get("actor") != "api":
        return JSONResponse(_rpc_error(None, -32001, "use uma chave de API (Authorization: Bearer nxs_...)"),
                            status_code=401, headers={"WWW-Authenticate": "Bearer"})
    ctx = {**ctx, "actor": "mcp"}

    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(_rpc_error(None, -32700, "JSON inválido"), status_code=400)

    if not isinstance(body, dict):  # lote saiu do protocolo em 2025-06-18 (e burlaria o limite)
        return JSONResponse(_rpc_error(None, -32600, "envie uma mensagem JSON-RPC por requisição"), status_code=400)
    reply = await run_in_threadpool(_handle, ctx, body)
    if reply is None:
        return Response(status_code=202)
    return JSONResponse(reply)


@router.get("/mcp")
@router.delete("/mcp")
def mcp_other():
    # Sem stream SSE nem sessão: só POST.
    return Response(status_code=405, headers={"Allow": "POST"})
