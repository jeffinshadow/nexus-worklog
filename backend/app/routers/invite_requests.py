"""Pedido de convite: na tela de login (só com e-mail configurado), quem não
tem conta pede ao administrador. O pedido fica guardado, os admins recebem um
e-mail e uma notificação nos aparelhos, e ele aparece em Admin, onde o admin
convida (o convite por link de sempre) ou recusa.

Público e sem revelar nada: a resposta é a mesma com conta existente, pedido
já aberto ou e-mail novo; limites por IP e por e-mail e um campo-armadilha
para robôs. Quem pediu recebe a confirmação de que o pedido chegou; recusado,
nada é enviado.
"""
import logging
import threading

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import audit, db, mailer, people, push
from ..deps import client_ip, require_admin, require_admin_csrf
from ..schemas import InviteIn, InviteRequestIn
from ..security import invite_req_email_limiter, invite_req_limiter
from .admin import invite_user

log = logging.getLogger("uvicorn.error")
router = APIRouter(tags=["invite-requests"])

SOURCES = {"colega": "indicação de colega", "site": "site da ShadowTec", "github": "GitHub", "outro": "outro"}


def _mail_admins(req: dict) -> None:
    from ..notify import Mail
    admins = db.query_all("""SELECT u.id, u.email FROM users u
                              WHERE EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'admin')""")
    origem = SOURCES[req["source"]] + (f" ({req['source_note']})" if req.get("source_note") else "")
    for a in admins:
        try:
            m = Mail(f"Pedido de convite: {req['name']}", f"{req['name']} quer usar o Nexus",
                     "Um pedido de convite chegou pela tela de login. Convide ou recuse em Admin.")
            m.blocks = [("Quem pede", [req["name"], req["email"], f"Como conheceu: {origem}"]),
                        ("Por que gostaria de usar", [req["reason"]])]
            m.link, m.button = "/#/admin", "Abrir em Admin"
            m.reason, m.settings_tab = "Você recebe este e-mail porque é administrador do Nexus.", None
            mailer.send(a["email"], m.subject, m.text(), m.html())
        except Exception as e:  # noqa: BLE001 — um admin sem e-mail não impede os outros
            log.warning("aviso de pedido de convite para o admin %s falhou: %s", a["id"], e)
        try:
            push.send(a["id"], {"title": "Pedido de convite", "body": f"{req['name']} quer usar o Nexus",
                                "url": "/#/admin", "tag": f"convite-{req['id']}", "kind": "convite"}, urgency="normal", ttl=86400)
        except Exception:  # noqa: BLE001
            log.exception("notificação do pedido de convite falhou")


def _mail_requester(req: dict) -> None:
    from ..notify import Mail
    try:
        m = Mail("Recebemos o seu pedido de convite", f"Olá, {req['name']}",
                 "O seu pedido de acesso ao Nexus chegou ao administrador. Se ele aprovar, você recebe o convite "
                 "neste e-mail, com o link para criar a sua senha.")
        m.link, m.button = "/login", "Abrir o Nexus"
        m.reason, m.settings_tab = "Enviado porque este e-mail foi usado para pedir um convite na tela de login.", None
        mailer.send(req["email"], m.subject, m.text(), m.html())
    except Exception as e:  # noqa: BLE001
        log.warning("confirmação do pedido de convite falhou: %s", e)


@router.post("/api/auth/invite-request", status_code=202)
def request_invite(data: InviteRequestIn, request: Request):
    if not mailer.configured():
        raise HTTPException(status_code=404, detail="não disponível")
    email = data.email.lower()
    if not invite_req_limiter.allow(f"ip:{client_ip(request)}") or not invite_req_email_limiter.allow(f"em:{email}"):
        raise HTTPException(status_code=429, detail="muitos pedidos; tente mais tarde")
    resposta = {"ok": True}
    if data.website:  # campo escondido preenchido: robô
        return resposta
    if db.query_one("SELECT 1 FROM users WHERE email = %s", (email,)):
        return resposta  # já tem conta: mesma resposta (o "Esqueci a senha" resolve)
    row = db.query_one(
        """INSERT INTO invite_requests (name, email, source, source_note, reason) VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (lower(email)) WHERE status = 'pending' DO NOTHING RETURNING *""",
        (" ".join(data.name.split()), email, data.source, (data.source_note or "").strip() or None, data.reason.strip()))
    if row:
        threading.Thread(target=lambda: (_mail_admins(row), _mail_requester(row)), daemon=True).start()
    return resposta


@router.get("/api/admin/invite-requests")
def list_requests(admin=Depends(require_admin)):
    return db.query_all("""SELECT r.id, r.name, r.email, r.source, r.source_note, r.reason, r.status, r.created_at, r.decided_at,
                                  (SELECT 1 FROM users u WHERE u.email = r.email) IS NOT NULL AS has_account
                             FROM invite_requests r
                            WHERE r.status = 'pending' OR r.decided_at > now() - interval '30 days'
                            ORDER BY r.status <> 'pending', r.created_at DESC""")


def _decide(rid: int, status: str, admin: dict) -> dict:
    row = db.query_one("""UPDATE invite_requests SET status = %s, decided_at = now(), decided_by = %s
                           WHERE id = %s AND status = 'pending' RETURNING *""", (status, admin["user_id"], rid))
    if not row:
        raise HTTPException(status_code=404, detail="pedido não encontrado ou já decidido")
    audit.record({**admin, "actor": "admin"}, f"invite_request.{status}", "invite_request", rid,
                 after={"email": row["email"], "name": row["name"]})
    return row


@router.post("/api/admin/invite-requests/{rid}/invite")
def invite(rid: int, admin=Depends(require_admin_csrf)):
    req = db.query_one("SELECT * FROM invite_requests WHERE id = %s AND status = 'pending'", (rid,))
    if not req:
        raise HTTPException(status_code=404, detail="pedido não encontrado ou já decidido")
    out = invite_user(InviteIn(email=req["email"]), admin=admin)  # 409 se já tiver conta
    _decide(rid, "invited", admin)
    if req["name"]:  # o nome que a pessoa deu já fica na conta (ela pode trocar)
        db.execute("UPDATE users SET display_name = COALESCE(display_name, %s) WHERE email = %s", (req["name"][:60], req["email"]))
    return out


@router.post("/api/admin/invite-requests/{rid}/decline")
def decline(rid: int, admin=Depends(require_admin_csrf)):
    _decide(rid, "declined", admin)
    return {"ok": True}


def pending_count() -> int:
    return db.query_one("SELECT count(*)::int AS n FROM invite_requests WHERE status = 'pending'")["n"]
