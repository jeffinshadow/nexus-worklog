"""E5: sem conexão de verdade (o nginx da homolog é desligado no meio), fila no aparelho e envio na volta."""
import base64, json, os, subprocess, sys, tempfile, time, urllib.request
import websocket
B = os.environ.get("NEXUS_E2E_URL", "http://localhost:8090")
EMAIL, PW = os.environ["NEXUS_E2E_USER"].split(":", 1)
OUT = sys.argv[1]
ok, falhas, erros = [], [], []
def check(nome, cond, extra=""):
    (ok if cond else falhas).append(nome + ("" if cond else f"  [{extra}]"))
def web(acao):
    subprocess.run(["ssh", os.environ["NEXUS_E2E_SSH"], f"cd {os.environ.get('NEXUS_E2E_DIR', '/srv/docker/nexus-worklog')} && docker compose {acao} web"], capture_output=True)
p = subprocess.Popen(["chromium", "--headless=new", "--remote-debugging-port=9561", "--remote-allow-origins=http://127.0.0.1:9561",
                      f"--user-data-dir={tempfile.mkdtemp()}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try: tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9561/json")); break
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
    def ev(js):
        r = cmd("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)
        return r.get("exceptionDetails", {}).get("exception", {}).get("description") if "exceptionDetails" in r else r["result"].get("value")
    shot = lambda nome: open(f"{OUT}/{nome}.png", "wb").write(base64.b64decode(cmd("Page.captureScreenshot", format="png")["data"]))
    api = lambda m, u, d=None: ev(f"""fetch('/api/auth/me').then(r=>r.json()).then(me=>fetch('/api{u}',{{method:'{m}',headers:{{'Content-Type':'application/json','X-CSRF-Token':me.csrf_token}},body:{json.dumps(json.dumps(d)) if d is not None else 'undefined'}}})).then(async r=>({{s:r.status,b:await r.json().catch(()=>null)}}))""")
    go = lambda u, w=3: (cmd("Page.navigate", url=B + u), time.sleep(w))

    cmd("Page.enable"); cmd("Runtime.enable")
    cmd("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)
    go("/login", 1.2)
    ev(f"fetch('/api/auth/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email:{json.dumps(EMAIL)},password:{json.dumps(PW)}}})}})")
    marca = str(int(time.time()) % 100000)
    tid = api("POST", "/worklog", {"title": f"E5 trocar cabo {marca}"})["b"]["id"]
    tfin = api("POST", "/worklog", {"title": f"E5 concluir {marca}"})["b"]["id"]
    rid = api("POST", "/recurring", {"label": f"E5 rotina {marca}", "freq": "weekly", "weekdays": 127})["b"]["id"]
    api("DELETE", "/timer")
    # com conexão: visita as telas (o service worker guarda)
    go("/#/hoje", 3); cmd("Page.reload"); time.sleep(3)
    go(f"/#/tarefas?id={tid}", 3); ev("document.querySelector('dialog.task-dialog')?.close()")
    go(f"/#/tarefas?id={tfin}", 3); ev("document.querySelector('dialog.task-dialog')?.close()")
    go("/#/hoje", 3)
    check("service worker no controle", ev("!!navigator.serviceWorker.controller"))

    web("stop"); time.sleep(2)
    t0 = time.time()
    cmd("Page.reload"); time.sleep(5)
    check("sem servidor: o app abre", ev("!!document.querySelector('#view-hoje .t-rec')"), ev("document.body.innerText.slice(0,200)"))
    check("barra 'sem conexão' com a hora", "mostrando o que havia" in (ev("document.querySelector('.offline-bar')?.innerText") or ""), ev("document.querySelector('.offline-bar')?.innerText"))
    # registro rápido com tempo
    ev(f"""(()=>{{const q=document.querySelector('[aria-label="Registrar tarefa rápida"]');q.value='E5 registro offline {marca} — 15min';
      q.dispatchEvent(new KeyboardEvent('keydown',{{key:'Enter',bubbles:true}}))}})()"""); time.sleep(2)
    # rotina
    ev(f"[...document.querySelectorAll('.check-row')].find(x=>x.textContent.includes('E5 rotina {marca}')).querySelector('input').click()"); time.sleep(2)
    check("rotina aparece marcada (fila por cima)", ev(f"[...document.querySelectorAll('.check-row')].find(x=>x.textContent.includes('E5 rotina {marca}')).querySelector('input').checked"))
    # concluir uma tarefa
    ev(f"[...document.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')==='Concluir E5 concluir {marca}')?.click()"); time.sleep(2)
    check("concluída some das abertas", not ev(f"document.getElementById('view-hoje').innerText.includes('E5 concluir {marca}')"))
    # anotação na tarefa (detalhe guardado)
    go(f"/#/tarefas?id={tid}", 4)
    ev("(()=>{const t=document.querySelector('.task-dialog textarea[placeholder^=\"Progresso\"]');t.value='Cabo trocado sem sinal';t.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',ctrlKey:true,bubbles:true}))})()")
    time.sleep(2)
    check("anotação aparece 'esperando conexão'", "esperando conexão" in (ev("document.querySelector('.task-dialog')?.innerText") or ""), (ev("document.querySelector('.task-dialog')?.innerText") or "")[:300])
    # cronômetro
    ev("[...document.querySelectorAll('.task-dialog button')].find(b=>b.textContent.trim()==='Cronômetro')?.click()"); time.sleep(2)
    check("cronômetro rodando sem conexão", not ev("document.getElementById('timer-side').classList.contains('hidden')"))
    time.sleep(62)
    ev("document.querySelector('#timer-side [aria-label^=\"Parar\"]').click()"); time.sleep(2)
    fila = ev("new Promise(ok=>{const r=indexedDB.open('nexus');r.onsuccess=()=>{const g=r.result.transaction('fila').objectStore('fila').getAll();g.onsuccess=()=>ok(g.result.map(o=>o.method+' '+o.path+(o.then.length?' +'+o.then.length:'')))}})")
    check("fila com as 6 ações", len(fila or []) == 6, fila)
    check("barra conta as alterações", "6 alterações esperando" in (ev("document.querySelector('.offline-bar')?.innerText") or ""), ev("document.querySelector('.offline-bar')?.innerText"))
    shot("e5-offline")

    web("start"); time.sleep(8)
    ev("dispatchEvent(new Event('online'))"); time.sleep(8)
    fila = ev("new Promise(ok=>{const r=indexedDB.open('nexus');r.onsuccess=()=>{const g=r.result.transaction('fila').objectStore('fila').getAll();g.onsuccess=()=>ok(g.result.length)}})")
    check("na volta: fila vazia", fila == 0, fila)
    reg = ev(f"fetch('/api/worklog?status=done').then(r=>r.json()).then(l=>l.find(x=>x.title==='E5 registro offline {marca}'))")
    check("registro rápido criado e concluído", bool(reg), reg)
    if reg:
        check("registro com 15 min", api("GET", f"/worklog/{reg['id']}")["b"]["minutes"] == 15 if "minutes" in api("GET", f"/worklog/{reg['id']}")["b"] else
              sum(e["minutes"] for e in api("GET", f"/worklog/{reg['id']}")["b"].get("time", [])) == 15, api("GET", f"/worklog/{reg['id']}")["b"].get("time"))
    check("rotina marcada no servidor", any(x["id"] == rid and x["done_today"] for x in api("GET", "/board")["b"]["recurring"]))
    fin = api("GET", f"/worklog/{tfin}")["b"]
    check("concluída no servidor", fin["status"] == "done", fin["status"])
    det = api("GET", f"/worklog/{tid}")["b"]
    check("anotação chegou", any(nn["body"] == "Cabo trocado sem sinal" for nn in det["notes"]))
    tempo = sum(e["minutes"] for e in det.get("time", []))
    check("cronômetro apontou ~1 min com a hora do aparelho", 1 <= tempo <= 2, det.get("time"))
    cmd("Page.reload"); time.sleep(4)
    check("barra some na volta", not ev("!!document.querySelector('.offline-bar')"), ev("document.querySelector('.offline-bar')?.innerText"))
    for x in (tid, tfin, (reg or {}).get("id")):
        if x: api("DELETE", f"/worklog/{x}")
finally:
    web("start")
    p.terminate()
    print("OK:", len(ok)); print("FALHAS:", "\n  ".join(falhas) or "nenhuma"); print("ERROS JS:", erros or "nenhum")
