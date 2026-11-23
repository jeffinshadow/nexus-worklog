"""Rodada 2, pacote 08: ordem alfabética com acentos no visualizador e nas
equipes; pausar rotina com trava; frases e pausas do desfazer de rotina."""
import threading
import time
from datetime import timedelta

from app import db
from app.routers import recurring as rec
from conftest import Api, SENHA_PADRAO, dia_hoje, hist, recuar_criacao, uid_de

NOMES = ["Água", "almoxarifado", "Zeladoria"]  # a ordem certa; lower() punha "Água" no fim


def _so(nomes):
    return [n for n in nomes if n in NOMES]


def _ultima(u, action, **kw):
    return next(h for h in hist(u, limit=200, **kw) if h["action"] == action)


def _cobrem_hoje(rid, hoje):
    return db.query_all("""SELECT id, end_d FROM recurring_pauses
                            WHERE recurring_id = %s AND start_d <= %s AND end_d >= %s ORDER BY id""", (rid, hoje, hoje))


# ------------------------------------------------------ ordem com acentos --
def test_pessoas_do_visualizador_do_painel_e_da_equipe_em_ordem_com_acento(admin, novo_usuario):
    ids = []
    for i, nome in enumerate(("Zeladoria", "almoxarifado", "Água")):
        u = novo_usuario(f"p{i}@example.com")
        assert u.put("/me/profile", {"display_name": nome}).status_code == 200
        assert u.put("/me/viewers", {"accept": True}).status_code == 200
        ids.append(uid_de(u))
    # Seletor de pessoas e cartões do painel da Equipe.
    assert _so(p["name"] for p in admin.get("/viewer/users").json()) == NOMES
    assert _so(p["name"] for p in admin.get("/viewer/team").json()["people"]) == NOMES
    # Membros de uma equipe (Admin › Equipes), na criação e na lista.
    r = admin.post("/admin/teams", {"name": "Predial", "member_ids": ids})
    assert r.status_code == 201, r.text
    assert [m["name"] for m in r.json()["members"]] == NOMES
    equipe = next(t for t in admin.get("/admin/teams").json() if t["name"] == "Predial")
    assert [m["name"] for m in equipe["members"]] == NOMES


def test_projetos_da_pessoa_no_visualizador_em_ordem_com_acento(admin, usuario):
    assert usuario.put("/me/viewers", {"accept": True}).status_code == 200
    for nome in ("Zeladoria", "almoxarifado", "Água"):
        assert usuario.post("/projects", {"name": nome}).status_code == 201
    r = admin.get(f"/viewer/users/{uid_de(usuario)}/projects")
    assert r.status_code == 200, r.text
    assert _so(p["name"] for p in r.json()) == NOMES


# ------------------------------------------------------- corrida do pausar --
def test_duas_pausas_ao_mesmo_tempo_deixam_um_periodo_so(usuario, monkeypatch):
    hoje = dia_hoje(usuario)
    rid = usuario.post("/recurring", {"label": "Ronda"}).json()["id"]
    outra = Api()
    outra.login(usuario.me["email"], SENHA_PADRAO)
    # Alarga a janela entre ler "está pausada?" e gravar: sem a trava na rotina, as
    # duas leem "não" e cada uma cria o seu período.
    ler = rec.current_pause

    def devagar(*a):
        cur = ler(*a)
        time.sleep(0.4)
        return cur
    monkeypatch.setattr(rec, "current_pause", devagar)

    fins = [(hoje + timedelta(days=d)).isoformat() for d in (5, 9)]
    largada, res = threading.Barrier(2), [None, None]

    def ir(i, api):
        largada.wait()
        res[i] = api.post(f"/recurring/{rid}/pause", {"until": fins[i]})
    ts = [threading.Thread(target=ir, args=(i, api)) for i, api in enumerate((usuario, outra))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert [r.status_code for r in res] == [200, 200]
    pausas = _cobrem_hoje(rid, hoje)
    assert len(pausas) == 1, pausas  # a segunda só mudou o fim da primeira
    assert pausas[0]["end_d"].isoformat() in fins
    # E o histórico conta a mesma história: uma pausa nova, uma mudança de fim.
    antes = [r["before"]["pause"] for r in db.query_all(
        "SELECT before FROM audit_log WHERE action = 'recurring.pause' AND entity_id = %s", (rid,))]
    assert len(antes) == 2 and sum(p is None for p in antes) == 1


# ------------------------------------------------------ frases do desfazer --
def test_edicao_anterior_a_troca_antiga_nao_manda_desfazer_a_troca(usuario):
    rid = usuario.post("/recurring", {"label": "Triagem"}).json()["id"]
    recuar_criacao(rid, 30)
    assert usuario.patch(f"/recurring/{rid}", {"label": "Triagem renomeada"}).status_code == 200
    novo = usuario.patch(f"/recurring/{rid}", {"freq": "weekly", "weekdays": 42}).json()
    assert novo["replaced"] == rid
    ren = _ultima(usuario, "recurring.update", entity="recurring", entity_id=rid)
    troca = _ultima(usuario, "recurring.replace")

    # Troca recente: ainda dá para desfazê-la, e a frase manda fazer isso.
    r = usuario.post(f"/history/{ren['id']}/undo")
    assert r.status_code == 409 and "desfaça a troca primeiro" in r.json()["detail"]

    # Troca há mais de 7 dias: ela mesma já não tem desfazer.
    db.execute("UPDATE audit_log SET created_at = created_at - interval '8 days' WHERE id IN (%s, %s)", (ren["id"], troca["id"]))
    r = usuario.post(f"/history/{troca['id']}/undo")
    assert r.status_code == 409 and "janela de 7 dias" in r.json()["detail"]
    r = usuario.post(f"/history/{ren['id']}/undo")
    assert r.status_code == 409
    assert r.json()["detail"] == "a agenda desta rotina foi trocada há mais de 7 dias; esta alteração não pode mais ser desfeita"
    assert db.query_one("SELECT undone_at FROM audit_log WHERE id = %s", (ren["id"],))["undone_at"] is None


# ------------------------------------------------- desfazer de "Retomar" --
def _duas_pausas_retomadas(usuario):
    hoje = dia_hoje(usuario)
    rid = usuario.post("/recurring", {"label": "Ronda"}).json()["id"]
    assert usuario.post(f"/recurring/{rid}/pause", {"until": (hoje + timedelta(days=10)).isoformat()}).status_code == 200
    # A segunda pausa que duas chamadas simultâneas deixavam (antes da trava).
    db.execute("INSERT INTO recurring_pauses (recurring_id, start_d, end_d) VALUES (%s, %s, %s)",
               (rid, hoje, hoje + timedelta(days=17)))
    antes = _cobrem_hoje(rid, hoje)
    assert len(antes) == 2
    assert usuario.delete(f"/recurring/{rid}/pause").status_code == 200
    assert not _cobrem_hoje(rid, hoje)
    return rid, hoje, antes, _ultima(usuario, "recurring.resume", entity="recurring", entity_id=rid)


def test_desfazer_retomar_reabre_todas_as_pausas_fechadas(usuario):
    rid, hoje, antes, h = _duas_pausas_retomadas(usuario)
    # O `pause` de sempre (a mais recente) continua lá; `pauses` traz todas.
    before = db.query_one("SELECT before FROM audit_log WHERE id = %s", (h["id"],))["before"]
    assert before["pause"]["id"] == antes[-1]["id"]
    assert sorted(p["id"] for p in before["pauses"]) == [p["id"] for p in antes]
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert _cobrem_hoje(rid, hoje) == antes  # as duas, cada uma com o fim que tinha


def test_desfazer_retomar_de_linha_antiga_reabre_a_mais_recente(usuario):
    rid, hoje, antes, h = _duas_pausas_retomadas(usuario)
    db.execute("UPDATE audit_log SET before = before - 'pauses' WHERE id = %s", (h["id"],))  # como era gravado antes
    assert usuario.post(f"/history/{h['id']}/undo").status_code == 200
    assert _cobrem_hoje(rid, hoje) == [antes[-1]]
