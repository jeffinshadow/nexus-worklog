"""Baixa PDFs do relatório da Marina na homologação. Uso: pdfs.py SAIDA_DIR"""
import base64, json, subprocess, sys, tempfile, time, urllib.request, websocket
from datetime import date, timedelta
import os


def _cred(var):
    """Credencial da homologação no ambiente: NEXUS_E2E_USER / NEXUS_E2E_ADMIN = "email:senha"."""
    v = os.environ.get(var)
    if not v or ":" not in v:
        sys.exit(f"defina {var}=email:senha (conta da homologação)")
    return tuple(v.split(":", 1))


B = os.environ.get("NEXUS_E2E_URL", "http://127.0.0.1:8090")

port=9372; OUT=sys.argv[1]
p = subprocess.Popen(["chromium","--headless=new",f"--remote-debugging-port={port}",f"--remote-allow-origins=http://127.0.0.1:{port}",f"--user-data-dir={tempfile.mkdtemp()}","about:blank"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try: tabs=json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json")); break
        except Exception: time.sleep(.2)
    ws=websocket.create_connection([t for t in tabs if t["type"]=="page"][0]["webSocketDebuggerUrl"],suppress_origin=True); n=[0]
    def cmd(m,**pr):
        n[0]+=1; ws.send(json.dumps({"id":n[0],"method":m,"params":pr}))
        while True:
            r=json.loads(ws.recv())
            if r.get("id")==n[0]: return r.get("result",r)
    ev=lambda js: cmd("Runtime.evaluate",expression=js,returnByValue=True,awaitPromise=True)["result"].get("value")
    cmd("Page.navigate",url=B+"/login.html"); time.sleep(1)
    ev("fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:'"+_cred('NEXUS_E2E_USER')[0]+"',password:'"+_cred('NEXUS_E2E_USER')[1]+"'})})")
    pid = {x['name']:x['id'] for x in ev("fetch('/api/projects').then(r=>r.json())")}
    d=date.today()
    for nome, qs in [("semana", f"start={(d-timedelta(days=6)).isoformat()}&end={d.isoformat()}"),
                     ("mes", f"start={(d-timedelta(days=29)).isoformat()}&end={d.isoformat()}"),
                     ("projeto", f"project={pid['Matriz']}")]:
        b64 = ev(f"fetch('/api/reports/export?{qs}').then(r=>r.arrayBuffer()).then(b=>{{let s='';const u=new Uint8Array(b);for(let i=0;i<u.length;i++)s+=String.fromCharCode(u[i]);return btoa(s)}})")
        open(f"{OUT}/{nome}.pdf","wb").write(base64.b64decode(b64)); print(nome, len(b64))
        time.sleep(.5)
finally: p.terminate()
