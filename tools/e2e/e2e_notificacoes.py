"""Verificação da E2 (homolog, conta demo): painel, ligar o aparelho, convite depois de instalado,
service worker mostrando a notificação e os botões Marcar feita / Adiar."""
import base64, json, os, subprocess, sys, tempfile, time, urllib.request
import websocket

B = os.environ.get("NEXUS_E2E_URL", "http://localhost:8090")
EMAIL, PW = os.environ["NEXUS_E2E_USER"].split(":", 1)
OUT = sys.argv[1]
ok, falhas, erros = [], [], []
def check(nome, cond, extra=""):
    (ok if cond else falhas).append(nome + ("" if cond else f"  [{extra}]"))

# Chaves "de navegador" válidas para a inscrição simulada (o Chromium de teste não fala com o FCM).
FAKE = """
(()=>{
  const ep='https://fcm.googleapis.com/fcm/send/e2e-'+Math.random().toString(36).slice(2);
  const b64u=(a)=>btoa(String.fromCharCode(...a)).replace(/\\+/g,'-').replace(/\\//g,'_').replace(/=+$/,'');
  const pub=new Uint8Array(65); pub[0]=4; for(let i=1;i<65;i++)pub[i]=i; const auth=new Uint8Array(16).fill(7);
  let sub=null;
  const mk=()=>({endpoint:ep, toJSON:()=>({endpoint:ep, keys:{p256dh:b64u(pub), auth:b64u(auth)}}), unsubscribe:async()=>{sub=null;return true}});
  PushManager.prototype.subscribe=async function(){ sub=mk(); window.__subscribed=(window.__subscribed||0)+1; return sub; };
  PushManager.prototype.getSubscription=async function(){ return sub; };
})();
"""

p = subprocess.Popen(["chromium", "--headless=new", "--remote-debugging-port=9531", "--remote-allow-origins=http://127.0.0.1:9531",
                      f"--user-data-dir={tempfile.mkdtemp()}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try: tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9531/json")); break
        except Exception: time.sleep(.2)
    browser_ws = json.load(urllib.request.urlopen("http://127.0.0.1:9531/json/version"))["webSocketDebuggerUrl"]
    ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"], suppress_origin=True)
    n = [0]; events = []
    def cmd(m, sock=None, **pr):
        sock = sock or ws
        n[0] += 1; sock.send(json.dumps({"id": n[0], "method": m, "params": pr}))
        while True:
            r = json.loads(sock.recv())
            if r.get("method") == "Runtime.exceptionThrown":
                erros.append(r["params"]["exceptionDetails"].get("exception", {}).get("description", "")[:200])
            if "method" in r: events.append(r)
            if r.get("id") == n[0]: return r.get("result", r)
    ev = lambda js: cmd("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)["result"].get("value")
    def shot(nome):
        open(f"{OUT}/{nome}.png", "wb").write(base64.b64decode(cmd("Page.captureScreenshot", format="png")["data"]))
    api = lambda m, u, d=None: ev(f"""fetch('/api/auth/me').then(r=>r.json()).then(me=>fetch('/api{u}',{{method:'{m}',headers:{{'Content-Type':'application/json','X-CSRF-Token':me.csrf_token}},body:{json.dumps(json.dumps(d)) if d is not None else 'undefined'}}})).then(async r=>({{s:r.status,b:await r.json().catch(()=>null)}}))""")

    cmd("Page.enable"); cmd("Runtime.enable")
    cmd("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)
    cmd("Page.addScriptToEvaluateOnNewDocument", source=FAKE)
    bws = websocket.create_connection(browser_ws, suppress_origin=True)
    cmd("Browser.grantPermissions", sock=bws, origin=B, permissions=["notifications"])
    cmd("Page.navigate", url=B + "/login"); time.sleep(1.2)
    ev(f"fetch('/api/auth/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email:{json.dumps(EMAIL)},password:{json.dumps(PW)}}})}})")
    # limpa aparelhos de execuções anteriores
    for d in (api("GET", "/push") or {}).get("b", {}).get("devices", []):
        api("DELETE", f"/push/devices/{d['id']}")

    cmd("Page.navigate", url=B + "/#/config?aba=avisos"); time.sleep(3.5)
    check("painel aparece", ev("!!document.querySelector('.push-here')"))
    check("estado: desligadas", "Desligadas neste aparelho" in (ev("document.querySelector('.push-here')?.innerText") or ""), ev("document.querySelector('.push-here')?.innerText"))
    shot("e2-painel-antes")
    ev("[...document.querySelectorAll('.push-here button')].find(b=>b.textContent.includes('Ligar')).click()"); time.sleep(2.5)
    check("ligar: inscreveu", ev("window.__subscribed") == 1)
    check("ligar: estado ligado", "Ligadas neste aparelho" in (ev("document.querySelector('.push-here')?.innerText") or ""), ev("document.querySelector('.push-here')?.innerText"))
    devs = api("GET", "/push")["b"]["devices"]
    check("servidor: 1 aparelho com nome", len(devs) == 1 and devs[0]["label"].startswith("Chrome"), devs)
    shot("e2-painel-ligado")
    # preferências
    ev("document.querySelector('input[aria-label=\"Prazos de hoje\"]').click()")
    ev("[...document.querySelectorAll('button')].find(b=>b.textContent==='Salvar notificações').click()"); time.sleep(1)
    check("preferência salva", api("GET", "/push")["b"]["prefs"]["deadline"] is False)
    api("PUT", "/push/prefs", {"deadline": True})

    # Service worker: notificação entregue (push sintético pelo CDP) e os botões.
    cmd("ServiceWorker.enable")
    for _ in range(10):  # os eventos chegam entre as respostas: uma chamada qualquer os recolhe
        time.sleep(.5); ev("1")
        if any(e.get("method") == "ServiceWorker.workerRegistrationUpdated" and e["params"]["registrations"] for e in events): break
    reg = next((e["params"]["registrations"] for e in events if e.get("method") == "ServiceWorker.workerRegistrationUpdated" and e["params"]["registrations"]), [])
    reg_id = reg[0]["registrationId"] if reg else None
    check("service worker registrado", bool(reg_id), reg)
    # uma rotina com horário para a demo
    r = api("POST", "/recurring", {"label": "E2 conferir nobreak", "freq": "weekly", "weekdays": 127, "remind_at": "06:00"})["b"]
    hoje = api("GET", "/recurring/reminders")["b"]["today"]
    msg = {"title": "E2 conferir nobreak", "body": "Agora, às 06:00", "url": "/#/hoje", "tag": f"rotina-{r['id']}-{hoje}", "kind": "rotina",
           "id": r["id"], "day": hoje, "require_interaction": True,
           "actions": [{"action": "feita", "title": "Marcar feita"}, {"action": "adiar", "title": "Adiar 10 min"}]}
    cmd("ServiceWorker.deliverPushMessage", origin=B, registrationId=reg_id, data=json.dumps(msg)); time.sleep(1.5)
    notes = ev("navigator.serviceWorker.ready.then(r=>r.getNotifications()).then(l=>l.map(n=>({t:n.title,b:n.body,tag:n.tag,a:(n.actions||[]).map(x=>x.action)})))")
    check("notificação mostrada", any(x["t"] == "E2 conferir nobreak" and x["a"] == ["feita", "adiar"] for x in notes or []), notes)
    # botão Adiar: dispara o clique dentro do service worker
    tid = next(t["targetId"] for t in cmd("Target.getTargets", sock=bws)["targetInfos"] if t["type"] == "service_worker")
    sess = cmd("Target.attachToTarget", sock=bws, targetId=tid, flatten=False)
    def sw_eval(js):
        return cmd("Target.sendMessageToTarget", sock=bws, sessionId=sess["sessionId"],
                   message=json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": js, "awaitPromise": True, "returnByValue": True}}))
    def click(action):
        sw_eval(f"""self.registration.getNotifications().then(l=>{{const n=l.find(x=>x.data&&x.data.id=={r['id']});
          if(n) self.dispatchEvent(new NotificationEvent('notificationclick',{{notification:n,action:'{action}'}}));}})""")
        time.sleep(2.5)
    click("adiar")
    import subprocess as sp
    q = f"select count(*) from push_snooze where recurring_id={r['id']}"
    remote = f"cd {os.environ.get('NEXUS_E2E_DIR', '/srv/docker/nexus-worklog')} && docker compose exec -T db sh -c 'psql -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -tAc \"" + q + "\"'"
    snooze = sp.run(["ssh", os.environ["NEXUS_E2E_SSH"], remote], capture_output=True, text=True).stdout.strip()
    check("Adiar: o servidor registrou", snooze.endswith("1"), snooze)
    cmd("ServiceWorker.deliverPushMessage", origin=B, registrationId=reg_id, data=json.dumps(msg)); time.sleep(1.5)
    click("feita")
    rem = api("GET", "/recurring/reminders")["b"]["items"]
    check("Marcar feita: rotina marcada pelo service worker", any(x["id"] == r["id"] and x["done"] for x in rem), rem)
    api("DELETE", f"/recurring/{r['id']}")

    # Convite depois de instalado: app "instalado" e permissão ainda não decidida
    for d in api("GET", "/push")["b"]["devices"]:
        api("DELETE", f"/push/devices/{d['id']}")
    cmd("Browser.resetPermissions", sock=bws)
    cmd("Page.addScriptToEvaluateOnNewDocument", source="""const _mm=matchMedia.bind(window);
      window.matchMedia=(q)=>q==='(display-mode: standalone)'?Object.assign(_mm('(min-width:0px)')):_mm(q);""")
    cmd("Page.navigate", url=B + "/#/hoje"); time.sleep(0.5); cmd("Page.reload"); time.sleep(5)
    check("convite: aparece instalado", ev("!!document.querySelector('.push-card')"), ev("Notification.permission"))
    check("convite: sem o de instalar", not ev("!!document.querySelector('.install-card')"))
    shot("e2-convite")
    cmd("Browser.grantPermissions", sock=bws, origin=B, permissions=["notifications"])
    ev("[...document.querySelectorAll('.push-card button')].find(b=>b.textContent==='Ativar').click()"); time.sleep(2.5)
    check("convite: Ativar ligou o aparelho", len(api("GET", "/push")["b"]["devices"]) == 1)
    check("convite: some depois", not ev("!!document.querySelector('.push-card')"))
    for d in api("GET", "/push")["b"]["devices"]:
        api("DELETE", f"/push/devices/{d['id']}")
finally:
    p.terminate()
    print("OK:", len(ok)); print("FALHAS:", "\n  ".join(falhas) or "nenhuma"); print("ERROS JS:", erros or "nenhum")
