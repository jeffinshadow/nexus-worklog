"""Concluir espera o fim da edição (detalhe, cartão, menu); avisos esperam salvar; evidência espera a foto."""
import base64, json, os, subprocess, sys, tempfile, time, urllib.request
import websocket
B = os.environ.get("NEXUS_E2E_URL", "http://localhost:8090"); EMAIL, PW = os.environ["NEXUS_E2E_USER"].split(":", 1); OUT = sys.argv[1]
ok, falhas, erros = [], [], []
def check(nome, cond, extra=""): (ok if cond else falhas).append(nome + ("" if cond else f"  [{extra}]"))
p = subprocess.Popen(["chromium", "--headless=new", "--remote-debugging-port=9581", "--remote-allow-origins=http://127.0.0.1:9581", f"--user-data-dir={tempfile.mkdtemp()}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try: tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9581/json")); break
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
    api = lambda m, u, d=None: ev(f"""fetch('/api/auth/me').then(r=>r.json()).then(me=>fetch('/api{u}',{{method:'{m}',headers:{{'Content-Type':'application/json','X-CSRF-Token':me.csrf_token}},body:{json.dumps(json.dumps(d)) if d is not None else 'undefined'}}})).then(async r=>({{s:r.status,b:await r.json().catch(()=>null)}}))""")
    cmd("Page.enable"); cmd("Runtime.enable"); cmd("Emulation.setFocusEmulationEnabled", enabled=True); cmd("Emulation.setDeviceMetricsOverride", width=1600, height=900, deviceScaleFactor=1, mobile=False)
    cmd("Page.navigate", url=B + "/login"); time.sleep(1.2)
    ev(f"fetch('/api/auth/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email:{json.dumps(EMAIL)},password:{json.dumps(PW)}}})}})")
    ev("localStorage.setItem('nexus.instalar.dispensado', String(Date.now()))")
    marca = str(int(time.time()) % 100000)
    tid = api("POST", "/worklog", {"title": f"Edição {marca}"})["b"]["id"]
    cmd("Page.navigate", url=B + f"/#/tarefas?id={tid}"); time.sleep(3.5)
    check("fora da edição: Concluir livre", ev("!document.querySelector('.task-main-actions .btn-primary').disabled"))
    ev("document.querySelector('.task-dialog .edit-toggle').click()"); time.sleep(1)
    check("editando: Concluir do detalhe desligado", ev("document.querySelector('.task-main-actions .btn-primary').disabled"))
    check("dica explica", ev("document.querySelector('.task-main-actions .btn-primary').title") == "Termine a edição (Pronto) para concluir")
    card = f"[data-task-id=\"{tid}\"]"
    check("cartão marcado em edição", ev(f"document.querySelector('{card}').classList.contains('editing')"))
    check("concluir do cartão esmaecido e sem clique", ev(f"getComputedStyle(document.querySelector('{card} button[aria-label^=Concluir]')).pointerEvents") == "none")
    # menu do clique direito: escolhe Concluir → recusa com aviso
    ev(f"document.querySelector('{card}').dispatchEvent(new MouseEvent('contextmenu',{{bubbles:true,clientX:300,clientY:300}}))"); time.sleep(.5)
    ev("[...document.querySelectorAll('.pop-menu button')].find(b=>b.textContent.includes('Concluir'))?.click()"); time.sleep(1.2)
    check("menu: não conclui durante a edição", api("GET", f"/worklog/{tid}")["b"]["status"] != "done")
    check("menu: avisa para terminar a edição", "Termine a edição" in (ev("document.querySelector('.toasts')?.innerText") or ""), ev("document.querySelector('.toasts')?.innerText"))
    # edita o título e conclui depois do Pronto
    ev("(()=>{const t=document.querySelector('.task-dialog textarea.inline-title');t.focus();t.value='Edição "+marca+" (revisada)';t.dispatchEvent(new Event('input'));t.blur()})()"); time.sleep(1)
    ev("[...document.querySelectorAll('.task-dialog .edit-toggle')].find(b=>b.textContent.includes('Pronto')).click()"); time.sleep(2)
    check("Pronto: libera o Concluir", ev("!document.querySelector('.task-main-actions .btn-primary').disabled"))
    check("Pronto: cartão sai do estado de edição", not ev(f"document.querySelector('{card}')?.classList.contains('editing')"))
    ev("document.querySelector('.task-main-actions .btn-primary').click()"); time.sleep(2)
    t = api("GET", f"/worklog/{tid}")["b"]
    check("concluída com o título editado", t["status"] == "done" and t["title"].endswith("(revisada)"), t["title"])
    # concluir pelo status dentro da edição continua valendo
    tid2 = api("POST", "/worklog", {"title": f"Status {marca}"})["b"]["id"]
    cmd("Page.navigate", url=B + f"/#/tarefas?id={tid2}"); time.sleep(3.5)
    ev("document.querySelector('.task-dialog .edit-toggle').click()"); time.sleep(1)
    ev("(()=>{const s=document.querySelector('.task-dialog select[aria-label=Status]');s.value='done';s.dispatchEvent(new Event('change'))})()"); time.sleep(2)
    check("status Concluída dentro da edição conclui", api("GET", f"/worklog/{tid2}")["b"]["status"] == "done")
    # avisos: testar espera salvar
    cmd("Page.navigate", url=B + "/#/config?aba=avisos"); time.sleep(3.5)
    ev("document.querySelectorAll('dialog[open]').forEach(d=>d.close())")
    livre = ev("(()=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Mandar um teste'));return b && !b.disabled})()")
    ev("document.querySelector('input[aria-label=\"Seu dia\"]').click()"); time.sleep(.3)
    check("avisos: com alteração, testar esmaece", ev("[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Mandar um teste')).disabled") and
          ev("[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Testar a semana')).title") == "Salve os avisos antes de testar")
    ev("[...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar avisos').click()"); time.sleep(1.5)
    check("avisos: depois de salvar, testar volta", ev("!([...document.querySelectorAll('button')].find(b=>b.textContent.includes('Mandar um teste')).disabled)") == bool(livre))
    ev("document.querySelector('input[aria-label=\"Seu dia\"]').click()"); time.sleep(.3)
    ev("[...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar avisos').click()"); time.sleep(1)
    # evidência: Salvar espera a foto
    rid = api("POST", "/recurring", {"label": f"Evid {marca}", "freq": "weekly", "weekdays": 127})["b"]["id"]
    api("POST", f"/recurring/{rid}/toggle", {"done": True})
    cmd("Page.navigate", url=B + "/#/hoje"); time.sleep(.4); cmd("Page.reload"); time.sleep(3.5)
    ev(f"document.querySelector('[aria-label=\"Evidência de Evid {marca}\"]').click()"); time.sleep(1.5)
    ev("document.querySelector('dialog[open] .photo-grid').dispatchEvent(new CustomEvent('photo-busy',{detail:true,bubbles:true}))")
    check("evidência: Salvar espera a foto", ev("(()=>{const b=document.querySelector('dialog[open] button[type=submit]');return b.disabled && b.textContent})()") == "Enviando a foto…")
    ev("document.querySelector('dialog[open] .photo-grid').dispatchEvent(new CustomEvent('photo-busy',{detail:false,bubbles:true}))")
    check("evidência: volta ao Salvar", ev("(()=>{const b=document.querySelector('dialog[open] button[type=submit]');return !b.disabled && b.textContent})()") == "Salvar")
    for x in (tid, tid2): api("DELETE", f"/worklog/{x}")
    api("DELETE", f"/recurring/{rid}")
finally:
    p.terminate(); print("OK:", len(ok)); print("FALHAS:", "\n  ".join(falhas) or "nenhuma"); print("ERROS JS:", erros or "nenhum")
