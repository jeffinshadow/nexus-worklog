"""Auditoria p13 (telas de tarefa): concluir, registro rápido, cronômetro e diálogos.

Uso (com o app no ar e os dados de demonstração):
    NX_BASE=http://localhost:8113 NX_SESSAO=<cookie session> python tools/e2e/e2e_p13_front_tarefas.py

Roda no computador (1440x900) e, nos casos de toque, no celular (390x844).
Cria tarefas "P13 ..." na conta e apaga no fim. Sai com 1 se algum caso falhar.
"""
import json, os, sys, time, urllib.request, urllib.error
from playwright.sync_api import sync_playwright

BASE = os.environ.get("NX_BASE", "http://localhost:8113")
SESS = os.environ.get("NX_SESSAO", "Fi3HAKKBl34tozd0NGGEiiVnK4-joUtKlQDCTLG9bQY")  # Juliana (semeadura do laboratório)
TAG = "P13 %d" % int(time.time())
falhas, erros_console = [], []


def api(method, path, body=None, _csrf=[]):
    req = urllib.request.Request(BASE + "/api" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "Cookie": "session=" + SESS})
    if method != "GET":
        if not _csrf:
            _csrf.append(api("GET", "/auth/me")["csrf_token"])
        req.add_header("X-CSRF-Token", _csrf[0])
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return {"_status": e.code, "_body": e.read().decode()[:300]}


def ok(nome, cond, extra=""):
    print(("ok   " if cond else "FALHA"), nome, ("" if cond else "-> " + str(extra)))
    if not cond:
        falhas.append(nome)


def toasts(pg):
    return pg.evaluate("[...document.querySelectorAll('.toast')].map(t => t.innerText.replace(/\\n/g, ' | '))")


def limpa_toasts(pg):
    pg.evaluate("document.querySelectorAll('.toast').forEach(t => t.remove())")


def nova(titulo, **kw):
    return {**api("POST", "/worklog", {"title": titulo, **kw}), "title": titulo}


def pagina(b, mobile=False):
    kw = dict(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True) if mobile else dict(viewport={"width": 1440, "height": 900})
    ctx = b.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo", service_workers="block", **kw)
    ctx.add_cookies([{"name": "session", "value": SESS, "url": BASE}])
    pg = ctx.new_page()
    pg.set_default_timeout(8000)
    pg.on("console", lambda m: erros_console.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    pg.on("pageerror", lambda e: erros_console.append("pageerror: " + str(e)))
    return ctx, pg


def lenta(ctx, pg, ms):
    cdp = ctx.new_cdp_session(pg)
    cdp.send("Network.enable")
    cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": ms, "downloadThroughput": -1, "uploadThroughput": -1})
    return cdp


def abre(pg, rota, seletor):
    """Vai para a tela e recarrega (o mesmo endereço não redesenha sozinho)."""
    pg.goto(BASE + "/#/hoje" if "tarefas" in rota else BASE + "/#/tarefas")
    pg.goto(BASE + rota)
    pg.wait_for_selector(seletor, state="attached")
    pg.wait_for_timeout(700)


def registro_rapido(pg):
    pg.goto(BASE + "/#/hoje")
    q = pg.locator('input[aria-label="Registrar tarefa rápida"]')
    q.wait_for()
    pg.wait_for_timeout(1200)
    sel = pg.locator('select[aria-label="Projeto do registro rápido"]')
    opcoes = sel.evaluate("e => [...e.options].filter(o => o.value && o.value !== '__new').map(o => o.value)")
    casos = [
        ("Atendi a recepção sem internet", ["Ficou em aberto: «", "Atendi a recepção sem internet»."]),
        ("Atendi a recepção 20min", ["Ficou em aberto.", "“20min” ficou no título", "use “— 20min”"]),
        ("Algo — 30h", ["Ficou em aberto.", "“30h” ficou no título: o máximo é 24h por apontamento"]),
        ("Reunião ^31/02", ["Ficou em aberto.", "“^31/02” ficou no título"]),
        ("Visita técnica @Filial Sul — 1h", ["Registrada e concluída com 1h", "«Filial Sul» não é um projeto seu"]),
    ]
    for valor, nome in [(opcoes[0] if opcoes else "", "com projeto"), ("", "sem projeto")]:
        for texto, esperado in casos:
            sel = pg.locator('select[aria-label="Projeto do registro rápido"]')
            sel.select_option(value=valor)
            limpa_toasts(pg)
            q = pg.locator('input[aria-label="Registrar tarefa rápida"]')
            q.fill(f"{TAG} {texto}")
            q.press("Enter")
            pg.wait_for_selector(".toast")
            pg.wait_for_timeout(900)
            t = " ".join(toasts(pg))
            ok(f"registro rápido [{nome}] {texto!r}", all(e in t for e in esperado), t)
    # "--" vale como o travessão; !aguarda nasce com o dia para cobrar
    limpa_toasts(pg)
    q = pg.locator('input[aria-label="Registrar tarefa rápida"]')
    q.fill(f"{TAG} Troca de toner -- 15min"); q.press("Enter"); pg.wait_for_selector(".toast"); pg.wait_for_timeout(900)
    t = " ".join(toasts(pg))
    ok("registro rápido: '--' conclui com o tempo", "concluída com 15min" in t, t)
    limpa_toasts(pg)
    q = pg.locator('input[aria-label="Registrar tarefa rápida"]')
    q.fill(f"{TAG} Trocar HD !aguarda peça da Dell"); q.press("Enter"); pg.wait_for_selector(".toast"); pg.wait_for_timeout(900)
    t = " ".join(toasts(pg))
    hd = [x for x in api("GET", "/board")["in_progress"] if x["title"] == f"{TAG} Trocar HD"]
    ok("registro rápido: !aguarda com dia para cobrar", bool(hd) and hd[0]["status"] == "blocked" and bool(hd[0].get("follow_up_on")) and "cobrar " in t, (t, hd[:1]))


def nova_tarefa(ctx, pg):
    pg.goto(BASE + "/#/tarefas"); pg.wait_for_selector(".column"); pg.wait_for_timeout(800)
    # Esc preserva; Cancelar descarta
    pg.keyboard.press("n"); pg.wait_for_selector("#dialog-worklog[open]")
    pg.fill("#wl-title", f"{TAG} rascunho"); pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
    pg.keyboard.press("n"); pg.wait_for_selector("#dialog-worklog[open]")
    ok("Nova tarefa: Esc preserva o título", pg.input_value("#wl-title") == f"{TAG} rascunho", pg.input_value("#wl-title"))
    pg.click("#wl-cancel"); pg.wait_for_timeout(400)
    pg.keyboard.press("n"); pg.wait_for_selector("#dialog-worklog[open]")
    ok("Nova tarefa: Cancelar limpa", pg.input_value("#wl-title") == "", pg.input_value("#wl-title"))
    # duração: mensagens
    pg.fill("#wl-title", f"{TAG} duração"); pg.fill("#wl-time", "abc")
    pg.locator("#form-worklog button[type=submit]").first.click(); pg.wait_for_timeout(300)
    ok("Nova tarefa: 'Não entendi a duração'", pg.evaluate("document.getElementById('wl-time').validationMessage").startswith("Não entendi a duração"))
    pg.fill("#wl-time", "30h")
    pg.locator("#form-worklog button[type=submit]").first.click(); pg.wait_for_timeout(300)
    ok("Nova tarefa: 'O máximo é 24h'", pg.evaluate("document.getElementById('wl-time').validationMessage") == "O máximo é 24h por apontamento.")
    pg.fill("#wl-time", "")
    # Enter + clique, com rede lenta = 1 tarefa; aviso "Tarefa criada." com Abrir
    posts = []
    pg.on("request", lambda r: posts.append(1) if r.method == "POST" and r.url.endswith("/api/worklog") else None)
    cdp = lenta(ctx, pg, 1500)
    titulo = f"{TAG} enter e clique"
    pg.fill("#wl-title", titulo)
    pg.press("#wl-title", "Enter"); pg.wait_for_timeout(200)
    pg.evaluate("document.getElementById('form-worklog').requestSubmit()")  # o segundo envio (o clique em Salvar)
    pg.wait_for_timeout(6000)
    cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
    iguais = [x for x in api("GET", "/board")["in_progress"] if x["title"] == titulo]
    ok("Nova tarefa: Enter + Salvar = 1 tarefa", len(posts) == 1 and len(iguais) == 1, (len(posts), len(iguais)))
    t = toasts(pg)
    ok("Nova tarefa: aviso 'Tarefa criada.' com Abrir", any("Tarefa criada." in x and "Abrir" in x for x in t), t)
    pg.locator(".toast button", has_text="Abrir").click()
    pg.wait_for_selector("dialog.task-dialog[open]")
    ok("Nova tarefa: Abrir mostra a tarefa", titulo in pg.locator("dialog.task-dialog[open] h2").first.inner_text())
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)


def cartao_e_detalhe(ctx, pg, mobile):
    a = nova(f"{TAG} cartão A"); b = nova(f"{TAG} cartão B")
    api("POST", f"/worklog/{a['id']}/checklist", {"label": "passo 1"}); api("POST", f"/worklog/{a['id']}/checklist", {"label": "passo 2"})
    api("POST", f"/worklog/{a['id']}/time", {"minutes": 40}); api("POST", f"/worklog/{a['id']}/notes", {"body": "nota"})
    api("PATCH", f"/worklog/{a['id']}", {"ticket": "4821"})
    abre(pg, "/#/tarefas", f'[data-task-id="{a["id"]}"]')
    card = pg.locator(f'[data-task-id="{a["id"]}"]')
    snap = card.aria_snapshot()
    ok("cartão: leitor de tela ouve os contadores", all(s in snap for s in ["checklist 0 de 2", "tempo apontado 40 min", "1 anotação"]), snap)
    link = card.locator("a.chip.ticket")
    if link.count():
        ok("cartão: link do chamado com nome", link.get_attribute("aria-label") == "Chamado 4821 (abre em nova aba)", link.get_attribute("aria-label"))
    else:
        print("     (sem endereço do sistema de chamados na conta: o link não existe, só o texto)")
    # dois cliques seguidos em cartões, rede lenta = 1 detalhe (o último)
    cdp = lenta(ctx, pg, 1200)
    ca = pg.locator(f'[data-task-id="{a["id"]}"] .card-open'); cb = pg.locator(f'[data-task-id="{b["id"]}"] .card-open')
    if mobile:
        ca.tap(); pg.wait_for_timeout(250); ca.tap()
    else:
        ca.click(); pg.wait_for_timeout(250); cb.click()
    pg.wait_for_timeout(4500)
    cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
    d = pg.locator("dialog.task-dialog[open]")
    ok("detalhe: dois toques seguidos = 1 detalhe", d.count() == 1 and pg.locator("dialog.task-dialog").count() == 1, (d.count(), pg.locator("dialog.task-dialog").count()))
    if not mobile:
        ok("detalhe: fica o último clicado", f"{TAG} cartão B" in d.locator("h2").first.inner_text(), d.locator("h2").first.inner_text())
    # anotação digitada sobrevive ao Esc
    nota = d.locator('textarea[aria-label="Nova anotação"]')
    nota.fill("texto que não quero perder")
    if mobile:
        d.locator("button[aria-label=Fechar]").first.click()
    else:
        pg.locator("#main").click(position={"x": 5, "y": 5}); pg.keyboard.press("Escape")
    pg.wait_for_timeout(500)
    ok("detalhe: fechou", pg.locator("dialog.task-dialog[open]").count() == 0)
    alvo = a if mobile else b
    pg.locator(f'[data-task-id="{alvo["id"]}"] .card-open').click(); pg.wait_for_selector("dialog.task-dialog[open]")
    ok("detalhe: a anotação não salva volta", pg.locator('dialog.task-dialog[open] textarea[aria-label="Nova anotação"]').input_value() == "texto que não quero perder")
    # duração no detalhe
    dur = pg.locator('dialog.task-dialog[open] input[aria-label="Duração"]')
    dur.fill("abc"); dur.press("Enter"); pg.wait_for_timeout(200)
    ok("detalhe: 'Não entendi a duração'", dur.evaluate("e => e.validationMessage").startswith("Não entendi a duração"))
    dur.fill("25h"); dur.press("Enter"); pg.wait_for_timeout(200)
    ok("detalhe: 'O máximo é 24h'", dur.evaluate("e => e.validationMessage") == "O máximo é 24h por apontamento.")
    dur.fill("")
    pg.locator("dialog.task-dialog[open] button[aria-label=Fechar]").first.click(); pg.wait_for_timeout(400)
    return a, b


def concluir(ctx, pg, a, b):
    abre(pg, "/#/tarefas", f'[data-task-id="{a["id"]}"]')
    # três toques com rede lenta = 1 conclusão
    posts = []
    pg.on("request", lambda r: posts.append(r.url) if r.method == "POST" and r.url.endswith("/finish") else None)
    cdp = lenta(ctx, pg, 1500)
    pg.evaluate("id => { window.__b = document.querySelector(`[data-task-id=\"${id}\"] .card-check`); }", a["id"])
    for _ in range(3):
        pg.evaluate("document.body.contains(window.__b) && window.__b.click()"); pg.wait_for_timeout(300)
    pg.wait_for_timeout(5000)
    cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
    ok("concluir: três toques = 1 envio", len(posts) == 1, len(posts))
    # concluída sem "como resolveu": a linha com Escrever no detalhe
    limpa_toasts(pg)
    pg.goto(BASE + f"/#/tarefas?id={a['id']}"); pg.wait_for_timeout(1200)
    if not pg.locator("dialog.task-dialog[open]").count():
        pg.evaluate("id => import('/js/task.js').then(m => m.openTask(id))", a["id"])
    d = pg.locator("dialog.task-dialog[open]"); d.wait_for()
    linha = d.locator(".ask-resolution")
    ok("detalhe da concluída: 'Como resolveu? (entra na busca)'", linha.count() == 1 and "Como resolveu? (entra na busca)" in linha.inner_text())
    linha.locator("button").click(); pg.wait_for_timeout(400)
    area = pg.locator('dialog[open] textarea[aria-label="Como resolveu"]')
    ok("detalhe da concluída: Escrever abre o diálogo", area.count() == 1)
    area.fill("reiniciei o roteador"); area.press("Control+Enter") if False else pg.locator("dialog[open] button[type=submit]", has_text="Salvar").click()
    pg.wait_for_timeout(900)
    ok("detalhe da concluída: resolução salva", api("GET", f"/worklog/{a['id']}").get("resolution") == "reiniciei o roteador")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    # resposta de concluir com `stopped` (contrato com o p03): aviso do cronômetro esquecido, com Apontar
    def com_stopped(route):
        r = route.fetch()
        body = r.json()
        body["stopped"] = {"task_id": b["id"], "minutes": 0, "needs_review": True, "started_at": "2026-11-22T08:00:00+00:00", "title": b["title"]}
        route.fulfill(response=r, json=body)
    pg.route("**/api/worklog/*/finish", com_stopped)
    abre(pg, "/#/tarefas", f'[data-task-id="{b["id"]}"]')
    limpa_toasts(pg)
    pg.locator(f'[data-task-id="{b["id"]}"] .card-check').click(); pg.wait_for_timeout(1200)
    t = toasts(pg)
    ok("concluir com cronômetro esquecido: aviso com Apontar", any("parei sem apontar" in x and "Apontar" in x for x in t), t)
    ok("concluir com cronômetro esquecido: o aviso de concluída continua", any("Concluída:" in x for x in t), t)
    pg.locator(".toast button", has_text="Apontar").click(); pg.wait_for_selector("dialog.task-dialog[open]")
    ok("Apontar abre a tarefa", b["title"] in pg.locator("dialog.task-dialog[open] h2").first.inner_text())
    pg.unroute("**/api/worklog/*/finish")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)


def cronometro(pg):
    c = nova(f"{TAG} cronômetro")
    api("POST", "/timer/start", {"task_id": c["id"], "title": c["title"]})
    abre(pg, "/#/tarefas", f'[data-task-id="{c["id"]}"]')
    pg.reload(); pg.wait_for_selector("#timer-side:not(.hidden), #timer-mobile:not(.hidden)", state="attached"); pg.wait_for_timeout(1000)  # o cronômetro é lido ao abrir o app
    limpa_toasts(pg)
    pg.locator("#main").click(position={"x": 5, "y": 5})
    pg.keyboard.press("s"); pg.wait_for_selector(".toast"); pg.wait_for_timeout(700)
    t = toasts(pg)
    ok("parar o cronômetro: 'Apontado N em «tarefa».' com Desfazer e Corrigir",
       any(f"em «{c['title']}»." in x and x.startswith("Apontado ") and "Desfazer" in x and "Corrigir" in x for x in t), t)
    ok("parar o cronômetro: no máximo duas ações", pg.locator(".toast.has-actions").last.locator("button").count() <= 2)
    ok("parar o cronômetro: apontou", len(api("GET", f"/worklog/{c['id']}")["time"]) == 1)
    pg.locator(".toast button", has_text="Corrigir").click(); pg.wait_for_selector("dialog.task-dialog[open] .time-form.row-edit")
    ok("Corrigir abre o apontamento em edição", pg.locator('dialog.task-dialog[open] input[aria-label="Duração do apontamento"]').count() == 1)
    pg.keyboard.press("Escape"); pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
    if pg.locator("dialog.task-dialog[open]").count():
        pg.locator("dialog.task-dialog[open] button[aria-label=Fechar]").first.click()
    # de novo, agora desfazendo
    api("POST", "/timer/start", {"task_id": c["id"], "title": c["title"]})
    abre(pg, "/#/tarefas", f'[data-task-id="{c["id"]}"]')
    pg.reload(); pg.wait_for_selector(f'[data-task-id="{c["id"]}"]', state="attached"); pg.wait_for_timeout(1200)
    limpa_toasts(pg)
    pg.locator("#main").click(position={"x": 5, "y": 5})
    pg.keyboard.press("s"); pg.wait_for_selector(".toast"); pg.wait_for_timeout(700)
    antes = len(api("GET", f"/worklog/{c['id']}")["time"])
    pg.locator(".toast button", has_text="Desfazer").click(); pg.wait_for_timeout(1200)
    depois = len(api("GET", f"/worklog/{c['id']}")["time"])
    ok("parar o cronômetro: Desfazer tira o apontamento", antes == 2 and depois == 1, (antes, depois, toasts(pg)))


def main():
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=os.environ.get("NX_CHROMIUM", "/usr/bin/chromium"), args=["--no-sandbox"])
            print("== computador 1440x900")
            ctx, pg = pagina(b)
            registro_rapido(pg)
            if "nova" not in os.environ.get("NX_PULA", ""):  # NX_PULA=nova: pula o diálogo (rodada de controle no código antigo)
                nova_tarefa(ctx, pg)
            a, bb = cartao_e_detalhe(ctx, pg, False)
            concluir(ctx, pg, a, bb)
            cronometro(pg)
            pg.screenshot(path=os.environ.get("NX_SHOT", "/dev/null") if os.environ.get("NX_SHOT") else None)
            ctx.close()
            print("== celular 390x844")
            ctx, pg = pagina(b, mobile=True)
            cartao_e_detalhe(ctx, pg, True)
            registro = pg.locator('input[aria-label="Registrar tarefa rápida"]')
            pg.goto(BASE + "/#/hoje"); registro.wait_for(); pg.wait_for_timeout(1000)
            limpa_toasts(pg)
            registro.fill(f"{TAG} celular 20min"); registro.press("Enter"); pg.wait_for_selector(".toast"); pg.wait_for_timeout(900)
            t = " ".join(toasts(pg))
            ok("celular: aviso do registro rápido", "Ficou em aberto" in t and "“20min” ficou no título" in t, t)
            larg = pg.evaluate("Math.max(...[...document.querySelectorAll('.toast')].map(e => e.getBoundingClientRect().right))")
            ok("celular: o aviso cabe na tela", larg <= 390, larg)
            ok("celular: o aviso inteiro cabe nas duas linhas", pg.evaluate("[...document.querySelectorAll('.toast > span:first-child')].every(e => e.scrollHeight <= e.clientHeight + 1)"))
            ok("celular: sem rolagem lateral", pg.evaluate("document.documentElement.scrollWidth <= innerWidth"))
            if os.environ.get("NX_SHOT"):
                pg.screenshot(path=os.environ["NX_SHOT"].replace(".png", "-celular.png"))
            ctx.close()
            b.close()
    finally:
        limpeza()
    ok("nenhum erro de console", not erros_console, erros_console[:5])
    print("\n%d falha(s)" % len(falhas), falhas)
    sys.exit(1 if falhas else 0)


def limpeza():
    """Apaga o que os roteiros P13 criaram (também de uma rodada interrompida)."""
    board = api("GET", "/board?done_limit=100")
    for x in board["in_progress"] + board["done"]:
        if x["title"].startswith("P13 "):
            api("DELETE", f"/worklog/{x['id']}")
    api("POST", "/timer/stop", {})


if __name__ == "__main__":
    main()
