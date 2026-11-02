"""O docs/openapi.json que vai para conectores (Power Automate, n8n, Make) e
geradores de cliente: o esquema do FastAPI com o que ele não sabe sozinho.

- `components.securitySchemes.bearer` + `security` global: a chave de API vai
  em `Authorization: Bearer nxs_...`.
- Rotas públicas (login, opções, pedido de convite, link do calendário):
  `security: []`.
- Rotas só do app (sessão do navegador: Admin, chaves, webhooks, Equipe,
  conta): `x-session-only: true`, `security: []` e a frase na descrição; por
  chave de API respondem 403.
- `X-Total-Count` declarado nas listas paginadas; `Retry-After` nas respostas
  429 e 503 (todas as rotas podem dar 503 com o banco ocupado).

O Swagger continua desligado em produção (main.py: openapi_url=None);
tools/openapi.py grava o arquivo e test_openapi_em_dia confere.
"""
import inspect

from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from . import deps

# Dependências que exigem a sessão do app (a chave de API recebe 403).
SESSION_DEPS = {deps.web_user_csrf, deps.web_active, deps.web_active_csrf, deps.require_admin,
                deps.require_admin_csrf, deps.require_viewer}
# Dependências que autenticam (sessão ou chave).
AUTH_DEPS = SESSION_DEPS | {deps.current_user, deps.active_user, deps.active_user_csrf, deps.require_assigner,
                            deps.require_assigner_csrf, deps.require_people_list}
SESSION_NOTE = "Só pelo app (sessão do navegador): por chave de API responde 403."


def _calls(dependant) -> set:
    out = set()
    for d in dependant.dependencies:
        out.add(d.call)
        out |= _calls(d)
    return out


def _flat(routes):
    """As rotas de verdade: o FastAPI novo guarda cada include_router como um nó
    (`original_router`); os routers daqui já levam o prefixo no caminho."""
    for r in routes:
        if isinstance(r, APIRoute):
            yield r
        elif getattr(r, "original_router", None) is not None:
            yield from _flat(r.original_router.routes)
        elif getattr(r, "routes", None):
            yield from _flat(r.routes)


def _paginated(route: APIRoute) -> bool:
    try:
        return "put_total(" in inspect.getsource(route.endpoint)
    except (OSError, TypeError):
        return False


def build(app) -> dict:
    spec = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
    comp = spec.setdefault("components", {})
    comp["securitySchemes"] = {"bearer": {
        "type": "http", "scheme": "bearer",
        "description": "Chave de API (Configurações > Chaves de API): Authorization: Bearer nxs_..."}}
    comp["headers"] = {
        "X-Total-Count": {"description": "Total de itens da lista, sem o limit/offset (páginas).",
                          "schema": {"type": "integer"}},
        "Retry-After": {"description": "Segundos para esperar antes de tentar de novo.", "schema": {"type": "integer"}},
    }
    comp["responses"] = {
        "TooManyRequests": {"description": "Limite de tentativas: espere o Retry-After.",
                            "headers": {"Retry-After": {"$ref": "#/components/headers/Retry-After"}}},
        "Busy": {"description": "Servidor ocupado: tente de novo depois do Retry-After.",
                 "headers": {"Retry-After": {"$ref": "#/components/headers/Retry-After"}}},
    }
    spec["security"] = [{"bearer": []}]
    for route in _flat(app.routes):
        if not route.include_in_schema:
            continue
        calls = _calls(route.dependant)
        for method in route.methods:
            op = spec["paths"].get(route.path_format, {}).get(method.lower())
            if op is None:
                continue
            if calls & SESSION_DEPS:
                op["x-session-only"] = True
                op["security"] = []
                op["description"] = (op.get("description", "") + "\n\n" + SESSION_NOTE).strip()
            elif not calls & AUTH_DEPS and route.path_format != "/mcp":  # /mcp confere a chave por dentro
                op["security"] = []  # pública
            resp = op.setdefault("responses", {})
            if _paginated(route):
                ok = next((c for c in ("200", "201") if c in resp), None)
                if ok:
                    resp[ok].setdefault("headers", {})["X-Total-Count"] = {"$ref": "#/components/headers/X-Total-Count"}
            resp.setdefault("429", {"$ref": "#/components/responses/TooManyRequests"})
            resp.setdefault("503", {"$ref": "#/components/responses/Busy"})
    return spec


def install(app) -> None:
    def openapi():
        if not app.openapi_schema:
            app.openapi_schema = build(app)
        return app.openapi_schema
    app.openapi = openapi
