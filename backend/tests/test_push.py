"""Notificações dos aparelhos (Web Push): inscrição, segurança do endpoint,
disparos agendados da rotina e da manhã, preferências e a criptografia de ponta
a ponta (o teste faz o papel do navegador e descriptografa o que sairia)."""
import base64
import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import http_ece
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from app import db, push
from app.config import config
from conftest import dia_hoje, uid_de

FCM = "https://fcm.googleapis.com/fcm/send/"
b64u = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
unb64u = lambda t: base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))  # noqa: E731


class Navegador:
    """Um aparelho: o par de chaves e o segredo que o navegador gera ao inscrever."""
    def __init__(self, nome="a1"):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = b"0123456789abcdef"
        self.endpoint = FCM + nome
        pub = self.key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.body = {"endpoint": self.endpoint, "keys": {"p256dh": b64u(pub), "auth": b64u(self.auth)}, "label": "Chrome · Android"}

    def abrir(self, corpo: bytes) -> dict:
        return json.loads(http_ece.decrypt(corpo, private_key=self.key, auth_secret=self.auth, version="aes128gcm"))


@pytest.fixture
def caixa(monkeypatch):
    """Troca a rede: guarda (endpoint, cabeçalhos, corpo) e responde `status`."""
    class Saida(list):
        estado = {"status": 201}
    saida = Saida()
    estado = saida.estado
    def transporte(endpoint, headers, body):
        saida.append((endpoint, headers, body))
        return estado["status"]
    monkeypatch.setattr(push, "TRANSPORT", transporte)
    return saida


def _ligar(u, nav=None):
    nav = nav or Navegador()
    r = u.post("/push/devices", nav.body)
    assert r.status_code == 201, r.text
    return nav


def _agora(dia, hh, mm):
    return datetime.combine(dia, time(hh, mm), tzinfo=ZoneInfo(config.APP_TZ))


def test_chave_publica_estavel_e_vapid_valido(usuario):
    k1 = usuario.get("/push").json()["public_key"]
    assert len(unb64u(k1)) == 65 and usuario.get("/push").json()["public_key"] == k1
    # O JWT do cabeçalho confere com a chave pública (ES256).
    head = push._vapid_header(FCM + "x")
    token, chave = head[len("vapid t="):].split(", k=")
    assert chave == k1
    h, c, s = token.split(".")
    claims = json.loads(unb64u(c))
    assert claims["aud"] == "https://fcm.googleapis.com" and claims["exp"] > datetime.now().timestamp()
    sig = unb64u(s)
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(k1))
    pub.verify(encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")),
               f"{h}.{c}".encode(), ec.ECDSA(hashes.SHA256()))


def test_inscricao_so_de_servico_conhecido(usuario):
    nav = Navegador()
    for ruim in ("https://intranet.local/push", "http://fcm.googleapis.com/x", "https://fcm.googleapis.com.evil.io/x"):
        assert usuario.post("/push/devices", {**nav.body, "endpoint": ruim}).status_code == 400, ruim
    assert usuario.post("/push/devices", {**nav.body, "keys": {"p256dh": "A" * 87, "auth": "B" * 22}}).status_code == 400
    _ligar(usuario, nav)
    d = usuario.get(f"/push?endpoint={nav.endpoint}").json()["devices"]
    assert len(d) == 1 and d[0]["current"] and d[0]["label"] == "Chrome · Android"
    assert usuario.delete(f"/push/devices/{d[0]['id']}").status_code == 200
    assert usuario.get("/push").json()["devices"] == []


def test_mesmo_navegador_outra_conta_passa_pra_quem_entrou(usuario, novo_usuario):
    nav = _ligar(usuario)
    outro = novo_usuario("outro@example.com")
    _ligar(outro, nav)
    assert usuario.get("/push").json()["devices"] == []
    assert len(outro.get("/push").json()["devices"]) == 1


def test_teste_criptografado_de_ponta_a_ponta(usuario, caixa):
    nav = _ligar(usuario)
    assert usuario.post("/push/test").json() == {"sent": 1}
    endpoint, headers, corpo = caixa[0]
    assert endpoint == nav.endpoint and headers["Content-Encoding"] == "aes128gcm" and headers["Authorization"].startswith("vapid t=")
    msg = nav.abrir(corpo)
    assert msg["title"] == "Notificações ligadas" and msg["url"] == "/#/config?aba=avisos"


def test_aparelho_que_sumiu_sai_da_lista(usuario, caixa):
    _ligar(usuario)
    caixa.estado["status"] = 410
    assert usuario.post("/push/test").status_code == 502
    assert usuario.get("/push").json()["devices"] == []


def _rotina(u, hhmm="09:00", **kw):
    r = u.post("/recurring", {"label": "Conferir backups", "freq": "weekly", "weekdays": 127, "remind_at": hhmm, **kw})
    assert r.status_code == 201
    return r.json()["id"]


def test_rotina_no_horario_repete_ate_marcar(usuario, caixa):
    nav = _ligar(usuario)
    rid = _rotina(usuario)
    hoje, uid = dia_hoje(usuario), uid_de(usuario)
    assert push.run_once(_agora(hoje, 8, 59)) == []
    assert push.run_once(_agora(hoje, 9, 0)) == [(uid, f"{rid}:0")]
    msg = nav.abrir(caixa[-1][2])
    assert msg["title"] == "Conferir backups" and msg["body"] == "Agora, às 09:00" and msg["kind"] == "rotina"
    assert [a["action"] for a in msg["actions"]] == ["feita", "adiar"] and msg["tag"] == f"rotina-{rid}-{hoje}"
    assert push.run_once(_agora(hoje, 9, 1)) == []                     # não repete o mesmo disparo
    assert push.run_once(_agora(hoje, 9, 10)) == [(uid, f"{rid}:10")]
    assert nav.abrir(caixa[-1][2])["body"].startswith("Era às 09:00")
    usuario.post(f"/recurring/{rid}/toggle", {"done": True})
    assert push.run_once(_agora(hoje, 9, 30)) == []                    # marcada: para


def test_backend_fora_do_ar_nao_manda_aviso_velho(usuario, caixa):
    _ligar(usuario)
    rid = _rotina(usuario)
    hoje, uid = dia_hoje(usuario), uid_de(usuario)
    assert push.run_once(_agora(hoje, 9, 20)) == [(uid, f"{rid}:10")]  # só o mais recente da janela
    assert push.run_once(_agora(hoje, 10, 30)) == []                   # +30 passou há mais de 15 min


def test_adiar_empurra_os_disparos(usuario, caixa):
    _ligar(usuario)
    rid = _rotina(usuario)
    hoje, uid = dia_hoje(usuario), uid_de(usuario)
    push.run_once(_agora(hoje, 9, 0))
    assert usuario.post(f"/recurring/{rid}/snooze", {"minutes": 10}).status_code == 200
    # O adiamento real é "agora + 10"; aqui fixamos 09:12 para o relógio do teste.
    db.execute("UPDATE push_snooze SET until = %s WHERE recurring_id = %s", (_agora(hoje, 9, 12), rid))
    assert push.run_once(_agora(hoje, 9, 10)) == []                    # +10 caiu dentro do adiamento
    assert push.run_once(_agora(hoje, 9, 12)) == [(uid, f"{rid}:a0912")]
    assert push.run_once(_agora(hoje, 9, 30)) == [(uid, f"{rid}:30")]


def test_rotina_que_exige_evidencia_nao_tem_marcar_e_conteudo_escondido(usuario, caixa):
    nav = _ligar(usuario)
    _rotina(usuario, require_note=True)
    usuario.put("/push/prefs", {"hide_content": True})
    push.run_once(_agora(dia_hoje(usuario), 9, 0))
    msg = nav.abrir(caixa[-1][2])
    assert [a["action"] for a in msg["actions"]] == ["adiar"]
    assert msg["title"] == "Rotina na hora" and "backups" not in json.dumps(msg)


def test_rotina_desligada_nas_preferencias(usuario, caixa):
    _ligar(usuario)
    _rotina(usuario)
    usuario.put("/push/prefs", {"routine": False})
    assert push.run_once(_agora(dia_hoje(usuario), 9, 0)) == []


def test_manha_prazos_e_cobranca_uma_vez(usuario, caixa):
    nav = _ligar(usuario)
    hoje, uid = dia_hoje(usuario), uid_de(usuario)
    usuario.post("/auth/settings", {"work_days": 127})
    usuario.post("/worklog", {"title": "Renovar certificado", "due_date": hoje.isoformat()})
    t = usuario.post("/worklog", {"title": "Peça do switch", "status": "blocked", "blocked_reason": "fornecedor"}).json()["id"]
    usuario.patch(f"/worklog/{t}", {"follow_up_on": hoje.isoformat()})
    assert push.run_once(_agora(hoje, 7, 59)) == []
    feitos = push.run_once(_agora(hoje, 8, 0))
    assert sorted(r for _, r in feitos) == ["cobrar", "prazos"]
    corpos = [nav.abrir(c[2]) for c in caixa]
    assert any(m["title"] == "Prazos de hoje" and "Renovar certificado" in m["body"] for m in corpos)
    assert any(m["title"] == "Cobrar hoje" and m["body"] == "Peça do switch" for m in corpos)
    assert push.run_once(_agora(hoje, 9, 0)) == []
    assert all(u == uid for u, _ in feitos)


def test_tarefa_atribuida(usuario, caixa):
    nav = _ligar(usuario)
    push.notify_assigned(uid_de(usuario), {"id": 7, "title": "Trocar o nobreak"}, "Ana")
    msg = nav.abrir(caixa[-1][2])
    assert msg["title"] == "Nova tarefa de Ana" and msg["url"] == "/#/tarefas?id=7"


def test_trocar_a_senha_desliga_os_aparelhos(usuario):
    _ligar(usuario)
    from app.security import revoke_access
    revoke_access(uid_de(usuario))
    assert usuario.get("/push").json()["devices"] == []
