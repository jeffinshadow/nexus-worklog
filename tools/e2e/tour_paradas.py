"""Reproduz: passeio aberto pela Ajuda fora do Hoje. Uso: repro.py desktop|mobile"""
import json, subprocess, sys, tempfile, time, urllib.request, websocket
import os


def _cred(var):
    """Credencial da homologação no ambiente: NEXUS_E2E_USER / NEXUS_E2E_ADMIN = "email:senha"."""
    v = os.environ.get(var)
    if not v or ":" not in v:
        sys.exit(f"defina {var}=email:senha (conta da homologação)")
    return tuple(v.split(":", 1))


B = os.environ.get("NEXUS_E2E_URL", "http://127.0.0.1:8090")

modo=sys.argv[1]; port=9380 if modo=="desktop" else 9381
p = subprocess.Popen(["chromium","--headless=new",f"--remote-debugging-port={port}",f"--remote-allow-origins=http://127.0.0.1:{port}",f"--user-data-dir={tempfile.mkdtemp()}","about:blank"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
erros=[]
try:
    for _ in range(50):
        try: tabs=json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json")); break
        except Exception: time.sleep(.2)
    ws=websocket.create_connection([t for t in tabs if t["type"]=="page"][0]["webSocketDebuggerUrl"],suppress_origin=True); n=[0]
    def cmd(m,**pr):
        n[0]+=1; ws.send(json.dumps({"id":n[0],"method":m,"params":pr}))
        while True:
            r=json.loads(ws.recv())
            if r.get("method")=="Runtime.exceptionThrown": erros.append(r["params"]["exceptionDetails"].get("exception",{}).get("description","")[:200])
            if r.get("id")==n[0]: return r.get("result",r)
    ev=lambda js: cmd("Runtime.evaluate",expression=js,returnByValue=True,awaitPromise=True)["result"].get("value")
    cmd("Runtime.enable")
    w,h_,mob=(390,844,True) if modo=="mobile" else (1440,1000,False)
    cmd("Emulation.setDeviceMetricsOverride",width=w,height=h_,deviceScaleFactor=1,mobile=mob)
    cmd("Page.navigate",url=B+"/login"); time.sleep(1)
    csrf=ev("fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:'"+_cred('NEXUS_E2E_USER')[0]+"',password:'"+_cred('NEXUS_E2E_USER')[1]+"'})}).then(r=>r.json()).then(j=>j.csrf_token)")
    ev(f"fetch('/api/me/tour',{{method:'PUT',headers:{{'Content-Type':'application/json','X-CSRF-Token':{json.dumps(csrf)}}},body:JSON.stringify({{done:true}})}})")
    def passeio(cenario, antes):
        cmd("Page.navigate",url=B+"/#/hoje"); time.sleep(2.5)
        for js, t in antes: ev(js); time.sleep(t)
        ok=ev("""(() => { const b=[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Fazer o tour guiado')&&b.offsetParent); if(!b) return false; b.click(); return true; })()""")
        if not ok: print("DEBUG", ev("JSON.stringify([...document.querySelectorAll('dialog[open]')].map(d => d.className + ' | ' + [...d.querySelectorAll('button')].map(b => b.textContent.trim() + ':' + !!b.offsetParent).join(',')))"))
        time.sleep(.8)
        ev("[...document.querySelectorAll('dialog.tour-dialog button')].find(b=>b.textContent==='Só o passeio').click()")
        time.sleep(3)
        titulos=[]
        for _ in range(12):
            t=ev("document.querySelector('#tour-pop-title')?.textContent")
            if not t: break
            titulos.append(t)
            ev("(() => { const b=[...document.querySelectorAll('.tour-pop button')].find(b=>/Próximo|Concluir/.test(b.textContent)); b && b.click(); })()"); time.sleep(.5)
        print(f"{cenario}: ajuda={ok} paradas={len(titulos)} {titulos}")
    ajuda_desk=("document.getElementById('btn-help').click()",.6)
    ajuda_mob=("location.hash='#/mais'",1.5), ("[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Ajuda'&&b.offsetParent).click()",.6)
    if modo=="desktop":
        passeio("ajuda no Hoje", [ajuda_desk])
        passeio("ajuda em Tarefas", [("location.hash='#/tarefas'",1.5), ajuda_desk])
        passeio("ajuda em Relatórios (1ª visita)", [("location.hash='#/relatorios'",1.5), ajuda_desk])
    else:
        passeio("ajuda pelo Mais", list(ajuda_mob))
finally:
    p.terminate(); print("erros JS:", erros or "nenhum")
