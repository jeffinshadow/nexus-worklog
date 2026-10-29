"""Perfil do próprio usuário (nome de exibição e foto) e o assistente.

Só pelo app (sessão + CSRF nas mudanças): chave de API não troca a foto de
ninguém. A foto é validada pelo CONTEÚDO, como o logo, mas só aceita PNG,
JPEG e WebP (nada de SVG, que pode carregar script).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from .. import audit, db, people, roles
from ..deps import clear_session_cookie
from ..security import login_limiter, verify_password
from ..deps import web_active, web_active_csrf
from ..schemas import AssistantIn, ConsentIn, DefaultProjectIn, DeleteMeIn, ProfileIn, TicketUrlIn, TourIn
from ..services import running_timer

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
    uid = user["user_id"]
    before = people.profile(uid)["display_name"]
    name = " ".join(data.display_name.split()) if data.display_name else None  # sem espaços duplicados
    db.execute("UPDATE users SET display_name = %s WHERE id = %s", (name or None, uid))
    audit.record(user, "profile.update", "user", uid, before={"display_name": before}, after={"display_name": name})
    return people.profile(uid)


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


@router.get("/avatar/{user_id}")
def get_avatar(user_id: int, user=Depends(web_active)):
    # A própria foto; admin, visualizador e atribuidor veem a de todos (listas de pessoas).
    if user_id != user["user_id"] and not set(user["roles"]) & {"admin", "viewer", "assigner"}:
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
                                        reopen_on, reopen_minutes, summary_from)
           VALUES (%(uid)s, %(enabled)s, %(idle_on)s, %(idle_minutes)s, %(idle_start)s, %(idle_end)s,
                   %(reopen_on)s, %(reopen_minutes)s, %(summary_from)s)
           ON CONFLICT (user_id) DO UPDATE SET
             enabled = EXCLUDED.enabled, idle_on = EXCLUDED.idle_on, idle_minutes = EXCLUDED.idle_minutes,
             idle_start = EXCLUDED.idle_start, idle_end = EXCLUDED.idle_end,
             reopen_on = EXCLUDED.reopen_on, reopen_minutes = EXCLUDED.reopen_minutes,
             summary_from = EXCLUDED.summary_from, updated_at = now()""",
        {"uid": uid, **data.model_dump()},
    )
    audit.record(user, "assistant.update", "assistant", uid, before=before, after=data.model_dump())
    return people.assistant_prefs(uid)


@router.get("/activity")
def activity(user=Depends(web_active)):
    """Último registro (de qualquer origem): o lembrete de inatividade confere
    aqui antes de avisar, para não cobrar quem registrou pela IA ou no celular."""
    # Com o cronômetro rodando a pessoa está trabalhando: o lembrete não cobra.
    return {"last_activity": people.last_activity(user["user_id"]), "timer": running_timer(user["user_id"])}


@router.put("/tickets")
def put_ticket_url(data: TicketUrlIn, user=Depends(web_active_csrf)):
    """Endereço do sistema de chamados; {id} vira o número (sem {id}, o número vai no fim)."""
    url = (data.ticket_url or "").strip() or None
    db.execute("UPDATE users SET ticket_url = %s WHERE id = %s", (url, user["user_id"]))
    audit.record(user, "tickets.update", "user", user["user_id"], after={"ticket_url": url})
    return {"ticket_url": url}


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


@router.put("/tour")
def put_tour(data: TourIn, user=Depends(web_active_csrf)):
    """Tour guiado visto (ou pulado). false = abre de novo no próximo acesso."""
    row = db.query_one("UPDATE users SET tour_done_at = CASE WHEN %s THEN now() END WHERE id = %s RETURNING tour_done_at",
                       (data.done, user["user_id"]))
    return {"tour_done_at": row["tour_done_at"]}


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
