"""Notificações do sistema: aparelhos, preferências e teste (ver app/push.py).
Só pela sessão do app (chave de API não liga notificação de aparelho)."""
import threading

from fastapi import APIRouter, Depends, HTTPException

from .. import db, push
from ..deps import web_active, web_active_csrf
from ..schemas import PushDeviceIn, PushPrefsIn

router = APIRouter(prefix="/api/push", tags=["push"])


@router.get("")
def overview(endpoint: str | None = None, user=Depends(web_active)):
    """Chave pública, preferências e os aparelhos ligados (current = este, pelo endpoint)."""
    devices = db.query_all(
        """SELECT id, label, created_at, last_ok_at, failures, endpoint = %s AS current
             FROM push_subscriptions WHERE user_id = %s ORDER BY created_at""", (endpoint or "", user["user_id"]))
    return {"public_key": push.public_key(), "prefs": push.prefs(user["user_id"]), "devices": devices}


@router.post("/devices", status_code=201)
def add_device(data: PushDeviceIn, user=Depends(web_active_csrf)):
    if not push.endpoint_ok(data.endpoint):
        raise HTTPException(status_code=400, detail="serviço de notificação não reconhecido")
    if not push.keys_ok(data.keys.p256dh, data.keys.auth):
        raise HTTPException(status_code=400, detail="chaves da inscrição inválidas")
    # O mesmo navegador com outra conta: o aparelho passa para quem entrou agora.
    row = db.query_one(
        """INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, label) VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (endpoint) DO UPDATE SET user_id = EXCLUDED.user_id, p256dh = EXCLUDED.p256dh,
                  auth = EXCLUDED.auth, label = EXCLUDED.label, last_seen_at = now(), failures = 0
           RETURNING id""",
        (user["user_id"], data.endpoint, data.keys.p256dh, data.keys.auth, data.label))
    return {"id": row["id"]}


@router.delete("/devices/{device_id}")
def remove_device(device_id: int, user=Depends(web_active_csrf)):
    if not db.execute("DELETE FROM push_subscriptions WHERE id = %s AND user_id = %s", (device_id, user["user_id"])):
        raise HTTPException(status_code=404, detail="aparelho não encontrado")
    return {"ok": True}


@router.put("/prefs")
def put_prefs(data: PushPrefsIn, user=Depends(web_active_csrf)):
    v = data.model_dump()
    db.execute(
        """INSERT INTO push_prefs (user_id, routine, follow_up, deadline, assigned, morning_hour, hide_content)
           VALUES (%(uid)s, %(routine)s, %(follow_up)s, %(deadline)s, %(assigned)s, %(morning_hour)s, %(hide_content)s)
           ON CONFLICT (user_id) DO UPDATE SET routine = EXCLUDED.routine, follow_up = EXCLUDED.follow_up,
                  deadline = EXCLUDED.deadline, assigned = EXCLUDED.assigned, morning_hour = EXCLUDED.morning_hour,
                  hide_content = EXCLUDED.hide_content, updated_at = now()""", {"uid": user["user_id"], **v})
    return push.prefs(user["user_id"])


@router.post("/test")
def test(device_id: int | None = None, user=Depends(web_active_csrf)):
    if not db.query_one("SELECT 1 FROM push_subscriptions WHERE user_id = %s" + (" AND id = %s" if device_id else ""),
                        (user["user_id"], device_id) if device_id else (user["user_id"],)):
        raise HTTPException(status_code=404, detail="nenhum aparelho com as notificações ligadas")
    msg = {"title": "Notificações ligadas", "body": "É assim que o Nexus vai avisar neste aparelho.",
           "url": "/#/config?aba=avisos", "tag": "teste", "kind": "teste"}
    sent = push.send(user["user_id"], msg, urgency="high", ttl=600, only_id=device_id)
    if not sent:
        raise HTTPException(status_code=502, detail="o serviço de notificação do aparelho não aceitou; tente ligar de novo")
    return {"sent": sent}


def spawn(fn, *args) -> None:
    """Envio fora da requisição (a rede pode levar segundos)."""
    threading.Thread(target=fn, args=args, daemon=True).start()
