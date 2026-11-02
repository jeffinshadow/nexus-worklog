"""Fotos na tarefa e como evidência da rotina.

O navegador já manda a foto reduzida (lado maior 1600 px) e regravada (WebP,
ou JPEG onde não há WebP), o que apaga EXIF e GPS, e a miniatura junto: aqui
só se confere o tipo pelo conteúdo, os limites e a cota. As fotos ficam no
banco (o backup leva) e saem só por esta API, com sessão: a dona e quem tem o
papel de visualizador. Excluir é desfazível (deleted_at); a faxina leva de vez
depois de 7 dias, junto com as de tarefas excluídas e não recuperadas.
"""
import base64
import binascii
import re
import tempfile
import zipfile
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field

from .. import audit, db
from ..config import config
from ..visibility import visible_sql
from ..deps import web_active, web_active_csrf
from .board import check_board_day
from .me import _sniff
from .worklog import device_time

router = APIRouter(prefix="/api", tags=["photos"])

MAX_BYTES = 1024 * 1024        # 1 MB por foto (já reduzida no navegador)
MAX_THUMB = 96 * 1024
MAX_PER_ITEM = 10              # por tarefa, ou por rotina num dia
UNDO_DAYS = 7


class PhotoIn(BaseModel):
    image: str = Field(min_length=100, max_length=1_400_000)   # base64
    thumb: str = Field(min_length=50, max_length=130_000)
    width: Optional[int] = Field(default=None, ge=1, le=10000)
    height: Optional[int] = Field(default=None, ge=1, le=10000)
    at: Optional[datetime] = None  # hora do aparelho (tirada sem sinal, enviada depois); até 24 h atrás
    # Idempotência (como nas anotações): reenviar com a mesma chave devolve a foto que já existe (200).
    external_ref: Optional[str] = Field(default=None, min_length=1, max_length=120)


def _decode(text: str, limit: int, what: str) -> tuple[bytes, str]:
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail=f"{what} ilegível") from None
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"{what} acima de {limit // 1024} KB")
    mime = _sniff(data)
    if not mime:
        raise HTTPException(status_code=415, detail="use uma foto PNG, JPEG ou WebP")
    return data, mime


def _quota(uid: int, extra: int) -> None:
    quota = config.PHOTO_QUOTA_MB * 1024 * 1024
    used = db.query_one("SELECT COALESCE(sum(bytes), 0)::bigint AS n FROM photos WHERE user_id = %s AND deleted_at IS NULL",
                        (uid,))["n"]
    if used + extra > quota:
        raise HTTPException(status_code=413, detail="o espaço de fotos da sua conta está cheio; exclua fotos antigas ou fale com o admin")


def _by_ref(uid: int, ref):
    return ref and db.query_one("SELECT id, width, height, created_at FROM photos WHERE user_id = %s AND external_ref = %s",
                                (uid, ref))


def _store(user: dict, data: PhotoIn, task_id: int | None = None, recurring_id: int | None = None, day: date | None = None,
           response: Response | None = None) -> dict:
    uid = user["user_id"]
    ref = (data.external_ref or "").strip() or None
    if found := _by_ref(uid, ref):
        if response is not None:
            response.status_code = 200
        return {**found, "existing": True}
    image, mime = _decode(data.image, MAX_BYTES, "foto")
    thumb, _ = _decode(data.thumb, MAX_THUMB, "miniatura")
    where, params = ("task_id = %s", (task_id,)) if task_id else ("recurring_id = %s AND day = %s", (recurring_id, day))
    n = db.query_one(f"SELECT count(*)::int AS n FROM photos WHERE user_id = %s AND deleted_at IS NULL AND {where}",
                     (uid, *params))["n"]
    if n >= MAX_PER_ITEM:
        raise HTTPException(status_code=409, detail=f"até {MAX_PER_ITEM} fotos em cada tarefa ou rotina do dia")
    _quota(uid, len(image) + len(thumb))
    try:
        row = db.query_one(
            """INSERT INTO photos (user_id, task_id, recurring_id, day, mime, image, thumb, width, height, bytes, created_at, external_ref)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now()), %s)
               RETURNING id, width, height, created_at""",
            (uid, task_id, recurring_id, day, mime, image, thumb, data.width, data.height, len(image) + len(thumb),
             device_time(data.at, "a foto"), ref))
    except UniqueViolation:  # duas chamadas iguais ao mesmo tempo: a segunda devolve a primeira
        if response is not None:
            response.status_code = 200
        return {**_by_ref(uid, ref), "existing": True}
    audit.record(user, "photo.create", "photo", row["id"],
                 after={"task_id": task_id, "recurring_id": recurring_id, "day": day, "bytes": len(image)})
    return row


@router.post("/worklog/{task_id}/photos", status_code=201)
def add_to_task(task_id: int, data: PhotoIn, response: Response, user=Depends(web_active_csrf)):
    if not db.query_one("SELECT 1 FROM worklog_tasks WHERE id = %s AND user_id = %s", (task_id, user["user_id"])):
        raise HTTPException(status_code=404, detail="tarefa não encontrada")
    return _store(user, data, task_id=task_id, response=response)


@router.post("/recurring/{recurring_id}/photos", status_code=201)
def add_to_routine(recurring_id: int, data: PhotoIn, response: Response, day: Optional[date] = None, user=Depends(web_active_csrf)):
    from ..services import app_today
    if not db.query_one("SELECT 1 FROM recurring_tasks WHERE id = %s AND user_id = %s", (recurring_id, user["user_id"])):
        raise HTTPException(status_code=404, detail="rotina não encontrada")
    return _store(user, data, recurring_id=recurring_id, day=check_board_day(day) or app_today(), response=response)


def for_task(uid: int, task_id: int) -> list[dict]:
    return db.query_all("""SELECT id, width, height, created_at FROM photos
                            WHERE user_id = %s AND task_id = %s AND deleted_at IS NULL ORDER BY created_at, id""", (uid, task_id))


@router.get("/recurring/{recurring_id}/photos")
def list_routine(recurring_id: int, day: date, user=Depends(web_active)):
    return db.query_all("""SELECT id, width, height, created_at FROM photos
                            WHERE user_id = %s AND recurring_id = %s AND day = %s AND deleted_at IS NULL
                            ORDER BY created_at, id""", (user["user_id"], recurring_id, day))


@router.get("/photos/{photo_id}")
def get_photo(photo_id: int, thumb: bool = False, user=Depends(web_active)):
    # Foto de outra pessoa: só o visualizador, e só se ela aceitou (como em routers/viewer.py).
    row = db.query_one(f"""SELECT f.user_id, f.mime, f.{'thumb' if thumb else 'image'} AS data,
                                  {visible_sql('u', int(user['user_id']))} AS viewable
                             FROM photos f JOIN users u ON u.id = f.user_id
                            WHERE f.id = %s AND f.deleted_at IS NULL""", (photo_id,))
    if not row or (row["user_id"] != user["user_id"]
                   and not ("viewer" in (user.get("roles") or []) and row["viewable"])):
        raise HTTPException(status_code=404, detail="foto não encontrada")
    data = bytes(row["data"])
    # O conteúdo de um id nunca muda, mas é evidência de cliente: o navegador guarda
    # só por um dia (só para esta pessoa), e não fica no aparelho depois de sair.
    return Response(content=data, media_type=_sniff(data) or row["mime"],
                    headers={"Cache-Control": "private, max-age=86400"})


@router.delete("/photos/{photo_id}")
def delete_photo(photo_id: int, user=Depends(web_active_csrf)):
    row = db.query_one("""UPDATE photos SET deleted_at = now() WHERE id = %s AND user_id = %s AND deleted_at IS NULL
                          RETURNING task_id, recurring_id, day""", (photo_id, user["user_id"]))
    if not row:
        raise HTTPException(status_code=404, detail="foto não encontrada")
    audit.record(user, "photo.delete", "photo", photo_id, before=dict(row))
    return {"ok": True}


def restore(uid: int, photo_id: int) -> bool:
    return bool(db.execute("UPDATE photos SET deleted_at = NULL WHERE id = %s AND user_id = %s", (photo_id, uid)))


def soft_delete(uid: int, photo_id: int) -> bool:
    return bool(db.execute("UPDATE photos SET deleted_at = now() WHERE id = %s AND user_id = %s AND deleted_at IS NULL",
                           (photo_id, uid)))


def cleanup() -> None:
    """Faxina (uma vez por hora, no agendador): excluídas há mais de 7 dias e as
    de tarefas que não existem mais nem podem voltar pelo desfazer."""
    db.execute("DELETE FROM photos WHERE deleted_at < now() - make_interval(days => %s)", (UNDO_DAYS,))
    db.execute(
        """DELETE FROM photos p WHERE p.task_id IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM worklog_tasks w WHERE w.id = p.task_id)
             AND NOT EXISTS (SELECT 1 FROM audit_log a WHERE a.entity = 'worklog' AND a.entity_id = p.task_id
                               AND a.action = 'worklog.delete' AND a.created_at > now() - make_interval(days => %s))""",
        (UNDO_DAYS,))


# ------------------------------------------------------------- exportação --

def _slug(text: str) -> str:
    return (re.sub(r"[^\w\-]+", "-", text, flags=re.UNICODE).strip("-")[:50] or "sem-nome").lower()


@router.get("/export/fotos.zip")
def export_zip(user=Depends(web_active)):
    """Todas as fotos da conta num .zip (pastas por tarefa e por rotina). Monta
    num arquivo temporário, uma foto por vez (a memória do backend é pequena)."""
    uid = user["user_id"]
    ids = db.query_all("""SELECT p.id, p.mime, p.day, p.task_id, w.title, r.label FROM photos p
                            LEFT JOIN worklog_tasks w ON w.id = p.task_id
                            LEFT JOIN recurring_tasks r ON r.id = p.recurring_id
                           WHERE p.user_id = %s AND p.deleted_at IS NULL ORDER BY p.id""", (uid,))
    if not ids:
        raise HTTPException(status_code=404, detail="nenhuma foto na conta")
    tmp = tempfile.TemporaryFile()
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:  # fotos já são comprimidas
        for p in ids:
            ext = {"image/webp": "webp", "image/jpeg": "jpg", "image/png": "png"}[p["mime"]]
            folder = (f"tarefa-{p['task_id']}-{_slug(p['title'] or '')}" if p["task_id"]
                      else f"rotina-{_slug(p['label'] or '')}")
            name = f"{p['day']}-{p['id']}.{ext}" if p["day"] else f"{p['id']}.{ext}"
            data = db.query_one("SELECT image FROM photos WHERE id = %s", (p["id"],))["image"]
            z.writestr(f"{folder}/{name}", bytes(data))
    tmp.seek(0)

    def chunks():
        try:
            while block := tmp.read(256 * 1024):
                yield block
        finally:
            tmp.close()
    return StreamingResponse(chunks(), media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="nexus-fotos.zip"'})
