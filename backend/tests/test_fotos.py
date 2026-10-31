"""Fotos na tarefa e na rotina: tipo pelo conteúdo, limites, cota, acesso,
excluir com desfazer, a tarefa excluída e recuperada, a faxina e o .zip."""
import base64
import io
import os
import zipfile

from app import db
from app.routers.photos import cleanup
from conftest import dia_hoje, hist, uid_de


def _webp(n=300):
    return b"RIFF" + (n + 4).to_bytes(4, "little") + b"WEBPVP8 " + os.urandom(n)


def _foto(n=300):
    return {"image": base64.b64encode(_webp(n)).decode(), "thumb": base64.b64encode(_webp(80)).decode(), "width": 1600, "height": 1200}


def _tarefa(u, titulo="Rack do 2º andar"):
    return u.post("/worklog", {"title": titulo}).json()["id"]


def test_foto_na_tarefa_e_acesso(usuario, novo_usuario, admin):
    tid = _tarefa(usuario)
    r = usuario.post(f"/worklog/{tid}/photos", _foto())
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert [p["id"] for p in usuario.get(f"/worklog/{tid}").json()["photos"]] == [pid]
    assert next(t for t in usuario.get("/board").json()["in_progress"] if t["id"] == tid)["photos_count"] == 1
    img = usuario.get(f"/photos/{pid}")
    assert img.status_code == 200 and img.content[:4] == b"RIFF" and "immutable" in img.headers["cache-control"]
    assert len(usuario.get(f"/photos/{pid}?thumb=true").content) < len(img.content)
    outro = novo_usuario("outro@example.com")
    assert outro.get(f"/photos/{pid}").status_code == 404          # de outra pessoa: não existe
    assert outro.post(f"/worklog/{tid}/photos", _foto()).status_code == 404
    assert admin.get(f"/photos/{pid}").status_code == 200          # o admin semeado é visualizador


def test_tipo_tamanho_e_limite(usuario):
    tid = _tarefa(usuario)
    gif = base64.b64encode(b"GIF89a" + os.urandom(200)).decode()
    assert usuario.post(f"/worklog/{tid}/photos", {**_foto(), "image": gif}).status_code == 415
    grande = base64.b64encode(_webp(1024 * 1024 + 10)).decode()
    assert usuario.post(f"/worklog/{tid}/photos", {**_foto(), "image": grande}).status_code in (413, 422)
    for _ in range(10):
        assert usuario.post(f"/worklog/{tid}/photos", _foto()).status_code == 201
    assert usuario.post(f"/worklog/{tid}/photos", _foto()).status_code == 409


def test_cota_do_admin(usuario, admin):
    tid = _tarefa(usuario)
    cfg = admin.get("/admin/settings").json()
    assert cfg["photo_quota_mb"] == 500
    admin.put("/admin/settings", {"retro_days": cfg["retro_days"], "support_contact": None, "photo_quota_mb": 0})
    assert usuario.post(f"/worklog/{tid}/photos", _foto()).status_code == 413
    admin.put("/admin/settings", {"retro_days": cfg["retro_days"], "support_contact": None})  # sem o campo: mantém
    assert admin.get("/admin/settings").json()["photo_quota_mb"] == 0


def test_excluir_e_desfazer(usuario):
    tid = _tarefa(usuario)
    pid = usuario.post(f"/worklog/{tid}/photos", _foto()).json()["id"]
    assert usuario.delete(f"/photos/{pid}").status_code == 200
    assert usuario.get(f"/photos/{pid}").status_code == 404
    assert usuario.get(f"/worklog/{tid}").json()["photos"] == []
    h = hist(usuario, entity="photo", entity_id=pid)[0]
    assert h["action"] == "photo.delete" and h["can_undo"]
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert usuario.get(f"/photos/{pid}").status_code == 200


def test_tarefa_excluida_e_recuperada_volta_com_as_fotos(usuario):
    tid = _tarefa(usuario)
    pid = usuario.post(f"/worklog/{tid}/photos", _foto()).json()["id"]
    assert usuario.delete(f"/worklog/{tid}").status_code == 200
    cleanup()  # dentro da janela do desfazer: a foto fica
    h = hist(usuario, entity="worklog", entity_id=tid)[0]
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert [p["id"] for p in usuario.get(f"/worklog/{tid}").json()["photos"]] == [pid]
    # Excluída de novo e passada a janela: a faxina leva.
    usuario.delete(f"/worklog/{tid}")
    db.execute("UPDATE audit_log SET created_at = now() - interval '8 days' WHERE entity = 'worklog' AND entity_id = %s", (tid,))
    cleanup()
    assert not db.query_one("SELECT 1 FROM photos WHERE id = %s", (pid,))


def test_criar_tarefa_com_foto_nao_se_desfaz_pelo_historico(usuario):
    tid = _tarefa(usuario)
    usuario.post(f"/worklog/{tid}/photos", _foto())
    h = next(x for x in hist(usuario, entity="worklog", entity_id=tid) if x["action"] == "worklog.create")
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 409


def test_foto_de_evidencia_da_rotina(usuario):
    rid = usuario.post("/recurring", {"label": "Conferir backups", "freq": "weekly", "weekdays": 127}).json()["id"]
    hoje = dia_hoje(usuario).isoformat()
    assert usuario.post(f"/recurring/{rid}/photos?day={hoje}", _foto()).status_code == 201
    assert len(usuario.get(f"/recurring/{rid}/photos?day={hoje}").json()) == 1
    assert next(r for r in usuario.get("/board").json()["recurring"] if r["id"] == rid)["photos"] == 1


def test_exportar_zip(usuario):
    tid = _tarefa(usuario, "Troca do switch")
    usuario.post(f"/worklog/{tid}/photos", _foto())
    r = usuario.get("/export/fotos.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    nomes = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len(nomes) == 1 and nomes[0].startswith(f"tarefa-{tid}-troca-do-switch/") and nomes[0].endswith(".webp")


def test_excluir_a_conta_apaga_as_fotos(usuario):
    tid = _tarefa(usuario)
    usuario.post(f"/worklog/{tid}/photos", _foto())
    uid = uid_de(usuario)
    db.execute("DELETE FROM users WHERE id = %s", (uid,))
    assert not db.query_one("SELECT 1 FROM photos WHERE user_id = %s", (uid,))
