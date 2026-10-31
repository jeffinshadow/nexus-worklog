"""Entrar com passkey: um autenticador de software (ES256, atestado "none",
verificação do usuário) faz o papel do celular ou do Windows Hello, e o servidor
confere de verdade (py_webauthn)."""
import base64
import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from app import db
from app.routers.passkeys import origin, rp_id
from conftest import Api, uid_de

b64u = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
unb64u = lambda t: base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))  # noqa: E731
UP, UV, AT = 0x01, 0x04, 0x40


class Autenticador:
    """Uma passkey num aparelho: chave privada, id e contador."""
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(32)
        self.count = 0
        self.handle = None

    def _auth_data(self, flags, extra=b""):
        return hashlib.sha256(rp_id().encode()).digest() + bytes([flags]) + struct.pack(">I", self.count) + extra

    def _client(self, tipo, challenge, origem=None):
        return json.dumps({"type": tipo, "challenge": challenge, "origin": origem or origin()}).encode()

    def criar(self, options, origem=None):
        self.handle = options["user"]["id"]
        n = self.key.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})
        attested = b"\0" * 16 + struct.pack(">H", len(self.cred_id)) + self.cred_id + cose
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": self._auth_data(UP | UV | AT, attested)})
        cid = b64u(self.cred_id)
        return {"id": cid, "rawId": cid, "type": "public-key", "response": {
            "clientDataJSON": b64u(self._client("webauthn.create", options["challenge"], origem)),
            "attestationObject": b64u(att), "transports": ["internal"]}}

    def entrar(self, options, flags=UP | UV, handle=None):
        self.count += 1
        ad = self._auth_data(flags)
        cd = self._client("webauthn.get", options["challenge"])
        sig = self.key.sign(ad + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
        cid = b64u(self.cred_id)
        return {"id": cid, "rawId": cid, "type": "public-key", "response": {
            "clientDataJSON": b64u(cd), "authenticatorData": b64u(ad), "signature": b64u(sig),
            "userHandle": handle if handle is not None else self.handle}}


def _cadastrar(u, aut=None, nome="Celular"):
    aut = aut or Autenticador()
    o = u.post("/auth/passkeys/register/options").json()
    assert o["options"]["authenticatorSelection"]["residentKey"] == "required"
    r = u.post("/auth/passkeys/register", {"challenge_id": o["challenge_id"], "credential": aut.criar(o["options"]), "name": nome})
    assert r.status_code == 201, r.text
    return aut


def _entrar(aut, **kw):
    a = Api()
    o = a.post("/auth/passkeys/login/options").json()
    return a, a.post("/auth/passkeys/login", {"challenge_id": o["challenge_id"], "credential": aut.entrar(o["options"], **kw)})


def test_cadastrar_e_entrar_sem_senha(usuario):
    aut = _cadastrar(usuario)
    lista = usuario.get("/auth/passkeys").json()
    assert [p["name"] for p in lista] == ["Celular"] and lista[0]["last_used_at"] is None
    a, r = _entrar(aut)
    assert r.status_code == 200, r.text
    assert a.get("/auth/me").json()["email"] == usuario.me["email"]    # a sessão vale
    assert usuario.get("/auth/passkeys").json()[0]["last_used_at"]
    assert any(h["action"] == "passkey.add" for h in usuario.get("/history?entity=passkey").json())


def test_sem_verificacao_do_usuario_nao_entra(usuario):
    aut = _cadastrar(usuario)
    _, r = _entrar(aut, flags=UP)  # tocou, mas sem digital/PIN
    assert r.status_code == 401


def test_contador_que_volta_denuncia_copia(usuario):
    aut = _cadastrar(usuario)
    assert _entrar(aut)[1].status_code == 200
    assert _entrar(aut)[1].status_code == 200
    aut.count = 0  # outra cópia da mesma chave, com o contador atrás
    assert _entrar(aut)[1].status_code == 401


def test_desafio_e_de_uso_unico_e_de_outro_site_nao_vale(usuario):
    aut = _cadastrar(usuario)
    a = Api()
    o = a.post("/auth/passkeys/login/options").json()
    cred = aut.entrar(o["options"])
    assert a.post("/auth/passkeys/login", {"challenge_id": o["challenge_id"], "credential": cred}).status_code == 200
    assert a.post("/auth/passkeys/login", {"challenge_id": o["challenge_id"], "credential": cred}).status_code == 400
    # Cadastro feito em outro endereço (phishing): recusado.
    o = usuario.post("/auth/passkeys/register/options").json()
    r = usuario.post("/auth/passkeys/register", {"challenge_id": o["challenge_id"],
                                                "credential": Autenticador().criar(o["options"], origem="https://nexus.golpe.example")})
    assert r.status_code == 400


def test_handle_de_outra_conta_nao_entra(usuario):
    aut = _cadastrar(usuario)
    _, r = _entrar(aut, handle=b64u((999999).to_bytes(8, "big")))
    assert r.status_code == 401


def test_remover_e_reset_pelo_admin_apaga(usuario, admin):
    aut = _cadastrar(usuario)
    pid = usuario.get("/auth/passkeys").json()[0]["id"]
    assert usuario.delete(f"/auth/passkeys/{pid}").status_code == 200
    assert _entrar(aut)[1].status_code == 401
    aut2 = _cadastrar(usuario, nome="Notebook")
    assert admin.post(f"/admin/users/{uid_de(usuario)}/reset-password").status_code == 200
    assert _entrar(aut2)[1].status_code == 401
    assert not db.query_one("SELECT 1 FROM webauthn_credentials WHERE user_id = %s", (uid_de(usuario),))


def test_mesma_passkey_nao_cadastra_duas_vezes(usuario):
    aut = _cadastrar(usuario)
    o = usuario.post("/auth/passkeys/register/options").json()
    assert len(o["options"]["excludeCredentials"]) == 1  # o aparelho já recusa
    r = usuario.post("/auth/passkeys/register", {"challenge_id": o["challenge_id"], "credential": aut.criar(o["options"])})
    assert r.status_code == 409
