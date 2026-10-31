"""Entrar com passkey (WebAuthn, py_webauthn).

A passkey é criada no aparelho (digital, rosto, Windows Hello, chave física) e
o servidor guarda só a chave pública, presa ao domínio do APP_URL: a criada na
homologação não vale em produção. Exige verificação do usuário (biometria ou
PIN), e o contador do autenticador denuncia cópia. A senha continua valendo.

Cadastrar e listar: só com a sessão do app. Entrar: público, com o mesmo
limite de tentativas do login por senha, e termina na mesma sessão.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from typing import Optional
from webauthn import (generate_authentication_options, generate_registration_options, options_to_json,
                      verify_authentication_response, verify_registration_response)
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement, UserVerificationRequirement)

from .. import audit, db, people
from ..config import config
from ..deps import client_ip, web_active, web_active_csrf
from ..routers.branding import branding
from ..security import login_limiter, new_token
from .auth import _start_session

log = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/api/auth/passkeys", tags=["auth"])

MAX_PER_USER = 10
CHALLENGE_TTL = timedelta(minutes=5)


class RegisterIn(BaseModel):
    challenge_id: str = Field(min_length=10, max_length=100)
    credential: dict
    name: Optional[str] = Field(default=None, max_length=60)


class LoginPasskeyIn(BaseModel):
    challenge_id: str = Field(min_length=10, max_length=100)
    credential: dict


def rp_id() -> str:
    return urlsplit(config.APP_URL).hostname or "localhost"


def origin() -> str:
    parts = urlsplit(config.APP_URL)
    return f"{parts.scheme}://{parts.netloc}"


def user_handle(uid: int) -> bytes:
    """Identificador da conta dentro da passkey: o número dela, sem e-mail."""
    return uid.to_bytes(8, "big")


def _save_challenge(kind: str, challenge: bytes, uid: int | None) -> str:
    db.execute("DELETE FROM webauthn_challenges WHERE expires_at <= now()")  # faxina
    cid = new_token()
    db.execute("INSERT INTO webauthn_challenges (id, user_id, kind, challenge, expires_at) VALUES (%s, %s, %s, %s, %s)",
               (cid, uid, kind, challenge, datetime.now(timezone.utc) + CHALLENGE_TTL))
    return cid


def _take_challenge(cid: str, kind: str, uid: int | None = None) -> bytes:
    row = db.query_one("""DELETE FROM webauthn_challenges WHERE id = %s AND kind = %s AND expires_at > now()
                          RETURNING user_id, challenge""", (cid, kind))
    if not row or (uid is not None and row["user_id"] != uid):
        raise HTTPException(status_code=400, detail="o pedido venceu; tente de novo")
    return bytes(row["challenge"])


@router.get("")
def list_passkeys(user=Depends(web_active)):
    return db.query_all("""SELECT id, name, backed_up, created_at, last_used_at FROM webauthn_credentials
                            WHERE user_id = %s ORDER BY created_at""", (user["user_id"],))


@router.post("/register/options")
def register_options(user=Depends(web_active_csrf)):
    uid = user["user_id"]
    existing = db.query_all("SELECT credential_id FROM webauthn_credentials WHERE user_id = %s", (uid,))
    if len(existing) >= MAX_PER_USER:
        raise HTTPException(status_code=409, detail=f"no máximo {MAX_PER_USER} passkeys por conta; remova uma antes")
    p = people.profile(uid)
    opts = generate_registration_options(
        rp_id=rp_id(), rp_name=" ".join(x for x in (branding()["line1"], branding()["line2"]) if x) or "Nexus",
        user_id=user_handle(uid), user_name=user["email"], user_display_name=p["name"],
        exclude_credentials=[PublicKeyCredentialDescriptor(id=bytes(c["credential_id"])) for c in existing],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED),
    )
    return {"challenge_id": _save_challenge("register", opts.challenge, uid), "options": json.loads(options_to_json(opts))}


@router.post("/register", status_code=201)
def register(data: RegisterIn, user=Depends(web_active_csrf)):
    uid = user["user_id"]
    challenge = _take_challenge(data.challenge_id, "register", uid)
    try:
        v = verify_registration_response(credential=data.credential, expected_challenge=challenge,
                                         expected_rp_id=rp_id(), expected_origin=origin(), require_user_verification=True)
    except Exception as e:  # noqa: BLE001 — a biblioteca levanta tipos variados; a mensagem não vaza
        log.info("cadastro de passkey recusado (usuário %s): %s", uid, e)
        raise HTTPException(status_code=400, detail="o aparelho não confirmou a passkey; tente de novo") from None
    transports = ",".join((data.credential.get("response") or {}).get("transports") or [])[:100] or None
    row = db.query_one(
        """INSERT INTO webauthn_credentials (user_id, credential_id, public_key, sign_count, transports, name, backed_up)
           VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (credential_id) DO NOTHING RETURNING id""",
        (uid, v.credential_id, v.credential_public_key, v.sign_count, transports,
         (data.name or "").strip() or None, bool(v.credential_backed_up)))
    if not row:
        raise HTTPException(status_code=409, detail="esta passkey já está cadastrada")
    audit.record(user, "passkey.add", "passkey", row["id"], after={"name": data.name})
    return {"id": row["id"]}


@router.delete("/{passkey_id}")
def remove(passkey_id: int, user=Depends(web_active_csrf)):
    row = db.query_one("DELETE FROM webauthn_credentials WHERE id = %s AND user_id = %s RETURNING name",
                       (passkey_id, user["user_id"]))
    if not row:
        raise HTTPException(status_code=404, detail="passkey não encontrada")
    audit.record(user, "passkey.remove", "passkey", passkey_id, before={"name": row["name"]})
    return {"ok": True}


@router.post("/login/options")
def login_options(request: Request):
    if not login_limiter.allow(f"ip:{client_ip(request)}"):
        raise HTTPException(status_code=429, detail="muitas tentativas, tente mais tarde")
    opts = generate_authentication_options(rp_id=rp_id(), user_verification=UserVerificationRequirement.REQUIRED)
    return {"challenge_id": _save_challenge("login", opts.challenge, None), "options": json.loads(options_to_json(opts))}


@router.post("/login")
def login(data: LoginPasskeyIn, request: Request, response: Response):
    ip = client_ip(request)
    if not login_limiter.allow(f"ip:{ip}"):
        raise HTTPException(status_code=429, detail="muitas tentativas, tente mais tarde")
    challenge = _take_challenge(data.challenge_id, "login")

    def falhou(motivo: str):
        log.warning("login por passkey falhou: ip=%s (%s)", ip, motivo)
        raise HTTPException(status_code=401, detail="passkey não reconhecida")

    try:
        cred_id = base64url_to_bytes(str(data.credential.get("rawId") or data.credential.get("id") or ""))
    except Exception:  # noqa: BLE001
        falhou("id ilegível")
    cred = db.query_one("SELECT * FROM webauthn_credentials WHERE credential_id = %s", (cred_id,))
    if not cred:
        falhou("credencial desconhecida")
    handle = (data.credential.get("response") or {}).get("userHandle")
    if handle and base64url_to_bytes(handle) != user_handle(cred["user_id"]):
        falhou("userHandle não confere")
    try:
        v = verify_authentication_response(
            credential=data.credential, expected_challenge=challenge, expected_rp_id=rp_id(), expected_origin=origin(),
            credential_public_key=bytes(cred["public_key"]), credential_current_sign_count=cred["sign_count"],
            require_user_verification=True)
    except Exception as e:  # noqa: BLE001
        falhou(str(e)[:120])
    user = db.query_one("SELECT * FROM users WHERE id = %s", (cred["user_id"],))
    if not user:
        falhou("conta excluída")
    db.execute("UPDATE webauthn_credentials SET sign_count = %s, last_used_at = now() WHERE id = %s",
               (v.new_sign_count, cred["id"]))
    return _start_session(user, response)

