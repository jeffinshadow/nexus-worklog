"""Rodada 2, pacote r2-03: o marcador da passada do agendador (Saúde do Nexus)
anda durante a passada, não só no fim dela."""
import asyncio
from datetime import datetime

from app import notify
from app.config import config

from conftest import uid_de


def test_marcador_da_passada_anda_entre_os_servicos(monkeypatch):
    """Passada lenta: cada serviço já encontra o marcador atualizado (antes só no fim)."""
    visto = {}

    def servico(nome):
        def roda(*a, **k):
            visto[nome] = notify.last_pass
            monkeypatch.setattr(notify, "last_pass", None)  # o próximo só vê o que for marcado depois deste
        return roda

    dub = lambda nome: type("D", (), {"run_once": staticmethod(servico(nome))})
    monkeypatch.setattr(notify, "last_pass", None)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.teste.invalid")
    monkeypatch.setattr(notify, "run_once", servico("email"))
    monkeypatch.setattr(notify, "faxina", servico("faxina"))
    asyncio.run(notify._pass(datetime(2026, 11, 23, 8, 1), dub("agenda"), dub("push")))
    assert visto["push"] and visto["agenda"] and visto["email"]   # começo da passada e entre os serviços
    assert notify.last_pass                                        # e no fim, como sempre


def test_marcador_da_passada_anda_a_cada_pessoa_do_email(monkeypatch, usuario):
    """Muita gente com SMTP lento: o marcador anda a cada pessoa, dentro do serviço de e-mail."""
    usuario.c.put("/api/notifications", json={"morning": True, "morning_hour": 8}, headers=usuario._h())
    visto = []
    monkeypatch.setattr(notify, "last_pass", None)
    monkeypatch.setattr(notify, "_user_pass", lambda u, *a: visto.append((u["id"], notify.last_pass)) or [])
    notify.run_once(datetime(2026, 11, 23, 8, 1))
    assert (uid_de(usuario), None) not in visto and uid_de(usuario) in [u for u, _ in visto]
