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
from datetime import date
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from .. import db, deps, services
from ..config import config
from ..labels import PRIO_PT, STATUS_PT
from ..labels import dur as _dur
from ..schemas import ChecklistIn, ChecklistUpdate, NoteIn, TimeIn, ToggleIn, WorklogIn, WorklogUpdate
from . import history as history_routes
from . import projects as project_routes
from . import search as search_routes
from . import recurring as recurring_routes
from . import worklog as worklog_routes
from .board import check_board_day

router = APIRouter(tags=["mcp"])

SUPPORTED_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26"]
SERVER_INFO = {"name": "nexus-worklog", "title": "Nexus Worklog", "version": "2.0.0"}
INSTRUCTIONS = (
    "Nexus Worklog: o registro do dia de trabalho do usuário. Use get_today para "
    "ver o dia (rotinas e tarefas abertas) e get_summary para a daily/retro (ontem e a "
    "semana, com tempo por projeto). Registre o que o usuário contar com "
    "create_task/update_task/complete_task, log_time e add_note; marque rotinas com "
    "set_recurring. Datas no formato AAAA-MM-DD, no fuso " + config.APP_TZ + ". Rotinas "
    "aceitam até 7 dias para trás; marcar uma rotina fora da agenda dela conta como extra. "
    "Tudo fica no histórico do usuário; use undo para corrigir um engano seu."
)

STATUS = ["todo", "in_progress", "blocked", "done"]
PRIO = {"alta": 1, "normal": 2, "baixa": 3}
DATE = {"type": "string", "format": "date", "description": "Data AAAA-MM-DD"}


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
    if t.get("priority") == 1:
        parts.append("(prioridade alta)")
    if t.get("project_name"):
        parts.append(f"{{{t['project_name']}}}")
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
    if "priority" in args:
        args["priority"] = _prio(args["priority"])
    return args


def _find_task(uid: int, task_id: int) -> dict:
    b = services.get_board(uid)
    for t in b["in_progress"] + b["done"]:
        if t["id"] == task_id:
            return t
    raise ToolError(f"tarefa #{task_id} não encontrada")


# ------------------------------------------------------------------- tools --

def t_get_today(ctx, args):
    uid = ctx["user_id"]
    b = services.get_board(uid)
    today = b["today"]
    lines = [f"Hoje: {today.isoformat()} ({'dia útil' if b['work_day'] else 'dia NÃO útil'})", ""]
    rec = [r for r in b["recurring"] if r["due"]]
    lines.append(f"Rotinas de hoje ({sum(r['done_today'] for r in rec)}/{len(rec)} feitas):")
    lines += _recurring_rows(rec) or ["  (nenhuma)"]
    extra = [r for r in b["recurring"] if not r["due"] and r["done_today"]]
    if extra:
        lines += [f"  [x] #{r['id']} {r['label']} (extra: fora da agenda)" for r in extra]
    lines.append("")
    open_ = b["in_progress"]
    lines.append(f"Tarefas abertas ({len(open_)}):")
    lines += [f"  {_task_line(t, today)}" for t in open_] or ["  (nenhuma)"]
    done_today = [t for t in b["done"] if t["completed_at"] and t["completed_at"].astimezone(services.app_tz()).date() == today]
    lines.append("")
    lines.append(f"Concluídas hoje ({len(done_today)}):")
    lines += [f"  #{t['id']} {t['title']}" for t in done_today] or ["  (nenhuma)"]
    return "\n".join(lines)


def t_list_tasks(ctx, args):
    status = args.get("status", "open")
    limit = int(args.get("limit", 50))
    b = services.get_board(ctx["user_id"])
    items = {"open": b["in_progress"], "done": b["done"], "all": b["in_progress"] + b["done"]}.get(status)
    if items is None:
        raise ToolError("status deve ser open, done ou all")
    items = items[: max(1, min(limit, 200))]
    return "\n".join(_task_line(t, b["today"]) for t in items) or "(nenhuma tarefa)"


def t_create_task(ctx, args):
    data = _call(WorklogIn, **_task_args(ctx["user_id"], args))
    res = _call(worklog_routes.create, data, user=ctx)
    return "Criada: " + _task_line(_find_task(ctx["user_id"], res["id"]), services.app_today())


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
    _call(worklog_routes.finish, task_id, user=ctx)
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
        lines += ["", "Rotinas:"] + [f"  #{x['id']} {x['label']}" + ("" if x["active"] else " (removida)") for x in r["recurring"]]
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
    return [f"  [{'x' if r['done_today'] else ' '}] #{r['id']} {r['label']}" + ("" if r["due"] else " (fora da agenda)")
            for r in rows]


def t_get_summary(ctx, args):
    s = services.get_summary(ctx["user_id"])

    def block(title, x, prev=None):
        out = [title]
        rec = f"{x['recurring_done']}/{x['recurring_total']}" if x["recurring_total"] else "nenhuma devida"
        out.append(f"  rotinas {rec}" + (f" (+{x['recurring_extra']} extra)" if x["recurring_extra"] else "")
                   + f" · {x['pontual_done']} tarefa(s) concluída(s) · {_dur(x['minutes']) if x['minutes'] else 'nada'} apontado")
        if prev:
            out.append(f"  mesma parte da semana passada: {prev['pontual_done']} concluída(s), {_dur(prev['minutes'])} apontado")
        out += [f"  - {d['title']}" + (f" {{{d['project']}}}" if d["project"] else "") for d in x["deliveries"][:15]]
        out += [f"  tempo em {p['name'] or 'sem projeto'}: {_dur(p['minutes'])}" for p in x["projects"] if p["minutes"]]
        if x["missed"]:
            out.append("  rotinas que ficaram para trás: " + ", ".join(x["missed"]))
        return out

    last = s["last_day"]
    return "\n".join(block(f"Último dia útil ({last['start'].isoformat()}):", last)
                     + [""] + block(f"Semana até hoje (desde {s['week']['start'].isoformat()}):", s["week"], s["week"]["previous"]))


def t_set_recurring(ctx, args):
    data = _call(ToggleIn, done=args.get("done", True), day=args.get("day"))
    res = _call(recurring_routes.toggle, int(args["task_id"]), data, user=ctx)
    return f"Rotina #{args['task_id']} {'marcada' if res['done'] else 'desmarcada'} em {res['day'].isoformat()}."


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
    res = _call(history_routes.undo, int(args["history_id"]), user=ctx)
    return f"Desfeito: ação #{res['undid']} ({res['action']})."


# nome -> (função, escreve?, descrição, inputSchema)
TOOLS = {
    "get_today": (t_get_today, False,
                  "Resumo de hoje: rotinas (feitas ou não), tarefas abertas com prazos/atrasos e o que foi concluído hoje.",
                  {"type": "object", "properties": {}}),
    "list_tasks": (t_list_tasks, False, "Lista tarefas pontuais do usuário.",
                   {"type": "object", "properties": {
                       "status": {"type": "string", "enum": ["open", "done", "all"], "default": "open"},
                       "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}}}),
    "create_task": (t_create_task, True, "Cria uma tarefa.",
                    {"type": "object", "required": ["title"], "properties": {
                        "title": {"type": "string", "maxLength": 200},
                        "description": {"type": ["string", "null"], "maxLength": 300},
                        "status": {"type": "string", "enum": STATUS, "default": "todo"},
                        "due_date": {**DATE, "type": ["string", "null"], "description": "Previsão de conclusão (AAAA-MM-DD)"},
                        "project": {"type": ["string", "null"], "description": "Nome do projeto/cliente (veja list_projects)"},
                        "priority": {"type": "string", "enum": ["alta", "normal", "baixa"], "default": "normal"}}}),
    "update_task": (t_update_task, True,
                    "Edita uma tarefa. Envie só os campos a mudar; description, due_date ou project = null apagam o campo.",
                    {"type": "object", "required": ["task_id"], "properties": {
                        "task_id": {"type": "integer"},
                        "title": {"type": "string", "maxLength": 200},
                        "description": {"type": ["string", "null"], "maxLength": 300},
                        "status": {"type": "string", "enum": STATUS},
                        "due_date": {**DATE, "type": ["string", "null"]},
                        "project": {"type": ["string", "null"]},
                        "priority": {"type": "string", "enum": ["alta", "normal", "baixa"]}}}),
    "get_summary": (t_get_summary, False, "Resumo para a daily/retro: o último dia útil e a semana até hoje (rotinas, tarefas concluídas, tempo por projeto, o que ficou para trás).",
                    {"type": "object", "properties": {}}),
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
    "complete_task": (t_complete_task, True, "Marca uma tarefa como concluída agora.",
                      {"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "integer"}}}),
    "list_recurring": (t_list_recurring, False, "Rotinas de um dia (padrão: hoje; até 7 dias atrás) e se foram feitas.",
                       {"type": "object", "properties": {"day": DATE}}),
    "set_recurring": (t_set_recurring, True, "Marca (done=true) ou desmarca uma rotina num dia (padrão hoje; até 7 dias atrás).",
                      {"type": "object", "required": ["task_id"], "properties": {
                          "task_id": {"type": "integer"},
                          "done": {"type": "boolean", "default": True},
                          "day": DATE}}),
    "get_history": (t_get_history, False, "Últimas ações na conta (app, API ou IA), com o que pode ser desfeito.",
                    {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}}}),
    "undo": (t_undo, True, "Desfaz uma ação do histórico (só a mais recente de cada item).",
             {"type": "object", "required": ["history_id"], "properties": {"history_id": {"type": "integer"}}}),
}

def _tool_list(ctx) -> list:
    out = []
    for name, (_, writes, desc, schema) in TOOLS.items():
        if writes and ctx.get("scope") != "write":
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
        result = {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": _tool_list(ctx)}
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        spec = TOOLS.get(name)
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
