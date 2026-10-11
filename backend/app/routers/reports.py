import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .. import db
from ..deps import active_user
from ..report_pdf import build_report_pdf
from ..services import app_today, get_report_range

router = APIRouter(prefix="/api/reports", tags=["reports"])

MAX_RANGE_DAYS = 366


def build_pdf_response(user_email: str, user_id: int, start: date, end: date,
                       project_id: int | None = None) -> Response:
    """Valida o periodo, monta os dados e devolve o PDF como download.

    Compartilhado com o router admin (extracao para outro usuario).
    """
    if start > end:
        raise HTTPException(status_code=400, detail="o início não pode ser depois do fim")
    if (end - start).days > MAX_RANGE_DAYS:
        raise HTTPException(status_code=400, detail=f"período máximo de {MAX_RANGE_DAYS} dias")

    # Nao ha dias futuros: limita o fim a hoje (no fuso da app).
    end = min(end, app_today())
    if start > end:
        raise HTTPException(status_code=400, detail="o início não pode ser no futuro")

    project = None
    if project_id is not None:
        project = db.query_one("SELECT id, name FROM projects WHERE id = %s AND user_id = %s",
                               (project_id, user_id))
        if not project:
            raise HTTPException(status_code=400, detail="projeto não encontrado")

    data = get_report_range(user_id, start, end, project)
    pdf = build_report_pdf(user_email, start, end, data)

    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", user_email).strip("-").lower() or "usuario"
    if project:
        slug += "-" + (re.sub(r"[^a-zA-Z0-9._-]+", "-", project["name"]).strip("-").lower() or "projeto")
    filename = f"relatorio-worklog-{slug}-{start.isoformat()}-a-{end.isoformat()}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export")
def export(
    start: date = Query(...),
    end: date = Query(...),
    project: int | None = Query(None),
    user=Depends(active_user),
):
    return build_pdf_response(user["email"], user["user_id"], start, end, project)
