"""Aceite do visualizador (sql/027): cada pessoa decide se quem tem o papel
viewer vê o registro dela. Existentes na migração ficam ligados; novos, não."""
import base64
import os
import pathlib

from app import db, main
from conftest import Bearer, criar_chave, hist, uid_de

MIGRACAO = pathlib.Path(main.SQL_DIR) / "027_aceite_visualizador.sql"


def _foto():
    webp = lambda n: b"RIFF" + (n + 4).to_bytes(4, "little") + b"WEBPVP8 " + os.urandom(n)  # noqa: E731
    return {"image": base64.b64encode(webp(300)).decode(), "thumb": base64.b64encode(webp(80)).decode(),
            "width": 1600, "height": 1200}


def _aceite(email):
    return db.query_one("SELECT viewers_allowed FROM users WHERE email = %s", (email,))["viewers_allowed"]


def _csv_emails(api):
    linhas = api.get("/viewer/export/apontamentos.csv").content.decode("utf-8-sig").splitlines()
    return {l.split(";")[-1] for l in linhas[1:]}


def test_conta_nova_comeca_desligada(usuario, admin):
    assert usuario.get("/auth/me").json()["viewers_allowed"] is False
    assert _aceite(usuario.me["email"]) is False
    assert _aceite(admin.me["email"]) is False  # o admin semeado também é conta nova


def test_visualizador_so_ve_quem_aceitou(admin, usuario):
    uid = uid_de(usuario)
    tid = usuario.post("/worklog", {"title": "Trocar nobreak"}).json()["id"]
    usuario.post(f"/worklog/{tid}/time", {"minutes": 30})
    foto = usuario.post(f"/worklog/{tid}/photos", _foto()).json()["id"]
    hoje = usuario.get("/board").json()["today"]
    rotas = [f"/viewer/users/{uid}/board", f"/viewer/users/{uid}/dashboard", f"/viewer/users/{uid}/projects",
             f"/viewer/users/{uid}/reports/export?start={hoje}&end={hoje}", f"/photos/{foto}"]

    # Sem o aceite: some da lista, do CSV e tudo dá 404 (o admin semeado é visualizador).
    assert usuario.me["email"] not in [u["email"] for u in admin.get("/viewer/users").json()]
    assert usuario.me["email"] not in _csv_emails(admin)
    for rota in rotas:
        assert admin.get(rota).status_code == 404, rota

    # Com o aceite: aparece e abre.
    r = usuario.put("/me/viewers", {"accept": True})
    assert r.status_code == 200 and r.json() == {"viewers_allowed": True}
    assert usuario.me["email"] in [u["email"] for u in admin.get("/viewer/users").json()]
    assert usuario.me["email"] in _csv_emails(admin)
    for rota in rotas:
        assert admin.get(rota).status_code == 200, rota
    assert admin.get(rotas[3]).content.startswith(b"%PDF")

    # Desligou: volta a sumir.
    assert usuario.put("/me/viewers", {"accept": False}).json() == {"viewers_allowed": False}
    for rota in rotas:
        assert admin.get(rota).status_code == 404, rota
    assert usuario.get(f"/photos/{foto}").status_code == 200  # a dona sempre vê


def test_aceite_vai_ao_historico_e_so_pelo_app(usuario):
    usuario.put("/me/viewers", {"accept": True})
    usuario.put("/me/viewers", {"accept": True})  # sem mudança: não registra de novo
    usuario.put("/me/viewers", {"accept": False})
    resumos = [h["summary"] for h in hist(usuario) if h["action"] == "viewers.consent"]
    assert len(resumos) == 2 and any("passou a permitir" in s for s in resumos) and any("deixou de permitir" in s for s in resumos)
    ia = Bearer(criar_chave(usuario)["token"])
    assert ia.c.put("/api/me/viewers", json={"accept": True}, headers=ia.h).status_code == 403
    assert _aceite(usuario.me["email"]) is False


def test_migracao_liga_existentes_e_nao_religa(usuario, novo_usuario):
    antiga = usuario.me["email"]
    try:
        # Banco "de antes": sem a coluna. Aplicar liga quem já existe...
        db.execute("ALTER TABLE users DROP COLUMN viewers_allowed")
        db.execute_script(MIGRACAO.read_text())
        assert _aceite(antiga) is True
        # ...e quem nasce depois começa desligado.
        nova = novo_usuario("nova@example.com").me["email"]
        assert _aceite(nova) is False
        # Quem desligou continua desligado ao rodar de novo (a migração roda a cada subida).
        db.execute("UPDATE users SET viewers_allowed = false WHERE email = %s", (antiga,))
        db.execute_script(MIGRACAO.read_text())
        db.execute_script(MIGRACAO.read_text())
        assert _aceite(antiga) is False and _aceite(nova) is False
    finally:
        db.execute_script(MIGRACAO.read_text())  # nunca deixa a suíte sem a coluna
