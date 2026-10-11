from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db
from ..deps import require_admin, require_admin_csrf
from ..schemas import InviteIn
from ..security import generate_temp_password, hash_password
from ..services import get_board, get_dashboard
from .board import check_board_day
from .reports import build_pdf_response

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _ensure_user(user_id: int) -> dict:
    row = db.query_one("SELECT id, email FROM users WHERE id = %s", (user_id,))
    if not row:
        raise HTTPException(status_code=404, detail="usuario nao encontrado")
    return row


@router.get("/users")
def list_users(admin=Depends(require_admin)):
    return db.query_all(
        "SELECT id, email, role, created_at FROM users ORDER BY role DESC, email"
    )


@router.post("/users", status_code=201)
def invite_user(data: InviteIn, admin=Depends(require_admin_csrf)):
    """Cria a conta de um convidado com senha temporaria (mostrada uma unica vez
    ao admin). O convidado troca a senha no primeiro login, como no reset."""
    email = data.email.lower()
    if db.query_one("SELECT 1 FROM users WHERE email = %s", (email,)):
        raise HTTPException(status_code=409, detail="email ja cadastrado")
    temp = generate_temp_password()
    db.execute(
        """INSERT INTO users (email, password_hash, role, must_change_password)
           VALUES (%s, %s, 'user', true)""",
        (email, hash_password(temp)),
    )
    return {"email": email, "temp_password": temp}


@router.get("/users/{user_id}/board")
def user_board(
    user_id: int,
    day: Optional[date] = Query(default=None),
    admin=Depends(require_admin),
):
    _ensure_user(user_id)
    return get_board(user_id, check_board_day(day))


@router.get("/users/{user_id}/dashboard")
def user_dashboard(user_id: int, admin=Depends(require_admin)):
    _ensure_user(user_id)
    return get_dashboard(user_id)


@router.get("/users/{user_id}/reports/export")
def user_report_export(
    user_id: int,
    start: date = Query(...),
    end: date = Query(...),
    admin=Depends(require_admin),
):
    target = _ensure_user(user_id)
    return build_pdf_response(target["email"], user_id, start, end)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, admin=Depends(require_admin_csrf)):
    """Redefine a senha de um usuario para uma temporaria gerada (mostrada uma
    unica vez ao admin). Forca troca no proximo login e encerra as sessoes do
    alvo. Sem envolvimento de e-mail. Para a propria conta, use a troca normal."""
    if user_id == admin["user_id"]:
        raise HTTPException(status_code=400, detail="use a troca de senha da sua propria conta")
    target = _ensure_user(user_id)

    temp = generate_temp_password()
    db.execute(
        "UPDATE users SET password_hash = %s, must_change_password = true WHERE id = %s",
        (hash_password(temp), user_id),
    )
    # Encerra TODAS as sessoes do alvo: ele so volta com a senha temporaria.
    db.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
    return {"email": target["email"], "temp_password": temp}
