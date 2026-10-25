"""Busca sem acento: tarefas (título, descrição, anotações, checklist,
apontamentos), rotinas e projetos."""
import re

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db
from ..deps import active_user
from ..labels import fold

router = APIRouter(prefix="/api", tags=["search"])

MAX_HITS = 40


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
    raw = title.replace("/", " ").split()
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
        f"""SELECT w.id, w.title, w.resolution, w.completed_at, w.ticket, ({score}) AS score
              FROM worklog_tasks w
             WHERE w.user_id = %(uid)s AND w.status = 'done' AND w.resolution IS NOT NULL
               AND ({score}) >= %(need)s
             ORDER BY score DESC, w.completed_at DESC NULLS LAST
             LIMIT 3""", params)
    # Só os que casam tanto quanto o melhor: "impressora financeiro" não puxa
    # "Onboarding (Financeiro)" se há uma impressora do financeiro resolvida.
    return [r for r in rows if r["score"] == rows[0]["score"]] if rows else []


@router.get("/search")
def search(q: str = Query(..., min_length=2, max_length=100), user=Depends(active_user)):
    uid = user["user_id"]
    fq = fold(q.strip()[:100]).lstrip("#")  # "#1234" acha o chamado; também pelo MCP (sem validação de Query)
    if len(fq) < 2:
        raise HTTPException(status_code=400, detail="busque ao menos 2 letras")
    like = _like(fq)

    tasks: dict[int, dict] = {}

    def task(row):
        t = tasks.get(row["id"])
        if not t:
            t = tasks[row["id"]] = {k: row[k] for k in (
                "id", "title", "status", "priority", "due_date", "completed_at", "created_at",
                "project_name", "project_color", "ticket", "after_hours")} | {"hits": []}
        return t

    base = """SELECT w.id, w.title, w.description, w.status, w.priority, w.due_date, w.completed_at,
                     w.created_at, w.ticket, w.after_hours, p.name AS project_name, p.color AS project_color{extra}
                FROM worklog_tasks w LEFT JOIN projects p ON p.id = w.project_id {join}
               WHERE w.user_id = %(uid)s AND {cond}
               ORDER BY w.created_at DESC LIMIT 200"""
    params = {"uid": uid, "like": like}

    for r in db.query_all(base.format(extra="", join="", cond="(nx_fold(w.title) LIKE %(like)s OR nx_fold(w.description) LIKE %(like)s"
                                      " OR nx_fold(w.ticket) LIKE %(like)s)"), params):
        t = task(r)
        if r["ticket"] and fq.lstrip("#") in fold(r["ticket"]):
            t["hits"].append({"kind": "chamado", "text": "#" + r["ticket"]})
        if fq in fold(r["title"]):
            t["hits"].append({"kind": "título", "text": r["title"]})
        if r["description"] and fq in fold(r["description"]):
            t["hits"].append({"kind": "descrição", "text": _snippet(r["description"], fq)})
    for kind, extra, join, cond, field in [
        ("anotação", ", n.body AS hit", "JOIN task_notes n ON n.task_id = w.id", "nx_fold(n.body) LIKE %(like)s", "hit"),
        ("checklist", ", c.label AS hit", "JOIN task_checklist c ON c.task_id = w.id", "nx_fold(c.label) LIKE %(like)s", "hit"),
        ("apontamento", ", e.note AS hit", "JOIN time_entries e ON e.task_id = w.id", "nx_fold(e.note) LIKE %(like)s", "hit"),
        ("como resolveu", ", w.resolution AS hit", "", "nx_fold(w.resolution) LIKE %(like)s", "hit"),
    ]:
        for r in db.query_all(base.format(extra=extra, join=join, cond=cond), params):
            t = task(r)
            if sum(1 for h in t["hits"] if h["kind"] == kind) < 3:
                t["hits"].append({"kind": kind, "text": _snippet(r[field], fq)})

    recurring = db.query_all(
        """SELECT id, label, active, freq FROM recurring_tasks
            WHERE user_id = %(uid)s AND nx_fold(label) LIKE %(like)s
            ORDER BY active DESC, position, id LIMIT 20""", params)
    projects = db.query_all(
        """SELECT id, name, color, archived FROM projects
            WHERE user_id = %(uid)s AND nx_fold(name) LIKE %(like)s ORDER BY archived, lower(name) LIMIT 20""", params)

    # Abertas primeiro (mais urgentes), depois concluídas mais recentes.
    ordered = sorted(tasks.values(), key=lambda t: (
        t["status"] == "done", t["priority"] if t["status"] != "done" else 0,
        -(t["completed_at"] or t["created_at"]).timestamp()))
    return {"q": q, "tasks": ordered[:MAX_HITS], "total_tasks": len(ordered),
            "recurring": recurring, "projects": projects}
