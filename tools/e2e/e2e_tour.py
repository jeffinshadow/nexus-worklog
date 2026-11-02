"""E2E na homologação (túnel 8090): tour guiado, filtro do Hoje, vários projetos, projeto padrão
e o tour OBRIGATÓRIO do primeiro acesso (Admin › Para empresas): conta nova convidada com nome e
papel, sem Pular/Esc, nome do convite no passo do nome, paradas de visibilidade e de "todos recebem de
quem atribui", conclusão no servidor.
Uso: e2e_tour.py SAIDA [desktop|mobile]   (precisa de NEXUS_E2E_USER e NEXUS_E2E_ADMIN)"""
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
    cmd("Page.navigate", url=B + "/login"); time.sleep(1)
    r = ev(f"fetch('/api/auth/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email:'{EMAIL}',password:'{PW}'}})}}).then(r=>r.json())")
    # Estado conhecido: tour não visto, sem projeto padrão.
    api("PUT", "/me/tour", {"done": False}); api("PUT", "/me/default-project", {"project_id": None})
    projs = api("GET", "/projects")["j"]
    pid = {x["name"]: x["id"] for x in projs}
    print("projetos:", list(pid))

    cmd("Page.navigate", url=B + "/#/hoje")
    check("tour abre sozinho", wait("!!document.querySelector('dialog.tour-dialog[open]')", 8))
    time.sleep(.4); shot("t01-boas-vindas")
    click(btn("Começar"))
    check("passo nome", wait("document.querySelector('#tour-title')?.textContent.includes('nome')"))
    shot("t02-nome")
    click(btn("Salvar e seguir")); check("passo tema", wait("document.querySelector('#tour-title')?.textContent.includes('escuro')"))
    shot("t02b-tema")
    click(btn("Seguir")); check("passo dias", wait("document.querySelector('#tour-title')?.textContent.includes('dias úteis')"))
    shot("t03-dias")
    click(btn("Salvar e seguir")); check("passo projetos", wait("document.querySelector('#tour-title')?.textContent.includes('frente')"))
    time.sleep(.3); shot("t04-projetos")
    click(btn("Seguir")); check("passo padrão", wait("document.querySelector('#tour-title')?.textContent.includes('Projeto padrão')"))
    matriz = pid.get("Matriz") or projs[0]["id"]
    ev(f"(() => {{ const s = document.querySelector('dialog.tour-dialog select'); s.value = '{matriz}'; }})()")
    shot("t05-padrao")
    click(btn("Salvar e seguir")); check("passo rotinas", wait("document.querySelector('#tour-title')?.textContent.includes('confere')"))
    time.sleep(.3); shot("t06-rotinas")
    # Pacote da área: tocar numa área mostra os itens (agenda e horário); tocar de novo desmarca (nada é criado aqui).
    check("pacotes no passo de rotinas", wait("document.querySelectorAll('dialog.tour-dialog .pack-area').length >= 5"))
    click("document.querySelector('dialog.tour-dialog .pack-area')")
    check("pacote mostra os itens", wait("document.querySelectorAll('dialog.tour-dialog .pack-item').length >= 3"))
    time.sleep(.3); shot("t06b-rotinas-pacote")
    click("document.querySelector('dialog.tour-dialog .pack-area[aria-pressed=true]')")
    check("pacote desmarcado", wait("!document.querySelector('dialog.tour-dialog .pack-item')"))
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
    cmd("Page.navigate", url=B + "/#/hoje"); time.sleep(2.5)
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
    # O Hoje mostra até 10 em aberto; passando disso, o link "Ver ... em Tarefas" leva ao resto.
    HOJE_MAX = 10
    mais = lambda: bool(ev("!!document.querySelector('.t-open .open-list a.see-all[href=\"#/tarefas\"]')"))
    check("filtro prioritárias", prio_rows == min(exp_prio, HOJE_MAX) and mais() == (exp_prio > HOJE_MAX), f"{prio_rows} vs {exp_prio}")
    shot("t30-filtro-prio")
    click("document.querySelector('.open-filter [data-filter=due]')"); time.sleep(.2)
    due_rows = ev("document.querySelectorAll('.t-open .open-list .list-row').length")
    check("filtro vence hoje", due_rows == min(exp_due, HOJE_MAX) and mais() == (exp_due > HOJE_MAX), f"{due_rows} vs {exp_due}")
    shot("t31-filtro-due")
    cmd("Page.reload"); wait("!!document.querySelector('.open-filter')", 8)
    check("filtro lembrado na aba", ev("document.querySelector('.open-filter [data-filter=due]').getAttribute('aria-pressed')") == "true")
    click("document.querySelector('.open-filter [data-filter=all]')"); time.sleep(.2)
    check("filtro todas", ev("document.querySelectorAll('.t-open .open-list .list-row').length") == total_rows == min(len(board["in_progress"]), HOJE_MAX)
          and mais() == (len(board["in_progress"]) > HOJE_MAX), f"{total_rows} vs {len(board['in_progress'])}")
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
    cmd("Page.navigate", url=B + "/#/tarefas"); time.sleep(2)
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

    # ---- tour obrigatório no primeiro acesso (sempre, para toda conta nova; convidada com nome e papel)
    AEMAIL, APW = _cred("NEXUS_E2E_ADMIN")
    login = lambda e, s: ev(f"fetch('/api/auth/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email:{json.dumps(e)},password:{json.dumps(s)}}})}}).then(r=>r.status)")  # noqa: E731
    cmd("Network.enable"); cmd("Network.clearBrowserCookies")
    cmd("Page.navigate", url=B + "/login"); time.sleep(1)
    check("admin entra", login(AEMAIL, APW) == 200)
    org0 = api("GET", "/admin/org")["j"]
    api("PUT", "/admin/org", {"team_visibility": "managers", "assign_receive": "all", "identity_managed": False})  # o tour é sempre obrigatório para conta nova
    nova = f"e2e.tour.{int(time.time())}@example.com"
    # Com equipes na instância (sql/043), Para empresas só vale para quem está em alguma: a convidada entra numa.
    equipes = [t["id"] for t in (api("GET", "/admin/teams")["j"] or []) if not t.get("archived_at")][:1]
    r = api("POST", "/admin/users", {"email": nova, "display_name": "Pessoa E2E", "roles": ["user"], "team_ids": equipes})
    check("convite com nome e papel", r["s"] == 201 and r["j"]["display_name"] == "Pessoa E2E")
    senha_nova = "Senha-E2E-Tour-Obrigatorio-1"
    cmd("Network.clearBrowserCookies")
    if r["j"].get("invite_url"):
        cmd("Page.navigate", url=r["j"]["invite_url"]); time.sleep(1.5)
        ev(f"(() => {{ for (const id of ['link-pw', 'link-pw2']) document.getElementById(id).value = {json.dumps(senha_nova)}; document.getElementById('form-link').requestSubmit(); }})()")
        time.sleep(2.5)
    else:  # sem e-mail no servidor: senha temporária, trocada no 1º acesso
        cmd("Page.navigate", url=B + "/login"); time.sleep(1)
        login(nova, r["j"]["temp_password"])
        api("POST", "/auth/change-password", {"current_password": r["j"]["temp_password"], "new_password": senha_nova})
        cmd("Page.navigate", url=B + "/#/hoje")
    check("tour obrigatório abre", wait("!!document.querySelector('dialog.tour-dialog[open]')", 10))
    time.sleep(.5); shot("t60-obrigatorio-boas-vindas")
    sem_pular = "![...document.querySelectorAll('dialog.tour-dialog button, .tour-pop button')].some(b => /Agora não|Só o passeio|Pular|Fechar|Encerrar/.test(b.textContent))"
    check("sem Pular/Agora não", ev(sem_pular))
    ev("document.querySelector('dialog.tour-dialog').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
    ev("document.querySelector('dialog.tour-dialog').dispatchEvent(new Event('cancel', {cancelable: true}))"); time.sleep(.3)
    check("Esc não fecha", ev("!!document.querySelector('dialog.tour-dialog[open]')"))
    click(btn("Começar"))
    check("nome do convite no passo do nome", wait("document.querySelector('dialog.tour-dialog input')?.value === 'Pessoa E2E'"))
    shot("t61-obrigatorio-nome")
    viu_vis = viu_rec = False
    for _ in range(12):  # Salvar e seguir / Seguir / Entendi / Criar e seguir, até o "pronto"
        t = ev("document.querySelector('#tour-title')?.textContent || ''")
        if "Quem vê" in t and not viu_vis:
            viu_vis = True; shot("t62-obrigatorio-visibilidade")
        if "quem atribui" in t and not viu_rec:
            viu_rec = True; shot("t63-obrigatorio-receber-tarefas")
        if "dia a dia" in t:
            break
        check(f"sem Pular em: {t}", ev(sem_pular))
        click("document.querySelector('dialog.tour-dialog .btn-primary')"); time.sleep(1.2)
    check("parada de visibilidade (só quando ativa)", viu_vis)
    check("parada de receber tarefas (só quando ativa)", viu_rec)
    click(btn("Fazer o passeio"))
    check("passeio abre", wait("!!document.querySelector('.tour-pop')", 15))
    check("passeio sem Encerrar", ev(sem_pular))
    for _ in range(15):
        if not ev("!!document.querySelector('.tour-pop')"):
            break
        click("document.querySelector('.tour-pop .btn-primary')"); time.sleep(.6)
    time.sleep(1)
    me = api("GET", "/auth/me")["j"]
    check("concluído no servidor", bool(me["tour_done_at"]) and me["tour_required"] is False)
    check("passou pela parada: sem o aviso único depois", me["assign_notice"] is False and me["visibility_notice"] is False)
    cmd("Page.navigate", url=B + "/#/hoje"); time.sleep(2.5)
    check("tour obrigatório não reabre", not ev("!!document.querySelector('dialog.tour-dialog[open]')"))
    # Limpeza: a conta de teste sai e as opções voltam como estavam.
    cmd("Network.clearBrowserCookies"); cmd("Page.navigate", url=B + "/login"); time.sleep(1)
    login(AEMAIL, APW)
    uid_nova = next(u["id"] for u in api("GET", "/admin/users")["j"] if u["email"] == nova)
    api("POST", f"/admin/users/{uid_nova}/delete", {"confirm_email": nova})
    api("PUT", "/admin/org", {k: org0[k] for k in ("team_visibility", "assign_receive", "identity_managed")})
finally:
    p.terminate()
    print("OK:", len(ok)); print("FALHAS:", falhas or "nenhuma"); print("ERROS JS:", erros or "nenhum")
