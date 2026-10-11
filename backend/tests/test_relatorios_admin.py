from datetime import date, timedelta


def test_pdf_do_proprio_usuario(usuario):
    usuario.post("/worklog", {"title": "Feita", "status": "done"})
    hoje = date.fromisoformat(usuario.get("/board").json()["today"])
    r = usuario.get(f"/reports/export?start={(hoje - timedelta(days=6)).isoformat()}&end={hoje.isoformat()}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_periodo_invertido_e_longo_demais(usuario):
    assert usuario.get("/reports/export?start=2026-02-01&end=2026-01-01").status_code == 400
    assert usuario.get("/reports/export?start=2024-01-01&end=2026-01-01").status_code == 400


def test_admin_ve_dados_de_outro_em_leitura(admin, usuario):
    usuario.post("/worklog", {"title": "Do colega"})
    uid = usuario.me["id"]
    b = admin.get(f"/admin/users/{uid}/board").json()
    assert any(t["title"] == "Do colega" for t in b["in_progress"])
    assert admin.get(f"/admin/users/{uid}/dashboard").status_code == 200


def test_reset_de_senha_pelo_admin(admin, usuario):
    r = admin.post(f"/admin/users/{usuario.me['id']}/reset-password")
    assert r.status_code == 200 and len(r.json()["temp_password"]) == 12
    assert usuario.get("/board").status_code == 401  # sessões do alvo encerradas
