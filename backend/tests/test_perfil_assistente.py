"""Perfil (nome de exibição e foto), preferências do assistente, última
atividade (lembrete de inatividade), "parada há N dias" e a prévia do relatório."""
from conftest import Bearer, criar_chave, dia_hoje

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h1v1z"/></svg>'


def _put(u, path, body):
    return u.c.put("/api" + path, json=body, headers=u._h())


def _foto(u, data, ctype="image/png"):
    return u.c.post("/api/me/avatar", content=data, headers=u._h({"Content-Type": ctype}))


def test_nome_derivado_do_email_e_escolhido(novo_usuario):
    u = novo_usuario("jefferson.oliveira@example.com")
    me = u.get("/auth/me").json()
    assert (me["display_name"], me["name"], me["avatar"]) == (None, "Jefferson", None)
    r = _put(u, "/me/profile", {"display_name": "  Jeff   Shadow "})
    assert r.status_code == 200 and r.json()["name"] == "Jeff Shadow"
    assert u.get("/auth/me").json()["display_name"] == "Jeff Shadow"
    assert _put(u, "/me/profile", {"display_name": "x" * 61}).status_code == 422
    assert _put(u, "/me/profile", {"display_name": ""}).json()["name"] == "Jefferson"  # vazio = volta ao derivado


def test_foto_pelo_conteudo_e_so_raster(usuario, novo_usuario, admin):
    assert _foto(usuario, SVG, "image/png").status_code == 415      # SVG nunca, nem disfarçado
    assert _foto(usuario, b"GIF89a....", "image/gif").status_code == 415
    assert _foto(usuario, PNG + b"\x00" * (256 * 1024), "image/png").status_code == 413
    r = _foto(usuario, JPEG, "image/png")                            # vale o conteúdo, não o header
    assert r.status_code == 200 and r.json()["avatar"].startswith("/api/me/avatar/")
    url = r.json()["avatar"]
    img = usuario.c.get(url)
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert "sandbox" in img.headers["content-security-policy"]
    assert admin.c.get(url).status_code == 200                       # o admin vê (lista de usuários)
    assert novo_usuario("outra@example.com").c.get(url).status_code == 404  # outro usuário não
    assert usuario.delete("/me/avatar").json()["avatar"] is None
    assert usuario.c.get(url).status_code == 404


def test_chave_de_api_nao_mexe_no_perfil(usuario):
    b = Bearer(criar_chave(usuario)["token"])
    assert b.c.put("/api/me/profile", json={"display_name": "IA"}, headers=b.h).status_code == 403
    assert b.c.post("/api/me/avatar", content=PNG, headers={**b.h, "Content-Type": "image/png"}).status_code == 403


def test_preferencias_do_assistente(usuario):
    assert usuario.get("/auth/me").json()["assistant"] == {  # lembrete de 30 min ligado por padrão
        "enabled": True, "idle_on": True, "idle_minutes": 30, "idle_start": 480, "idle_end": 1080,
        "reopen_on": True, "reopen_minutes": 10, "summary_from": 840}
    ok = {"enabled": False, "idle_on": False, "idle_minutes": 45, "idle_start": 540, "idle_end": 1020,
          "reopen_on": False, "reopen_minutes": 25, "summary_from": 600}
    assert _put(usuario, "/me/assistant", ok).json() == ok
    assert usuario.get("/auth/me").json()["assistant"] == ok
    assert _put(usuario, "/me/assistant", {**ok, "idle_minutes": 2}).status_code == 422
    assert _put(usuario, "/me/assistant", {**ok, "idle_start": 1020, "idle_end": 540}).status_code == 422
    assert _put(usuario, "/me/assistant", {**ok, "reopen_minutes": 0}).status_code == 422
    assert _put(usuario, "/me/assistant", {**ok, "summary_from": 1440}).status_code == 422


def test_ultima_atividade_conta_so_registro(usuario):
    assert usuario.get("/me/activity").json()["last_activity"] is None
    _put(usuario, "/me/assistant", {"enabled": True, "idle_on": True})  # mexer em preferências não conta
    assert usuario.get("/me/activity").json()["last_activity"] is None
    usuario.post("/worklog", {"title": "Troca de toner"})
    assert usuario.get("/me/activity").json()["last_activity"] is not None
    b = Bearer(criar_chave(usuario)["token"])
    assert b.get("/me/activity").status_code == 403  # é do app, não da chave


def test_tarefa_aberta_traz_ultimo_movimento(usuario):
    tid = usuario.post("/worklog", {"title": "Firewall da Matriz", "status": "blocked"}).json()["id"]
    t = next(t for t in usuario.get("/board").json()["in_progress"] if t["id"] == tid)
    assert t["touched_at"] is not None


def test_previa_do_relatorio(usuario):
    hoje = dia_hoje(usuario).isoformat()
    tid = usuario.post("/worklog", {"title": "Entregue"}).json()["id"]
    usuario.post(f"/worklog/{tid}/time", {"minutes": 90})
    usuario.post(f"/worklog/{tid}/finish")
    r = usuario.get(f"/reports/preview?start={hoje}&end={hoje}")
    assert r.status_code == 200 and (r.json()["pontual_done"], r.json()["minutes"]) == (1, 90)
    assert usuario.get("/reports/preview").status_code == 400  # sem período nem projeto


def test_nome_no_admin_e_no_email(usuario, admin):
    _put(usuario, "/me/profile", {"display_name": "Colega"})
    linha = next(u for u in admin.get("/admin/users").json() if u["email"] == "colega@example.com")
    assert linha["name"] == "Colega"
    from app import notify
    from conftest import uid_de
    assert notify.build_morning(uid_de(usuario), dia_hoje(usuario), True).title == "Bom dia, Colega"
