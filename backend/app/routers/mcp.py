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

from .. import deps, services
from ..schemas import ToggleIn, WorklogIn, WorklogUpdate
from . import history as history_routes
from . import recurring as recurring_routes
from . import worklog as worklog_routes
from .board import check_board_day

router = APIRouter(tags=["mcp"])

SUPPORTED_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26"]
SERVER_INFO = {"name": "nexus-worklog", "title": "Nexus Worklog", "version": "2.0.0"}
INSTRUCTIONS = (
    "Nexus Worklog: o registro do dia de trabalho do usuário. Use get_today para "
    "ver o dia (recorrentes e tarefas abertas). Registre o que o usuário contar com "
    "create_task/update_task/complete_task e marque rotinas com set_recurring. "
    "Datas no formato AAAA-MM-DD, no fuso de Brasília. Recorrentes aceitam até 7 dias "
    "para trás. Tudo fica no histórico do usuário; use undo para corrigir um engano seu."
)

STATUS = ["todo", "in_progress", "blocked", "done"]
STATUS_PT = {"todo": "a fazer", "in_progress": "em andamento", "blocked": "bloqueada", "done": "concluída"}
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
    if t.get("due_date") and t["status"] != "done":
        due = t["due_date"]
        parts.append(f"prazo {due.isoformat()}" + (" (ATRASADA)" if due < today else ""))
    if t.get("completed_at"):
        parts.append(f"concluída em {t['completed_at'].date().isoformat()}")
    if t.get("description"):
        parts.append(f"— {t['description']}")
    return " ".join(parts)


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
    rec = b["recurring"]
    lines.append(f"Recorrentes ({sum(r['done_today'] for r in rec)}/{len(rec)} feitas):")
    lines += [f"  [{'x' if r['done_today'] else ' '}] #{r['id']} {r['label']}" for r in rec] or ["  (nenhuma)"]
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
    data = _call(WorklogIn, **args)
    res = _call(worklog_routes.create, data, user=ctx)
    return "Criada: " + _task_line(_find_task(ctx["user_id"], res["id"]), services.app_today())


def t_update_task(ctx, args):
    args = dict(args)
    task_id = args.pop("task_id", None)
    if task_id is None:
        raise ToolError("informe task_id")
    data = _call(WorklogUpdate, **args)
    _call(worklog_routes.update, int(task_id), data, user=ctx)
    return "Atualizada: " + _task_line(_find_task(ctx["user_id"], int(task_id)), services.app_today())


def t_complete_task(ctx, args):
    task_id = int(args["task_id"])
    _call(worklog_routes.finish, task_id, user=ctx)
    return "Concluída: " + _task_line(_find_task(ctx["user_id"], task_id), services.app_today())


def t_list_recurring(ctx, args):
    day = _call(check_board_day, date.fromisoformat(args["day"])) if args.get("day") else None
    b = services.get_board(ctx["user_id"], day)
    head = f"Recorrentes de {b['day'].isoformat()} ({'dia útil' if b['work_day'] else 'dia não útil: marcações contam como extra'}):"
    rows = [f"  [{'x' if r['done_today'] else ' '}] #{r['id']} {r['label']}" for r in b["recurring"]]
    return "\n".join([head, *(rows or ["  (nenhuma)"])])


def t_set_recurring(ctx, args):
    data = _call(ToggleIn, done=args.get("done", True), day=args.get("day"))
    res = _call(recurring_routes.toggle, int(args["task_id"]), data, user=ctx)
    return f"Recorrente #{args['task_id']} {'marcada' if res['done'] else 'desmarcada'} em {res['day'].isoformat()}."


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
                  "Resumo de hoje: recorrentes (feitas ou não), tarefas abertas com prazos/atrasos e o que foi concluído hoje.",
                  {"type": "object", "properties": {}}),
    "list_tasks": (t_list_tasks, False, "Lista tarefas pontuais do usuário.",
                   {"type": "object", "properties": {
                       "status": {"type": "string", "enum": ["open", "done", "all"], "default": "open"},
                       "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}}}),
    "create_task": (t_create_task, True, "Cria uma tarefa pontual.",
                    {"type": "object", "required": ["title"], "properties": {
                        "title": {"type": "string", "maxLength": 200},
                        "description": {"type": ["string", "null"], "maxLength": 300},
                        "status": {"type": "string", "enum": STATUS, "default": "todo"},
                        "due_date": {**DATE, "type": ["string", "null"], "description": "Previsão de conclusão (AAAA-MM-DD)"}}}),
    "update_task": (t_update_task, True,
                    "Edita uma tarefa. Envie só os campos a mudar; description ou due_date = null apagam o campo.",
                    {"type": "object", "required": ["task_id"], "properties": {
                        "task_id": {"type": "integer"},
                        "title": {"type": "string", "maxLength": 200},
                        "description": {"type": ["string", "null"], "maxLength": 300},
                        "status": {"type": "string", "enum": STATUS},
                        "due_date": {**DATE, "type": ["string", "null"]}}}),
    "complete_task": (t_complete_task, True, "Marca uma tarefa como concluída agora.",
                      {"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "integer"}}}),
    "list_recurring": (t_list_recurring, False, "Recorrentes de um dia (padrão: hoje; até 7 dias atrás) e se foram feitas.",
                       {"type": "object", "properties": {"day": DATE}}),
    "set_recurring": (t_set_recurring, True, "Marca (done=true) ou desmarca uma recorrente num dia (padrão hoje; até 7 dias atrás).",
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

    if isinstance(body, list):  # lote (versões antigas do protocolo)
        replies = [r for r in [await run_in_threadpool(_handle, ctx, m) for m in body] if r is not None]
        return JSONResponse(replies) if replies else Response(status_code=202)
    reply = await run_in_threadpool(_handle, ctx, body)
    if reply is None:
        return Response(status_code=202)
    return JSONResponse(reply)


@router.get("/mcp")
@router.delete("/mcp")
def mcp_other():
    # Sem stream SSE nem sessão: só POST.
    return Response(status_code=405, headers={"Allow": "POST"})
