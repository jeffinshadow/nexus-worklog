"""Verificação da E1 (homolog, conta demo): manifest/instalação, atalhos, compartilhar, número no ícone, convite."""
import json, os, subprocess, sys, tempfile, time, urllib.request, urllib.parse
import websocket

B = os.environ.get("NEXUS_E2E_URL", "http://localhost:8090")
EMAIL, PW = os.environ["NEXUS_E2E_USER"].split(":", 1)
OUT = sys.argv[1]
ok, falhas, erros = [], [], []
def check(nome, cond, extra=""):
    (ok if cond else falhas).append(nome + ("" if cond else f"  [{extra}]"))

def browser(port, ua=None):
    p = subprocess.Popen(["chromium", "--headless=new", f"--remote-debugging-port={port}", f"--remote-allow-origins=http://127.0.0.1:{port}",
                          f"--user-data-dir={tempfile.mkdtemp()}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try: tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json")); break
        except Exception: time.sleep(.2)
    ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"], suppress_origin=True)
    n = [0]
    def cmd(m, **pr):
        n[0] += 1; ws.send(json.dumps({"id": n[0], "method": m, "params": pr}))
        while True:
            r = json.loads(ws.recv())
            if r.get("method") == "Runtime.exceptionThrown":
                erros.append(r["params"]["exceptionDetails"].get("exception", {}).get("description", "")[:200])
            if r.get("id") == n[0]: return r.get("result", r)
    ev = lambda js: cmd("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)["result"].get("value")
    cmd("Page.enable"); cmd("Runtime.enable")
    if ua: cmd("Emulation.setUserAgentOverride", userAgent=ua)
    # Registra as chamadas do número no ícone e simula o pedido de instalação do navegador.
    cmd("Page.addScriptToEvaluateOnNewDocument", source="""
      window.__badge=[]; navigator.setAppBadge=(n)=>{window.__badge.push(n);return Promise.resolve()};
      navigator.clearAppBadge=()=>{window.__badge.push(0);return Promise.resolve()};""")
    return p, cmd, ev

def login(cmd, ev):
    cmd("Page.navigate", url=B + "/login"); time.sleep(1.2)
    return ev(f"fetch('/api/auth/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email:{json.dumps(EMAIL)},password:{json.dumps(PW)}}})}}).then(r=>r.status)")

def go(cmd, url, w=3):
    cmd("Page.navigate", url=B + url); time.sleep(w)

procs = []
try:
    p, cmd, ev = browser(9521); procs.append(p)
    cmd("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)
    check("login", login(cmd, ev) == 200)
    go(cmd, "/#/hoje")
    m = cmd("Page.getAppManifest")
    check("manifest sem erros", not m.get("errors"), m.get("errors"))
    man = json.loads(m.get("data") or "{}")
    check("manifest: 3 atalhos", len(man.get("shortcuts", [])) == 3)
    check("manifest: compartilhar (com fotos)", (man.get("share_target") or {}).get("action") == "/compartilhar" and (man.get("share_target") or {}).get("method") == "POST")
    inst = cmd("Page.getInstallabilityErrors")
    check("instalável (sem erros de instalação)", not inst.get("installabilityErrors"), inst.get("installabilityErrors"))
    for src in ["/img/atalho-nova.png", "/img/telas/hoje.webp", "/img/telas/cel-hoje.webp"]:
        check("arquivo " + src, ev(f"fetch('{src}').then(r=>r.status)") == 200)

    # Atalho: nova tarefa
    go(cmd, "/#/hoje?acao=nova")
    check("atalho nova: formulário aberto", ev("document.getElementById('dialog-worklog').open") is True)
    check("atalho nova: endereço limpo", ev("location.hash") == "#/hoje", ev("location.hash"))
    ev("document.getElementById('dialog-worklog').close()")
    # Atalho: registro rápido
    go(cmd, "/#/hoje?acao=rapido")
    check("atalho rápido: campo com foco", ev("document.activeElement && document.activeElement.getAttribute('aria-label')") == "Registrar tarefa rápida",
          ev("document.activeElement && document.activeElement.outerHTML.slice(0,80)"))

    # Número no ícone: atrasadas (a demo tem 1)
    check("número no ícone", ev("window.__badge.length>0 && window.__badge[window.__badge.length-1]>=1"), ev("JSON.stringify(window.__badge)"))

    # Compartilhar: texto curto
    go(cmd, "/?title=" + urllib.parse.quote("Impressora do RH sem toner") + "&text=" + urllib.parse.quote("Pediram pelo WhatsApp\nsala 2"))
    check("compartilhar: formulário aberto", ev("document.getElementById('dialog-worklog').open") is True)
    check("compartilhar: título", ev("document.getElementById('wl-title').value") == "Impressora do RH sem toner", ev("document.getElementById('wl-title').value"))
    check("compartilhar: descrição", ev("document.getElementById('wl-desc').value") == "Pediram pelo WhatsApp · sala 2", ev("document.getElementById('wl-desc').value"))
    check("compartilhar: endereço limpo", ev("location.search") == "", ev("location.search"))
    shot = cmd("Page.captureScreenshot", format="png")
    import base64; open(f"{OUT}/e1-compartilhar.png", "wb").write(base64.b64decode(shot["data"]))
    ev("document.getElementById('dialog-worklog').close()")

    # Compartilhar: texto longo vira anotação ao salvar
    longo = "Assunto do e-mail\n" + ("Linha do corpo do e-mail com detalhes do problema. " * 12)
    go(cmd, "/?text=" + urllib.parse.quote(longo) + "&url=" + urllib.parse.quote("https://exemplo.com/chamado/77"))
    check("longo: título = 1ª linha", ev("document.getElementById('wl-title').value") == "Assunto do e-mail")
    check("longo: descrição = link", ev("document.getElementById('wl-desc').value") == "https://exemplo.com/chamado/77", ev("document.getElementById('wl-desc').value"))
    ev("document.getElementById('wl-title').value='E1 teste compartilhar longo'")
    ev("document.querySelector('#form-worklog [type=submit], #dialog-worklog button[type=submit]').click()"); time.sleep(2.5)
    tid = ev("""fetch('/api/worklog?status=open').then(r=>r.json()).then(l=>{const t=l.find(x=>x.title==='E1 teste compartilhar longo');return t&&t.id})""")
    check("longo: tarefa criada", bool(tid))
    if tid:
        t = ev(f"fetch('/api/worklog/{tid}').then(r=>r.json())")
        check("longo: texto inteiro na anotação", len(t.get("notes", [])) == 1 and t["notes"][0]["body"].startswith("Linha do corpo"), str(t.get("notes"))[:120])
        ev(f"fetch('/api/auth/me').then(r=>r.json()).then(me=>fetch('/api/worklog/{tid}',{{method:'DELETE',headers:{{'X-CSRF-Token':me.csrf_token}}}}))")

    # Convite para instalar: pedido simulado do navegador
    go(cmd, "/#/hoje", .5); cmd("Page.reload"); time.sleep(1)
    ev("""(()=>{const e=new Event('beforeinstallprompt');window.__prompted=0;e.prompt=()=>{window.__prompted++};
      e.userChoice=Promise.resolve({outcome:'accepted'});dispatchEvent(e)})()""")
    time.sleep(8)
    check("convite: aparece", ev("!!document.querySelector('.install-card')"))
    shot = cmd("Page.captureScreenshot", format="png"); open(f"{OUT}/e1-convite.png", "wb").write(base64.b64decode(shot["data"]))
    ev("[...document.querySelectorAll('.install-card button')].find(b=>b.textContent==='Instalar').click()"); time.sleep(.5)
    check("convite: Instalar chama o navegador", ev("window.__prompted") == 1)
    # Ajuda: botão Instalar o app
    ev("document.getElementById('btn-help').click()"); time.sleep(.6)
    check("ajuda: Instalar o app", ev("[...document.querySelectorAll('dialog[open] button')].some(b=>b.textContent.includes('Instalar o app'))"))

    # Compartilhar sem sessão: guarda, passa pelo login e abre depois
    p2, cmd2, ev2 = browser(9522); procs.append(p2)
    cmd2("Page.navigate", url=B + "/?text=" + urllib.parse.quote("Trocar cabo do ponto 14")); time.sleep(2.5)
    check("sem sessão: foi pro login", ev2("location.pathname") == "/login", ev2("location.pathname"))
    ev2(f"document.getElementById('login-email').value={json.dumps(EMAIL)};document.getElementById('login-password').value={json.dumps(PW)};document.getElementById('form-login').requestSubmit()")
    time.sleep(4)
    check("sem sessão: depois do login abre a tarefa compartilhada", ev2("document.getElementById('dialog-worklog').open && document.getElementById('wl-title').value") == "Trocar cabo do ponto 14",
          ev2("document.getElementById('wl-title') && document.getElementById('wl-title').value"))

    # iPhone: passo a passo
    p3, cmd3, ev3 = browser(9523, ua="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"); procs.append(p3)
    cmd3("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=2, mobile=True)
    login(cmd3, ev3); go(cmd3, "/#/hoje", 6)
    check("iPhone: convite aparece", ev3("!!document.querySelector('.install-card')"))
    shot = cmd3("Page.captureScreenshot", format="png"); open(f"{OUT}/e1-iphone-convite.png", "wb").write(base64.b64decode(shot["data"]))
    ev3("[...document.querySelectorAll('.install-card button')].find(b=>b.textContent==='Como instalar').click()"); time.sleep(.6)
    check("iPhone: passo a passo", "Adicionar à Tela de Início" in (ev3("document.querySelector('dialog[open]')?.innerText") or ""))
    shot = cmd3("Page.captureScreenshot", format="png"); open(f"{OUT}/e1-iphone-passos.png", "wb").write(base64.b64decode(shot["data"]))
    ev3("document.querySelector('dialog[open] .btn-primary').click()"); time.sleep(.3)
    go(cmd3, "/#/hoje", 6)
    check("iPhone: dispensado não volta", not ev3("!!document.querySelector('.install-card')"))
finally:
    for p in procs: p.terminate()
    print("OK:", len(ok)); print("FALHAS:", "\n  ".join(falhas) or "nenhuma"); print("ERROS JS:", erros or "nenhum")
