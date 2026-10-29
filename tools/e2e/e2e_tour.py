"""E2E na homologação (túnel 8090): tour guiado, filtro do Hoje, vários projetos, projeto padrão.
Uso: e2e_tour.py SAIDA [desktop|mobile]"""
import base64, json, subprocess, sys, tempfile, time, urllib.request
import websocket
import os


def _cred(var):
    """Credencial da homologação no ambiente: NEXUS_E2E_USER / NEXUS_E2E_ADMIN = "email:senha"."""
    v = os.environ.get(var)
    if not v or ":" not in v:
        sys.exit(f"defina {var}=email:senha (conta da homologação)")
    return tuple(v.split(":", 1))


B = os.environ.get("NEXUS_E2E_URL", "http://127.0.0.1:8090")


OUT, modo = sys.argv[1], sys.argv[2]
EMAIL, PW = _cred("NEXUS_E2E_USER")
port = 9361 if modo == "mobile" else 9360
prof = tempfile.mkdtemp()
p = subprocess.Popen(["chromium", "--headless=new", f"--remote-debugging-port={port}", f"--remote-allow-origins=http://127.0.0.1:{port}",
                      "--hide-scrollbars", f"--user-data-dir={prof}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
erros, ok, falhas = [], [], []


def check(nome, cond, extra=""):
    (ok if cond else falhas).append(nome + (f" ({extra})" if extra and not cond else ""))


try:
    for _ in range(50):
        try:
            tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json")); break
        except Exception:
            time.sleep(.2)
    ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"], suppress_origin=True)
    n = [0]

    def cmd(m, **pr):
        n[0] += 1; ws.send(json.dumps({"id": n[0], "method": m, "params": pr}))
        while True:
            r = json.loads(ws.recv())
            if r.get("method") == "Runtime.exceptionThrown":
                erros.append(r["params"]["exceptionDetails"].get("exception", {}).get("description", "")[:300])
            if r.get("method") == "Log.entryAdded" and r["params"]["entry"]["level"] == "error":
                erros.append(r["params"]["entry"]["text"][:200])
            if r.get("id") == n[0]: return r.get("result", r)

    def ev(js):
        r = cmd("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r: raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", js)[:300])
        return r["result"].get("value")

    def shot(nome):
        r = cmd("Page.captureScreenshot", format="png")
        open(f"{OUT}/{nome}{'-m' if modo == 'mobile' else ''}.png", "wb").write(base64.b64decode(r["data"]))

    def wait(js, t=6):
        end = time.time() + t
        while time.time() < end:
            if ev(js): return True
            time.sleep(.15)
        return False

    def click(sel_js):  # expressão que devolve o elemento
        return ev(f"(() => {{ const el = {sel_js}; if (!el) return false; el.click(); return true; }})()")

    def btn(texto, scope="document"):
        return f"[...{scope}.querySelectorAll('button')].find(b => b.textContent.trim() === {json.dumps(texto)} && b.offsetParent)"

    api = lambda method, path, body=None: ev(
        f"fetch('/api/auth/me').then(r => r.json()).then(m => fetch('/api{path}', {{method: '{method}', headers: {{'Content-Type': 'application/json', 'X-CSRF-Token': m.csrf_token}}, "
        f"body: {json.dumps(json.dumps(body)) if body is not None else 'undefined'}}})).then(async r => ({{s: r.status, j: await r.json().catch(() => null)}}))")

    cmd("Page.enable"); cmd("Runtime.enable"); cmd("Log.enable")
    w, h_, sc, mob = (390, 844, 2, True) if modo == "mobile" else (1440, 1000, 1, False)
    cmd("Emulation.setDeviceMetricsOverride", width=w, height=h_, deviceScaleFactor=sc, mobile=mob)
    cmd("Page.navigate", url=B + "/login.html"); time.sleep(1)
    r = ev(f"fetch('/api/auth/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email:'{EMAIL}',password:'{PW}'}})}}).then(r=>r.json())")
    # Estado conhecido: tour não visto, sem projeto padrão.
    api("PUT", "/me/tour", {"done": False}); api("PUT", "/me/default-project", {"project_id": None})
    projs = api("GET", "/projects")["j"]
    pid = {x["name"]: x["id"] for x in projs}
    print("projetos:", list(pid))

    cmd("Page.navigate", url=B + "/index.html#/hoje")
    check("tour abre sozinho", wait("!!document.querySelector('dialog.tour-dialog[open]')", 8))
    time.sleep(.4); shot("t01-boas-vindas")
    click(btn("Começar"))
    check("passo nome", wait("document.querySelector('#tour-title')?.textContent.includes('chamado')"))
    shot("t02-nome")
    click(btn("Salvar e seguir")); check("passo dias", wait("document.querySelector('#tour-title')?.textContent.includes('dias úteis')"))
    shot("t03-dias")
    click(btn("Salvar e seguir")); check("passo projetos", wait("document.querySelector('#tour-title')?.textContent.includes('frente')"))
    time.sleep(.3); shot("t04-projetos")
    click(btn("Seguir")); check("passo padrão", wait("document.querySelector('#tour-title')?.textContent.includes('Projeto padrão')"))
    matriz = pid.get("Matriz") or projs[0]["id"]
    ev(f"(() => {{ const s = document.querySelector('dialog.tour-dialog select'); s.value = '{matriz}'; }})()")
    shot("t05-padrao")
    click(btn("Salvar e seguir")); check("passo rotinas", wait("document.querySelector('#tour-title')?.textContent.includes('confere')"))
    time.sleep(.3); shot("t06-rotinas")
    click(btn("Criar e seguir")); check("passo pronto", wait("document.querySelector('#tour-title')?.textContent.includes('dia a dia')"))
    shot("t07-pronto")
    me = api("GET", "/auth/me")["j"]
    check("projeto padrão salvo", me["default_project_id"] == matriz, me["default_project_id"])
    click(btn("Fazer o passeio"))
    check("passeio abre", wait("!!document.querySelector('.tour-pop')", 8))
    total = int(ev("document.querySelector('.tour-pop .tour-step').textContent.split(' de ')[1]"))
    print("paradas do passeio:", total)
    for i in range(total):
        time.sleep(.6)
        titulo = ev("document.querySelector('#tour-pop-title').textContent")
        # O cartão cabe na tela e o destaque está sobre o alvo.
        dentro = ev("(() => { const r = document.querySelector('.tour-pop').getBoundingClientRect(); return r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight; })()")
        check(f"cartão na tela: {titulo}", dentro)
        shot(f"t1{i}-passeio")
        click(btn("Concluir" if i == total - 1 else "Próximo", "document.querySelector('.tour-pop')"))
    check("passeio fecha", wait("!document.querySelector('.tour-layer')"))
    me = api("GET", "/auth/me")["j"]
    check("tour marcado como visto", bool(me["tour_done_at"]))
    cmd("Page.navigate", url=B + "/index.html#/hoje"); time.sleep(2.5)
    check("tour não reabre", not ev("!!document.querySelector('dialog.tour-dialog[open]')"))

    # ---- filtro do Hoje
    wait("!!document.querySelector('.open-filter')")
    total_rows = ev("document.querySelectorAll('.t-open .open-list .list-row').length")
    click("document.querySelector('.open-filter [data-filter=prio]')"); time.sleep(.2)
    prio_rows = ev("document.querySelectorAll('.t-open .open-list .list-row').length")
    board = api("GET", "/board")["j"]
    today = board["today"]
    exp_prio = sum(1 for t in board["in_progress"] if t["priority"] == 1)
    exp_due = sum(1 for t in board["in_progress"] if t["due_date"] and t["due_date"] <= today)
    check("filtro prioritárias", prio_rows == exp_prio, f"{prio_rows} vs {exp_prio}")
    shot("t30-filtro-prio")
    click("document.querySelector('.open-filter [data-filter=due]')"); time.sleep(.2)
    due_rows = ev("document.querySelectorAll('.t-open .open-list .list-row').length")
    check("filtro vence hoje", due_rows == exp_due, f"{due_rows} vs {exp_due}")
    shot("t31-filtro-due")
    cmd("Page.reload"); wait("!!document.querySelector('.open-filter')", 8)
    check("filtro lembrado na aba", ev("document.querySelector('.open-filter [data-filter=due]').getAttribute('aria-pressed')") == "true")
    click("document.querySelector('.open-filter [data-filter=all]')"); time.sleep(.2)
    check("filtro todas", ev("document.querySelectorAll('.t-open .open-list .list-row').length") == total_rows == len(board["in_progress"]),
          f"{total_rows} vs {len(board['in_progress'])}")
    print(f"abertas={total_rows} prio={prio_rows} vence={due_rows}")

    # ---- registro rápido com dois @ e o padrão
    nomes = list(pid)
    a, b2 = nomes[0], nomes[1]
    ev(f"(() => {{ const q = document.querySelector('.quick-row input'); q.value = 'E2E dois projetos @{a} @{b2}'; q.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', bubbles: true}})); }})()")
    time.sleep(1.5)
    found = api("GET", "/search?q=E2E%20dois%20projetos")["j"]["tasks"]
    t = found[0] if found else None
    check("rápido com dois @", t and t["project_name"] == a and [x["name"] for x in t["extra_projects"]] == [b2], t)
    check("quick select = padrão", ev("document.querySelector('.quick-row select').value") == str(matriz))

    # ---- nova tarefa (diálogo): padrão pré-selecionado e outro projeto
    click("document.querySelector('[data-fab]')")
    wait("document.getElementById('dialog-worklog').open")
    time.sleep(.5)
    check("diálogo com padrão", ev("document.getElementById('wl-project').value") == str(matriz))
    outro = pid[b2] if pid[b2] != matriz else pid[a]
    ev(f"(() => {{ const s = document.querySelector('#wl-extra select'); s.value = '{outro}'; s.dispatchEvent(new Event('change')); }})()")
    time.sleep(.3)
    ev("document.getElementById('wl-title').value = 'E2E diálogo extra'")
    shot("t40-dialogo-extra")
    ev("document.getElementById('form-worklog').requestSubmit()"); time.sleep(1.5)
    t = (api("GET", "/search?q=E2E%20dialogo%20extra")["j"]["tasks"] or [None])[0]
    check("diálogo salvou extra", t and [x["id"] for x in t["extra_projects"]] == [outro], t)

    # ---- detalhe: editar extras
    tid = t["id"]
    cmd("Page.navigate", url=B + f"/index.html#/tarefas"); time.sleep(2)
    ev(f"import('/js/task.js').then(m => m.openTask({tid}, () => {{}}))"); time.sleep(1.2)
    shot("t50-detalhe-leitura")
    click("document.querySelector('dialog[open] .edit-toggle')"); time.sleep(.8)
    has_field = ev("!!document.querySelector('.task-props .extra-projects')")
    check("detalhe tem outros projetos", has_field)
    shot("t51-detalhe-edicao")
    if has_field:
        click("document.querySelector('.task-props .extra-projects .chip-x')"); time.sleep(1)
        d = api("GET", f"/worklog/{tid}")["j"]
        check("detalhe tirou extra", d["extra_projects"] == [], d["extra_projects"])

    # Limpeza das tarefas de teste (o padrão volta a nenhum).
    for q in ("E2E%20dois%20projetos", "E2E%20dialogo%20extra"):
        for x in api("GET", f"/search?q={q}")["j"]["tasks"]:
            api("DELETE", f"/worklog/{x['id']}")
    api("PUT", "/me/default-project", {"project_id": None})
finally:
    p.terminate()
    print("OK:", len(ok)); print("FALHAS:", falhas or "nenhuma"); print("ERROS JS:", erros or "nenhum")
