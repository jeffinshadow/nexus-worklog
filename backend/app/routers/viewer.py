"""Visualizador de tarefas: vê, sem editar, o registro de cada pessoa
(quadro, retrospectiva, relatório em PDF) e baixa as horas da equipe.

Só pelo app (nunca por chave de API), como o admin. Lista só contas com o
papel Usuário que deram o aceite (users.viewers_allowed, em Configurações >
Conta): quem não aceitou responde 404, como quem não existe.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db, people
from ..deps import require_viewer
from .dashboard import MONTH, parse_month
from ..services import app_today, get_board, get_dashboard
from .board import check_board_day
from .export import time_csv
from .reports import build_pdf_response

router = APIRouter(prefix="/api/viewer", tags=["viewer"])


def _ensure_user(user_id: int) -> dict:
    row = db.query_one(
        """SELECT u.id, u.email FROM users u
            WHERE u.id = %s AND u.viewers_allowed
              AND EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'user')""",
        (user_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="usuário não encontrado")
    return row


@router.get("/users")
def list_users(viewer=Depends(require_viewer)):
    # Só quem já entrou e segue com acesso (convite pendente ou conta bloqueada
    # não têm o que mostrar), em ordem de nome, como aparecem no seletor.
    rows = db.query_all(
        """SELECT u.id, u.email FROM users u
            WHERE u.viewers_allowed AND NOT u.invite_pending AND u.blocked_at IS NULL
              AND EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'user')""")
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
