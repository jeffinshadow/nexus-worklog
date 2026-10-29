import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import audit, db, links, mailer, people, roles
from ..config import config
from ..deps import (
    active_user_csrf,
    clear_session_cookie,
    client_ip,
    current_user,
    web_user_csrf,
    set_session_cookie,
)
from ..schemas import ChangePasswordIn, ForgotIn, LinkPasswordIn, LoginIn, SettingsIn
from ..services import app_today, app_tz, task_retro_days
from .recurring import replace_routine
from ..security import (
    burn_password_check,
    hash_password,
    login_email_limiter,
    login_limiter,
    needs_rehash,
    new_token,
    reset_email_limiter,
    reset_limiter,
    revoke_access,
    token_hash,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("uvicorn.error")


def _public(row: dict, csrf: str) -> dict:
    uid = row.get("user_id") or row.get("id")
    return {
        "id": uid,
        "email": row["email"],
        **people.profile(uid),  # display_name, name, avatar
        **(db.query_one("SELECT ticket_url, accepts_assignments_at, default_project_id, tour_done_at FROM users WHERE id = %s",
                        (uid,)) or {}),
        "assistant": people.assistant_prefs(uid),
        "role": row["role"],
        "roles": roles.of(uid),
        "retro_days": task_retro_days(),  # limite de datas retroativas em tarefas
        "support_contact": (db.query_one("SELECT support_contact FROM app_settings WHERE id = 1") or {}).get("support_contact"),
        "must_change_password": row["must_change_password"],
        "work_days": row["work_days"],
        "tz": config.APP_TZ,  # o front formata datas/horas no fuso da app
        "csrf_token": csrf,
    }


@router.post("/login")
def login(data: LoginIn, request: Request, response: Response):
    ip = client_ip(request)
    email = data.email.lower()
    fail_keys = (f"em:{email}|{ip}", f"em:{email}")
    if (not login_limiter.allow(f"ip:{ip}") or login_limiter.blocked(fail_keys[0])
            or login_email_limiter.blocked(fail_keys[1])):
        raise HTTPException(status_code=429, detail="muitas tentativas, tente mais tarde")

    def falhou():
        log.warning("login falhou: ip=%s conta=%s", ip, token_hash(email)[:12])  # sem o e-mail em claro
        login_limiter.allow(fail_keys[0])
        login_email_limiter.allow(fail_keys[1])
        raise HTTPException(status_code=401, detail="credenciais invalidas")

    user = db.query_one("SELECT * FROM users WHERE email = %s", (email,))
    if not user:
        burn_password_check(data.password)  # mesmo custo de um e-mail existente
        falhou()
    if not verify_password(user["password_hash"], data.password):
        falhou()

    if needs_rehash(user["password_hash"]):
        db.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (hash_password(data.password), user["id"]),
        )

    # Faxina barata: sessoes vencidas e historico antigo (o desfazer so vale
    # para o recente; excluir de verdade nao pode durar para sempre no log).
    db.execute("DELETE FROM sessions WHERE expires_at <= now()")
    db.execute("DELETE FROM audit_log WHERE created_at < now() - interval '180 days'")
    # Links de convite/senha já usados ou vencidos não servem para nada depois de um mês.
    db.execute("""DELETE FROM auth_links WHERE created_at < now() - interval '30 days'
                   AND (used_at IS NOT NULL OR expires_at <= now())""")

    return _start_session(user, response)


def _start_session(user: dict, response: Response) -> dict:
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


# ------------------------------------------- convite e recuperação por e-mail --
# Só existem com SMTP configurado. A tela de login pergunta em /options.

@router.get("/options")
def options():
    """O que a tela de login oferece (público): "Esqueci a senha" só com e-mail."""
    return {"email": mailer.configured()}


def _reset_mail(email: str, link: str):
    from ..notify import Mail  # import tardio: notify importa rotas
    m = Mail("Redefinir a sua senha do Nexus", "Redefinir a senha",
             "Alguém (provavelmente você) pediu para redefinir a senha desta conta. O link vale por 1 hora e funciona uma vez só.")
    m.blocks = [("Não foi você?", ["Pode ignorar este e-mail: a senha atual continua valendo."])]
    m.link, m.absolute, m.button = link, True, "Criar uma senha nova"
    m.reason, m.settings_tab = f"Enviado para {email} a pedido da tela de login.", None
    return m


def _send_quiet(to: str, mail) -> None:
    try:
        mailer.send(to, mail.subject, mail.text(), mail.html())
    except Exception as e:  # noqa: BLE001 — a resposta já foi dada (não revela se a conta existe)
        log.warning("e-mail de recuperação falhou: %s", e)


@router.post("/forgot")
def forgot(data: ForgotIn, request: Request):
    """Manda o link de nova senha. A resposta é sempre a mesma (não diz se o
    e-mail tem conta) e o envio sai em segundo plano (o tempo também não diz)."""
    if not mailer.configured():
        raise HTTPException(status_code=400, detail="recuperação por e-mail indisponível: fale com o administrador")
    email = data.email.lower()
    if not reset_limiter.allow(f"ip:{client_ip(request)}") or not reset_email_limiter.allow(f"em:{email}"):
        raise HTTPException(status_code=429, detail="muitos pedidos, tente mais tarde")
    user = db.query_one("SELECT id, email FROM users WHERE email = %s", (email,))
    if user:
        link = links.url("reset", links.issue(user["id"], "reset"))
        threading.Thread(target=_send_quiet, args=(user["email"], _reset_mail(user["email"], link)), daemon=True).start()
        audit.record({"user_id": user["id"], "actor": "web"}, "password.forgot", "password", user["id"])
    return {"ok": True}


@router.get("/link")
def link_info(kind: Literal["invite", "reset"], token: str, request: Request):
    """Para quem abriu o link: de que conta é (ou 404 se venceu/foi usado)."""
    if not login_limiter.allow(f"ip:{client_ip(request)}"):
        raise HTTPException(status_code=429, detail="muitas tentativas, tente mais tarde")
    row = links.peek(token, kind)
    if not row:
        raise HTTPException(status_code=404, detail="link inválido, vencido ou já usado")
    return {"email": row["email"], "display_name": row["display_name"]}


def _set_password(uid: int, password: str) -> None:
    db.execute("""UPDATE users SET password_hash = %s, must_change_password = false, invite_pending = false
                   WHERE id = %s""", (hash_password(password), uid))


@router.post("/invite/accept")
def accept_invite(data: LinkPasswordIn, request: Request, response: Response):
    """Convidado cria a própria senha (e o nome) e já entra."""
    if not login_limiter.allow(f"ip:{client_ip(request)}"):
        raise HTTPException(status_code=429, detail="muitas tentativas, tente mais tarde")
    uid = links.consume(data.token, "invite")
    if not uid:
        raise HTTPException(status_code=400, detail="convite inválido, vencido ou já usado: peça um novo ao administrador")
    _set_password(uid, data.password)
    nome = " ".join((data.display_name or "").split()) or None
    if nome:
        db.execute("UPDATE users SET display_name = %s WHERE id = %s", (nome, uid))
    audit.record({"user_id": uid, "actor": "web"}, "user.invite_accept", "user", uid)
    return _start_session(db.query_one("SELECT * FROM users WHERE id = %s", (uid,)), response)


@router.post("/reset")
def reset_by_link(data: LinkPasswordIn, request: Request, response: Response):
    """Senha nova pelo link do e-mail: encerra as outras sessões e corta chaves
    de API e calendário (como a troca de senha) e já entra."""
    if not login_limiter.allow(f"ip:{client_ip(request)}"):
        raise HTTPException(status_code=429, detail="muitas tentativas, tente mais tarde")
    uid = links.consume(data.token, "reset")
    if not uid:
        raise HTTPException(status_code=400, detail="link inválido, vencido ou já usado: peça outro na tela de login")
    _set_password(uid, data.password)
    db.execute("DELETE FROM sessions WHERE user_id = %s", (uid,))
    revoke_access(uid)
    audit.record({"user_id": uid, "actor": "web"}, "password.reset_link", "password", uid)
    return _start_session(db.query_one("SELECT * FROM users WHERE id = %s", (uid,)), response)


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
    if not login_limiter.allow(f"pw:{session['user_id']}"):  # sessão roubada não testa senhas à vontade
        raise HTTPException(status_code=429, detail="muitas tentativas, tente mais tarde")
    if data.new_password == data.current_password:  # inclusive a temporária que o admin viu
        raise HTTPException(status_code=400, detail="a senha nova precisa ser diferente da atual")
    row = db.query_one("SELECT password_hash FROM users WHERE id = %s", (session["user_id"],))
    if not row or not verify_password(row["password_hash"], data.current_password):
        raise HTTPException(status_code=400, detail="senha atual incorreta")

    db.execute(
        "UPDATE users SET password_hash = %s, must_change_password = false WHERE id = %s",
        (hash_password(data.new_password), session["user_id"]),
    )
    # Encerra as demais sessoes (mantem a atual) e corta chaves de API e o
    # link do calendario: quem tinha acesso por elas precisa de um novo.
    db.execute(
        "DELETE FROM sessions WHERE user_id = %s AND id <> %s",
        (session["user_id"], session["sid"]),
    )
    revoke_access(session["user_id"])
    return {"ok": True}


@router.post("/settings")
def save_settings(data: SettingsIn, session=Depends(active_user_csrf)):
    """Preferências do próprio usuário (hoje: dias úteis).

    Mudar os dias úteis NÃO reescreve o passado: cada rotina "nos dias úteis"
    que já tem história fica congelada com os dias antigos (vira semanal) e
    recomeça hoje seguindo os novos; as já encerradas só congelam."""
    uid, before = session["user_id"], session["work_days"]
    if before == data.work_days:
        return {"ok": True, "work_days": before}
    today = app_today()
    for r in db.query_all(
            """SELECT id FROM recurring_tasks WHERE user_id = %s AND COALESCE(freq, 'daily') = 'daily'
                  AND (active OR deactivated_at IS NOT NULL)""", (uid,)):
        snap = audit.recurring_snapshot(r["id"], uid)
        freeze = {"freq": "weekly", "weekdays": before}
        if snap["active"] and snap["created_at"].astimezone(app_tz()).date() < today:
            replace_routine(session, snap, {"label": snap["label"], "freq": "daily"}, freeze)
        elif not snap["active"]:
            db.execute("UPDATE recurring_tasks SET freq = 'weekly', weekdays = %s WHERE id = %s AND user_id = %s",
                       (before, r["id"], uid))
    db.execute("UPDATE users SET work_days = %s WHERE id = %s", (data.work_days, uid))
    audit.record(session, "settings.update", "user", uid,
                 before={"work_days": before}, after={"work_days": data.work_days})
    return {"ok": True, "work_days": data.work_days}
