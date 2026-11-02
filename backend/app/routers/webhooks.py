"""Webhooks de saída: cadastro (a entrega fica em app/webhooks.py).

Cadastrar e religar só pelo app (sessão + CSRF): uma chave de API vazada não
abre um canal permanente para fora (revogar a chave não desligaria o webhook).
Testar (ping) e editar também só pelo app. Listar e apagar também por chave. O segredo aparece uma vez, na criação.
"""
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db, webhooks
from ..deps import active_user, active_user_csrf, web_active_csrf
from ..schemas import WebhookIn, WebhookUpdate
from ..security import webhook_test_limiter

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

COLS = ("id, url, events, created_at, last_delivered_at, last_event_id, failures, last_error, "
        "next_attempt_at, disabled_at, (disabled_at IS NULL) AS active")


@router.get("")
def list_webhooks(user=Depends(active_user)):
    return db.query_all(f"SELECT {COLS} FROM webhooks WHERE user_id = %s ORDER BY created_at DESC, id DESC",
                        (user["user_id"],))


@router.post("", status_code=201)
def create_webhook(data: WebhookIn, user=Depends(web_active_csrf)):
    uid = user["user_id"]
    if db.query_one("SELECT count(*) AS n FROM webhooks WHERE user_id = %s", (uid,))["n"] >= webhooks.MAX_PER_USER:
        raise HTTPException(status_code=409, detail=f"limite de {webhooks.MAX_PER_USER} webhooks; apague algum")
    try:
        webhooks.check_url(data.url)
    except webhooks.Refused as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    salt = webhooks.new_salt()
    # Começa do agora: o que já aconteceu antes não é reenviado (o feed tem o passado).
    row = db.query_one(
        f"""INSERT INTO webhooks (user_id, url, events, secret_salt, last_event_id)
            VALUES (%s, %s, %s, %s, (SELECT COALESCE(max(id), 0) FROM audit_log))
         RETURNING {COLS}""",
        (uid, data.url, data.events, salt),
    )
    # No histórico só o domínio: o caminho pode carregar um segredo do destino.
    audit.record(user, "webhook.create", "webhook", row["id"],
                 after={"name": urlsplit(data.url).hostname, "events": data.events})
    db.execute("UPDATE webhooks SET last_event_id = (SELECT max(id) FROM audit_log) WHERE id = %s",
               (row["id"],))  # nem o próprio cadastro é enviado
    return {**row, "secret": webhooks.secret_for(salt)}  # única vez em que o segredo sai


@router.patch("/{hook_id}")
def update_webhook(hook_id: int, data: WebhookUpdate, user=Depends(web_active_csrf)):
    """Troca o endereço e/ou os eventos sem recriar: o segredo e a fila seguem.
    O endereço novo passa pela mesma checagem do cadastro (https público)."""
    uid = user["user_id"]
    before = db.query_one("SELECT id, url, events FROM webhooks WHERE id = %s AND user_id = %s", (hook_id, uid))
    if not before:
        raise HTTPException(status_code=404, detail="não encontrado")
    url = data.url if data.url is not None else before["url"]
    events = data.events if data.events is not None else before["events"]
    if url != before["url"]:
        try:
            webhooks.check_url(url)
        except webhooks.Refused as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
    row = db.query_one(f"UPDATE webhooks SET url = %s, events = %s WHERE id = %s AND user_id = %s RETURNING {COLS}",
                       (url, events, hook_id, uid))
    if (url, events) != (before["url"], before["events"]):
        audit.record(user, "webhook.update", "webhook", hook_id,
                     before={"name": urlsplit(before["url"]).hostname, "events": before["events"]},
                     after={"name": urlsplit(url).hostname, "events": events})
    return row


@router.post("/{hook_id}/enable")
def enable_webhook(hook_id: int, user=Depends(web_active_csrf)):
    """Religa um desligado por falhas: continua do evento em que parou."""
    row = db.query_one(
        f"""UPDATE webhooks SET disabled_at = NULL, failures = 0, next_attempt_at = NULL, last_error = NULL
             WHERE id = %s AND user_id = %s RETURNING {COLS}""",
        (hook_id, user["user_id"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="não encontrado")
    audit.record(user, "webhook.enable", "webhook", hook_id, after={"name": urlsplit(row["url"]).hostname})
    return row


@router.post("/{hook_id}/test")
def test_webhook(hook_id: int, user=Depends(web_active_csrf)):
    """Envia agora um evento de teste assinado (X-Nexus-Event: ping) e devolve
    {ok, status, ms, error}. Só pelo app; não conta como falha nem desliga.
    Vale também para um desligado (testar antes de religar)."""
    hook = db.query_one("SELECT id, url, secret_salt FROM webhooks WHERE id = %s AND user_id = %s",
                        (hook_id, user["user_id"]))
    if not hook:
        raise HTTPException(status_code=404, detail="não encontrado")
    if not webhook_test_limiter.allow(f"wt:{user['user_id']}"):
        raise HTTPException(status_code=429, detail="muitos testes seguidos; aguarde um minuto")
    return webhooks.ping(hook)


@router.delete("/{hook_id}")
def delete_webhook(hook_id: int, user=Depends(active_user_csrf)):
    row = db.query_one("DELETE FROM webhooks WHERE id = %s AND user_id = %s RETURNING id, url",
                       (hook_id, user["user_id"]))
    if not row:
        raise HTTPException(status_code=404, detail="não encontrado")
    audit.record(user, "webhook.delete", "webhook", hook_id, before={"name": urlsplit(row["url"]).hostname})
    return {"ok": True}
