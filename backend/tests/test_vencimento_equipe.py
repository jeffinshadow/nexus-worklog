"""Vencimentos compartilhados com uma equipe (sql/044, pedido do dono 02/11): quem é da
equipe vê, renova e vira tarefa na própria conta; só quem criou edita e exclui; o aviso
vai a cada membro uma vez; sem equipe nada muda; quem não é da equipe não alcança nada
por id (app, API e MCP)."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import agenda, db, notify
from app.config import config
from conftest import Bearer, criar_chave, dia_hoje, hist, texto, uid_de


def _equipe(admin, nome, *membros):
    r = admin.post("/admin/teams", {"name": nome, "member_ids": [uid_de(m) for m in membros]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _agora(dia, hh=10):
    return datetime.combine(dia, time(hh, 0), tzinfo=ZoneInfo(config.APP_TZ))


@pytest.fixture
def cena(admin, novo_usuario):
    """Ana (cria), Bia (da equipe), Caio (de fora) e a equipe "Infra" com Ana e Bia."""
    ana, bia, caio = novo_usuario("ana@example.com"), novo_usuario("bia@example.com"), novo_usuario("caio@example.com")
    tid = _equipe(admin, "Infra", ana, bia)
    hoje = dia_hoje(ana)
    rid = ana.post("/renewals", {"label": "Certificado do site", "expires_on": (hoje + timedelta(days=5)).isoformat(), "warn_days": 5,
                                 "team_id": tid}).json()["id"]
    return {"ana": ana, "bia": bia, "caio": caio, "tid": tid, "rid": rid, "hoje": hoje, "admin": admin}


def test_visibilidade_membro_nao_membro_e_ao_sair(cena):
    ana, bia, caio, rid = cena["ana"], cena["bia"], cena["caio"], cena["rid"]
    da_ana = ana.get("/renewals").json()[0]
    assert da_ana["mine"] and da_ana["team_name"] == "Infra" and da_ana["owner_name"] is None
    da_bia = bia.get("/renewals").json()
    assert [r["id"] for r in da_bia] == [rid]
    assert da_bia[0]["team_name"] == "Infra" and not da_bia[0]["mine"] and da_bia[0]["owner_name"] == "Ana"
    assert da_bia[0]["project_id"] is None and da_bia[0]["warning"]
    assert caio.get("/renewals").json() == []
    # Sair da equipe = deixa de ver (o admin tira a Bia).
    r = cena["admin"].patch(f"/admin/teams/{cena['tid']}", {"member_ids": [uid_de(ana)]})
    assert r.status_code == 200, r.text
    assert bia.get("/renewals").json() == []
    assert bia.patch(f"/renewals/{rid}", {"expires_on": "2031-01-01"}).status_code == 404
    assert [r["id"] for r in ana.get("/renewals").json()] == [rid]


def test_so_quem_criou_edita_e_exclui(cena):
    ana, bia, rid = cena["ana"], cena["bia"], cena["rid"]
    for corpo in ({"label": "Outro"}, {"warn_days": 3}, {"team_id": None}, {"note": "x"}, {"expires_on": "2031-01-01", "label": "x"}):
        assert bia.patch(f"/renewals/{rid}", corpo).status_code == 403, corpo
    assert bia.delete(f"/renewals/{rid}").status_code == 403
    assert len(ana.get("/renewals").json()) == 1 and ana.get("/renewals").json()[0]["label"] == "Certificado do site"
    assert ana.patch(f"/renewals/{rid}", {"label": "Certificado novo", "warn_days": 7}).status_code == 200
    assert ana.delete(f"/renewals/{rid}").status_code == 200
    assert bia.get("/renewals").json() == []


def test_renovei_do_membro_vai_para_o_historico_de_quem_criou(cena):
    ana, bia, rid, hoje = cena["ana"], cena["bia"], cena["rid"], cena["hoje"]
    nova = (hoje + timedelta(days=370)).isoformat()
    assert bia.patch(f"/renewals/{rid}", {"expires_on": nova}).status_code == 200
    assert ana.get("/renewals").json()[0]["expires_on"] == nova
    h = hist(ana, entity="renewal", entity_id=rid)[0]
    assert "Bia" in h["summary"] and "renovou" in h["summary"]
    # Quem criou desfaz (volta a data antiga).
    assert ana.post(f"/history/{h['id']}/undo").status_code == 200
    assert ana.get("/renewals").json()[0]["days_left"] == 5


def test_virar_tarefa_cai_na_conta_de_cada_um(cena):
    ana, bia, rid = cena["ana"], cena["bia"], cena["rid"]
    exp = bia.get("/renewals").json()[0]["expires_on"]
    ref = f"renewal:{rid}:{exp}"
    # O app manda project_id nulo (o projeto é de quem criou) e a chave da tarefa.
    t = bia.post("/worklog", {"title": "Renovar: Certificado do site", "due_date": exp, "external_ref": ref}).json()
    assert bia.get(f"/worklog/{t['id']}").json()["title"] == "Renovar: Certificado do site"
    again = bia.post("/worklog", {"title": "Renovar: Certificado do site", "due_date": exp, "external_ref": ref}).json()
    assert again["id"] == t["id"] and again["existing"]                # não duplica para a mesma pessoa
    assert ana.get(f"/worklog/{t['id']}").status_code == 404           # não foi para a conta da Ana
    t2 = ana.post("/worklog", {"title": "Renovar: Certificado do site", "due_date": exp, "external_ref": ref}).json()
    assert t2["id"] != t["id"]                                          # cada um tem a sua


def test_aviso_uma_vez_por_membro_e_no_email_da_manha(cena, admin):
    ana, bia, caio, hoje = cena["ana"], cena["bia"], cena["caio"], cena["hoje"]
    for u in (ana, bia, caio):
        criar_chave(u)  # a agenda só olha quem tem chave ou webhook
    feitos = agenda.run_once(_agora(hoje))
    assert sorted(u for u, _ in feitos) == sorted([uid_de(ana), uid_de(bia)])
    assert agenda.run_once(_agora(hoje, 11)) == []                      # sem duplicar
    for u, esperado in ((ana, 1), (bia, 1), (caio, 0)):
        n = db.query_one("SELECT count(*) AS n FROM audit_log WHERE user_id = %s AND action = 'renewal.warning'", (uid_de(u),))["n"]
        assert n == esperado
    for u, tem in ((ana, True), (bia, True), (caio, False)):
        m = notify.build_morning(uid_de(u), hoje, True)
        assert tem == any(h == "Vencimentos" and any("Certificado do site" in i for i in itens) for h, itens in m.blocks)
    ics = bia.c.get(bia.post("/calendar", {}).json()["path"]).text.replace("\r\n ", "")
    assert "Vence: Certificado do site" in ics


def test_so_as_equipes_dele_e_campo_some_sem_equipes(admin, novo_usuario, cena):
    ana, caio, bia = cena["ana"], cena["caio"], cena["bia"]
    outra = _equipe(admin, "Redes", caio)
    exp = (cena["hoje"] + timedelta(days=60)).isoformat()
    assert [t["name"] for t in ana.get("/renewals/teams").json()["teams"]] == ["Infra"]
    assert ana.post("/renewals", {"label": "x", "expires_on": exp, "team_id": outra}).status_code == 400
    rid = ana.post("/renewals", {"label": "y", "expires_on": exp}).json()["id"]
    assert ana.patch(f"/renewals/{rid}", {"team_id": outra}).status_code == 400
    assert ana.patch(f"/renewals/{rid}", {"team_id": cena["tid"]}).status_code == 200
    assert ana.patch(f"/renewals/{rid}", {"team_id": None}).status_code == 200
    assert [r["label"] for r in bia.get("/renewals").json()] == ["Certificado do site"]
    # O admin master escolhe qualquer equipe.
    assert {t["name"] for t in admin.get("/renewals/teams").json()["teams"]} == {"Infra", "Redes"}
    assert admin.post("/renewals", {"label": "z", "expires_on": exp, "team_id": outra}).status_code == 201


def test_instancia_sem_equipes_nao_muda(usuario, novo_usuario):
    hoje = dia_hoje(usuario)
    assert usuario.get("/renewals/teams").json() == {"teams": []}
    exp = (hoje + timedelta(days=3)).isoformat()
    assert usuario.post("/renewals", {"label": "Domínio", "expires_on": exp, "team_id": 1}).status_code == 400
    rid = usuario.post("/renewals", {"label": "Domínio", "expires_on": exp}).json()["id"]
    r = usuario.get("/renewals").json()[0]
    assert r["team_id"] is None and r["team_name"] is None and r["mine"]
    assert novo_usuario("outro@example.com").get("/renewals").json() == []
    assert usuario.delete(f"/renewals/{rid}").status_code == 200


def test_equipe_excluida_ou_arquivada_volta_a_ser_so_de_quem_criou(cena):
    ana, bia, admin, tid = cena["ana"], cena["bia"], cena["admin"], cena["tid"]
    assert admin.patch(f"/admin/teams/{tid}", {"archived": True}).status_code == 200
    assert bia.get("/renewals").json() == []
    r = ana.get("/renewals").json()[0]
    assert r["team_name"] is None
    db.execute("DELETE FROM teams WHERE id = %s", (tid,))
    assert ana.get("/renewals").json()[0]["team_id"] is None


def test_idor_nao_membro_por_id_app_api_e_mcp(cena):
    ana, bia, caio, rid = cena["ana"], cena["bia"], cena["caio"], cena["rid"]
    assert caio.patch(f"/renewals/{rid}", {"expires_on": "2031-01-01"}).status_code == 404
    assert caio.delete(f"/renewals/{rid}").status_code == 404
    assert caio.patch(f"/renewals/{rid}", {"label": "invadido"}).status_code == 404
    chave_caio = Bearer(criar_chave(caio)["token"])
    assert chave_caio.delete(f"/renewals/{rid}").status_code == 404
    assert "Certificado do site" not in texto(chave_caio.tool("list_renewals"))
    # O membro vê pelo MCP, marcado como equipe e só leitura.
    t = texto(Bearer(criar_chave(bia)["token"]).tool("list_renewals"))
    assert "Certificado do site" in t and "equipe Infra, de Ana" in t
    assert len(ana.get("/renewals").json()) == 1
