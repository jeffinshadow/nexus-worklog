import re
import threading
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .. import db, people
from ..config import config
from ..deps import active_user
from ..security import pdf_limiter
from .branding import branding
from ..report_pdf import build_report_pdf
from ..services import IN_PROJECT, app_today, get_report_range

router = APIRouter(prefix="/api/reports", tags=["reports"])

_pdf_slot = threading.BoundedSemaphore(1)
MAX_RANGE_DAYS = 366       # período escolhido, em dias (inclusivo)
MAX_PROJECT_DAYS = 3 * 366  # "projeto inteiro": no máximo os últimos ~3 anos


def project_first_day(user_id: int, project_id: int) -> date:
    """Primeiro dia com algo do projeto: criação dele, de uma tarefa ou um apontamento."""
    tz = config.APP_TZ
    row = db.query_one(
        """
        SELECT LEAST(
          (SELECT (created_at AT TIME ZONE %s)::date FROM projects WHERE id = %s),
          (SELECT min((w.created_at AT TIME ZONE %s)::date) FROM worklog_tasks w WHERE """ + IN_PROJECT + """ AND w.user_id = %s),
          (SELECT min((w.completed_at AT TIME ZONE %s)::date) FROM worklog_tasks w WHERE """ + IN_PROJECT + """ AND w.user_id = %s),
          (SELECT min(e.day) FROM time_entries e JOIN worklog_tasks w ON w.id = e.task_id
            WHERE """ + IN_PROJECT + """ AND e.user_id = %s)
        ) AS d
        """,
        (tz, project_id, tz, project_id, project_id, user_id, tz, project_id, project_id, user_id,
         project_id, project_id, user_id),
    )
    return min(row["d"] or app_today(), app_today())


def resolve_range(user_id: int, start: date | None, end: date | None, project_id: int | None):
    """Valida o período (o mesmo do PDF e da prévia): devolve (início, fim,
    projeto ou None, projeto inteiro?)."""
    project = None
    if project_id is not None:
        project = db.query_one("SELECT id, name FROM projects WHERE id = %s AND user_id = %s",
                               (project_id, user_id))
        if not project:
            raise HTTPException(status_code=400, detail="projeto não encontrado")
    elif start is None or end is None:
        raise HTTPException(status_code=400, detail="informe início e fim (ou escolha um projeto)")

    whole = project is not None and start is None
    # Nao ha dias futuros: limita o fim a hoje (no fuso da app) antes de medir.
    end = min(end or app_today(), app_today())
    truncated = False
    if whole:
        first = project_first_day(user_id, project["id"])
        start = max(first, end - timedelta(days=MAX_PROJECT_DAYS - 1))
        truncated = start > first
    if start > end:
        raise HTTPException(status_code=400, detail="o início não pode ser depois do fim nem no futuro")
    if not whole and (end - start).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(status_code=400, detail=f"período máximo de {MAX_RANGE_DAYS} dias")
    if project:
        project["whole"] = whole
        project["truncated"] = truncated
    return start, end, project, whole


def build_pdf_response(user_email: str, user_id: int, start: date | None, end: date | None,
                       project_id: int | None = None) -> Response:
    """Valida o periodo, monta os dados e devolve o PDF como download.

    Com projeto, as datas são opcionais: sem início, vale desde a primeira
    atividade do projeto (relatório do projeto inteiro, sem limite de dias);
    sem fim, até hoje. Compartilhado com o router admin.
    """
    if not pdf_limiter.allow(f"pdf:{user_id}"):
        raise HTTPException(status_code=429, detail="muitos relatórios em sequência; aguarde um minuto")
    start, end, project, whole = resolve_range(user_id, start, end, project_id)
    data = get_report_range(user_id, start, end, project)
    brand = branding()
    # Um PDF por vez no servidor (o fpdf2 monta tudo em memória numa VM pequena).
    if not _pdf_slot.acquire(timeout=5):
        raise HTTPException(status_code=429, detail="outro relatório está sendo gerado; tente em instantes")
    try:
        pdf = build_report_pdf(people.label(user_id, user_email), start, end, data, brand)
    finally:
        _pdf_slot.release()

    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", user_email).strip("-").lower() or "usuario"
    if project:
        slug += "-" + (re.sub(r"[^a-zA-Z0-9._-]+", "-", project["name"]).strip("-").lower() or "projeto")
    span = "projeto-completo" if whole else f"{start.isoformat()}-a-{end.isoformat()}"
    filename = f"relatorio-worklog-{slug}-{span}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export")
def export(
    start: date | None = Query(None),
    end: date | None = Query(None),
    project: int | None = Query(None),
    user=Depends(active_user),
):
    return build_pdf_response(user["email"], user["user_id"], start, end, project)


@router.get("/preview")
def preview(
    start: date | None = Query(None),
    end: date | None = Query(None),
    project: int | None = Query(None),
    user=Depends(active_user),
):
    """O que o PDF vai trazer (a frase do assistente antes de exportar)."""
    start, end, proj, _ = resolve_range(user["user_id"], start, end, project)
    s = get_report_range(user["user_id"], start, end, proj)["summary"]
    return {"start": start, "end": end, "pontual_done": s["pontual_done"], "minutes": s["minutes"],
            "recurring_done": s["recurring_done"], "recurring_total": s["recurring_total"],
            "active_days": s["active_days"]}
