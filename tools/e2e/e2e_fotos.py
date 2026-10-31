"""E4 no navegador: foto na tarefa (arquivo grande reduzido), print colado, visualizador,
excluir com desfazer, evidência da rotina e compartilhar com foto (service worker)."""
import base64, json, os, subprocess, sys, tempfile, time, urllib.request
import websocket
B = os.environ.get("NEXUS_E2E_URL", "http://localhost:8090")
EMAIL, PW = os.environ["NEXUS_E2E_USER"].split(":", 1)
OUT = sys.argv[1]
GRANDE, PRINT = os.path.join(OUT, "foto-grande.jpg"), os.path.join(OUT, "print.png")
ok, falhas, erros = [], [], []
def check(nome, cond, extra=""):
    (ok if cond else falhas).append(nome + ("" if cond else f"  [{extra}]"))
p = subprocess.Popen(["chromium", "--headless=new", "--remote-debugging-port=9551", "--remote-allow-origins=http://127.0.0.1:9551",
                      f"--user-data-dir={tempfile.mkdtemp()}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try: tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9551/json")); break
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
    api = lambda m, u, d=None: ev(f"""fetch('/api/auth/me').then(r=>r.json()).then(me=>fetch('/api{u}',{{method:'{m}',headers:{{'Content-Type':'application/json','X-CSRF-Token':me.csrf_token}},body:{json.dumps(json.dumps(d)) if d is not None else 'undefined'}}})).then(async r=>({{s:r.status,b:await r.json().catch(()=>null)}}))""")
    def set_file(selector, path):
        doc = cmd("DOM.getDocument", depth=-1, pierce=True)["root"]["nodeId"]
        node = cmd("DOM.querySelector", nodeId=doc, selector=selector)["nodeId"]
        cmd("DOM.setFileInputFiles", files=[path], nodeId=node)

    cmd("Page.enable"); cmd("Runtime.enable"); cmd("DOM.enable")
    cmd("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)
    cmd("Page.navigate", url=B + "/login"); time.sleep(1.2)
    ev(f"fetch('/api/auth/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email:{json.dumps(EMAIL)},password:{json.dumps(PW)}}})}})")
    # sobras de rodadas anteriores (mesmos nomes) atrapalhariam os seletores
    for rr in api("GET", "/board")["b"]["recurring"]:
        if rr["label"].startswith("E4 "): api("DELETE", f"/recurring/{rr['id']}")
    for tt in ev("fetch('/api/worklog?status=open').then(r=>r.json())") or []:
        if tt["title"].startswith("E4 "): api("DELETE", f"/worklog/{tt['id']}")
    tid = api("POST", "/worklog", {"title": "E4 rack do 2º andar"})["b"]["id"]
    cmd("Page.navigate", url=B + f"/#/tarefas?id={tid}"); time.sleep(3)
    check("detalhe aberto com a seção Fotos", ev("!!document.querySelector('.task-photos .photo-add')"))
    set_file(".task-photos input[type=file]", GRANDE); time.sleep(4)
    det = api("GET", f"/worklog/{tid}")["b"]
    check("foto grande enviada", len(det["photos"]) == 1, det.get("photos"))
    if det["photos"]:
        ph = det["photos"][0]
        check("reduzida a 1600 px", max(ph["width"], ph["height"]) == 1600, ph)
        info = ev(f"fetch('/api/photos/{ph['id']}').then(async r=>({{type:r.headers.get('content-type'),size:(await r.arrayBuffer()).byteLength}}))")
        check("regravada em WebP e < 1 MB", info["type"] == "image/webp" and info["size"] < 1024 * 1024, info)
    check("miniatura na tela", ev("document.querySelectorAll('.task-photos .photo-thumb img').length") == 1)
    # print colado
    b64 = base64.b64encode(open(PRINT, "rb").read()).decode()
    ev(f"""(async()=>{{const b=new Blob([Uint8Array.from(atob('{b64}'),c=>c.charCodeAt(0))],{{type:'image/png'}});const dt=new DataTransfer();
      dt.items.add(new File([b],'print.png',{{type:'image/png'}}));
      document.querySelector('dialog.task-dialog').dispatchEvent(new ClipboardEvent('paste',{{clipboardData:dt,bubbles:true,cancelable:true}}))}})()""")
    time.sleep(4)
    check("print colado virou foto", len(api("GET", f"/worklog/{tid}")["b"]["photos"]) == 2)
    check("etiqueta de fotos no quadro", "2" in (ev(f"[...document.querySelectorAll('[data-task-id=\"{tid}\"] .tag')].map(t=>t.title+t.textContent).join()") or ""),
          ev(f"[...document.querySelectorAll('[data-task-id=\"{tid}\"] .tag')].map(t=>t.title+t.textContent).join()"))
    shot("e4-detalhe")
    # visualizador e excluir com desfazer
    ev("document.querySelector('.task-photos .photo-thumb').click()"); time.sleep(1)
    check("visualizador abre", ev("!!document.querySelector('dialog.photo-dialog[open] img.photo-big')"))
    shot("e4-visualizador")
    ev("document.querySelector('dialog.photo-dialog [aria-label=\"Excluir a foto\"]').click()"); time.sleep(2)
    check("excluiu", len(api("GET", f"/worklog/{tid}")["b"]["photos"]) == 1)
    ev("[...document.querySelectorAll('.toast button')].find(b=>b.textContent==='Desfazer')?.click()"); time.sleep(2)
    check("desfazer devolveu", len(api("GET", f"/worklog/{tid}")["b"]["photos"]) == 2)
    # evidência da rotina
    rot = f"E4 nobreak {int(time.time()) % 100000}"
    r = api("POST", "/recurring", {"label": rot, "freq": "weekly", "weekdays": 127})["b"]
    hoje = api("GET", "/recurring/reminders")["b"]["today"]
    api("POST", f"/recurring/{r['id']}/toggle", {"done": True})
    cmd("Page.navigate", url=B + "/#/hoje"); time.sleep(.5); cmd("Page.reload"); time.sleep(3)
    ev(f"document.querySelector('[aria-label=\"Evidência de {rot}\"]').click()"); time.sleep(1.5)
    check("evidência com fotos", ev("!!document.querySelector('dialog[open] .photo-add')"))
    set_file("dialog[open] input[type=file]", PRINT); time.sleep(4)
    check("foto na evidência", len(api("GET", f"/recurring/{r['id']}/photos?day={hoje}")["b"]) == 1)
    shot("e4-evidencia")
    ev("[...document.querySelectorAll('dialog[open] button')].find(b=>b.textContent==='Cancelar').click()"); time.sleep(2)
    check("Hoje mostra '1 foto' na rotina", "1 foto" in (ev(f"[...document.querySelectorAll('.check-row')].find(x=>x.textContent.includes('{rot}'))?.textContent") or ""))
    # compartilhar com foto (o service worker atende o POST)
    ev("navigator.serviceWorker.ready.then(()=>1)"); cmd("Page.reload"); time.sleep(3)
    ctrl = ev("!!navigator.serviceWorker.controller")
    check("service worker controla a página", ctrl)
    ev(f"""(async()=>{{const b=new Blob([Uint8Array.from(atob('{b64}'),c=>c.charCodeAt(0))],{{type:'image/png'}});const fd=new FormData();
      fd.append('title','');fd.append('text','Painel do nobreak com alarme');fd.append('fotos',new File([b],'p.png',{{type:'image/png'}}));
      return (await fetch('/compartilhar',{{method:'POST',body:fd,redirect:'manual'}})).type}})()""")
    cmd("Page.navigate", url=B + "/?compartilhado=1"); time.sleep(4)
    check("compartilhar: nova tarefa preenchida", ev("document.getElementById('dialog-worklog').open && document.getElementById('wl-title').value") == "Painel do nobreak com alarme",
          ev("document.getElementById('wl-title').value"))
    ev("document.getElementById('wl-title').value='E4 compartilhada com foto'")
    ev("document.querySelector('#dialog-worklog button[type=submit]').click()"); time.sleep(5)
    t2 = ev("fetch('/api/worklog?status=open').then(r=>r.json()).then(l=>(l.find(x=>x.title==='E4 compartilhada com foto')||{}).id)")
    check("compartilhar: foto foi junto", bool(t2) and len(api("GET", f"/worklog/{t2}")["b"]["photos"]) == 1)
    # limpeza
    for x in (tid, t2):
        if x: api("DELETE", f"/worklog/{x}")
    api("DELETE", f"/recurring/{r['id']}")
finally:
    p.terminate()
    print("OK:", len(ok)); print("FALHAS:", "\n  ".join(falhas) or "nenhuma"); print("ERROS JS:", erros or "nenhum")
