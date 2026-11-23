"""Matriz de permissões por rota, gerada das próprias rotas (app.routes).

Rota nova entra sozinha na conferência; trocar a dependência de uma rota por outra mais fraca quebra o teste.
As regras olham o MÉTODO e o PREFIXO da rota (não só a dependência declarada): uma rota de /api/admin/ que
perdesse o require_admin continuaria na lista e falharia aqui.

Quando um teste daqui falhar por rota NOVA, classifique a rota em vez de afrouxar o teste:
- rota aberta de propósito (sem login): acrescente em PUBLICAS;
- escrita que dispensa CSRF de propósito: acrescente em ESCRITA_SEM_CSRF;
- rota que a senha temporária alcança: acrescente em COM_SENHA_TEMPORARIA;
- o resto: use a dependência certa de app/deps.py (a do prefixo, se for /api/admin/, /api/viewer/ ou /api/assign)."""
import re

from app import db, deps
from app.main import app
from tests.conftest import Api, Bearer, criar_chave

# Rotas abertas de propósito (sem login). Rota pública nova tem de entrar aqui, à vista de quem revisa.
PUBLICAS = {
    ("GET", "/api/health"), ("POST", "/api/auth/login"), ("GET", "/api/auth/options"), ("POST", "/api/auth/forgot"),
    ("POST", "/api/auth/link"), ("GET", "/api/auth/link"), ("POST", "/api/auth/invite/accept"), ("POST", "/api/auth/reset"),
    ("POST", "/api/auth/email/confirm"), ("POST", "/mcp"), ("DELETE", "/mcp"), ("GET", "/mcp"), ("GET", "/api/branding"),
    ("GET", "/api/branding/logo"), ("GET", "/api/calendar/{token}.ics"), ("POST", "/api/auth/passkeys/login/options"),
    ("POST", "/api/auth/passkeys/login"), ("GET", "/api/auth/invite-request/form"), ("POST", "/api/auth/invite-request"),
}
DEPS = ("current_user", "web_user_csrf", "active_user", "active_user_csrf", "web_active", "web_active_csrf", "require_admin",
        "require_admin_csrf", "require_viewer", "require_assigner", "require_assigner_csrf", "require_people_list")
NOME = {getattr(deps, n): n for n in DEPS}


def _dep(d):
    for x in d.dependencies:
        if x.call in NOME:
            return NOME[x.call]
        if (achou := _dep(x)):
            return achou
    return None


def _rotas():
    for r in app.routes:
        for c in (r.effective_route_contexts() if hasattr(r, "effective_route_contexts") else [r]):
            route = getattr(c, "route", c)
            if not hasattr(route, "dependant"):
                continue
            path = getattr(c, "path", None) or route.path
            for m in sorted((route.methods or set()) - {"HEAD", "OPTIONS"}):
                yield m, path, _dep(route.dependant)


ROTAS = list(_rotas())
ESCREVE = {"POST", "PUT", "PATCH", "DELETE"}


def _url(path):
    return re.sub(r"\{[^}]+\}", "1", path)


def _chama(cliente, m, path, headers=None):
    return cliente.request(m, _url(path), headers=headers or {}, json={} if m in ESCREVE else None)


# Escritas que dispensam CSRF de propósito (só gravam no log / leitura feita por POST). Lista à vista de quem revisa.
ESCRITA_SEM_CSRF = {("POST", "/api/client-errors")}
# O que a conta com senha temporária alcança: ver quem é, trocar a senha e sair. Mais nada.
COM_SENHA_TEMPORARIA = {("GET", "/api/auth/me"), ("POST", "/api/auth/change-password"), ("POST", "/api/auth/logout"),
                        ("POST", "/api/auth/logout-others")}
# Só pelo app (sessão do navegador), nunca por chave de API.
SO_APP = {"web_user_csrf", "web_active", "web_active_csrf", "require_admin", "require_admin_csrf", "require_viewer"}

PRIVADAS = [(m, p, d) for m, p, d in ROTAS if (m, p) not in PUBLICAS]


def _admin(p):
    return p.startswith("/api/admin/")


def _viewer(p):
    return p.startswith("/api/viewer/")


def _assign(p):
    return p == "/api/assign" or p.startswith("/api/assign/")


def _de_papel(p, d):
    return _admin(p) or _viewer(p) or _assign(p) or (d or "").startswith("require_")


def _lista(titulo, erradas):
    return f"{titulo} ({len(erradas)}):\n" + "\n".join(f"  {e}" for e in erradas)


def _todos_os_papeis():
    db.execute("INSERT INTO user_roles (user_id, role) SELECT id, r FROM users, unnest(ARRAY['user','viewer','assigner']) r "
               "ON CONFLICT DO NOTHING")


# ------------------------------------------------------------ regras (sem chamar a rota) --

def test_toda_rota_tem_dono_ou_esta_na_lista_de_publicas():
    sem = {(m, p) for m, p, d in ROTAS if d is None}
    assert sem == PUBLICAS, (
        f"rota SEM LOGIN fora da lista PUBLICAS (rota nova? ponha a dependência de app/deps.py ou, se é aberta de "
        f"propósito, acrescente em PUBLICAS): {sorted(sem - PUBLICAS)}; em PUBLICAS mas não existe mais ou passou a "
        f"exigir login: {sorted(PUBLICAS - sem)}")


def test_toda_escrita_exige_csrf_e_cada_prefixo_o_seu_papel():
    """Regra independente da dependência declarada: trocar require_admin_csrf por require_admin (ou por
    active_user_csrf) numa rota quebra aqui, mesmo sem nenhum teste específico da rota."""
    sem_csrf = {(m, p) for m, p, d in ROTAS if d and m in ESCREVE and not d.endswith("_csrf")}
    assert sem_csrf == ESCRITA_SEM_CSRF, (
        f"rota de ESCRITA sem dependência *_csrf (use a variante _csrf ou acrescente em ESCRITA_SEM_CSRF): "
        f"{sorted(sem_csrf - ESCRITA_SEM_CSRF)}; sobrando em ESCRITA_SEM_CSRF: {sorted(ESCRITA_SEM_CSRF - sem_csrf)}")
    fora = [(m, p, d) for m, p, d in ROTAS
            if (_admin(p) and not (d or "").startswith("require_admin"))
            or (_viewer(p) and d != "require_viewer")
            or (_assign(p) and not (d or "").startswith("require_assigner")
                and (m, p, d) != ("GET", "/api/assign/people", "require_people_list"))]
    assert not fora, _lista("rota com dependência mais fraca que a do prefixo (/api/admin/ pede require_admin*, "
                            "/api/viewer/ pede require_viewer, /api/assign pede require_assigner*)", fora)
    temp = {(m, p) for m, p, d in ROTAS if d in ("current_user", "web_user_csrf")}
    assert temp == COM_SENHA_TEMPORARIA, (
        f"rota que a SENHA TEMPORÁRIA alcança fora da lista (use active_user*/web_active* ou acrescente em "
        f"COM_SENHA_TEMPORARIA): {sorted(temp - COM_SENHA_TEMPORARIA)}; sobrando: {sorted(COM_SENHA_TEMPORARIA - temp)}")


# ------------------------------------------- comportamento (chama cada rota de verdade) --
# As rotas são escolhidas por método e prefixo, não pela dependência declarada: a rota enfraquecida
# continua na lista e falha, em vez de sair dela.

def test_sem_login_toda_rota_privada_responde_401():
    anon = Api()
    erradas = [(m, p, r.status_code) for m, p, d in PRIVADAS if (r := _chama(anon.c, m, p)).status_code != 401]
    assert not erradas, _lista("rota privada que não responde 401 sem login", erradas)


def test_escrita_sem_csrf_responde_403(admin):
    """Sessão de admin com todos os papéis, sem o cabeçalho X-CSRF-Token: nenhuma rota de escrita passa."""
    _todos_os_papeis()
    erradas = []
    for m, p, d in PRIVADAS:
        if m in ESCREVE and (m, p) not in ESCRITA_SEM_CSRF:
            r = _chama(admin.c, m, p)
            if r.status_code != 403 or "CSRF" not in r.text:
                erradas.append((m, p, r.status_code, r.text[:60]))
    assert not erradas, _lista("escrita aceita sem o cabeçalho X-CSRF-Token", erradas)


def test_usuario_comum_nao_entra_em_rota_de_papel(usuario):
    erradas = []
    for m, p, d in PRIVADAS:
        if _de_papel(p, d):
            r = _chama(usuario.c, m, p, usuario._h())
            if r.status_code != 403 or "restrito" not in r.text:
                erradas.append((m, p, r.status_code, r.text[:60]))
    assert not erradas, _lista("rota de admin, de quem acompanha ou de quem atribui aberta ao usuário comum", erradas)


def test_chave_de_api_de_admin_nao_entra_no_que_e_so_do_app(admin):
    _todos_os_papeis()
    b = Bearer(criar_chave(admin)["token"])
    erradas = []
    for m, p, d in PRIVADAS:
        if d in SO_APP or _admin(p) or _viewer(p):
            r = _chama(b.c, m, p, b.h)
            if r.status_code != 403 or "só pelo app" not in r.text:
                erradas.append((m, p, r.status_code, r.text[:60]))
    assert not erradas, _lista("rota só do app aceita chave de API", erradas)


def test_chave_de_leitura_nao_escreve_em_rota_nenhuma(usuario, admin):
    db.execute("INSERT INTO user_roles (user_id, role) SELECT id, 'assigner' FROM users ON CONFLICT DO NOTHING")
    b = Bearer(criar_chave(usuario, scope="read")["token"])
    erradas = []
    for m, p, d in PRIVADAS:
        if m in ESCREVE and (m, p) not in ESCRITA_SEM_CSRF:
            r = _chama(b.c, m, p, b.h)
            if r.status_code != 403 or not ("só de leitura" in r.text or "só pelo app" in r.text):
                erradas.append((m, p, r.status_code, r.text[:60]))
    assert not erradas, _lista("escrita aceita com chave de API só de leitura", erradas)


def test_senha_temporaria_so_alcanca_a_troca_de_senha(admin):
    r = admin.post("/admin/users", {"email": "nova@example.com"})
    u = Api()
    u.login("nova@example.com", r.json()["temp_password"])
    erradas = []
    for m, p, d in PRIVADAS:
        if (m, p) not in COM_SENHA_TEMPORARIA:
            r = _chama(u.c, m, p, u._h())
            if r.status_code != 403 or "troca de senha" not in r.text:
                erradas.append((m, p, r.status_code, r.text[:60]))
    assert not erradas, _lista("rota alcançada com senha temporária (antes da troca obrigatória)", erradas)
