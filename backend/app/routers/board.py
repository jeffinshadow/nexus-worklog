from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import active_user
from ..services import app_today, board_day_range, get_board

router = APIRouter(prefix="/api/board", tags=["board"])


def check_board_day(day: Optional[date]) -> Optional[date]:
    """Dia pedido para as recorrentes: hoje ou até RETRO_DAYS dias atrás."""
    if day is None:
        return None
    min_day, today = board_day_range(app_today())
    if not (min_day <= day <= today):
        raise HTTPException(status_code=400, detail="dia fora da janela de edição")
    return day


@router.get("")
def board(
    day: Optional[date] = Query(default=None),
    project: Optional[int] = Query(default=None, ge=0, description="0 = sem projeto"),
    user=Depends(active_user),
):
    return get_board(user["user_id"], check_board_day(day), project)
