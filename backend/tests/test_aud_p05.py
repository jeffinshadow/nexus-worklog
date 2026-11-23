"""Auditoria, pacote p05: exportações e PDF. CSV filtrado por projeto e com as
colunas novas no fim, "exportar tudo" completo, e o PDF de projeto que explica
as horas (tempo por tarefa, tempo do período, tarefa em dois projetos, horário
do cronômetro), com idioma, marcadores, nome de arquivo sem perder acento,
no-store e o limite por quem pede."""
import csv
import io
import re
from datetime import timedelta

import pytest

from app import db, report_pdf
from conftest import dia_hoje, uid_de


def _proj(u, nome):
    return u.post("/projects", {"name": nome}).json()["id"]


def _tarefa(u, titulo, **kw):
    r = u.post("/worklog", {"title": titulo, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _tempo(u, tid, minutos, dia=None, nota=None):
    """Aponta hoje e, se pedido, recua o dia direto no banco (sem depender do limite retroativo)."""
    r = u.post(f"/worklog/{tid}/time", {"minutes": minutos, **({"note": nota} if nota else {})})
    assert r.status_code == 201, r.text
    if dia:
        db.execute("UPDATE time_entries SET day = %s WHERE id = %s", (dia, r.json()["id"]))
    return r.json()["id"]


def _cronometro(u, tid, minutos=5):
    assert u.post("/timer/start", {"task_id": tid}).status_code in (200, 201)
    db.execute("UPDATE task_timers SET started_at = now() - make_interval(mins => %s) WHERE task_id = %s", (minutos, tid))
    r = u.post("/timer/stop")
    assert r.status_code == 200, r.text


def _linhas(resp):
    assert resp.status_code == 200, resp.text
    return list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))


@pytest.fixture
def textos(monkeypatch):
    """Todo texto que o PDF escreve (o fpdf2 grava glifos de um subconjunto da fonte: não dá para procurar nos bytes)."""
    vistos, original = [], report_pdf._s

    def espia(text):
        out = original(text)
        vistos.append(out)
        return out
    monkeypatch.setattr(report_pdf, "_s", espia)
    return vistos


def _min(texto: str) -> int:
    """"7h42" / "1h" / "45 min" -> minutos."""
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)(?: min)?)?", texto.strip())
    assert m and (m.group(1) or m.group(2)), texto
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)


def _tempo_depois(textos, rotulo, de=0) -> int:
    """O primeiro tempo ("1h30", "45 min") escrito depois de `rotulo` (a linha da tabela)."""
    i = textos.index(rotulo, de)
    return _min(next(t for t in textos[i + 1:] if re.fullmatch(r"\d+h\d*|\d+ min", t)))


# ------------------------------------------------------------------- CSV --

def test_csv_filtra_por_projeto_principal_e_extra(usuario, novo_usuario):
    alfa, beta = _proj(usuario, "Alfa"), _proj(usuario, "Beta")
    so_alfa = _tarefa(usuario, "Só da Alfa", project_id=alfa)
    so_beta = _tarefa(usuario, "Só da Beta", project_id=beta)
    conjunta = _tarefa(usuario, "Reunião conjunta", project_id=alfa, extra_project_ids=[beta])
    solta = _tarefa(usuario, "Sem projeto")
    for tid, m in ((so_alfa, 10), (so_beta, 20), (conjunta, 30), (solta, 40)):
        _tempo(usuario, tid, m)
    hoje = dia_hoje(usuario).isoformat()

    # Sem project: como antes, tudo.
    todas = _linhas(usuario.get("/export/apontamentos.csv"))
    assert sorted(l[4] for l in todas[1:]) == ["Reunião conjunta", "Sem projeto", "Só da Alfa", "Só da Beta"]
    assert len(_linhas(usuario.get("/export/tarefas.csv"))) == 5

    # Projeto principal e projeto extra: o mesmo critério do PDF.
    r = usuario.get(f"/export/apontamentos.csv?project={alfa}")
    assert sorted(l[4] for l in _linhas(r)[1:]) == ["Reunião conjunta", "Só da Alfa"]
    assert 'filename="nexus-apontamentos-alfa-' in r.headers["content-disposition"]
    b = _linhas(usuario.get(f"/export/apontamentos.csv?project={beta}&start={hoje}&end={hoje}"))
    assert sorted(l[4] for l in b[1:]) == ["Reunião conjunta", "Só da Beta"]
    assert sum(int(l[1]) for l in b[1:]) == 50
    # A soma do CSV do projeto é o tempo do PDF do projeto (a prévia lê a mesma conta).
    assert usuario.get(f"/reports/preview?project={beta}&start={hoje}&end={hoje}").json()["minutes"] == 50

    t = usuario.get(f"/export/tarefas.csv?project={beta}&start={hoje}&end={hoje}")
    assert sorted(l[1] for l in _linhas(t)[1:]) == ["Reunião conjunta", "Só da Beta"]
    assert f'filename="nexus-tarefas-beta-{hoje}-a-{hoje}.csv"' in t.headers["content-disposition"]

    # Projeto que não existe ou de outra pessoa: 404 (não devolve o CSV inteiro calado).
    outra = novo_usuario("outra@example.com")
    alheio = _proj(outra, "Alheio")
    for kind in ("apontamentos.csv", "tarefas.csv"):
        assert usuario.get(f"/export/{kind}?project={alheio}").status_code == 404
        assert usuario.get(f"/export/{kind}?project=999999").status_code == 404
    # O filtro só vale para os dois CSV: as outras exportações seguem como antes.
    assert usuario.get(f"/export/tudo.json?project={alheio}").status_code == 200


def test_csv_colunas_novas_no_fim(usuario, admin):
    alfa, beta = _proj(usuario, "Alfa"), _proj(usuario, "Beta")
    tid = _tarefa(usuario, "Reunião conjunta", project_id=alfa, extra_project_ids=[beta])
    _tempo(usuario, tid, 15)
    _cronometro(usuario, tid, 5)
    hoje = dia_hoje(usuario).isoformat()

    ap = _linhas(usuario.get("/export/apontamentos.csv"))
    # As dez de sempre, na mesma ordem, e as novas no fim.
    assert ap[0] == ["data", "minutos", "horas", "tarefa_id", "tarefa", "projeto", "observacao", "origem", "chamado",
                     "plantao", "outros_projetos", "inicio", "fim"]
    digitado, crono = sorted(ap[1:], key=lambda l: l[11])
    assert digitado[5] == "Alfa" and digitado[10] == "Beta" and digitado[11:] == ["", ""]
    assert crono[6] == "cronômetro" and re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", crono[11])
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", crono[12]) and crono[11] < crono[12]

    base = ["id", "titulo", "descricao", "status", "prioridade", "projeto", "criada_em", "prazo", "concluida_em",
            "checklist", "minutos", "horas", "anotacoes", "chamado", "plantao", "aguardando", "como_resolveu"]
    ta = _linhas(usuario.get("/export/tarefas.csv"))
    assert ta[0] == base + ["outros_projetos"] and ta[1][-1] == "Beta" and ta[1][5] == "Alfa"
    tp = _linhas(usuario.get(f"/export/tarefas.csv?start={hoje}&end={hoje}"))
    assert tp[0] == base + ["minutos_no_periodo", "horas_no_periodo", "outros_projetos"] and tp[1][-1] == "Beta"

    # O CSV da equipe (mesma função): `usuario` continua onde estava e as novas vêm depois.
    usuario.put("/me/viewers", {"accept": True})
    eq = _linhas(admin.get("/viewer/export/apontamentos.csv"))
    assert eq[0][10:] == ["usuario", "outros_projetos", "inicio", "fim"]


def test_tudo_json_traz_o_que_faltava(usuario, admin):
    uid = uid_de(usuario)
    tid = _tarefa(usuario, "Com lembrete e cronômetro")
    _cronometro(usuario, tid, 5)
    db.execute("UPDATE worklog_tasks SET remind_at = now() + interval '1 day', assigned_at = now(), "
               "assigned_by = (SELECT id FROM users WHERE email = %s) WHERE id = %s", (admin.me["email"], tid))
    rid = usuario.post("/recurring", {"label": "Conferir backup"}).json()["id"]
    hoje = dia_hoje(usuario)
    db.execute("UPDATE recurring_tasks SET steps = %s WHERE id = %s", (["abrir o painel", "anotar o tamanho"], rid))
    db.execute("INSERT INTO recurring_pauses (recurring_id, start_d, end_d) VALUES (%s, %s, %s)",
               (rid, hoje + timedelta(days=10), hoje + timedelta(days=12)))
    db.execute("INSERT INTO week_reviews (user_id, week_start, done_at) VALUES (%s, %s, now())", (uid, hoje - timedelta(days=7)))
    team = db.query_one("INSERT INTO teams (name) VALUES ('Infraestrutura') RETURNING id")["id"]
    db.execute("INSERT INTO team_members (team_id, user_id) VALUES (%s, %s)", (team, uid))

    r = usuario.get("/export/tudo.json")
    assert r.status_code == 200
    d = r.json()
    t = d["tasks"][0]
    assert t["remind_at"] and t["assigned_at"] and t["assigned_by"]
    assert t["time"][0]["started_at"] and t["time"][0]["ended_at"]
    rot = d["recurring"][0]
    assert rot["steps"] == ["abrir o painel", "anotar o tamanho"]
    assert rot["pauses"] == [{"start_d": (hoje + timedelta(days=10)).isoformat(), "end_d": (hoje + timedelta(days=12)).isoformat(),
                              "created_at": rot["pauses"][0]["created_at"]}]
    assert [w["week_start"] for w in d["week_reviews"]] == [(hoje - timedelta(days=7)).isoformat()] and d["week_reviews"][0]["done_at"]
    assert d["teams"] == ["Infraestrutura"] and d["roles"] == ["user"]
    # Só acrescenta: as chaves de antes continuam.
    for k in ("exported_at", "user", "profile", "prefs", "projects", "templates", "photos", "tasks",
              "time_on_transferred_tasks", "recurring", "renewals"):
        assert k in d, k
    # O histórico continua de fora (fica para o dono decidir).
    assert "history" not in d


# ------------------------------------------------------------------- PDF --

def test_pdf_de_projeto_explica_as_horas(usuario, textos):
    hoje = dia_hoje(usuario)
    alfa, beta = _proj(usuario, "Alfa"), _proj(usuario, "Beta")
    aberta = _tarefa(usuario, "Migração em andamento", project_id=alfa)
    feita = _tarefa(usuario, "Relatório de estoque", project_id=alfa)
    conjunta = _tarefa(usuario, "Reunião conjunta", project_id=beta, extra_project_ids=[alfa])
    _tempo(usuario, aberta, 100)
    _tempo(usuario, feita, 60, dia=hoje - timedelta(days=40))  # fora do período
    _tempo(usuario, feita, 35)
    _tempo(usuario, conjunta, 90)
    _cronometro(usuario, aberta, 5)
    assert usuario.patch(f"/worklog/{feita}", {"status": "done"}).status_code == 200
    ini = (hoje - timedelta(days=6)).isoformat()

    r = usuario.get(f"/reports/export?project={alfa}&start={ini}&end={hoje.isoformat()}")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    capa = usuario.get(f"/reports/preview?project={alfa}&start={ini}&end={hoje.isoformat()}").json()["minutes"]
    assert capa == 100 + 35 + 90 + 5

    # Tabela nova: toda tarefa com tempo no período, concluída ou não, e o total igual à capa.
    assert "Tempo por tarefa (3)" in textos
    i = textos.index("Tempo por tarefa (3)")
    fim = textos.index("Total", i)
    tabela = textos[i:fim]
    for titulo in ("Migração em andamento", "Relatório de estoque", "Reunião conjunta"):
        assert titulo in tabela, titulo
    assert "em aberto" in tabela and "concluída" in tabela
    assert _tempo_depois(textos, "Total", i) == capa == _min("3h50")
    por_tarefa = {t: _tempo_depois(textos, t, i) for t in ("Migração em andamento", "Relatório de estoque", "Reunião conjunta")}
    assert por_tarefa == {"Migração em andamento": 105, "Relatório de estoque": 35, "Reunião conjunta": 90}
    assert sum(por_tarefa.values()) == capa

    # Tarefa em dois projetos: marcada na linha, com a frase que só saía no PDF geral.
    assert "também em: Beta" in textos
    assert report_pdf.MULTI_NOTE in textos
    # Concluída: o tempo do período, e o total da tarefa quando é outro.
    assert "de 1h35 no total" in textos
    # Cronômetro: o horário no diário, não a palavra.
    assert any(re.fullmatch(r"Migração em andamento — \d\d:\d\d–\d\d:\d\d", t) for t in textos), textos[-30:]
    assert not any("cronômetro" in t for t in textos)

    # No PDF do outro projeto a mesma tarefa aponta de volta para este.
    textos.clear()
    assert usuario.get(f"/reports/export?project={beta}&start={ini}&end={hoje.isoformat()}").status_code == 200
    assert "também em: Alfa" in textos

    # No PDF geral não há a tabela (lá a seção de projetos já reparte o tempo).
    textos.clear()
    assert usuario.get(f"/reports/export?start={ini}&end={hoje.isoformat()}").status_code == 200
    assert not any(t.startswith("Tempo por tarefa") for t in textos)
    assert not any(t.startswith("também em:") for t in textos)


def test_pdf_de_projeto_inteiro_nao_cita_o_menu_do_app(usuario, textos):
    hoje = dia_hoje(usuario)
    alfa = _proj(usuario, "Alfa")
    tid = _tarefa(usuario, "Antiga, ainda aberta", project_id=alfa)
    _tempo(usuario, tid, 45, dia=hoje - timedelta(days=90))
    _tempo(usuario, tid, 15)
    assert usuario.get(f"/reports/export?project={alfa}").status_code == 200
    assert "Tempo por tarefa (1)" in textos
    assert _tempo_depois(textos, "Total") == 60
    assert not any("Meu mês" in t for t in textos)


def test_capa_de_periodo_fechado_fala_de_hoje(usuario, textos):
    hoje = dia_hoje(usuario)
    _tarefa(usuario, "Ainda aberta")
    ontem = hoje - timedelta(days=1)
    assert usuario.get(f"/reports/export?start={(hoje - timedelta(days=3)).isoformat()}&end={ontem.isoformat()}").status_code == 200
    assert any(f"Hoje ({hoje:%d/%m}) há 1 tarefa em aberto" in t for t in textos)
    assert not any("Fica 1 tarefa" in t for t in textos)
    textos.clear()  # período que chega a hoje: a frase de sempre
    assert usuario.get(f"/reports/export?start={ontem.isoformat()}&end={hoje.isoformat()}").status_code == 200
    assert any("Fica 1 tarefa em aberto" in t for t in textos)


def test_pdf_tem_idioma_marcadores_nome_sem_perder_acento_e_no_store(usuario):
    hoje = dia_hoje(usuario).isoformat()
    pid = _proj(usuario, "Épsilon Móveis")
    _tempo(usuario, _tarefa(usuario, "Ajuste no ERP", project_id=pid), 30)
    r = usuario.get(f"/reports/export?project={pid}&start={hoje}&end={hoje}")
    assert r.status_code == 200
    assert b"/Lang" in r.content and b"pt-BR" in r.content
    assert b"/Outlines" in r.content
    assert "epsilon-moveis" in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store"


def test_diario_nao_repete_o_titulo_da_tarefa_concluida_no_dia(usuario, textos):
    """Ramo morto do diário: o apontamento com anotação da tarefa concluída no dia mostra só a anotação."""
    hoje = dia_hoje(usuario).isoformat()
    tid = _tarefa(usuario, "Trocar a fonte do servidor")
    _tempo(usuario, tid, 20, nota="peça em garantia")
    usuario.patch(f"/worklog/{tid}", {"status": "done"})
    assert usuario.get(f"/reports/export?start={hoje}&end={hoje}").status_code == 200
    assert "peça em garantia" in textos
    assert "Trocar a fonte do servidor — peça em garantia" not in textos


def test_limite_de_pdf_e_de_quem_pede(usuario, admin):
    uid = uid_de(usuario)
    usuario.put("/me/viewers", {"accept": True})
    hoje = dia_hoje(usuario).isoformat()
    rota = f"/viewer/users/{uid}/reports/export?start={hoje}&end={hoje}"
    for _ in range(6):
        assert admin.get(rota).status_code == 200
    assert admin.get(rota).status_code == 429  # o gestor chegou ao limite dele
    # ...e a pessoa continua baixando o próprio relatório.
    assert usuario.get(f"/reports/export?start={hoje}&end={hoje}").status_code == 200
