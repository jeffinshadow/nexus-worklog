from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import active_user
from ..services import app_today, get_dashboard

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

MONTH = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="AAAA-MM; sem ele, os últimos 30 dias")


def parse_month(month: Optional[str]) -> date | None:
    """AAAA-MM -> dia 1 do mês. Mês futuro não tem retrospectiva."""
    if month is None:
        return None
    m = date(int(month[:4]), int(month[5:]), 1)
    if m > app_today().replace(day=1):
        raise HTTPException(status_code=400, detail="mês no futuro")
    return m


@router.get("")
def dashboard(month: Optional[str] = MONTH, user=Depends(active_user)):
    return get_dashboard(user["user_id"], parse_month(month))
