"""Perfil do próprio usuário (nome de exibição e foto) e o assistente.

Só pelo app (sessão + CSRF nas mudanças): chave de API não troca a foto de
ninguém. A foto é validada pelo CONTEÚDO, como o logo, mas só aceita PNG,
JPEG e WebP (nada de SVG, que pode carregar script).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from .. import audit, db, people
from ..deps import web_active, web_active_csrf
from ..schemas import AssistantIn, ProfileIn

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
    # A própria foto; o admin vê a de todos (lista de usuários).
    if user_id != user["user_id"] and user["role"] != "admin":
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
        """INSERT INTO assistant_prefs (user_id, enabled, idle_on, idle_minutes, idle_start, idle_end)
           VALUES (%(uid)s, %(enabled)s, %(idle_on)s, %(idle_minutes)s, %(idle_start)s, %(idle_end)s)
           ON CONFLICT (user_id) DO UPDATE SET
             enabled = EXCLUDED.enabled, idle_on = EXCLUDED.idle_on, idle_minutes = EXCLUDED.idle_minutes,
             idle_start = EXCLUDED.idle_start, idle_end = EXCLUDED.idle_end, updated_at = now()""",
        {"uid": uid, **data.model_dump()},
    )
    audit.record(user, "assistant.update", "assistant", uid, before=before, after=data.model_dump())
    return people.assistant_prefs(uid)


@router.get("/activity")
def activity(user=Depends(web_active)):
    """Último registro (de qualquer origem): o lembrete de inatividade confere
    aqui antes de avisar, para não cobrar quem registrou pela IA ou no celular."""
    return {"last_activity": people.last_activity(user["user_id"])}
