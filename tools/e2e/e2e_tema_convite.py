"""Pedido de convite (login → admin), tema da conta e avatar padrão.
Uso: source e2e.env && python e2e_tema_convite.py SAIDA  (precisa do Mailpit da homologação em 127.0.0.1:8025)"""
import base64, json, os, subprocess, sys, tempfile, time, urllib.request
import websocket

B = os.environ.get("NEXUS_E2E_URL", "http://localhost:8090")
MAILPIT = os.environ.get("NEXUS_E2E_MAILPIT", "http://127.0.0.1:8025")
U = os.environ["NEXUS_E2E_USER"].split(":", 1)
A = os.environ["NEXUS_E2E_ADMIN"].split(":", 1)
OUT = sys.argv[1]
ok, falhas, erros = [], [], []
def check(nome, cond, extra=""): (ok if cond else falhas).append(nome + ("" if cond else f"  [{extra}]"))
def mails(to):
    try: d = json.load(urllib.request.urlopen(f"{MAILPIT}/api/v1/search?query=to:{to}"))
    except Exception: return []
    return [m["Subject"] for m in d.get("messages", [])]

p = subprocess.Popen(["chromium", "--headless=new", "--remote-debugging-port=9593", "--remote-allow-origins=http://127.0.0.1:9593",
                      f"--user-data-dir={tempfile.mkdtemp()}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try: tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9593/json")); break
        except Exception: time.sleep(.2)
    ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"], suppress_origin=True); n = [0]
    def cmd(m, **pr):
        n[0] += 1; ws.send(json.dumps({"id": n[0], "method": m, "params": pr}))
        while True:
            r = json.loads(ws.recv())
            if r.get("method") == "Runtime.exceptionThrown": erros.append(r["params"]["exceptionDetails"].get("exception", {}).get("description", "")[:200])
            if r.get("id") == n[0]: return r.get("result", r)
    def ev(js):
        r = cmd("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)
        return r["exceptionDetails"]["exception"].get("description") if "exceptionDetails" in r else r["result"].get("value")
    def login(c):
        cmd("Network.clearBrowserCookies"); cmd("Page.navigate", url=B + "/login"); time.sleep(1.3)
        ev("localStorage.setItem('nexus.instalar.dispensado', String(Date.now()))")
        ev(f"fetch('/api/auth/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email:{json.dumps(c[0])},password:{json.dumps(c[1])}}})}})")
    go = lambda r, w=3: (cmd("Page.navigate", url=B + "/#/" + r), time.sleep(.3), cmd("Page.reload"), time.sleep(w))
    cmd("Page.enable"); cmd("Runtime.enable"); cmd("Emulation.setFocusEmulationEnabled", enabled=True)
    cmd("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)

    # ---- pedido de convite pela tela de login
    marca = str(int(time.time()) % 100000)
    email = f"pedido{marca}@exemplo.com.br"
    cmd("Network.clearBrowserCookies"); cmd("Page.navigate", url=B + "/login"); time.sleep(1.8)
    check("login: link de pedir convite", ev("!document.getElementById('go-request').classList.contains('hidden')"))
    ev("document.getElementById('go-request').click()"); time.sleep(.5)
    ev(f"""(()=>{{const s=(id,v)=>{{const e=document.getElementById(id);e.value=v;e.dispatchEvent(new Event('change'))}};
      s('req-name','Teste Pedido {marca}');s('req-email','{email}');s('req-source','colega');s('req-note','um colega');
      s('req-reason','Quero registrar o suporte da filial.');document.getElementById('request-submit').click()}})()"""); time.sleep(3)
    check("pedido: confirmação na tela", "Pedido enviado" in (ev("document.getElementById('request-ok').textContent") or ""), ev("document.getElementById('request-error').textContent"))
    time.sleep(2)
    check("pedido: e-mail de confirmação para quem pediu", any("Recebemos o seu pedido" in s for s in mails(email)), mails(email))
    check("pedido: e-mail ao admin", any(f"Teste Pedido {marca}" in s for s in mails(A[0])), mails(A[0])[:3])

    # ---- admin vê, com número no menu, e convida
    login(A); go("admin", 3.5)
    check("admin: número no menu", (ev("document.querySelector('#nav [data-view=\"admin\"] .nav-badge')?.textContent") or "0") != "0")
    row = f"[...document.querySelectorAll('.request-row')].find(r=>r.textContent.includes('{email}'))"
    check("admin: pedido na lista", ev(f"!!{row}"))
    ev(f"{row}.querySelector('.btn-primary').click()"); time.sleep(3)
    check("admin: Convidar mostra o convite", "Convite" in (ev("document.querySelector('dialog[open] h2')?.textContent") or ""), ev("document.querySelector('dialog[open]')?.innerText"))
    ev("document.querySelectorAll('dialog[open]').forEach(d=>d.close())")
    check("admin: pedido marcado como convidado", "convidado" in (ev(f"{row}?.textContent") or ""))
    time.sleep(2)
    check("convite chegou para quem pediu", any("Convite" in s for s in mails(email)), mails(email))

    # ---- tema da conta e avatar padrão
    login(U); go("config?aba=conta", 3)
    check("avatar padrão (ícone, sem letra)", ev("!!document.querySelector('.who .avatar-default svg')") and not (ev("document.querySelector('.who .avatar')?.textContent") or "").strip())
    ev("[...document.querySelectorAll('.seg [data-v]')].find(b=>b.dataset.v==='light').click()"); time.sleep(1.2)
    check("tema Claro aplicado", ev("document.documentElement.dataset.theme") == "light")
    check("fundo claro de verdade", ev("getComputedStyle(document.body).backgroundColor") in ("rgb(246, 247, 250)",), ev("getComputedStyle(document.body).backgroundColor"))
    cmd("Page.reload"); time.sleep(3)
    check("tema continua depois de recarregar", ev("document.documentElement.dataset.theme") == "light")
    check("tema guardado na conta", ev("fetch('/api/auth/me').then(r=>r.json()).then(m=>m.theme)") == "light")
    ev("[...document.querySelectorAll('.seg [data-v]')].find(b=>b.dataset.v==='auto').click()"); time.sleep(1)
    check("Automático tira o forçado", ev("document.documentElement.dataset.theme") is None)
finally:
    p.terminate()
    print("OK:", len(ok)); print("FALHAS:", "\n  ".join(falhas) or "nenhuma"); print("ERROS JS:", erros or "nenhum")
