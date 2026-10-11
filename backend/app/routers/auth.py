from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import audit, db
from ..config import config
from ..deps import (
    active_user_csrf,
    clear_session_cookie,
    client_ip,
    current_user,
    web_user_csrf,
    set_session_cookie,
)
from ..schemas import ChangePasswordIn, LoginIn, RegisterIn, SettingsIn
from ..security import (
    burn_password_check,
    hash_password,
    login_limiter,
    register_limiter,
    needs_rehash,
    new_token,
    password_ok,
    token_hash,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _public(row: dict, csrf: str) -> dict:
    return {
        "id": row.get("user_id") or row.get("id"),
        "email": row["email"],
        "role": row["role"],
        "must_change_password": row["must_change_password"],
        "work_days": row["work_days"],
        "csrf_token": csrf,
    }


@router.get("/config")
def public_config():
    """Configuracao publica que a tela de login precisa (sem autenticacao)."""
    return {"registration_open": config.REGISTRATION_OPEN}


@router.post("/register", status_code=201)
def register(data: RegisterIn, request: Request):
    if not config.REGISTRATION_OPEN:
        raise HTTPException(status_code=403, detail="cadastro fechado: peça um convite ao administrador")
    if not register_limiter.allow(f"ip:{client_ip(request)}"):
        raise HTTPException(status_code=429, detail="muitas tentativas, tente mais tarde")
    email = data.email.lower()
    if db.query_one("SELECT 1 FROM users WHERE email = %s", (email,)):
        raise HTTPException(status_code=409, detail="email ja cadastrado")
    db.execute(
        "INSERT INTO users (email, password_hash, role) VALUES (%s, %s, 'user')",
        (email, hash_password(data.password)),
    )
    return {"ok": True}


@router.post("/login")
def login(data: LoginIn, request: Request, response: Response):
    ip = client_ip(request)
    email = data.email.lower()
    if not login_limiter.allow(f"ip:{ip}") or login_limiter.blocked(f"em:{email}"):
        raise HTTPException(status_code=429, detail="muitas tentativas, tente mais tarde")

    user = db.query_one("SELECT * FROM users WHERE email = %s", (email,))
    if not user:
        burn_password_check(data.password)  # mesmo custo de um e-mail existente
        login_limiter.allow(f"em:{email}")
        raise HTTPException(status_code=401, detail="credenciais invalidas")
    if not verify_password(user["password_hash"], data.password):
        login_limiter.allow(f"em:{email}")
        raise HTTPException(status_code=401, detail="credenciais invalidas")

    if needs_rehash(user["password_hash"]):
        db.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (hash_password(data.password), user["id"]),
        )

    # Faxina barata: sessoes vencidas so eram apagadas quando reutilizadas.
    db.execute("DELETE FROM sessions WHERE expires_at <= now()")

    token = new_token()
    csrf = new_token()
    expires = datetime.now(timezone.utc) + timedelta(days=config.SESSION_TTL_DAYS)
    db.execute(
        """INSERT INTO sessions (user_id, token_hash, csrf_token, expires_at)
           VALUES (%s, %s, %s, %s)""",
        (user["id"], token_hash(token), csrf, expires),
    )
    set_session_cookie(response, token)
    return _public(user, csrf)


@router.post("/logout")
def logout(request: Request, response: Response, session=Depends(web_user_csrf)):
    token = request.cookies.get(config.SESSION_COOKIE)
    if token:
        db.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash(token),))
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(session=Depends(current_user)):
    return _public(session, session["csrf_token"])


@router.post("/change-password")
def change_password(data: ChangePasswordIn, session=Depends(web_user_csrf)):
    if not password_ok(data.new_password):
        raise HTTPException(status_code=400, detail="senha nova fraca")
    row = db.query_one("SELECT password_hash FROM users WHERE id = %s", (session["user_id"],))
    if not row or not verify_password(row["password_hash"], data.current_password):
        raise HTTPException(status_code=400, detail="senha atual incorreta")

    db.execute(
        "UPDATE users SET password_hash = %s, must_change_password = false WHERE id = %s",
        (hash_password(data.new_password), session["user_id"]),
    )
    # Encerra as demais sessoes do usuario (mantem a atual).
    db.execute(
        "DELETE FROM sessions WHERE user_id = %s AND id <> %s",
        (session["user_id"], session["sid"]),
    )
    return {"ok": True}


@router.post("/settings")
def save_settings(data: SettingsIn, session=Depends(active_user_csrf)):
    """Preferências do próprio usuário (hoje: dias úteis)."""
    before = session["work_days"]
    db.execute("UPDATE users SET work_days = %s WHERE id = %s", (data.work_days, session["user_id"]))
    if before != data.work_days:
        audit.record(session, "settings.update", "user", session["user_id"],
                     before={"work_days": before}, after={"work_days": data.work_days})
    return {"ok": True, "work_days": data.work_days}
