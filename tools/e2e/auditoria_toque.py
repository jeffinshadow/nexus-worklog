"""Áreas de toque no celular (390 px): todo controle clicável visível menor que 44 px (altura ou largura)."""
import json, os, subprocess, sys, tempfile, time, urllib.request, collections
import websocket
B = os.environ.get("NEXUS_E2E_URL", "http://localhost:8090")
CONTAS = [("user", os.environ["NEXUS_E2E_USER"].split(":", 1)), ("admin", os.environ["NEXUS_E2E_ADMIN"].split(":", 1))]
TELAS = {"user": ["hoje", "tarefas", "projetos", "vencimentos", "dashboard", "relatorios", "historico", "busca?q=rede",
                  "config?aba=modelos", "config?aba=avisos", "config?aba=calendario", "config?aba=ia", "config?aba=conta", "mais"],
         "admin": ["admin", "equipe", "atribuir"]}
JS = r"""(()=>{
  const out=[];
  for (const el of document.querySelectorAll('button, a[href], select, input:not([type=hidden]), summary, [role=tab], [role=radio], label.weekday-option, label.check-row')) {
    if (el.closest('.hidden,[hidden],.sr-only,.trap') || el.closest('dialog:not([open])')) continue;
    const cs = getComputedStyle(el); if (cs.display==='none' || cs.visibility==='hidden' || +cs.opacity===0) continue;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
    if (r.bottom < 0 || r.top > innerHeight*4) continue;
    if (el.tagName==='INPUT' && (el.type==='checkbox'||el.type==='radio') && el.closest('label')) continue; // a label é o alvo
    if (el.tagName==='A' && cs.display==='inline' && el.closest('p,li,small,dd')) continue; // link no meio do texto
    let w=Math.round(r.width), h=Math.round(r.height);
    const af = getComputedStyle(el, '::after');
    if (af.content && af.content !== 'none' && af.position === 'absolute') {  // alvo estendido por pseudo-elemento
      const t=-parseFloat(af.top)||0, b=-parseFloat(af.bottom)||0, l=-parseFloat(af.left)||0, rr=-parseFloat(af.right)||0;
      w += Math.max(0,l)+Math.max(0,rr); h += Math.max(0,t)+Math.max(0,b);
    }
    if (h < 44 || w < 44) {
      const cls = el.tagName.toLowerCase() + '.' + [...el.classList].slice(0,3).join('.');
      const txt = (el.getAttribute('aria-label') || el.textContent || el.value || '').trim().replace(/\s+/g,' ').slice(0,28);
      out.push([cls, w+'x'+h, txt]);
    }
  }
  return out; })()"""
p = subprocess.Popen(["chromium", "--headless=new", "--remote-debugging-port=9594", "--remote-allow-origins=http://127.0.0.1:9594", f"--user-data-dir={tempfile.mkdtemp()}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
res = collections.OrderedDict()
try:
    for _ in range(50):
        try: tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9594/json")); break
        except Exception: time.sleep(.2)
    ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"], suppress_origin=True); n = [0]
    def cmd(m, **pr):
        n[0] += 1; ws.send(json.dumps({"id": n[0], "method": m, "params": pr}))
        while True:
            r = json.loads(ws.recv())
            if r.get("id") == n[0]: return r.get("result", r)
    ev = lambda js: cmd("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)["result"].get("value")
    def coleta(tela):
        for cls, sz, txt in ev(JS) or []:
            res.setdefault(cls, {"tam": collections.Counter(), "ex": txt, "telas": set()})
            res[cls]["tam"][sz] += 1; res[cls]["telas"].add(tela)
    cmd("Page.enable"); cmd("Runtime.enable")
    cmd("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=2, mobile=True)
    cmd("Network.clearBrowserCookies"); cmd("Page.navigate", url=B + "/login"); time.sleep(1.5); coleta("login")
    for papel, (email, pw) in CONTAS:
        cmd("Network.clearBrowserCookies"); cmd("Page.navigate", url=B + "/login"); time.sleep(1.2)
        ev("localStorage.setItem('nexus.instalar.dispensado', String(Date.now()))")
        ev(f"fetch('/api/auth/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email:{json.dumps(email)},password:{json.dumps(pw)}}})}})")
        for tela in TELAS[papel]:
            cmd("Page.navigate", url=B + "/#/" + tela); time.sleep(.3); cmd("Page.reload"); time.sleep(2.8)
            coleta(tela)
        if papel == "user":
            cmd("Page.navigate", url=B + "/#/tarefas"); time.sleep(.3); cmd("Page.reload"); time.sleep(2.8)
            ev("document.querySelector('.card-open')?.click()"); time.sleep(1.5); coleta("detalhe da tarefa")
            ev("document.querySelector('.task-dialog .edit-toggle')?.click()"); time.sleep(1); coleta("detalhe em edição")
            ev("[...document.querySelectorAll('.task-appbar button')].find(b=>b.getAttribute('aria-label')==='Mais ações')?.click()"); time.sleep(.8); coleta("menu ⋮ do detalhe")
            cmd("Page.navigate", url=B + "/#/hoje"); time.sleep(.3); cmd("Page.reload"); time.sleep(2.8)
            ev("document.getElementById('fab')?.click()"); time.sleep(1); coleta("nova tarefa")
            ev("document.querySelectorAll('dialog[open]').forEach(d=>d.close())")
            ev("document.querySelector('.list-row .only-mob[aria-label^=\"Mais ações\"]')?.click()"); time.sleep(.8); coleta("menu ⋮ da linha")
finally:
    p.terminate()
for cls, d in sorted(res.items(), key=lambda kv: -sum(kv[1]["tam"].values())):
    print(f"{cls:42s} {', '.join(f'{k}×{v}' for k, v in d['tam'].most_common(3)):30s} «{d['ex']}»  [{', '.join(sorted(d['telas']))[:70]}]")
