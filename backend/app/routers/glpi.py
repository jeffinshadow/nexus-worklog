"""GLPI: a conexão de cada pessoa e o teste do admin (a conversa com o GLPI fica em app/glpi.py).

Tudo só pelo app (sessão + CSRF): uma chave de API vazada não troca nem usa o
token do GLPI de ninguém. O token entra e nunca mais sai.
"""
from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db, glpi
from ..deps import require_admin_csrf, web_active, web_active_csrf
from ..schemas import GlpiTokenIn
from ..security import webhook_test_limiter

router = APIRouter(tags=["glpi"])


def _limit(user: dict) -> None:
    # Cada chamada daqui conversa com o GLPI (até 15 s): poucas por minuto por pessoa.
    if not webhook_test_limiter.allow(f"glpi:{user['user_id']}"):
        raise HTTPException(status_code=429, detail="muitas tentativas seguidas; aguarde um minuto")


@router.get("/api/me/glpi")
def get_glpi(user=Depends(web_active)):
    """Estado da conexão com o GLPI: `available` (o admin configurou), `connected`,
    o nome no GLPI, a última sincronização, o erro (se houver) e as soluções que o GLPI recusou."""
    return glpi.state(user["user_id"])


@router.put("/api/me/glpi")
def connect_glpi(data: GlpiTokenIn, user=Depends(web_active_csrf)):
    """Conecta com o token pessoal do GLPI (no GLPI: Minhas configurações › Token de API): confere no
    GLPI antes de guardar (cifrado) e já faz a primeira sincronização."""
    if "user" not in user["roles"]:
        raise HTTPException(status_code=403, detail="esta conta não tem registro próprio")
    _limit(user)
    try:
        name = glpi.connect(user["user_id"], data.token.strip())
    except glpi.GlpiError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    audit.record(user, "glpi.connect", "user", user["user_id"], after={"name": name})
    glpi.sync(user["user_id"], manual=True)
    return glpi.state(user["user_id"])


@router.post("/api/me/glpi/sync")
def sync_glpi(user=Depends(web_active_csrf)):
    """Atualizar agora: puxa os chamados e manda as soluções pendentes (tira a pausa por falhas)."""
    if "user" not in user["roles"]:
        raise HTTPException(status_code=403, detail="esta conta não tem registro próprio")
    _limit(user)
    glpi.retry(user["user_id"])
    glpi.sync(user["user_id"], manual=True)
    return glpi.state(user["user_id"])


@router.delete("/api/me/glpi")
def disconnect_glpi(user=Depends(web_active_csrf)):
    """Desconecta: apaga o token. As tarefas ficam; nada mais é enviado ao GLPI."""
    if db.execute("DELETE FROM glpi_accounts WHERE user_id = %s", (user["user_id"],)):
        audit.record(user, "glpi.disconnect", "user", user["user_id"])
    return glpi.state(user["user_id"])


@router.post("/api/admin/glpi/test")
def test_glpi(admin=Depends(require_admin_csrf)):
    """Testa o endereço e o App-Token salvos: {ok, error}. Não usa o token de ninguém."""
    _limit(admin)
    try:
        cfg = glpi.settings()
    except glpi.GlpiError as e:
        return {"ok": False, "error": str(e)}
    if not cfg:
        raise HTTPException(status_code=400, detail="salve o endereço do GLPI antes de testar")
    return glpi.probe(cfg)
