"""Rodada 2, pacote 09 (documentação): toda rota aberta à chave de API ou pública
está citada em docs/API.md.

Vale para as rotas do app.openapi() que não são "só do app" (`x-session-only`):
são as que quem integra precisa achar na referência. A rota conta como citada
quando o API.md traz, entre crases, o método e o caminho: inteiro
(`GET /api/board`) ou sem o prefixo da seção (`POST /{id}/finish` debaixo de
"## Tarefas — `/api/worklog`"). O nome do parâmetro não importa ({id} = {task_id}).
"""
import os
import pathlib
import re

DOCS = pathlib.Path(os.environ.get("OPENAPI_FILE") or pathlib.Path(__file__).parents[2] / "docs" / "openapi.json").parent


def _sem_nome(texto: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", texto)


def rotas_sem_citacao(spec: dict, doc: str) -> list[str]:
    doc = _sem_nome(doc)
    # Prefixos das seções: "## Tarefas — `/api/worklog`".
    titulos = "\n".join(linha for linha in doc.splitlines() if linha.startswith("#"))
    prefixos = set(re.findall(r"`(/api/[a-z/-]+)`", titulos))
    faltam = []
    for caminho, operacoes in spec["paths"].items():
        c = _sem_nome(caminho)
        formas = {c} | {c[len(p):] or "/" for p in prefixos if c == p or c.startswith(p + "/")}
        for metodo, op in operacoes.items():
            if op.get("x-session-only"):
                continue
            if not any(re.search(r"`%s %s[`?]" % (metodo.upper(), re.escape(f)), doc) for f in formas):
                faltam.append(f"{metodo.upper()} {caminho}")
    return faltam


def test_rotas_abertas_citadas_no_api_md():
    from app.main import app
    doc = (DOCS / "API.md").read_text(encoding="utf-8")
    faltam = rotas_sem_citacao(app.openapi(), doc)
    assert not faltam, "rotas sem citação em docs/API.md (`MÉTODO /caminho` entre crases): " + ", ".join(faltam)


def test_a_conferencia_pega_rota_sem_citacao():
    """A regra não passa por acaso: rota que o texto não cita aparece; a só do app, não."""
    spec = {"paths": {
        "/api/worklog/{task_id}/finish": {"post": {}},
        "/api/board": {"get": {}, "put": {}},
        "/api/admin/users": {"get": {"x-session-only": True}},
    }}
    doc = "## Tarefas — `/api/worklog`\n| `POST /{id}/finish` | W | conclui |\n| `GET /api/board?day=` | | o quadro |\n"
    assert rotas_sem_citacao(spec, doc) == ["PUT /api/board"]
