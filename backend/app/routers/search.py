"""Busca sem acento: tarefas (título, descrição, anotações, checklist,
apontamentos), rotinas e projetos."""
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .. import db
from ..deps import active_user
from ..labels import fold
from ..paging import clamp, put_total, OFFSET_MAX
from ..services import ASSIGNER_NAME, EXTRA_PROJECTS, PROJECT_ICON

router = APIRouter(prefix="/api", tags=["search"])

MAX_HITS = 40   # tarefas por resposta, sem limit (o app pede páginas de 20)
SIDE_HITS = 20  # rotinas e projetos por resposta, sem side_limit (o app pede 10)
MAX_WORDS = 8   # palavras por busca (cada uma é um conjunto a mais na interseção)


def _snippet(text: str, q: str, width: int = 70) -> str:
    """Trecho de `text` em volta da primeira ocorrência de `q` (sem acento)."""
    i = fold(text).find(q)
    if i < 0 or len(text) <= width * 2:
        return text if len(text) <= width * 2 else text[: width * 2].rstrip() + "…"
    a, b = max(0, i - width), min(len(text), i + len(q) + width)
    return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")


# Palavras que não dizem qual é o problema ("não", "para", "com"...).
_VAZIAS = {"para", "pelo", "pela", "com", "sem", "nao", "esta", "esse", "essa", "isso", "como", "mais",
           "muito", "quando", "onde", "porque", "tarefa", "fazer", "verificar", "ver", "ajustar",
           "dos", "das", "nos", "nas", "uma", "uns", "por", "que", "novo", "nova", "outra", "outro"}


def _words(fq: str) -> list[str]:
    """Palavras da consulta (já sem acento), sem repetir. Palavra de uma letra
    só não filtra nada ("a", "o", "e"); se só houver dessas, vale a frase inteira."""
    words = list(dict.fromkeys(w.lstrip("#") for w in fq.split()))
    return [w for w in words if len(w) >= 2][:MAX_WORDS] or [fq]


def _all(col: str, n: int) -> str:
    """Condição "o campo tem TODAS as palavras" (rotinas e projetos: um campo só)."""
    return " AND ".join(f"nx_fold({col}) LIKE %(w{i})s" for i in range(n))


def _any(col: str, n: int) -> str:
    return "(" + " OR ".join(f"nx_fold({col}) LIKE %(w{i})s" for i in range(n)) + ")"


# Cada linha é um texto (já sem acento) de uma tarefa da pessoa: os campos da
# própria tarefa juntos (separados por chr(1), que nenhuma busca contém) e uma
# linha por anotação, item de checklist e apontamento. MATERIALIZED: o nx_fold
# roda uma vez por texto, não uma vez por palavra buscada.
_SRC = """src AS MATERIALIZED (
               SELECT w.id, nx_fold(w.title) || chr(1) || nx_fold(w.description) || chr(1)
                      || nx_fold(w.ticket) || chr(1) || nx_fold(w.resolution) AS f
                 FROM worklog_tasks w WHERE w.user_id = %(uid)s
               UNION ALL SELECT n.task_id, nx_fold(n.body) FROM task_notes n WHERE n.user_id = %(uid)s
               UNION ALL SELECT c.task_id, nx_fold(c.label) FROM task_checklist c WHERE c.user_id = %(uid)s
               UNION ALL SELECT e.task_id, nx_fold(e.note) FROM time_entries e WHERE e.user_id = %(uid)s)"""


def _hit(n: int) -> str:
    """CTEs `src` e `hit`: as tarefas com TODAS as palavras, cada uma em
    qualquer texto da tarefa, e se a frase inteira aparece em algum (`exact`).
    Uma passada só por tabela, seja qual for o número de palavras."""
    every = " AND ".join(f"bool_or(f LIKE %(w{i})s)" for i in range(n))
    return f"""{_SRC},
           hit AS (SELECT id, COALESCE(bool_or(f LIKE %(like)s), FALSE) AS exact FROM src GROUP BY id HAVING {every})"""


def _first(text: str, words: list[str]) -> str | None:
    """A palavra da consulta que aparece primeiro em `text` (None: nenhuma)."""
    f = fold(text)
    found = [(f.find(w), w) for w in words if w in f]
    return min(found)[1] if found else None


def _like(text: str) -> str:
    """Padrão LIKE de "contém", com %, _ e \\ do texto escapados."""
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@router.get("/search/similar")
def similar(title: str = Query(..., min_length=3, max_length=200), user=Depends(active_user)):
    """"Já resolvi isso antes?": até 3 tarefas concluídas, com "como resolveu",
    cujo título tem palavras em comum com `title` (sem acento, 3+ letras: VPN,
    DNS). Mais palavras em comum primeiro; com 4+ palavras no título, exige 2."""
    return find_similar(user["user_id"], title)


def find_similar(uid: int, title: str) -> list[dict]:
    # Palavras de 3+ letras, ou siglas de 2 em maiúsculas (AD, IP, RH, TI), sem
    # repetir, as mais específicas (longas) primeiro — o corte em 6 é estável.
    raw = [x for x in re.split(r"[^\w]+", title) if x]  # "VPN: caiu", "(Financeiro)": só as palavras
    words = list(dict.fromkeys(fold(x) for x in raw
                               if (len(x) >= 3 or (len(x) == 2 and x.isupper())) and fold(x) not in _VAZIAS))
    words = sorted(words, key=len, reverse=True)[:6]
    if not words:
        return []
    need = 2 if len(words) >= 4 else 1
    # Sigla curta casa só como palavra inteira ("ad" não casa "adaptador").
    terms = [f"(nx_fold(w.title) ~ %(w{i})s)::int" if len(w) <= 3 else f"(nx_fold(w.title) LIKE %(w{i})s)::int"
             for i, w in enumerate(words)]
    score = " + ".join(terms)
    params = {"uid": uid, "need": need,
              **{f"w{i}": (rf"\m{re.escape(w)}\M" if len(w) <= 3 else _like(w)) for i, w in enumerate(words)}}
    rows = db.query_all(
        f"""SELECT w.id, w.title, w.resolution, w.completed_at, w.ticket, ({score}) AS score, {ASSIGNER_NAME}
              FROM worklog_tasks w
             WHERE w.user_id = %(uid)s AND w.status = 'done' AND w.resolution IS NOT NULL
               AND ({score}) >= %(need)s
             ORDER BY score DESC, w.completed_at DESC NULLS LAST
             LIMIT 3""", params)
    # Só os que casam tanto quanto o melhor: "impressora financeiro" não puxa
    # "Onboarding (Financeiro)" se há uma impressora do financeiro resolvida.
    return [r for r in rows if r["score"] == rows[0]["score"]] if rows else []


@router.get("/search")
def search(
    q: str = Query(..., min_length=2, max_length=100),
    offset: Annotated[int, Query(ge=0, le=OFFSET_MAX, description="Tarefas: pula as N primeiras (páginas)")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Tarefas por resposta (padrão 40)")] = MAX_HITS,
    rec_offset: Annotated[int, Query(ge=0, le=OFFSET_MAX, description="Rotinas: pula as N primeiras")] = 0,
    proj_offset: Annotated[int, Query(ge=0, le=OFFSET_MAX, description="Projetos: pula os N primeiros")] = 0,
    side_limit: Annotated[int, Query(ge=1, le=50, description="Rotinas e projetos por resposta (padrão 20)")] = SIDE_HITS,
    response: Response = None,
    user=Depends(active_user),
):
    """Tarefas, rotinas e projetos com o termo. Cada seção pagina sozinha
    (offset/limit; rec_offset, proj_offset e side_limit) e traz o total real:
    total_tasks, total_recurring, total_projects (X-Total-Count = total_tasks)."""
    # "O termo" são as palavras da busca: todas têm de aparecer, em qualquer ordem e campo.
    # (A docstring vai para o openapi.json: fica como está até o integrador regerar.)
    uid = user["user_id"]
    fq = fold(q.strip()[:100]).lstrip("#")  # "#1234" acha o chamado; também pelo MCP (sem validação de Query)
    if len(fq) < 2:
        raise HTTPException(status_code=400, detail="busque ao menos 2 letras")
    offset, limit = clamp(offset, 0, OFFSET_MAX, 0), clamp(limit, 1, 100, MAX_HITS)
    rec_offset, proj_offset = clamp(rec_offset, 0, OFFSET_MAX, 0), clamp(proj_offset, 0, OFFSET_MAX, 0)
    side_limit = clamp(side_limit, 1, 50, SIDE_HITS)
    words = _words(fq)
    n = len(words)
    like = _like(fq)
    wl = {f"w{i}": _like(w) for i, w in enumerate(words)}
    params = {"uid": uid, "like": like, "lim": limit, "off": offset, **wl}

    # Quais tarefas casam (todas as palavras, cada uma em qualquer campo) e a
    # ordem: a frase exata primeiro; depois abertas (as mais urgentes) e as
    # concluídas mais recentes; o id desempata, para nenhuma aparecer em duas
    # páginas. Os trechos só são lidos para a página.
    page = db.query_all(
        f"""WITH {_hit(n)}
           SELECT w.id, count(*) OVER () AS total
             FROM worklog_tasks w JOIN hit ON hit.id = w.id
            WHERE w.user_id = %(uid)s
            ORDER BY NOT hit.exact, w.status = 'done', CASE WHEN w.status <> 'done' THEN w.priority ELSE 0 END,
                     COALESCE(w.completed_at, w.created_at) DESC, w.id DESC
            LIMIT %(lim)s OFFSET %(off)s""", params)
    total_tasks = page[0]["total"] if page else (
        0 if offset == 0 else _count_tasks(params, n))  # página além do fim: lista vazia, total certo
    ids = [r["id"] for r in page]
    params["ids"] = ids

    tasks: dict[int, dict] = {}

    def task(row):
        t = tasks.get(row["id"])
        if not t:
            t = tasks[row["id"]] = {k: row[k] for k in (
                "id", "title", "status", "priority", "due_date", "completed_at", "created_at",
                "project_name", "project_color", "project_icon", "extra_projects", "ticket", "after_hours", "assigned_by_name")} | {"hits": []}
        return t

    base = """SELECT w.id, w.title, w.description, w.status, w.priority, w.due_date, w.completed_at,
                     w.created_at, w.ticket, w.after_hours, p.name AS project_name, p.color AS project_color,
                     """ + PROJECT_ICON + ", " + ASSIGNER_NAME + ", " + EXTRA_PROJECTS + """{extra}
                FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id {join}
               WHERE w.user_id = %(uid)s AND w.id = ANY(%(ids)s) AND {cond}
               ORDER BY w.created_at DESC, w.id DESC"""

    if ids:
        for r in db.query_all(base.format(extra="", join="", cond="TRUE"), params):
            t = task(r)
            if r["ticket"] and _first(r["ticket"], words):
                t["hits"].append({"kind": "chamado", "text": "#" + r["ticket"]})
            if _first(r["title"], words):
                t["hits"].append({"kind": "título", "text": r["title"]})
            if r["description"] and (w := _first(r["description"], words)):
                t["hits"].append({"kind": "descrição", "text": _snippet(r["description"], w)})
        # Uma consulta por tipo de trecho para a página inteira (qualquer das palavras).
        for kind, extra, join, cond, field in [
            # user_id também no JOIN: o banco filtra pelo índice da pessoa, não varre todas as contas.
            ("anotação", ", n.body AS hit", "JOIN task_notes n ON n.task_id = w.id AND n.user_id = %(uid)s", _any("n.body", n), "hit"),
            ("checklist", ", c.label AS hit", "JOIN task_checklist c ON c.task_id = w.id AND c.user_id = %(uid)s", _any("c.label", n), "hit"),
            ("apontamento", ", e.note AS hit", "JOIN time_entries e ON e.task_id = w.id AND e.user_id = %(uid)s", _any("e.note", n), "hit"),
            ("como resolveu", ", w.resolution AS hit", "", _any("w.resolution", n), "hit"),
        ]:
            for r in db.query_all(base.format(extra=extra, join=join, cond=cond), params):
                t = task(r)
                if sum(1 for h in t["hits"] if h["kind"] == kind) < 3:
                    t["hits"].append({"kind": kind, "text": _snippet(r[field], _first(r[field], words) or fq)})

    side = {"uid": uid, "lim": side_limit, **wl}
    recurring = db.query_all(
        f"""SELECT id, label, active, freq, count(*) OVER () AS total FROM recurring_tasks
            WHERE user_id = %(uid)s AND {_all("label", n)}
            ORDER BY active DESC, position, id LIMIT %(lim)s OFFSET %(off)s""", side | {"off": rec_offset})
    projects = db.query_all(
        f"""SELECT id, name, color, COALESCE(icon, 'pasta') AS icon, archived, count(*) OVER () AS total FROM projects
            WHERE user_id = %(uid)s AND {_all("name", n)}
            ORDER BY archived, nx_fold(name), id LIMIT %(lim)s OFFSET %(off)s""", side | {"off": proj_offset})
    total_rec = recurring[0]["total"] if recurring else db.query_one(
        f"SELECT count(*)::int AS n FROM recurring_tasks WHERE user_id = %(uid)s AND {_all('label', n)}", side)["n"]
    total_proj = projects[0]["total"] if projects else db.query_one(
        f"SELECT count(*)::int AS n FROM projects WHERE user_id = %(uid)s AND {_all('name', n)}", side)["n"]
    for r in recurring + projects:
        r.pop("total")

    put_total(response, total_tasks)
    return {"q": q, "tasks": [tasks[i] for i in ids if i in tasks], "total_tasks": int(total_tasks),
            "recurring": recurring, "total_recurring": int(total_rec),
            "projects": projects, "total_projects": int(total_proj)}


def _count_tasks(params: dict, n: int) -> int:
    return db.query_one(
        f"""WITH {_hit(n)}
            SELECT count(*)::int AS n FROM hit JOIN worklog_tasks w ON w.id = hit.id AND w.user_id = %(uid)s""", params)["n"]
