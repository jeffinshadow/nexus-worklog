from fastapi import APIRouter, Depends

from ..deps import active_user
from ..services import get_summary

router = APIRouter(prefix="/api/summary", tags=["summary"])


@router.get("")
def summary(user=Depends(active_user)):
    return get_summary(user["user_id"])
