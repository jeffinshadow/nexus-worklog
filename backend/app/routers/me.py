"""Perfil do próprio usuário (nome de exibição e foto) e o assistente.

Só pelo app (sessão + CSRF nas mudanças): chave de API não troca a foto de
ninguém. A foto é validada pelo CONTEÚDO, como o logo, mas só aceita PNG,
JPEG e WebP (nada de SVG, que pode carregar script).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from .. import audit, db, links, mailer, org, people, roles
from ..deps import clear_session_cookie
from ..security import login_limiter, verify_password
from ..deps import web_active, web_active_csrf
from ..schemas import (AssistantIn, ConsentIn, DefaultProjectIn, DeleteMeIn, EmailChangeIn, ProfileIn, ThemeIn,
                       TicketUrlIn, TourIn)
from ..services import running_timer
from ..visibility import visible_sql

router = APIRouter(prefix="/api/me", tags=["me"])

MAX_AVATAR_BYTES = 256 * 1024


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.put("/profile")
def put_profile(data: ProfileIn, user=Depends(web_active_csrf)):
    org.ensure_identity_editable()  # "Nome e e-mail definidos pela administração": só o admin muda
    uid = user["user_id"]
    before = people.profile(uid)["display_name"]
    name = " ".join(data.display_name.split()) if data.display_name else None  # sem espaços duplicados
    db.execute("UPDATE users SET display_name = %s WHERE id = %s", (name or None, uid))
    audit.record(user, "profile.update", "user", uid, before={"display_name": before}, after={"display_name": name})
    return people.profile(uid)


def _confirm_mail(new: str, link: str):
    from ..notify import Mail  # import tardio: notify importa rotas
    m = Mail("Confirme o seu e-mail novo no Nexus", "Confirme o e-mail novo",
             "Alguém (provavelmente você) pediu para usar este endereço na conta do Nexus. "
             "O e-mail só muda depois que você confirmar. O link vale por 24 horas e funciona uma vez só.")
    m.blocks = [("Não foi você?", ["Pode ignorar este e-mail: nada muda sem a confirmação."])]
    m.link, m.absolute, m.button = link, True, "Confirmar o e-mail novo"
    m.reason, m.settings_tab = f"Enviado para {new} a pedido de Configurações > Conta.", None
    return m


@router.post("/email")
def request_email_change(data: EmailChangeIn, user=Depends(web_active_csrf)):
    """Trocar o próprio e-mail: pede a senha atual e manda um link de
    confirmação ao endereço NOVO (24 horas, uso único). O e-mail só muda quando
    a pessoa confirma (POST /api/auth/email/confirm); o antigo recebe um aviso.
    Bloqueado quando a administração define nome e e-mail."""
    org.ensure_identity_editable()
    uid = user["user_id"]
    if not mailer.configured():
        raise HTTPException(status_code=400, detail="o servidor não manda e-mail: peça a troca a quem administra o Nexus")
    if not login_limiter.allow(f"pw:{uid}"):  # sessão roubada não testa senhas à vontade
        raise HTTPException(status_code=429, detail="muitas tentativas, tente mais tarde")
    row = db.query_one("SELECT email, password_hash FROM users WHERE id = %s", (uid,))
    if not row or not verify_password(row["password_hash"], data.password):
        raise HTTPException(status_code=400, detail="senha atual incorreta")
    new = data.new_email.lower()
    if new == row["email"]:
        raise HTTPException(status_code=400, detail="esse já é o e-mail da sua conta")
    if db.query_one("SELECT 1 FROM users WHERE email = %s", (new,)):
        raise HTTPException(status_code=409, detail="esse e-mail já é de outra conta")
    link = links.url("email", links.issue(uid, "email", new_email=new))
    m = _confirm_mail(new, link)
    try:
        mailer.send(new, m.subject, m.text(), m.html())
    except mailer.MailError as e:
        links.cancel(uid, "email")
        logging.getLogger("uvicorn.error").warning("confirmação de e-mail não saiu: %s", e)
        raise HTTPException(status_code=502, detail="não foi possível mandar o e-mail de confirmação: tente de novo mais tarde") from e
    audit.record(user, "email.change_request", "user", uid, before={"email": row["email"]}, after={"email": new})
    return {"email_pending": new}


@router.delete("/email")
def cancel_email_change(user=Depends(web_active_csrf)):
    """Desiste da troca pendente: o link mandado ao endereço novo deixa de valer."""
    links.cancel(user["user_id"], "email")
    return {"email_pending": None}


@router.post("/avatar")
async def upload_avatar(request: Request, user=Depends(web_active_csrf)):
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="arquivo vazio")
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail="foto acima de 256 KB")
    mime = _sniff(data)
    if not mime:
        raise HTTPException(status_code=415, detail="use uma foto PNG, JPEG ou WebP")
    db.execute(
        """INSERT INTO user_avatars (user_id, image, mime) VALUES (%s, %s, %s)
           ON CONFLICT (user_id) DO UPDATE SET image = EXCLUDED.image, mime = EXCLUDED.mime, updated_at = now()""",
        (user["user_id"], data, mime),
    )
    audit.record(user, "profile.avatar", "user", user["user_id"], after={"mime": mime, "bytes": len(data)})
    return people.profile(user["user_id"])


@router.delete("/avatar")
def delete_avatar(user=Depends(web_active_csrf)):
    db.execute("DELETE FROM user_avatars WHERE user_id = %s", (user["user_id"],))
    audit.record(user, "profile.avatar_reset", "user", user["user_id"])
    return people.profile(user["user_id"])


def _avatar_visible(user: dict, user_id: int) -> bool:
    """A própria foto e, para o admin, a de todos. Visualizador e atribuidor só
    veem a foto de quem aparece nas listas deles (o mesmo aceite de viewer.py e
    assign.list_people): papel Usuário e, conforme o papel, aceitou ser visto ou
    aceitou receber tarefas (e não está bloqueado). O resto: 404, como sem foto."""
    roles = set(user.get("roles") or [])
    if user_id == user["user_id"] or "admin" in roles:
        return True
    conds = []
    if "viewer" in roles:
        conds.append(visible_sql("u"))
    if "assigner" in roles:
        conds.append("(u.accepts_assignments_at IS NOT NULL AND u.blocked_at IS NULL)")
    if not conds:
        return False
    return bool(db.query_one(
        f"""SELECT 1 FROM users u WHERE u.id = %(id)s
              AND EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'user')
              AND ({' OR '.join(conds)})""", {"id": user_id}))


@router.get("/avatar/{user_id}")
def get_avatar(user_id: int, user=Depends(web_active)):
    if not _avatar_visible(user, user_id):
        raise HTTPException(status_code=404, detail="sem foto")
    r = db.query_one("SELECT image, mime FROM user_avatars WHERE user_id = %s", (user_id,))
    if not r:
        raise HTTPException(status_code=404, detail="sem foto")
    return Response(
        content=bytes(r["image"]),
        media_type=r["mime"],
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.put("/assistant")
def put_assistant(data: AssistantIn, user=Depends(web_active_csrf)):
    uid = user["user_id"]
    before = people.assistant_prefs(uid)
    db.execute(
        """INSERT INTO assistant_prefs (user_id, enabled, idle_on, idle_minutes, idle_start, idle_end,
                                        reopen_on, reopen_minutes, summary_from, stale_days)
           VALUES (%(uid)s, %(enabled)s, %(idle_on)s, %(idle_minutes)s, %(idle_start)s, %(idle_end)s,
                   %(reopen_on)s, %(reopen_minutes)s, %(summary_from)s, %(stale_days)s)
           ON CONFLICT (user_id) DO UPDATE SET
             enabled = EXCLUDED.enabled, idle_on = EXCLUDED.idle_on, idle_minutes = EXCLUDED.idle_minutes,
             idle_start = EXCLUDED.idle_start, idle_end = EXCLUDED.idle_end,
             reopen_on = EXCLUDED.reopen_on, reopen_minutes = EXCLUDED.reopen_minutes,
             summary_from = EXCLUDED.summary_from, stale_days = EXCLUDED.stale_days, updated_at = now()""",
        {"uid": uid, **data.model_dump()},
    )
    audit.record(user, "assistant.update", "assistant", uid, before=before, after=data.model_dump())
    return people.assistant_prefs(uid)


@router.get("/visibility")
def visibility(user=Depends(web_active)):
    """Quem, além da pessoa, tem papel que alcança o registro dela (Configurações >
    Conta): visualizador (registro, relatórios e fotos de quem aceitou, ver
    PUT /me/viewers) e admin (que concede papéis). Só nome e papel; sem e-mail."""
    rows = db.query_all(
        """SELECT u.email, u.display_name, array_agg(r.role ORDER BY r.role) AS roles
             FROM users u JOIN user_roles r ON r.user_id = u.id
            WHERE r.role IN ('admin', 'viewer') AND u.id <> %s
            GROUP BY u.id ORDER BY lower(COALESCE(u.display_name, u.email))""",
        (user["user_id"],),
    )
    return [{"name": r["display_name"] or people.name_from_email(r["email"]), "roles": r["roles"]} for r in rows]


@router.get("/activity")
def activity(user=Depends(web_active)):
    """Último registro (de qualquer origem): o lembrete de inatividade confere
    aqui antes de avisar, para não cobrar quem registrou pela IA ou no celular."""
    # Com o cronômetro rodando a pessoa está trabalhando: o lembrete não cobra.
    return {"last_activity": people.last_activity(user["user_id"]), "timer": running_timer(user["user_id"])}


@router.put("/tickets")
def put_ticket_url(data: TicketUrlIn, user=Depends(web_active_csrf)):
    """Endereço do sistema de chamados; {id} vira o número (sem {id}, o número vai no fim).
    Com o endereço definido pela administração (Admin › Para empresas), 409: o
    da instância vale para todos; o da pessoa fica guardado e volta a valer se
    o admin esvaziar o global."""
    if org.get()["ticket_url"]:
        raise HTTPException(status_code=409, detail=TICKETS_BY_ADMIN)
    url = (data.ticket_url or "").strip() or None
    db.execute("UPDATE users SET ticket_url = %s WHERE id = %s", (url, user["user_id"]))
    audit.record(user, "tickets.update", "user", user["user_id"], after={"ticket_url": url})
    return {"ticket_url": url, "ticket_url_managed": False}


TICKETS_BY_ADMIN = ("Nesta instância do Nexus, o endereço do sistema de chamados é definido pela administração "
                    "e vale para todos. Para mudar, fale com quem administra.")


@router.put("/default-project")
def put_default_project(data: DefaultProjectIn, user=Depends(web_active_csrf)):
    """Projeto aplicado à tarefa criada sem projeto (no app, pela API, pela IA
    ou recebida por atribuição). Só projeto ativo da própria pessoa."""
    uid = user["user_id"]
    if data.project_id is not None and not db.query_one(
            "SELECT 1 FROM projects WHERE id = %s AND user_id = %s AND NOT archived", (data.project_id, uid)):
        raise HTTPException(status_code=400, detail="projeto não encontrado")
    before = db.query_one("SELECT default_project_id FROM users WHERE id = %s", (uid,))["default_project_id"]
    db.execute("UPDATE users SET default_project_id = %s WHERE id = %s", (data.project_id, uid))
    if before != data.project_id:
        audit.record(user, "default_project.update", "user", uid,
                     before={"default_project_id": before}, after={"default_project_id": data.project_id})
    return {"default_project_id": data.project_id}


@router.put("/theme")
def put_theme(data: ThemeIn, user=Depends(web_active_csrf)):
    """Tema da interface (auto = o do aparelho). Vale em todos os aparelhos da conta."""
    db.execute("UPDATE users SET theme = %s WHERE id = %s", (data.theme, user["user_id"]))
    return {"theme": data.theme}


@router.put("/tour")
def put_tour(data: TourIn, user=Depends(web_active_csrf)):
    """Tour guiado visto (ou pulado, quando não é obrigatório). false = abre de
    novo no próximo acesso. Concluído uma vez, o primeiro acesso acabou: o tour
    obrigatório nunca mais força esta conta. Quem passou pelo tour já viu a
    parada da visibilidade (quando ativa): o aviso único não aparece depois."""
    row = db.query_one(
        """UPDATE users SET tour_done_at = CASE WHEN %(d)s THEN now() END,
                            tour_first_access = CASE WHEN %(d)s THEN false ELSE tour_first_access END,
                            visibility_notice_at = CASE WHEN %(d)s AND EXISTS (SELECT 1 FROM app_settings
                                 WHERE id = 1 AND team_visibility = 'managers') THEN now() ELSE visibility_notice_at END
            WHERE id = %(u)s RETURNING tour_done_at""",
        {"d": data.done, "u": user["user_id"]})
    return {"tour_done_at": row["tour_done_at"], **{k: v for k, v in org.for_user(user["user_id"]).items()
                                                   if k in ("tour_required", "visibility_notice")}}


@router.put("/visibility-notice")
def seen_visibility_notice(user=Depends(web_active_csrf)):
    """"Entendi" no aviso único de que quem gerencia a equipe vê o registro de todos."""
    db.execute("UPDATE users SET visibility_notice_at = now() WHERE id = %s", (user["user_id"],))
    return {"visibility_notice": False}


@router.put("/role-notice")
def seen_role_notice(user=Depends(web_active_csrf)):
    """"Entendi" no aviso único de papel ganho ou retirado pelo admin."""
    db.execute("UPDATE users SET role_notice = NULL WHERE id = %s", (user["user_id"],))
    return {"role_notice": None}


@router.put("/assignments")
def put_assignments(data: ConsentIn, user=Depends(web_active_csrf)):
    """Consentimento para receber tarefas de um atribuidor (só pelo app).
    Desligar não mexe nas tarefas já recebidas."""
    uid = user["user_id"]
    before = db.query_one("SELECT accepts_assignments_at FROM users WHERE id = %s", (uid,))["accepts_assignments_at"]
    if data.accept and before is None:
        db.execute("UPDATE users SET accepts_assignments_at = now() WHERE id = %s", (uid,))
    elif not data.accept and before is not None:
        db.execute("UPDATE users SET accepts_assignments_at = NULL WHERE id = %s", (uid,))
    after = db.query_one("SELECT accepts_assignments_at FROM users WHERE id = %s", (uid,))["accepts_assignments_at"]
    if (before is None) != (after is None):
        audit.record(user, "assignments.consent", "user", uid,
                     before={"accept": before is not None}, after={"accept": after is not None})
    return {"accepts_assignments_at": after}


@router.put("/viewers")
def put_viewers(data: ConsentIn, user=Depends(web_active_csrf)):
    """Aceite do visualizador (só pelo app): com ele, quem tem o papel viewer vê
    o registro da pessoa em Equipe (quadro, números, PDF, horas, fotos)."""
    if org.get()["team_visibility"] == "managers":
        # A escolha fica guardada como está e volta a valer quando a administração
        # voltar para "Cada pessoa escolhe"; enquanto isso, não muda.
        raise HTTPException(status_code=409, detail=org.VISIBILITY_LOCKED + " A sua escolha fica guardada e volta a valer se isso mudar.")
    uid = user["user_id"]
    before = db.query_one("SELECT viewers_allowed FROM users WHERE id = %s", (uid,))["viewers_allowed"]
    db.execute("UPDATE users SET viewers_allowed = %s WHERE id = %s", (data.accept, uid))
    if before != data.accept:
        audit.record(user, "viewers.consent", "user", uid, before={"accept": before}, after={"accept": data.accept})
    return {"viewers_allowed": data.accept}


@router.post("/delete")
def delete_me(data: DeleteMeIn, response: Response, user=Depends(web_active_csrf)):
    """A própria pessoa exclui a conta e todos os dados dela (LGPD), com a
    senha. Sem volta; exporte antes em Relatórios. O último admin não sai."""
    uid = user["user_id"]
    if not login_limiter.allow(f"pw:{uid}"):  # sessão roubada não testa senhas à vontade
        raise HTTPException(status_code=429, detail="muitas tentativas, tente mais tarde")
    row = db.query_one("SELECT password_hash FROM users WHERE id = %s", (uid,))
    if not row or not verify_password(row["password_hash"], data.password):
        raise HTTPException(status_code=400, detail="senha incorreta")
    if "admin" in user["roles"] and roles.admins_count() <= 1:
        raise HTTPException(status_code=400, detail="você é o único admin: dê o papel de admin a outra pessoa antes")
    if not roles.delete_account(uid):
        raise HTTPException(status_code=400, detail="você é o único admin: dê o papel de admin a outra pessoa antes")
    logging.getLogger("uvicorn.error").info("conta %s excluída pela própria pessoa", uid)
    clear_session_cookie(response)
    return {"ok": True}
