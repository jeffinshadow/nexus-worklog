"""Auditoria p16: a busca exige todas as palavras, em qualquer ordem e campo."""


def _ids(c, q):
    return [t["id"] for t in c.get("/search?q=" + q.replace(" ", "%20").replace("#", "%23")).json()["tasks"]]


def test_busca_por_palavras_em_qualquer_ordem(usuario, novo_usuario):
    sw = usuario.post("/worklog", {"title": "Trocar o switch do rack 2"}).json()["id"]
    bk = usuario.post("/worklog", {"title": "Testar a restauração do backup do ERP"}).json()["id"]
    usuario.post("/worklog", {"title": "Backup do servidor de arquivos"})

    assert _ids(usuario, "switch rack") == [sw]
    assert _ids(usuario, "rack switch") == [sw]
    assert _ids(usuario, "backup ERP") == [bk]
    assert _ids(usuario, "restauração backup") == [bk]
    # Acentos, maiúsculas e espaços a mais não importam.
    assert _ids(usuario, "RESTAURACAO   Backup") == [bk]
    assert _ids(usuario, "backup  érp") == [bk]
    # Uma palavra que não existe zera, mesmo com a outra presente.
    r = usuario.get("/search?q=backup%20impressora").json()
    assert r["tasks"] == [] and r["total_tasks"] == 0
    # Página além do fim: lista vazia, total certo (contagem com as mesmas palavras).
    r = usuario.get("/search?q=switch%20rack&offset=5").json()
    assert r["tasks"] == [] and r["total_tasks"] == 1
    # Outra pessoa não acha.
    outro = novo_usuario("outro-p16@example.com")
    assert _ids(outro, "switch rack") == [] and _ids(outro, "backup ERP") == []


def test_busca_palavras_em_campos_diferentes(usuario):
    tid = usuario.post("/worklog", {"title": "Impressora do financeiro"}).json()["id"]
    usuario.post(f"/worklog/{tid}/notes", {"body": "Troquei o fusor e limpei o rolete"})
    usuario.post(f"/worklog/{tid}/checklist", {"label": "Pedir toner reserva"})
    outra = usuario.post("/worklog", {"title": "Impressora da recepção"}).json()["id"]
    usuario.post(f"/worklog/{outra}/notes", {"body": "Sem papel"})

    r = usuario.get("/search?q=impressora%20fusor").json()
    assert [t["id"] for t in r["tasks"]] == [tid] and r["total_tasks"] == 1
    kinds = {h["kind"] for h in r["tasks"][0]["hits"]}
    assert {"título", "anotação"} <= kinds
    # Três campos: título, anotação e checklist.
    assert _ids(usuario, "financeiro rolete toner") == [tid]
    # As duas palavras existem, mas em tarefas diferentes: nada.
    assert _ids(usuario, "fusor papel") == []
    assert _ids(usuario, "recepção fusor") == []


def test_busca_frase_exata_primeiro(usuario):
    # Aberta e urgente, com as palavras soltas: viria primeiro pela ordem antiga.
    solta = usuario.post("/worklog", {"title": "Rack novo: ligar o switch", "priority": 1}).json()["id"]
    exata = usuario.post("/worklog", {"title": "Etiquetar switch rack B", "priority": 3}).json()["id"]
    nota = usuario.post("/worklog", {"title": "Sala técnica", "priority": 3}).json()["id"]
    usuario.post(f"/worklog/{nota}/notes", {"body": "faltou o switch rack no inventário"})

    ids = _ids(usuario, "switch rack")
    assert set(ids[:2]) == {exata, nota} and ids[2] == solta
    # Ordem invertida: ninguém tem a frase exata, mas todas voltam.
    assert set(_ids(usuario, "rack switch")) == {solta, exata, nota}


def test_busca_uma_palavra_como_antes(usuario):
    a = usuario.post("/worklog", {"title": "Renovar certificado", "ticket": "4321"}).json()["id"]
    b = usuario.post("/worklog", {"title": "Certificados da VPN"}).json()["id"]
    usuario.post("/recurring", {"label": "Conferir backup do ERP"})
    usuario.post("/projects", {"name": "ERP novo"})

    assert set(_ids(usuario, "certificado")) == {a, b}
    assert _ids(usuario, "#4321") == [a]
    assert _ids(usuario, "certificado #4321") == [a]
    assert usuario.get("/search?q=a").status_code == 422
    assert usuario.get("/search?q=%25%25").json()["tasks"] == []
    # Palavras de uma letra não filtram ("o", "a"); só delas, vale a frase.
    assert _ids(usuario, "renovar o certificado") == [a]
    # Rotinas e projetos: todas as palavras no nome.
    r = usuario.get("/search?q=erp%20backup").json()
    assert [x["label"] for x in r["recurring"]] == ["Conferir backup do ERP"] and r["total_recurring"] == 1
    assert r["projects"] == [] and r["total_projects"] == 0
    r = usuario.get("/search?q=novo%20erp").json()
    assert [x["name"] for x in r["projects"]] == ["ERP novo"] and r["recurring"] == []
