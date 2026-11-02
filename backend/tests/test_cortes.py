"""Simplificações da 2.0 (rodada 7): avisos únicos num só diálogo, modelos obsoletos,
pedido de convite com tempo mínimo de preenchimento."""
import time

from app import db, mailer
from conftest import Api, ligar_pedido_convite, uid_de
from test_para_empresas import _org


def test_um_entendi_da_todos_os_avisos_unicos_como_vistos(admin, usuario):
    _org(admin, team_visibility="managers", assign_receive="all")
    db.execute("UPDATE users SET role_notice = '{\"added\": [\"assigner\"], \"removed\": []}' WHERE id = %s", (uid_de(usuario),))
    me = usuario.get("/auth/me").json()
    assert me["visibility_notice"] is True and me["assign_notice"] is True and me["role_notice"]["added"] == ["assigner"]
    # "O que mudou para você": um só PUT dá os três como vistos.
    assert usuario.put("/me/notices-seen").json() == {"visibility_notice": False, "assign_notice": False, "role_notice": None}
    me = usuario.get("/auth/me").json()
    assert me["visibility_notice"] is False and me["assign_notice"] is False and me["role_notice"] is None


def test_modelos_obsoletos_ainda_respondem(usuario):
    r = usuario.post("/templates", {"name": "Toner", "title": "Trocar toner", "checklist": ["retirar", "instalar"]})
    assert r.status_code == 201
    assert [t["name"] for t in usuario.get("/templates").json()] == ["Toner"]
    assert usuario.post(f"/templates/{r.json()['id']}/use").status_code == 201
    # Fora das instruções da IA (a ferramenta existe, mas está marcada como obsoleta).
    from app.routers import mcp
    assert "create_from_template" not in mcp.INSTRUCTIONS and "list_templates" not in mcp.INSTRUCTIONS
    assert "OBSOLETA" in mcp.TOOLS["list_templates"][2]


def test_pedido_de_convite_exige_tempo_minimo(monkeypatch):
    import app.routers.invite_requests as ir
    monkeypatch.setattr(ir, "form_ok", ir._form_ok)       # volta a regra real (o conftest a desliga)
    ligar_pedido_convite()
    monkeypatch.setattr(mailer, "configured", lambda: True)
    for lim in (ir.invite_req_limiter, ir.invite_req_email_limiter):  # várias tentativas seguidas: sem os limites
        monkeypatch.setattr(lim, "allow", lambda k: True)
    monkeypatch.setattr(mailer, "send", lambda *a, **k: None)
    corpo = {"name": "Ana", "email": "ana@empresa.com.br", "source": "colega", "reason": "Quero registrar o suporte."}

    def enviar(token):
        return Api().post("/auth/invite-request", {**corpo, "form_t": token} if token is not None else corpo)

    agora = int(time.time())
    assert enviar(None).status_code == 400                                   # sem carimbo
    assert enviar("lixo").status_code == 400                                 # carimbo inválido
    assert enviar(ir.form_token(agora)).status_code == 400                   # rápido demais (< 3 s)
    assert enviar(ir.form_token(agora - 3601 - 5)).status_code == 400        # velho demais (> 1 h)
    assert enviar(f"{agora - 60}.{'0' * 32}").status_code == 400             # assinatura falsa
    r = enviar(ir.form_token(agora - 10))
    assert r.status_code == 202, r.text
    # O carimbo vem do servidor, no momento em que o formulário é mostrado.
    t = Api().get("/auth/invite-request/form").json()["t"]
    assert t.split(".")[0].isdigit() and ir.form_token(int(t.split(".")[0])) == t
    assert "tente de novo" in enviar(None).json()["detail"].lower()          # mensagem genérica
