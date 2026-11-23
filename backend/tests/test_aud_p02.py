"""Auditoria, pacote p02 (equipes, visualizador, fotos e administração de contas):
arquivar a última equipe não abre o escopo (excluir, sim, com aviso); fotos e
foto de perfil fora do cache depois de Sair; foto de perfil no zip; fotos e o
dia local no log do master; quadro de quem acompanha sem cronômetro nem
lembretes; "Precisa de atenção" sem as tarefas de quem olha e com o total;
vencimentos da equipe na exclusão de conta; "atribuída por mim" zerada quando
a tarefa volta para quem atribuiu; aviso por e-mail no reset com senha temporária."""
import io
import zipfile
from datetime import date, datetime, timedelta, timezone

from app import db, mailer, visibility
from app.routers import admin as admin_mod
from conftest import uid_de
from test_equipes import _aceita, _equipe, _lista, _org, _papeis, caixa, cena  # noqa: F401 (fixtures)
from test_fotos import _foto as foto_b64


# ------------------------------------------------------ última equipe --

def test_arquivar_a_unica_equipe_nao_abre_o_escopo(admin, cena, novo_usuario):
    chefe, ana, bia = cena
    tid = _equipe(admin, "Campo", chefe, ana)
    assert _lista(chefe) == {"ana@example.com"}
    assert "bia@example.com" not in _aceita(chefe)
    assert admin.patch(f"/admin/teams/{tid}", {"archived": True}).status_code == 200
    # Arquivada, ninguém compartilha equipe: o visualizador não ganha alcance, o atribuidor também não.
    assert _lista(chefe) == set()
    assert chefe.get(f"/viewer/users/{uid_de(bia)}/board").status_code == 404
    assert chefe.get(f"/viewer/users/{uid_de(ana)}/board").status_code == 404
    assert not ({"ana@example.com", "bia@example.com"} & _aceita(chefe))
    assert chefe.post("/assign", {"user_id": uid_de(bia), "title": "de outra área"}).status_code in (403, 404)
    assert chefe.get("/viewer/teams").json()["on"] is True
    assert ana.get("/auth/me").json()["teams_on"] is True
    # "Visível para quem gerencia" não vale para quem não está em equipe ativa (company_sql).
    carla = novo_usuario("carla@example.com")
    _org(admin, team_visibility="managers")
    assert _lista(chefe) == set()
    assert chefe.get(f"/viewer/users/{uid_de(carla)}/board").status_code == 404
    # Criar outra equipe com uma arquivada no cadastro não é "a primeira".
    r = admin.post("/admin/teams", {"name": "Outra", "member_ids": []})
    assert r.status_code == 201 and r.json()["first"] is False


def test_excluir_a_ultima_equipe_avisa_e_volta_ao_uso_pessoal(admin, cena):
    chefe, ana, bia = cena
    a = _equipe(admin, "Campo", chefe, ana)
    b = _equipe(admin, "Escritório", bia)
    assert admin.patch(f"/admin/teams/{b}", {"archived": True}).status_code == 200
    r = admin.delete(f"/admin/teams/{a}")
    assert r.status_code == 200 and r.json()["last"] is False   # sobra a arquivada: segue com equipes
    assert _lista(chefe) == set()
    r = admin.delete(f"/admin/teams/{b}")
    assert r.status_code == 200 and r.json()["last"] is True
    assert _lista(chefe) == {"ana@example.com", "bia@example.com"}
    assert chefe.get("/viewer/teams").json()["on"] is False


# -------------------------------------------------------------- fotos --

def _foto(u):
    tid = u.post("/worklog", {"title": "Com foto"}).json()["id"]
    r = u.post(f"/worklog/{tid}/photos", foto_b64())
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _avatar(u):
    import base64
    data = base64.b64decode(foto_b64()["image"])
    r = u.c.post("/api/me/avatar", content=data, headers=u._h({"Content-Type": "image/webp"}))
    assert r.status_code in (200, 201), r.text
    return data


def test_zip_sem_cache_e_com_a_foto_de_perfil(usuario):
    assert usuario.get("/export/fotos.zip").status_code == 404
    data = _avatar(usuario)
    r = usuario.get("/export/fotos.zip")   # só a foto de perfil já dá zip
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    _foto(usuario)
    r = usuario.get("/export/fotos.zip")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    perfil = [n for n in z.namelist() if n.startswith("perfil/")]
    assert len(perfil) == 1 and z.read(perfil[0]) == data
    assert len(z.namelist()) == 2


def test_foto_e_avatar_com_vary_cookie(usuario):
    pid = _foto(usuario)
    _avatar(usuario)
    for path in (f"/photos/{pid}", f"/photos/{pid}?thumb=true", f"/me/avatar/{uid_de(usuario)}"):
        r = usuario.get(path)
        assert r.status_code == 200, path
        assert "cookie" in r.headers["vary"].lower(), path
        assert r.headers["cache-control"] == "private, max-age=86400"


def _views(what=None):
    rows = db.query_all("SELECT after->>'what' AS what, entity_id FROM audit_log WHERE action = 'master.view' ORDER BY id")
    return [r for r in rows if what is None or r["what"] == what]


def test_foto_aberta_pelo_master_vai_para_o_log(admin, usuario):
    pid = _foto(usuario)
    usuario.put("/me/viewers", {"accept": True})
    assert admin.put("/admin/master/roles", {"viewer": True}).status_code == 200
    master = type(admin)()
    from conftest import ADMIN_PW
    master.login(admin.me["email"], ADMIN_PW)   # sessão nova, já com o papel
    assert master.get(f"/photos/{pid}?thumb=true").status_code == 200
    assert master.get(f"/photos/{pid}").status_code == 200
    v = _views("fotos")
    assert len(v) == 1 and v[0]["entity_id"] == uid_de(usuario)   # uma linha por pessoa e por dia
    # A dona abrindo a própria foto não gera nada.
    assert usuario.get(f"/photos/{pid}").status_code == 200
    assert len(_views("fotos")) == 1


def test_log_do_master_usa_o_dia_do_app(admin, usuario, monkeypatch):
    """22h de Brasília já é o dia seguinte em UTC: a linha de ontem (dia do app)
    não pode esconder a de hoje, e a de hoje cedo (ainda "ontem" em UTC) vale."""
    usuario.put("/me/viewers", {"accept": True})
    viewer = {"user_id": uid_de(admin), "email": admin.me["email"], "roles": ["admin", "viewer"]}
    alvo = uid_de(usuario)
    visibility.log_master_view(viewer, alvo, "quadro")
    assert len(_views("quadro")) == 1
    visibility.log_master_view(viewer, alvo, "quadro")
    assert len(_views("quadro")) == 1                       # mesmo dia: uma linha só
    # A linha foi gravada "ontem às 22h de Brasília" (01h UTC de hoje no relógio do banco).
    from app.services import app_today, app_tz
    ontem_22h = datetime.combine(app_today() - timedelta(days=1), datetime.min.time(), app_tz()).replace(hour=22)
    db.execute("UPDATE audit_log SET created_at = %s WHERE action = 'master.view'", (ontem_22h.astimezone(timezone.utc),))
    visibility.log_master_view(viewer, alvo, "quadro")
    assert len(_views("quadro")) == 2                       # dia novo do app: linha nova
    # E a de hoje à 00h30 de Brasília continua valendo para o resto do dia.
    hoje_0030 = datetime.combine(app_today(), datetime.min.time(), app_tz()).replace(minute=30)
    db.execute("UPDATE audit_log SET created_at = %s WHERE id = (SELECT max(id) FROM audit_log WHERE action = 'master.view')",
               (hoje_0030.astimezone(timezone.utc),))
    visibility.log_master_view(viewer, alvo, "quadro")
    assert len(_views("quadro")) == 2


# ------------------------------------------------- quadro de quem acompanha --

def test_quadro_do_visualizador_sem_cronometro_nem_lembrete(admin, cena):
    chefe, ana, _ = cena
    tid = ana.post("/worklog", {"title": "Com lembrete"}).json()["id"]
    quando = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert ana.patch(f"/worklog/{tid}", {"remind_at": quando}).status_code == 200
    assert ana.post("/timer/start", {"task_id": tid}).status_code in (200, 201)
    meu = ana.get("/board").json()
    assert meu["timer"] and any(t.get("remind_at") for t in meu["in_progress"])
    b = chefe.get(f"/viewer/users/{uid_de(ana)}/board")
    assert b.status_code == 200
    b = b.json()
    assert b["timer"] is None
    tarefas = b["in_progress"] + b["done"] + b["recurring"]
    assert tarefas and any(t["id"] == tid for t in b["in_progress"])
    for t in tarefas:
        assert not ({"remind_at", "first_on", "touched_at"} & set(t)), t
    # O painel manda só o dia da última atividade, sem a hora.
    p = next(x for x in chefe.get("/viewer/team").json()["people"] if x["id"] == uid_de(ana))
    assert p["last_activity"] and date.fromisoformat(p["last_activity"])


def test_atencao_sem_as_tarefas_de_quem_olha_e_com_o_total(admin, cena):
    chefe, ana, bia = cena
    chefe.put("/me/viewers", {"accept": True})    # o chefe também tem registro e é visível para si
    amanha = (date.today() + timedelta(days=1)).isoformat()
    minha = chefe.post("/worklog", {"title": "Minha, vencendo", "due_date": amanha}).json()["id"]
    for i in range(9):
        assert ana.post("/worklog", {"title": f"Vencendo {i}", "due_date": amanha}).status_code == 201
    t = chefe.get("/viewer/team").json()
    assert len(t["attention"]) == 6
    assert t["attention_total"] == 9
    assert all(x["user_id"] == uid_de(ana) for x in t["attention"])
    assert minha not in [x["task_id"] for x in t["attention"]]


# ------------------------------------------------------- excluir conta --

def test_excluir_conta_conta_os_vencimentos_da_equipe(admin, cena):
    chefe, ana, bia = cena
    tid = _equipe(admin, "Campo", chefe, ana)
    em30 = (date.today() + timedelta(days=30)).isoformat()
    assert ana.post("/renewals", {"label": "Certificado", "expires_on": em30, "team_id": tid}).status_code == 201
    assert ana.post("/renewals", {"label": "Domínio", "expires_on": em30, "team_id": tid}).status_code == 201
    assert ana.post("/renewals", {"label": "Só meu", "expires_on": em30}).status_code == 201
    linha = next(u for u in admin.get("/admin/users").json() if u["email"] == "ana@example.com")
    assert linha["shared_renewals"] == [{"team": "Campo", "count": 2}]
    assert next(u for u in admin.get("/admin/users").json() if u["email"] == "bia@example.com")["shared_renewals"] == []
    r = admin.post(f"/admin/users/{uid_de(ana)}/delete", {"confirm_email": "ana@example.com"})
    assert r.status_code == 200, r.text
    assert r.json()["renewals"] == 3 and r.json()["shared_renewals"] == 2
    log = db.query_one("SELECT before FROM audit_log WHERE action = 'user.delete' ORDER BY id DESC LIMIT 1")["before"]
    assert log["shared_renewals"] == 2


def test_transferir_para_quem_atribuiu_zera_o_atribuida_por(admin, cena):
    chefe, ana, bia = cena
    r = chefe.post("/assign", {"user_id": uid_de(ana), "title": "Do chefe para Ana"})
    assert r.status_code == 201, r.text
    de_outro = ana.post("/worklog", {"title": "Da própria Ana"}).json()["id"]
    r = admin.post(f"/admin/users/{uid_de(ana)}/block", {"transfer_to": uid_de(chefe)})
    assert r.status_code == 200 and r.json()["transferred"]["count"] >= 2
    rows = db.query_all("SELECT title, assigned_by, assigned_at FROM worklog_tasks WHERE user_id = %s", (uid_de(chefe),))
    assert {x["title"] for x in rows} >= {"Do chefe para Ana", "Da própria Ana"}
    assert all(x["assigned_by"] is None and x["assigned_at"] is None for x in rows)
    assert not [t for t in chefe.get("/assign/sent").json() if t.get("title") == "Do chefe para Ana"]
    assert de_outro


def test_transferir_para_outra_pessoa_mantem_quem_atribuiu(admin, cena):
    chefe, ana, bia = cena
    assert chefe.post("/assign", {"user_id": uid_de(ana), "title": "Do chefe para Ana"}).status_code == 201
    assert admin.post(f"/admin/users/{uid_de(ana)}/block", {"transfer_to": uid_de(bia)}).status_code == 200
    row = db.query_one("SELECT assigned_by, assigned_at FROM worklog_tasks WHERE user_id = %s AND title = 'Do chefe para Ana'",
                       (uid_de(bia),))
    assert row["assigned_by"] == uid_de(chefe) and row["assigned_at"] is not None


# ------------------------------------------------- reset com senha temporária --

def test_reset_com_senha_temporaria_avisa_a_pessoa_por_email(admin, usuario, caixa):
    caixa.clear()
    r = admin.post(f"/admin/users/{uid_de(usuario)}/reset-password", {"method": "temp"})
    assert r.status_code == 200 and r.json()["notified"] is True
    senha = r.json()["temp_password"]
    avisos = [m for m in caixa if m[0] == usuario.me["email"]]
    assert len(avisos) == 1
    _, assunto, corpo = avisos[0]
    assert "redefinida" in assunto
    assert senha not in corpo and senha not in assunto
    assert "administra" in corpo and str(date.today().year) in corpo


def test_reset_com_senha_temporaria_sem_email_nao_avisa(admin, usuario, monkeypatch):
    enviados = []
    monkeypatch.setattr(mailer, "configured", lambda: False)
    monkeypatch.setattr(mailer, "send", lambda *a, **k: enviados.append(a))
    r = admin.post(f"/admin/users/{uid_de(usuario)}/reset-password", {"method": "temp"})
    assert r.status_code == 200 and r.json()["notified"] is False and not enviados
