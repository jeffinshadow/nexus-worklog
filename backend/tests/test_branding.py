from conftest import Api, Bearer, criar_chave

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
SVG_OK = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0h10v10z"/></svg>'


def _upload(api, data, ctype="image/png"):
    return api.c.post("/api/admin/branding/logo", content=data,
                      headers={"X-CSRF-Token": api.csrf, "Content-Type": ctype})


def test_padrao_e_publico():
    r = Api().get("/branding")
    assert r.status_code == 200 and r.json() == {"line1": "nexus", "line2": "worklog", "logo": None}
    assert Api().get("/branding/logo").status_code == 404


def test_admin_edita_textos_e_envia_logo(admin):
    assert admin.c.put("/api/admin/branding", json={"line1": "shadow", "line2": "tec.br"},
                       headers={"X-CSRF-Token": admin.csrf}).status_code == 200
    r = _upload(admin, SVG_OK, "image/svg+xml")
    assert r.status_code == 200 and r.json()["logo"].startswith("/api/branding/logo?v=")
    pub = Api().get("/branding").json()
    assert (pub["line1"], pub["line2"]) == ("shadow", "tec.br")
    logo = Api().c.get(pub["logo"])
    assert logo.status_code == 200 and logo.headers["content-type"].startswith("image/svg+xml")
    assert "sandbox" in logo.headers["content-security-policy"]
    assert admin.c.delete("/api/admin/branding/logo", headers={"X-CSRF-Token": admin.csrf}).json()["logo"] is None


def test_tipo_real_pelo_conteudo(admin):
    assert _upload(admin, PNG, "image/svg+xml").status_code == 200  # é PNG, mesmo dizendo SVG
    assert Api().c.get(Api().get("/branding").json()["logo"]).headers["content-type"] == "image/png"
    assert _upload(admin, b"GIF89a....", "image/png").status_code == 415
    assert _upload(admin, b"<html><script>x</script></html>", "image/svg+xml").status_code == 415


def test_svg_perigoso_recusado(admin):
    for bad in (
        b'<svg><script>alert(1)</script></svg>',
        b'<svg onload="alert(1)"></svg>',
        b'<svg><a href="javascript:alert(1)"><path/></a></svg>',
        b'<svg><foreignObject><div/></foreignObject></svg>',
        b'<svg><image href="https://evil.example/x.png"/></svg>',
    ):
        assert _upload(admin, bad, "image/svg+xml").status_code == 400, bad
    ok_embutido = b'<svg><image href="data:image/png;base64,AAAA"/><use href="#a"/></svg>'
    assert _upload(admin, ok_embutido, "image/svg+xml").status_code == 200


def test_limite_e_permissoes(admin, usuario):
    assert _upload(admin, PNG + b"\x00" * (256 * 1024), "image/png").status_code == 413
    assert _upload(usuario, PNG).status_code == 403
    assert usuario.c.put("/api/admin/branding", json={"line1": "x"}, headers={"X-CSRF-Token": usuario.csrf}).status_code == 403
    b = Bearer(criar_chave(admin)["token"])
    assert b.c.post("/api/admin/branding/logo", content=PNG, headers={**b.h, "Content-Type": "image/png"}).status_code == 403
    assert admin.c.put("/api/admin/branding", json={"line1": ""}, headers={"X-CSRF-Token": admin.csrf}).status_code == 422


def test_relatorio_usa_identidade_e_sobrevive_a_logo_qualquer(admin):
    """O PDF usa o lockup configurado; logo que o gerador não entende cai no dragão."""
    from datetime import date
    tid = admin.post("/worklog", {"title": "Entrega com acento — çãé", "priority": 1}).json()["id"]
    admin.post(f"/worklog/{tid}/time", {"minutes": 50, "note": "emoji 🚀 vira ?"})
    admin.post(f"/worklog/{tid}/finish")
    hoje = date.fromisoformat(admin.get("/board").json()["today"]).isoformat()
    admin.c.put("/api/admin/branding", json={"line1": "engage", "line2": "ti"}, headers=admin._h())
    for logo, ctype in ((SVG_OK, "image/svg+xml"), (PNG, "image/png"), (b"<svg xmlns='http://www.w3.org/2000/svg'><g/></svg>", "image/svg+xml")):
        assert _upload(admin, logo, ctype).status_code == 200
        r = admin.get(f"/reports/export?start={hoje}&end={hoje}")
        assert r.status_code == 200 and r.content[:4] == b"%PDF", r.text[:200]
