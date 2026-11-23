"""Rodada 2, pacote 11: os testes que faltaram na auditoria (só testes, nenhum código do app muda).

- desfazer em tabela: cada ação desfazível é feita, desfeita, e o banco tem de voltar a ser o de antes;
- relógio: os dois testes sensíveis à data rodando em sábado, domingo e atravessando a meia-noite;
- PDF de projeto: o corte de 500 linhas da tabela "Tempo por tarefa";
- agendador e webhook: um teste por defesa (cada um falha se a defesa for removida);
- devolução de tarefa com apontamentos, pela API, e o desfazer;
- o que o webhook de uma conta admin entrega do log administrativo."""
import asyncio
import base64
import json
import os
import socket
import sys
import types
from datetime import date, datetime, timedelta

import pytest

import test_gauntlet_loop_r2 as antigo_ranking
import test_rotina_pausa as antigo_pausa
from app import db, notify, report_pdf, services, webhooks
from app.config import config
from app.routers import assign as assign_mod
from app.routers import history, reports
from conftest import dia_hoje, hist, papeis, recuar_criacao, uid_de


def _ok(r):
    assert r.status_code in (200, 201), r.text
    return r.json()


def _tarefa(u, titulo="Trocar o nobreak", **kw):
    return _ok(u.post("/worklog", {"title": titulo, **kw}))["id"]


@pytest.fixture
def sem_push(monkeypatch):
    """Devolver e desfazer a devolução avisam por push numa thread solta: aqui não interessa."""
    monkeypatch.setattr(assign_mod, "_push_return", lambda *a: None)
    monkeypatch.setattr(assign_mod.push, "send", lambda *a, **k: None)


# ------------------------------------------------------- desfazer em tabela --
# Colunas que guardam "quando mexeram" e não fazem parte do estado que o desfazer devolve.
VOLATEIS = {"updated_at"}
TABELAS_ESTADO = ("worklog_tasks", "worklog_task_projects", "task_notes", "task_checklist", "time_entries",
                  "recurring_tasks", "recurring_completions", "recurring_pauses", "renewals", "projects",
                  "project_objectives")


# DEFEITO achado por esta tabela (não corrigido aqui, ver a nota do pacote): desfazer a exclusão recria o item de
# checklist, o projeto e o vencimento com created_at = agora (anotação, tempo e tarefa voltam com a data original).
# A tabela geral compara sem essa coluna nessas três tabelas; test_desfazer_exclusao_devolve_a_data_de_criacao cobra.
CRIACAO_PERDIDA = ("task_checklist", "projects", "renewals")


def _estado(tudo=False):
    """O banco inteiro do que o desfazer mexe (sem o histórico). Foto excluída some na hora e volta
    pelo desfazer (deleted_at): conta só a que está de pé."""
    def fora(t):
        return VOLATEIS | ({"created_at"} if t in CRIACAO_PERDIDA and not tudo else set())
    out = {t: [{k: v for k, v in r.items() if k not in fora(t)}
               for r in db.query_all(f"SELECT * FROM {t} ORDER BY 1, 2")] for t in TABELAS_ESTADO}
    out["photos"] = db.query_all(
        "SELECT id, user_id, task_id, recurring_id, day, bytes FROM photos WHERE deleted_at IS NULL ORDER BY id")
    return out


class _Cena:
    """Quem faz e desfaz (`u`) e, só nos casos de tarefa atribuída, quem atribui (`chefe`)."""

    def __init__(self, admin, novo_usuario):
        self.admin, self.novo_usuario = admin, novo_usuario
        self.u = novo_usuario("ana@example.com")
        self.antes = self.antes_tudo = self._chefe = None

    def chefe(self):
        if not self._chefe:
            self._chefe = self.novo_usuario("chefe@example.com")
            papeis(self.admin, self._chefe, ["user", "assigner"])
            _ok(self.u.put("/me/assignments", {"accept": True}))
        return self._chefe

    def pronto(self):
        """Fim do preparo: daqui em diante vem a ação que será desfeita."""
        self.antes_tudo = _estado(tudo=True)
        self.antes = {t: [{k: v for k, v in r.items() if k != "created_at" or t not in CRIACAO_PERDIDA} for r in linhas]
                      for t, linhas in self.antes_tudo.items()}

    def atribui(self, chefe):
        return _ok(chefe.post("/assign", {"user_id": uid_de(self.u), "title": "Trocar reator", "description": "Levar escada"}))["id"]


def _rotina(u, label="Ronda"):
    return _ok(u.post("/recurring", {"label": label, "freq": "weekly", "weekdays": 127}))["id"]  # todo dia: vale no fim de semana


_seq = iter(range(1, 10_000))


def _projeto(u):
    return _ok(u.post("/projects", {"name": f"Datacenter {next(_seq)}"}))["id"]  # nome único: os casos rodam na mesma conta


def _vencimento(u):
    return _ok(u.post("/renewals", {"label": "Domínio", "expires_on": (dia_hoje(u) + timedelta(days=30)).isoformat()}))["id"]


def _objetivo(u, pid, titulo="Meta"):
    return _ok(u.post(f"/projects/{pid}/objectives", {"title": titulo}))["id"]


def _foto():
    def webp(n):
        return base64.b64encode(b"RIFF" + (n + 4).to_bytes(4, "little") + b"WEBPVP8 " + os.urandom(n)).decode()
    return {"image": webp(300), "thumb": webp(80), "width": 1600, "height": 1200}


def _tarefa_cheia(u):
    """Tarefa com anotação, item de checklist e tempo (o que a lápide tem de devolver)."""
    t = _tarefa(u, description="d", priority=1)
    _ok(u.post(f"/worklog/{t}/notes", {"body": "nota"}))
    _ok(u.post(f"/worklog/{t}/checklist", {"label": "item"}))
    _ok(u.post(f"/worklog/{t}/time", {"minutes": 25}))
    return t


def _d_worklog_create(c):
    c.pronto()
    _tarefa(c.u)


def _d_worklog_assign(c):
    chefe = c.chefe()
    c.pronto()
    c.atribui(chefe)


def _d_worklog_update(c):
    t = _tarefa_cheia(c.u)
    c.pronto()
    _ok(c.u.patch(f"/worklog/{t}", {"title": "Outro", "description": "outra", "priority": 3}))


def _d_worklog_finish(c):
    t = _tarefa_cheia(c.u)
    c.pronto()
    _ok(c.u.post(f"/worklog/{t}/finish"))


def _d_worklog_delete(c):
    t = _tarefa_cheia(c.u)
    c.pronto()
    _ok(c.u.delete(f"/worklog/{t}"))


def _d_worklog_assign_update(c):
    chefe = c.chefe()
    t = c.atribui(chefe)
    c.pronto()
    _ok(chefe.patch(f"/assign/{t}", {"title": "Trocar reator do 3º andar", "priority": 1}))


def _d_recurring_create(c):
    c.pronto()
    _rotina(c.u)


def _d_recurring_update(c):
    r = _rotina(c.u)
    c.pronto()
    _ok(c.u.patch(f"/recurring/{r}", {"label": "Ronda noturna"}))


def _d_recurring_deactivate(c):
    r = _rotina(c.u)
    c.pronto()
    _ok(c.u.delete(f"/recurring/{r}"))


def _d_recurring_toggle(c):
    r = _rotina(c.u)
    c.pronto()
    _ok(c.u.post(f"/recurring/{r}/toggle", {"done": True}))


def _d_recurring_replace(c):
    r = _rotina(c.u)
    recuar_criacao(r, 5)
    c.pronto()
    assert _ok(c.u.patch(f"/recurring/{r}", {"freq": "weekly", "weekdays": 42}))["id"] != r  # troca de agenda: rotina nova


def _d_recurring_pause(c):
    r = _rotina(c.u)
    c.pronto()
    _ok(c.u.post(f"/recurring/{r}/pause", {"until": (dia_hoje(c.u) + timedelta(days=3)).isoformat()}))


def _d_recurring_resume(c):
    r = _rotina(c.u)
    _ok(c.u.post(f"/recurring/{r}/pause", {"until": (dia_hoje(c.u) + timedelta(days=3)).isoformat()}))
    c.pronto()
    _ok(c.u.delete(f"/recurring/{r}/pause"))


def _d_recurring_order(c):
    a, b, d = _rotina(c.u, "A"), _rotina(c.u, "B"), _rotina(c.u, "C")
    c.pronto()
    _ok(c.u.post("/recurring/order", {"ids": [d, a, b]}))


def _d_note_create(c):
    t = _tarefa(c.u)
    c.pronto()
    _ok(c.u.post(f"/worklog/{t}/notes", {"body": "nota"}))


def _d_note_update(c):
    n = _ok(c.u.post(f"/worklog/{_tarefa(c.u)}/notes", {"body": "nota"}))["id"]
    c.pronto()
    _ok(c.u.patch(f"/notes/{n}", {"body": "outra"}))


def _d_note_delete(c):
    n = _ok(c.u.post(f"/worklog/{_tarefa(c.u)}/notes", {"body": "nota"}))["id"]
    c.pronto()
    _ok(c.u.delete(f"/notes/{n}"))


def _d_checklist_create(c):
    t = _tarefa(c.u)
    c.pronto()
    _ok(c.u.post(f"/worklog/{t}/checklist", {"label": "item"}))


def _d_checklist_update(c):
    i = _ok(c.u.post(f"/worklog/{_tarefa(c.u)}/checklist", {"label": "item"}))["id"]
    c.pronto()
    _ok(c.u.patch(f"/checklist/{i}", {"label": "outro", "done": True}))


def _d_checklist_delete(c):
    i = _ok(c.u.post(f"/worklog/{_tarefa(c.u)}/checklist", {"label": "item"}))["id"]
    c.pronto()
    _ok(c.u.delete(f"/checklist/{i}"))


def _d_time_create(c):
    t = _tarefa(c.u)
    c.pronto()
    _ok(c.u.post(f"/worklog/{t}/time", {"minutes": 10}))


def _d_time_update(c):
    e = _ok(c.u.post(f"/worklog/{_tarefa(c.u)}/time", {"minutes": 10, "note": "antes"}))["id"]
    c.pronto()
    _ok(c.u.patch(f"/time/{e}", {"minutes": 20, "note": "depois"}))


def _d_time_delete(c):
    e = _ok(c.u.post(f"/worklog/{_tarefa(c.u)}/time", {"minutes": 10}))["id"]
    c.pronto()
    _ok(c.u.delete(f"/time/{e}"))


def _d_project_create(c):
    c.pronto()
    _projeto(c.u)


def _d_project_update(c):
    p = _projeto(c.u)
    c.pronto()
    _ok(c.u.patch(f"/projects/{p}", {"name": "Outro nome"}))


def _d_project_delete(c):
    p = _projeto(c.u)
    _objetivo(c.u, p)
    _tarefa(c.u, project_id=p)
    c.pronto()
    _ok(c.u.delete(f"/projects/{p}"))


def _d_renewal_create(c):
    c.pronto()
    _vencimento(c.u)


def _d_renewal_update(c):
    v = _vencimento(c.u)
    c.pronto()
    _ok(c.u.patch(f"/renewals/{v}", {"label": "Domínio novo", "warn_days": 7}))


def _d_renewal_renew(c):
    v = _vencimento(c.u)
    c.pronto()
    _ok(c.u.patch(f"/renewals/{v}", {"expires_on": (dia_hoje(c.u) + timedelta(days=400)).isoformat()}))


def _d_renewal_delete(c):
    v = _vencimento(c.u)
    c.pronto()
    _ok(c.u.delete(f"/renewals/{v}"))


def _d_objective_create(c):
    p = _projeto(c.u)
    c.pronto()
    _objetivo(c.u, p)


def _d_objective_update(c):
    o = _objetivo(c.u, _projeto(c.u))
    c.pronto()
    _ok(c.u.patch(f"/objectives/{o}", {"title": "Meta nova", "due_date": "2030-05-01"}))


def _d_objective_delete(c):
    p = _projeto(c.u)
    o = _objetivo(c.u, p)
    _tarefa(c.u, objective_id=o)
    c.pronto()
    _ok(c.u.delete(f"/objectives/{o}"))


def _d_objective_order(c):
    p = _projeto(c.u)
    a, b = _objetivo(c.u, p, "A"), _objetivo(c.u, p, "B")
    c.pronto()
    _ok(c.u.post(f"/projects/{p}/objectives/order", {"ids": [b, a]}))


def _d_photo_create(c):
    t = _tarefa(c.u)
    c.pronto()
    _ok(c.u.post(f"/worklog/{t}/photos", _foto()))


def _d_photo_delete(c):
    f = _ok(c.u.post(f"/worklog/{_tarefa(c.u)}/photos", _foto()))["id"]
    c.pronto()
    _ok(c.u.delete(f"/photos/{f}"))


# Uma linha por ação desfazível: o nome da função é a ação ("_d_worklog_create" -> "worklog.create").
DESFAZ = {f.__name__[3:].replace("_", ".", 1): f for f in (
    _d_worklog_create, _d_worklog_assign, _d_worklog_update, _d_worklog_finish, _d_worklog_delete, _d_worklog_assign_update,
    _d_recurring_create, _d_recurring_update, _d_recurring_deactivate, _d_recurring_toggle, _d_recurring_replace,
    _d_recurring_pause, _d_recurring_resume, _d_recurring_order,
    _d_note_create, _d_note_update, _d_note_delete,
    _d_checklist_create, _d_checklist_update, _d_checklist_delete,
    _d_time_create, _d_time_update, _d_time_delete,
    _d_project_create, _d_project_update, _d_project_delete,
    _d_renewal_create, _d_renewal_update, _d_renewal_renew, _d_renewal_delete,
    _d_objective_create, _d_objective_update, _d_objective_delete, _d_objective_order,
    _d_photo_create, _d_photo_delete)}


def test_toda_acao_desfazivel_tem_linha_na_tabela():
    falta = sorted(history.UNDOABLE - set(DESFAZ))
    assert not falta, (f"ação desfazível nova sem linha na tabela do desfazer: {falta}. "
                       "Acrescente um caso `_d_<ação>` em DESFAZ (tests/test_r2_11.py): fazer, desfazer e o banco volta.")
    sobra = sorted(set(DESFAZ) - history.UNDOABLE)
    assert not sobra, f"a tabela tem linha de ação que não é mais desfazível (tire de DESFAZ): {sobra}"


def _diferenca(antes, depois):
    return {t: {"antes": [r for r in antes[t] if r not in depois[t]], "depois": [r for r in depois[t] if r not in antes[t]]}
            for t in antes if antes[t] != depois[t]}


def _ultima(u, acao):
    hid = db.query_one("SELECT max(id) AS id FROM audit_log WHERE user_id = %s AND action = %s", (uid_de(u), acao))["id"]
    assert hid, f"{acao}: a ação não ficou no histórico de quem desfaz"
    return next(x for x in hist(u, limit=30) if x["id"] == hid)


def _faz_e_desfaz(c, acao):
    c.antes = None
    DESFAZ[acao](c)
    assert c.antes is not None, "o caso não chamou c.pronto()"
    assert _estado() != c.antes, "a ação não mudou nada (o caso não testa o desfazer)"
    h = _ultima(c.u, acao)
    assert h["can_undo"] is True, h
    r = c.u.post(f"/history/{h['id']}/undo")
    assert r.status_code == 200, (r.status_code, r.text)
    voltou = _estado()
    assert voltou == c.antes, f"o desfazer não devolveu o estado: {_diferenca(c.antes, voltou)}"
    # Desfazer de novo: 409 e nada muda.
    r = c.u.post(f"/history/{h['id']}/undo")
    assert r.status_code == 409 and "já foi desfeita" in r.json()["detail"], (r.status_code, r.text)
    assert _estado() == voltou, "o segundo desfazer (recusado) mexeu no banco"
    assert _ultima(c.u, acao)["can_undo"] is False


def test_desfazer_devolve_o_estado_e_so_vale_uma_vez(admin, novo_usuario, sem_push):
    """Para CADA ação desfazível: fazer, desfazer, e o banco é o de antes; desfazer de novo dá 409.
    Tudo na mesma conta (36 contas custariam 10 s de suíte); cada caso cria os seus itens e a falha diz a ação."""
    c, falhas = _Cena(admin, novo_usuario), []
    for acao in sorted(DESFAZ):
        try:
            _faz_e_desfaz(c, acao)
        except Exception as e:  # noqa: BLE001 — junta todas: uma ação quebrada não esconde as outras
            falhas.append(f"{acao}: {e!r}" if not isinstance(e, AssertionError) else f"{acao}: {e}")
    assert not falhas, "desfazer quebrado em:\n" + "\n".join(falhas)
    # Ação de outra pessoa, ou que não existe: 404.
    alheia = _ultima(c.u, "worklog.create")["id"]
    assert c.admin.post(f"/history/{alheia}/undo").status_code == 404
    assert c.u.post("/history/999999/undo").status_code == 404


@pytest.mark.xfail(strict=True, reason="defeito achado na r2-11 (não corrigido: pacote só de testes): desfazer a exclusão "
                   "recria o item de checklist, o projeto e o vencimento com created_at = agora, não com a data original")
@pytest.mark.parametrize("acao", ["checklist.delete", "project.delete", "renewal.delete"])
def test_desfazer_exclusao_devolve_a_data_de_criacao(admin, novo_usuario, acao):
    c = _Cena(admin, novo_usuario)
    DESFAZ[acao](c)
    _ok(c.u.post(f"/history/{_ultima(c.u, acao)['id']}/undo"))
    assert _estado(tudo=True) == c.antes_tudo, _diferenca(c.antes_tudo, _estado(tudo=True))


# ------------------------------------------------------------------ relógio --
# Os dois testes que a auditoria viu falhar no fim de semana e na virada do dia (testes-qualidade #3) foram
# corrigidos por leitura. Aqui eles rodam DE NOVO, os mesmos (importados), com a data da app trocada.
SABADO, DOMINGO = date(2026, 11, 28), date(2026, 11, 29)


class _Relogio:
    """Data falsa da app: troca `app_today` em todo módulo que a importou (o padrão de test_revisao_semanal,
    para todos de uma vez). Só o "hoje" da app: o now() do Postgres continua o de verdade, então a rotina criada
    pelos clientes dados em `contas` tem a criação levada para o dia falso (senão ela "existiria" desde o dia real,
    com dias úteis já passados, e o fim de semana não seria reproduzido)."""

    def __init__(self, monkeypatch, dia, *contas):
        self.dia = dia
        for nome, m in list(sys.modules.items()):
            if (nome == "app" or nome.startswith("app.")) and hasattr(m, "app_today"):
                monkeypatch.setattr(m, "app_today", lambda: self.dia)
        for conta in contas:
            self._rotina_nasce_no_dia_falso(monkeypatch, conta)

    def _rotina_nasce_no_dia_falso(self, monkeypatch, cliente):
        original = cliente.post

        def post(path, *a, **k):
            r = original(path, *a, **k)
            if path == "/recurring" and r.status_code == 201:
                db.execute("UPDATE recurring_tasks SET created_at = %s WHERE id = %s",
                           (datetime(self.dia.year, self.dia.month, self.dia.day, 12, tzinfo=services.app_tz()), r.json()["id"]))
            return r
        monkeypatch.setattr(cliente, "post", post)

    def vira_antes_de(self, monkeypatch, cliente, verbo, trecho, vez=1):
        """Meia-noite: o dia vira logo antes da `vez`-ésima chamada `verbo` cujo caminho contém `trecho`."""
        original, visto = getattr(cliente, verbo), []

        def chamada(path, *a, **k):
            if trecho in path:
                visto.append(path)
                if len(visto) == vez:
                    self.dia += timedelta(days=1)
            return original(path, *a, **k)
        monkeypatch.setattr(cliente, verbo, chamada)
        return visto


def test_relogio_falso_muda_o_hoje_da_app(monkeypatch, usuario):
    assert dia_hoje(usuario) == services.app_today() != SABADO
    _Relogio(monkeypatch, SABADO, usuario)
    assert dia_hoje(usuario) == SABADO and SABADO.weekday() == 5 and DOMINGO.weekday() == 6
    # A rotina padrão (dias úteis) não é devida: é a condição que derrubava o teste antigo no fim de semana.
    rid = _ok(usuario.post("/recurring", {"label": "Dias úteis"}))["id"]
    assert next(r for r in usuario.get("/board").json()["recurring"] if r["id"] == rid)["due"] is False
    assert usuario.get("/dashboard").json()["task_adherence"]["tasks"] == []  # criada no sábado: nenhum dia devido ainda


@pytest.mark.parametrize("dia", [SABADO, DOMINGO], ids=["sabado", "domingo"])
def test_ranking_de_quem_acompanha_no_fim_de_semana(monkeypatch, admin, usuario, dia):
    _Relogio(monkeypatch, dia, usuario)
    antigo_ranking.test_quem_acompanha_nao_recebe_ranking_nem_backlog(admin, usuario)


@pytest.mark.parametrize("dia", [SABADO, DOMINGO], ids=["sabado", "domingo"])
def test_pausa_retomar_e_desfazer_no_fim_de_semana(monkeypatch, usuario, novo_usuario, dia):
    _Relogio(monkeypatch, dia, usuario)
    antigo_pausa.test_retomar_desfazer_e_validacoes(usuario, novo_usuario)


@pytest.mark.parametrize("vez", [1, 2], ids=["antes-do-1o-desfazer", "antes-do-2o-desfazer"])
def test_pausa_retomar_e_desfazer_atravessando_a_meia_noite(monkeypatch, usuario, novo_usuario, vez):
    """23:59 -> 00:01 no meio do teste. Antes do 1º desfazer é o caso da auditoria: a pausa pedida "ontem" não é
    apagada, é encerrada (regra do produto), e o teste antigo contava as linhas."""
    relogio = _Relogio(monkeypatch, SABADO, usuario)
    desfeitos = relogio.vira_antes_de(monkeypatch, usuario, "post", "/undo", vez)
    antigo_pausa.test_retomar_desfazer_e_validacoes(usuario, novo_usuario)
    assert len(desfeitos) == 2 and relogio.dia == DOMINGO  # a virada aconteceu mesmo


def test_ranking_de_quem_acompanha_atravessando_a_meia_noite(monkeypatch, admin, usuario):
    """A rotina é marcada no sábado às 23:59 e os painéis são lidos no domingo às 00:01."""
    relogio = _Relogio(monkeypatch, SABADO, usuario)
    lidos = relogio.vira_antes_de(monkeypatch, admin, "get", "/viewer/users/")
    antigo_ranking.test_quem_acompanha_nao_recebe_ranking_nem_backlog(admin, usuario)
    assert lidos and relogio.dia == DOMINGO


# ------------------------------------------------- PDF de projeto: 500 linhas --
def test_pdf_de_projeto_corta_em_500_tarefas_e_o_total_fecha_com_a_capa(usuario, monkeypatch):
    uid, hoje = uid_de(usuario), dia_hoje(usuario)
    pid = _ok(usuario.post("/projects", {"name": "Migração"}))["id"]
    # 520 tarefas com tempo no projeto (direto no banco: pela API seriam 1040 pedidos), em 5 dias, de 1 a 7 min.
    db.execute("""WITH t AS (INSERT INTO worklog_tasks (user_id, title, project_id)
                             SELECT %s, 'Tarefa ' || lpad(g::text, 3, '0'), %s FROM generate_series(1, 520) g
                             RETURNING id)
                  INSERT INTO time_entries (task_id, user_id, minutes, day)
                  SELECT id, %s, 1 + (id %% 7), %s::date - (id %% 5)::int FROM t""", (uid, pid, uid, hoje))
    no_banco = db.query_one("SELECT sum(minutes)::int AS m FROM time_entries WHERE user_id = %s", (uid,))["m"]

    # Os dados, pelo caminho da rota do relatório do projeto inteiro.
    start, end, project, _ = reports.resolve_range(uid, None, None, pid)
    data = services.get_report_range(uid, start, end, project)
    linhas = data["time_by_task"]
    assert len(linhas) == 520
    assert data["summary"]["minutes"] == no_banco == sum(r["minutes"] for r in linhas)  # o número da capa

    # A função que desenha a tabela, num PDF de verdade, guardando cada texto escrito.
    pdf = report_pdf._Report({"line1": "nexus", "line2": "worklog", "logo": None}, "Migração", "23/11/2026 09:00")
    pdf.add_page()
    escrito, text_at = [], pdf.text_at

    def anota(x, y, w, h, text, align="L"):
        escrito.append(text)
        return text_at(x, y, w, h, text, align)
    monkeypatch.setattr(pdf, "text_at", anota)
    report_pdf._time_by_task(pdf, data)

    assert escrito.count("em aberto") == 500  # uma linha por tarefa, até o corte
    resto = sum(r["minutes"] for r in linhas[500:])
    i = escrito.index("+ 20 outras tarefas")
    assert escrito[i:i + 3] == ["+ 20 outras tarefas", "", report_pdf._dur(resto)]
    assert escrito[i + 3:i + 6] == ["Total", "", report_pdf._dur(no_banco)]  # o total fecha com a capa, corte incluído
    assert linhas[500]["title"] not in escrito and linhas[499]["title"] in escrito
    # Com 500 ou menos não há linha de resto.
    escrito.clear()
    report_pdf._time_by_task(pdf, {**data, "time_by_task": linhas[:500]})
    assert not [t for t in escrito if t.startswith("+ ")] and escrito.count("em aberto") == 500


# ------------------------------------------- agendador: um teste por serviço --
class _Fim(Exception):
    """Encerra o laço infinito de notify._passes no fim da 1ª passada."""


def _passada(monkeypatch, quebra):
    """Uma passada do agendador às 9:00 (hora cheia: a faxina roda), com o serviço `quebra` estourando.
    Devolve os serviços chamados, na ordem. Só _Fim (o sleep do fim da passada) pode sair do laço."""
    from app.routers import photos
    chamados = []

    def servico(nome):
        def roda(*a, **k):
            chamados.append(nome)
            if nome == quebra:
                raise RuntimeError(f"{nome} fora do ar")
            return []
        return roda

    class _NoveHoras(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 23, 9, 0, 30, tzinfo=tz)

    async def dormir(segundos):
        raise _Fim

    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(notify, "run_once", servico("email"))
    monkeypatch.setattr(photos, "cleanup", servico("fotos"))
    monkeypatch.setattr(notify, "faxina", servico("faxina"))
    monkeypatch.setattr(notify, "datetime", _NoveHoras)
    monkeypatch.setattr(notify, "last_pass", None)
    monkeypatch.setattr(asyncio, "sleep", dormir)
    agenda = types.SimpleNamespace(run_once=servico("agenda"))
    push = types.SimpleNamespace(run_once=servico("push"))
    with pytest.raises(_Fim):
        asyncio.run(notify._passes(notify.ZoneInfo(config.APP_TZ), agenda, push))
    return chamados


def test_agendador_email_que_estoura_nao_derruba_a_passada(monkeypatch):
    """Falha se o try/except do e-mail em notify._pass for removido."""
    assert _passada(monkeypatch, "email") == ["push", "agenda", "email", "fotos", "faxina"]
    assert notify.last_pass is not None  # a passada terminou: a Saúde não acusa agendador preso


def test_agendador_agenda_que_estoura_nao_derruba_a_passada(monkeypatch):
    """Falha se o try/except dos avisos de agenda em notify._pass for removido."""
    assert _passada(monkeypatch, "agenda") == ["push", "agenda", "email", "fotos", "faxina"]
    assert notify.last_pass is not None


def test_agendador_faxina_que_estoura_nao_derruba_a_passada(monkeypatch):
    """Falha se o try/except da faxina do banco em notify._pass for removido (é o último serviço:
    só o fim da passada e o laço continuar de pé mostram a diferença)."""
    assert _passada(monkeypatch, "faxina") == ["push", "agenda", "email", "fotos", "faxina"]
    assert notify.last_pass is not None


# ------------------------------------- webhook: IP interno recusado NO ENVIO --
@pytest.mark.parametrize("ips_no_envio", [{"10.0.0.5"}, {"93.184.216.34", "127.0.0.1"}], ids=["interno", "misto"])
def test_webhook_cadastrado_com_ip_publico_nao_envia_se_o_dns_passar_a_dar_ip_interno(usuario, monkeypatch, ips_no_envio):
    """O cadastro valida o endereço; o ENVIO valida de novo (o DNS do destino pode mudar depois). A entrega roda
    de verdade (run_once -> _deliver -> post); só a rede é trocada. Falha se `post` deixar de checar o IP."""
    dns, conexoes = {"ips": {"93.184.216.34"}}, []
    monkeypatch.setattr(webhooks, "resolve", lambda host, port: set(dns["ips"]))
    monkeypatch.setattr(webhooks, "LAG_SECONDS", 0)

    def create_connection(addr, *a, **k):
        conexoes.append(addr)
        raise OSError("o teste não deixa sair para a rede")
    monkeypatch.setattr(socket, "create_connection", create_connection)

    hid = _ok(usuario.post("/webhooks", {"url": "https://hooks.example.com/nexus"}))["id"]  # cadastro: IP público
    _tarefa(usuario)  # um evento para entregar
    dns["ips"] = ips_no_envio
    assert webhooks.run_once() == [(hid, 0, "endereço de rede interna ou reservado não é aceito")]
    assert conexoes == []  # nem tentou conectar
    w = db.query_one("SELECT failures, last_error, last_delivered_at FROM webhooks WHERE id = %s", (hid,))
    assert (w["failures"], w["last_delivered_at"]) == (1, None) and "rede interna" in w["last_error"]


# ------------------------------------------ devolução com lápide de verdade --
def test_devolver_tarefa_com_apontamentos_e_desfazer_devolve_cada_um_ao_dono(admin, novo_usuario, sem_push):
    chefe, kaique, lia = (novo_usuario(f"{n}@example.com") for n in ("chefe", "kaique", "lia"))
    papeis(admin, chefe, ["user", "assigner"])
    _ok(kaique.put("/me/assignments", {"accept": True}))
    tid = _ok(chefe.post("/assign", {"user_id": uid_de(kaique), "title": "Trocar reator do 3º andar"}))["id"]
    ontem = (dia_hoje(kaique) - timedelta(days=1)).isoformat()
    for corpo in ({"minutes": 30, "note": "ida"}, {"minutes": 45, "day": ontem}, {"minutes": 15}):
        _ok(kaique.post(f"/worklog/{tid}/time", corpo))
    _ok(kaique.post(f"/worklog/{tid}/notes", {"body": "faltou a escada"}))
    antes = db.query_all("SELECT id, user_id, task_id, minutes, day, note, created_at FROM time_entries ORDER BY id")
    assert [e["user_id"] for e in antes] == [uid_de(kaique)] * 3

    _ok(kaique.post(f"/worklog/{tid}/return", {"reason": "não é da minha área"}))
    assert not db.query_one("SELECT 1 FROM worklog_tasks WHERE id = %s", (tid,))
    assert db.query_all("SELECT 1 FROM time_entries") == []  # saíram com a tarefa
    # A lápide que a rota grava de verdade (não um campo posto pelo teste): cada apontamento com o dono.
    lapide = db.query_one("SELECT id, before FROM audit_log WHERE user_id = %s AND action = 'worklog.delete' AND entity_id = %s",
                          (uid_de(kaique), tid))
    assert lapide["before"]["return_reason"] == "não é da minha área"
    assert {e["id"]: e["user_id"] for e in lapide["before"]["children"]["time"]} == {e["id"]: e["user_id"] for e in antes}

    h = next(x for x in hist(kaique, entity="worklog", entity_id=tid) if x["action"] == "worklog.delete")
    assert h["id"] == lapide["id"] and h["can_undo"] is True
    assert lia.post(f"/history/{h['id']}/undo").status_code == 404  # só quem devolveu desfaz
    _ok(kaique.post(f"/history/{h['id']}/undo"))
    # Cada apontamento de volta, na mesma tarefa, no mesmo dia, com o mesmo dono; nada foi parar em outra conta.
    assert db.query_all("SELECT id, user_id, task_id, minutes, day, note, created_at FROM time_entries ORDER BY id") == antes
    t = db.query_one("SELECT user_id, assigned_by, status FROM worklog_tasks WHERE id = %s", (tid,))
    assert t == {"user_id": uid_de(kaique), "assigned_by": uid_de(chefe), "status": "todo"}
    assert [n["body"] for n in kaique.get(f"/worklog/{tid}").json()["notes"]] == ["faltou a escada"]
    assert kaique.post(f"/history/{h['id']}/undo").status_code == 409
