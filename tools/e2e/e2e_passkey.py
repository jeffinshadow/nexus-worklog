"""E3 no navegador: passkey com o autenticador virtual do Chrome (homolog em localhost)."""
import base64, json, os, subprocess, sys, tempfile, time, urllib.request
import websocket
B = os.environ.get("NEXUS_E2E_URL", "http://localhost:8090")
EMAIL, PW = os.environ["NEXUS_E2E_USER"].split(":", 1)
OUT = sys.argv[1]
ok, falhas, erros = [], [], []
def check(nome, cond, extra=""):
    (ok if cond else falhas).append(nome + ("" if cond else f"  [{extra}]"))
p = subprocess.Popen(["chromium", "--headless=new", "--remote-debugging-port=9541", "--remote-allow-origins=http://127.0.0.1:9541",
                      f"--user-data-dir={tempfile.mkdtemp()}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try: tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9541/json")); break
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
    shot = lambda nome: open(f"{OUT}/{nome}.png", "wb").write(base64.b64decode(cmd("Page.captureScreenshot", format="png")["data"]))
    cmd("Page.enable"); cmd("Runtime.enable")
    cmd("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
    cmd("WebAuthn.enable", enableUI=False)
    aut = cmd("WebAuthn.addVirtualAuthenticator", options={"protocol": "ctap2", "transport": "internal", "hasResidentKey": True,
                                                            "hasUserVerification": True, "isUserVerified": True, "automaticPresenceSimulation": True})["authenticatorId"]
    cmd("Page.navigate", url=B + "/login"); time.sleep(1.5)
    check("login: botão de passkey", ev("!document.getElementById('login-passkey').classList.contains('hidden')"))
    ev(f"fetch('/api/auth/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email:{json.dumps(EMAIL)},password:{json.dumps(PW)}}})}})")
    # limpa passkeys de execuções anteriores
    ev("""fetch('/api/auth/me').then(r=>r.json()).then(async me=>{const l=await (await fetch('/api/auth/passkeys')).json();
      for(const x of l) await fetch('/api/auth/passkeys/'+x.id,{method:'DELETE',headers:{'X-CSRF-Token':me.csrf_token}})})""")
    cmd("Page.navigate", url=B + "/#/config?aba=conta"); time.sleep(3)
    check("painel Passkeys", ev("[...document.querySelectorAll('.panel h2')].some(h=>h.textContent==='Passkeys')"))
    ev("[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Adicionar passkey')).click()"); time.sleep(3)
    lista = ev("fetch('/api/auth/passkeys').then(r=>r.json())")
    check("cadastrou 1 passkey", len(lista or []) == 1, lista)
    creds = cmd("WebAuthn.getCredentials", authenticatorId=aut)["credentials"]
    check("autenticador guardou a passkey (residente)", len(creds) == 1 and creds[0]["isResidentCredential"], creds)
    ev("[...document.querySelectorAll('.panel')].find(p=>p.querySelector('h2')?.textContent==='Passkeys')?.scrollIntoView()"); time.sleep(.5)
    shot("e3-painel")
    # sair e entrar com o botão
    ev("fetch('/api/auth/me').then(r=>r.json()).then(me=>fetch('/api/auth/logout',{method:'POST',headers:{'X-CSRF-Token':me.csrf_token}}))")
    check("saiu", ev("fetch('/api/auth/me').then(r=>r.status)") == 401)  # antes do login: lá o autenticador virtual entra sozinho
    cmd("Page.navigate", url=B + "/login"); time.sleep(1.5)
    shot("e3-login")
    ev("document.getElementById('login-passkey').click()"); time.sleep(4)
    check("entrou com o botão", ev("location.pathname") == "/" and ev("fetch('/api/auth/me').then(r=>r.status)") == 200, ev("location.href"))
    check("contador/uso registrado", bool(ev("fetch('/api/auth/passkeys').then(r=>r.json()).then(l=>l[0].last_used_at)")))
    # sair e entrar pela sugestão do campo (mediation conditional)
    ev("fetch('/api/auth/me').then(r=>r.json()).then(me=>fetch('/api/auth/logout',{method:'POST',headers:{'X-CSRF-Token':me.csrf_token}}))")
    cmd("Page.navigate", url=B + "/login?next=%23%2Ftarefas"); time.sleep(5)
    check("entrou pela sugestão do campo e voltou à tela pedida", ev("location.hash") == "#/tarefas" and ev("fetch('/api/auth/me').then(r=>r.status)") == 200, ev("location.href"))
    # remover
    cmd("Page.navigate", url=B + "/#/config?aba=conta"); time.sleep(3)
    ev("document.querySelector('button[aria-label^=\"Remover\"]').click()"); time.sleep(.6)
    ev("[...document.querySelectorAll('dialog[open] button')].find(b=>b.textContent==='Remover').click()"); time.sleep(1.5)
    check("removeu", ev("fetch('/api/auth/passkeys').then(r=>r.json()).then(l=>l.length)") == 0)
    # sem passkey cadastrada no servidor: o botão avisa
    ev("fetch('/api/auth/me').then(r=>r.json()).then(me=>fetch('/api/auth/logout',{method:'POST',headers:{'X-CSRF-Token':me.csrf_token}}))")
    cmd("Page.navigate", url=B + "/login"); time.sleep(2)
    ev("document.getElementById('login-passkey').click()"); time.sleep(3)
    check("passkey removida não entra", ev("fetch('/api/auth/me').then(r=>r.status)") == 401 and "não reconhecida" in (ev("document.getElementById('login-error').textContent") or ""),
          ev("document.getElementById('login-error').textContent"))
finally:
    p.terminate()
    print("OK:", len(ok)); print("FALHAS:", "\n  ".join(falhas) or "nenhuma"); print("ERROS JS:", erros or "nenhum")
