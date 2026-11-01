"""Pacotes de rotina por área: lista fixa, aplicar cria projeto + rotinas, sem duplicar."""
from conftest import Bearer, criar_chave, hist, texto


def _pacote(u, pid):
    return next(p for p in u.get("/routine-packs").json() if p["id"] == pid)


def _rotinas(u):
    return {r["label"]: r for r in u.get("/board").json()["recurring"]}


def test_lista_tem_as_areas_com_agenda_e_horario(usuario):
    packs = usuario.get("/routine-packs").json()
    assert [p["id"] for p in packs] == ["manutencao", "ti", "atendimento", "campo", "seguranca"]
    for p in packs:
        assert p["name"] and p["description"] and p["project"] == {"name": p["name"], "icon": p["icon"]}
        assert 3 <= len(p["items"]) <= 6
        keys = [i["key"] for i in p["items"]]
        assert len(keys) == len(set(keys))
        for i in p["items"]:
            assert i["remind_at"] and i["exists"] is False
            assert i["freq"] in ("daily", "weekly", "monthly")
            assert (i["weekdays"] is not None) == (i["freq"] == "weekly")
            assert (i["month_day"] is not None) == (i["freq"] == "monthly")
    # Fora de TI, nada de jargão de TI.
    jargao = ("backup", "servidor", "vpn", "chamado", "log")
    for pid in ("manutencao", "atendimento"):
        txt = " ".join(i["label"].lower() for i in _pacote(usuario, pid)["items"])
        assert not any(j in txt for j in jargao)


def test_lista_exige_login(usuario):
    from conftest import Api
    assert Api().get("/routine-packs").status_code in (401, 403)


def test_aplicar_cria_projeto_com_icone_e_rotinas_com_agenda(usuario):
    r = usuario.post("/routine-packs/manutencao/apply", {})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["project"]["created"] is True and res["project"]["icon"] == "manutencao"
    assert res["project"]["name"] == "Manutenção predial" and res["skipped"] == []
    proj = next(p for p in usuario.get("/projects").json() if p["id"] == res["project"]["id"])
    assert proj["icon"] == "manutencao" and proj["description"]
    rot = _rotinas(usuario)
    assert len(rot) == 5
    ronda = rot["Fazer a ronda do prédio"]
    assert ronda["freq"] == "daily" and ronda["remind_at"].startswith("08:00") and not ronda["require_note"]
    quadro = rot["Conferir o quadro elétrico (aquecimento e disjuntores)"]
    assert quadro["freq"] == "weekly" and quadro["weekdays"] == 2 and quadro["remind_at"].startswith("09:00")
    ext = rot["Conferir os extintores (validade e lacre)"]
    assert ext["freq"] == "monthly" and ext["month_day"] == 1 and ext["require_note"] is True
    # Cada criação entra no histórico (desfaz uma a uma).
    acoes = [x["action"] for x in hist(usuario, limit=20)]
    assert acoes.count("recurring.create") == 5 and acoes.count("project.create") == 1


def test_aplicar_so_os_itens_marcados_e_sem_projeto(usuario):
    res = usuario.post("/routine-packs/ti/apply", {"items": ["backups", "atualizacoes"], "project": False}).json()
    assert res["project"] is None and len(res["created"]) == 2
    assert usuario.get("/projects").json() == []
    rot = _rotinas(usuario)
    assert set(rot) == {"Conferir os backups da noite", "Aplicar as atualizações pendentes"}
    assert rot["Conferir os backups da noite"]["require_note"] is True
    assert rot["Aplicar as atualizações pendentes"]["weekdays"] == 32  # sexta


def test_idempotente_nao_duplica(usuario):
    usuario.post("/recurring", {"label": "conferir a AGENDA do dia"})  # já tinha, com outra grafia
    primeiro = usuario.post("/routine-packs/atendimento/apply", {}).json()
    assert primeiro["skipped"] == ["Conferir a agenda do dia"] and len(primeiro["created"]) == 3
    assert next(i for i in _pacote(usuario, "atendimento")["items"] if i["key"] == "retorno")["exists"] is True
    segundo = usuario.post("/routine-packs/atendimento/apply", {}).json()
    assert segundo["created"] == [] and len(segundo["skipped"]) == 4
    assert segundo["project"]["created"] is False and segundo["project"]["id"] == primeiro["project"]["id"]
    assert len(usuario.get("/projects").json()) == 1 and len(_rotinas(usuario)) == 4


def test_projeto_arquivado_volta_e_nome_parecido_e_reaproveitado(usuario):
    pid = usuario.post("/projects", {"name": "segurança da informação"}).json()["id"]
    usuario.patch(f"/projects/{pid}", {"archived": True})
    res = usuario.post("/routine-packs/seguranca/apply", {"items": []}).json()
    assert res["project"]["id"] == pid and res["project"]["created"] is False and res["created"] == []
    assert next(p for p in usuario.get("/projects").json() if p["id"] == pid)["archived"] is False


def test_erros(usuario):
    assert usuario.post("/routine-packs/nada/apply", {}).status_code == 404
    r = usuario.post("/routine-packs/ti/apply", {"items": ["ronda"]})
    assert r.status_code == 400 and "ronda" in r.json()["detail"]
    assert usuario.post("/routine-packs/ti/apply", {"items": [], "project": False}).status_code == 400
    sem_csrf = usuario.c.post("/api/routine-packs/ti/apply", json={})
    assert sem_csrf.status_code == 403
    assert _rotinas(usuario) == {}


def test_pacotes_pela_ia(usuario):
    b = Bearer(criar_chave(usuario)["token"])
    lista = texto(b.tool("list_routine_packs"))
    assert "manutencao: Manutenção predial" in lista and "extintores:" in lista and "todo mês, dia 1" in lista
    res = b.tool("apply_routine_pack", pack="campo", items=["links", "filiais"])
    assert not res["isError"]
    t = texto(res)
    assert "Projeto criado" in t and "ícone rede" in t and "toda seg, qui" in t and "às 08:00" in t
    de_novo = texto(b.tool("apply_routine_pack", pack="campo", items=["links"]))
    assert "reaproveitado" in de_novo and "nada duplicado" in de_novo
    assert "[já existe]" in texto(b.tool("list_routine_packs"))
    assert b.tool("apply_routine_pack", pack="xyz")["isError"]
    leitura = Bearer(criar_chave(usuario, nome="r", scope="read")["token"])
    nomes = {t["name"] for t in leitura.rpc("tools/list").json()["result"]["tools"]}
    assert "list_routine_packs" in nomes and "apply_routine_pack" not in nomes
