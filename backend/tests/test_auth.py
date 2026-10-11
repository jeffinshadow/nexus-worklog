from conftest import ADMIN_EMAIL, ADMIN_PW_INICIAL, Api


def test_cadastro_publico_fechado_por_padrao():
    a = Api()
    assert a.get("/auth/config").json() == {"registration_open": False}
    r = a.post("/auth/register", {"email": "intruso@example.com", "password": "Senha-Qualquer-1"})
    assert r.status_code == 403


def test_admin_precisa_trocar_senha_no_primeiro_login():
    a = Api()
    r = a.login(ADMIN_EMAIL, ADMIN_PW_INICIAL)
    assert r.json()["must_change_password"] is True
    assert a.get("/board").status_code == 403


def test_login_errado_e_inexistente_respondem_igual():
    a = Api()
    r1 = a.c.post("/api/auth/login", json={"email": "naoexiste@example.com", "password": "x" * 12})
    r2 = a.c.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": "x" * 12})
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json()


def test_rate_limit_de_login_ignora_x_forwarded_for():
    a = Api()
    codigos = [
        a.c.post("/api/auth/login", json={"email": f"x{i}@example.com", "password": "errada"},
                 headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code
        for i in range(12)
    ]
    assert 429 in codigos


def test_mutacao_sem_csrf_e_recusada(usuario):
    r = usuario.c.post("/api/worklog", json={"title": "x"})
    assert r.status_code == 403


def test_convite_pelo_admin(admin, novo_usuario):
    u = novo_usuario("convidado@example.com")
    assert u.me["role"] == "user"
    assert admin.post("/admin/users", {"email": "convidado@example.com"}).status_code == 409


def test_usuario_comum_nao_convida_nem_ve_admin(usuario):
    assert usuario.post("/admin/users", {"email": "x@example.com"}).status_code == 403
    assert usuario.get("/admin/users").status_code == 403


def test_configuracoes_dias_uteis(usuario):
    assert usuario.get("/auth/me").json()["work_days"] == 62
    assert usuario.post("/auth/settings", {"work_days": 0}).status_code == 422
    assert usuario.post("/auth/settings", {"work_days": 128}).status_code == 422
    assert usuario.post("/auth/settings", {"work_days": 127}).status_code == 200
    assert usuario.get("/auth/me").json()["work_days"] == 127
