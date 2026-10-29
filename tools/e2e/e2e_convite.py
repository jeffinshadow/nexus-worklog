"""E2E na homologação (túnel 8090 + Mailpit 8025): convite por link, esqueci a senha,
confirmação de senha e semanas do resumo. Uso: e2e_convite.py SAIDA [desktop|mobile]"""
import base64, json, re, subprocess, sys, tempfile, time, urllib.request
import websocket
import os


def _cred(var):
    """Credencial da homologação no ambiente: NEXUS_E2E_USER / NEXUS_E2E_ADMIN = "email:senha"."""
    v = os.environ.get(var)
    if not v or ":" not in v:
        sys.exit(f"defina {var}=email:senha (conta da homologação)")
    return tuple(v.split(":", 1))


B = os.environ.get("NEXUS_E2E_URL", "http://127.0.0.1:8090")
MAILPIT = os.environ.get("NEXUS_E2E_MAILPIT", "http://127.0.0.1:8025")


OUT, modo = sys.argv[1], sys.argv[2]
ADMIN = _cred("NEXUS_E2E_ADMIN")
MARINA = _cred("NEXUS_E2E_USER")
NOVO = "e2e.convite@example.com"
SENHA1, SENHA2 = "Senha-Do-Convite-1", "Senha-Do-Reset-22"
ok, falhas, erros = [], [], []
procs = []


def check(nome, cond, extra=""):
    (ok if cond else falhas).append(nome + (f" ({extra})" if extra and not cond else ""))


def mailpit_last(to):
    for _ in range(30):
        lst = json.load(urllib.request.urlopen(MAILPIT + "/api/v1/messages?limit=10"))
        for m in lst.get("messages", []):
            if any(t["Address"] == to for t in m["To"]):
                msg = json.load(urllib.request.urlopen(f"{MAILPIT}/api/v1/message/{m['ID']}"))
                return msg
        time.sleep(.3)
    return None


def mailpit_clear():
    req = urllib.request.Request(MAILPIT + "/api/v1/messages", method="DELETE")
    urllib.request.urlopen(req)


class Browser:
    def __init__(self, port):
        prof = tempfile.mkdtemp()
        self.p = subprocess.Popen(["chromium", "--headless=new", f"--remote-debugging-port={port}", f"--remote-allow-origins=http://127.0.0.1:{port}",
                                   "--hide-scrollbars", f"--user-data-dir={prof}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(self.p)
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json")); break
            except Exception:
                time.sleep(.2)
        self.ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"], suppress_origin=True)
        self.n = 0
        self.cmd("Page.enable"); self.cmd("Runtime.enable")
        w, h_, mob = (390, 844, True) if modo == "mobile" else (1440, 1000, False)
        self.cmd("Emulation.setDeviceMetricsOverride", width=w, height=h_, deviceScaleFactor=2 if mob else 1, mobile=mob)

    def cmd(self, m, **pr):
        self.n += 1; self.ws.send(json.dumps({"id": self.n, "method": m, "params": pr}))
        while True:
            r = json.loads(self.ws.recv())
            if r.get("method") == "Runtime.exceptionThrown":
                erros.append(r["params"]["exceptionDetails"].get("exception", {}).get("description", "")[:200])
            if r.get("id") == self.n: return r.get("result", r)

    def ev(self, js):
        r = self.cmd("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r: raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", js)[:300])
        return r["result"].get("value")

    def go(self, url, wait=2.0):
        self.cmd("Page.navigate", url=url); time.sleep(wait)

    def shot(self, nome):
        r = self.cmd("Page.captureScreenshot", format="png")
        open(f"{OUT}/{nome}{'-m' if modo == 'mobile' else ''}.png", "wb").write(base64.b64decode(r["data"]))

    def wait(self, js, t=8):
        end = time.time() + t
        while time.time() < end:
            if self.ev(js): return True
            time.sleep(.15)
        return False

    def login(self, email, pw):
        self.go(B + "/login.html", 1)
        return self.ev(f"fetch('/api/auth/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email:{json.dumps(email)},password:{json.dumps(pw)}}})}}).then(r=>r.status)")

    def api(self, method, path, body=None):
        return self.ev(
            f"fetch('/api/auth/me').then(r => r.json()).then(m => fetch('/api{path}', {{method: '{method}', headers: {{'Content-Type': 'application/json', 'X-CSRF-Token': m.csrf_token}}, "
            f"body: {json.dumps(json.dumps(body)) if body is not None else 'undefined'}}})).then(async r => ({{s: r.status, j: await r.json().catch(() => null)}}))")

    def fill(self, sel, value):
        self.ev(f"(() => {{ const el = document.querySelector({json.dumps(sel)}); el.value = {json.dumps(value)}; el.dispatchEvent(new Event('input', {{bubbles: true}})); }})()")

    def click(self, js):
        return self.ev(f"(() => {{ const el = {js}; if (!el) return false; el.click(); return true; }})()")

    def btn(self, texto):
        return f"[...document.querySelectorAll('button')].find(b => b.textContent.trim() === {json.dumps(texto)} && b.offsetParent)"


try:
    mailpit_clear()
    adm = Browser(9400 if modo == "desktop" else 9410)
    adm.login(*ADMIN)
    # Limpa uma execução anterior.
    for u in adm.api("GET", "/admin/users")["j"]:
        if u["email"] == NOVO:
            adm.api("POST", f"/admin/users/{u['id']}/delete", {"confirm_email": NOVO})

    # ---- convite pelo Admin
    adm.go(B + "/index.html#/admin", 2.5)
    adm.ev("document.querySelector('dialog.tour-dialog')?.close()")
    adm.click(adm.btn("Novo usuário")); time.sleep(.8)
    check("diálogo diz que vai por link", adm.ev("document.querySelector('dialog[open]').textContent.includes('link para criar a própria senha')"))
    adm.fill("dialog[open] input[type=email]", NOVO)
    adm.shot("c01-convidar")
    adm.click(adm.btn("Enviar convite"));
    check("convite enviado", adm.wait("document.querySelector('dialog[open] h2')?.textContent === 'Convite enviado'"))
    link_admin = adm.ev("document.querySelector('dialog[open] .codebox')?.textContent")
    adm.shot("c02-convite-enviado")
    adm.click(adm.btn("Pronto")); time.sleep(1)
    check("lista mostra pendente", adm.ev(f"[...document.querySelectorAll('.list-row')].some(r => r.textContent.includes({json.dumps(NOVO)}) && r.textContent.includes('convite pendente'))"))
    msg = mailpit_last(NOVO)
    check("e-mail do convite chegou", bool(msg))
    link = re.search(r"https?://\S+#convite=[\w-]+", msg["Text"]).group(0)
    check("link do e-mail = link do admin", link == link_admin, f"{link} vs {link_admin}")
    token = link.split("#convite=")[1]

    # ---- convidado abre o link
    conv = Browser(9401 if modo == "desktop" else 9411)
    conv.go(B + "/login.html#convite=" + token, 2)
    check("form do convite", conv.ev("!document.getElementById('form-link').classList.contains('hidden') && document.getElementById('link-sub').textContent.includes('" + NOVO + "')"))
    check("token sai da barra", conv.ev("location.hash === ''"))
    conv.fill("#link-name", "Convidado E2E")
    conv.fill("#link-pw", SENHA1); conv.fill("#link-pw2", SENHA1 + "x")
    check("senhas diferentes bloqueiam", conv.ev("!document.getElementById('form-link').checkValidity()"))
    conv.shot("c03-aceitar-convite")
    conv.fill("#link-pw2", SENHA1)
    check("senhas iguais liberam", conv.ev("document.getElementById('form-link').checkValidity()"))
    conv.click("document.getElementById('link-submit')")
    check("entrou no app", conv.wait("location.pathname === '/index.html' && !!document.querySelector('#app:not(.hidden)')", 10))
    check("tour abre para o convidado", conv.wait("!!document.querySelector('dialog.tour-dialog[open]')", 6))
    me = conv.api("GET", "/auth/me")["j"]
    check("nome do convite salvo", me["display_name"] == "Convidado E2E", me.get("display_name"))
    conv.go(B + "/login.html#convite=" + token, 2)
    check("link usado não vale", conv.ev("document.getElementById('link-sub').textContent.includes('venceu ou já foi usado')"))
    conv.shot("c04-convite-usado")

    # ---- esqueci a senha
    rec = Browser(9402 if modo == "desktop" else 9412)
    rec.go(B + "/login.html", 2)
    check("link esqueci aparece", rec.wait("!document.getElementById('go-forgot').classList.contains('hidden')"))
    rec.shot("c05-login")
    rec.fill("#login-email", NOVO)
    rec.click("document.getElementById('go-forgot')"); time.sleep(.3)
    check("e-mail já vem preenchido", rec.ev("document.getElementById('forgot-email').value") == NOVO)
    mailpit_clear()
    rec.click("document.querySelector('#form-forgot [type=submit]')")
    check("mensagem neutra", rec.wait("!document.getElementById('forgot-ok').classList.contains('hidden')"))
    rec.shot("c06-esqueci")
    msg = mailpit_last(NOVO)
    check("e-mail de senha chegou", bool(msg))
    rlink = re.search(r"#senha=([\w-]+)", msg["Text"]).group(1)
    rec.go(B + "/login.html#senha=" + rlink, 2)
    check("form senha nova", rec.ev("document.getElementById('link-title').textContent") == "Crie uma senha nova")
    check("sem campo de nome", rec.ev("document.getElementById('link-name-wrap').classList.contains('hidden')"))
    rec.fill("#link-pw", SENHA2); rec.fill("#link-pw2", SENHA2)
    rec.shot("c07-senha-nova")
    rec.click("document.getElementById('link-submit')")
    check("entrou com a senha nova", rec.wait("location.pathname === '/index.html'", 10))
    check("sessão do convite caiu", conv.ev("fetch('/api/auth/me').then(r => r.status)") == 401)

    # ---- confirmação na troca de senha (Conta)
    rec.go(B + "/index.html#/config?aba=conta", 3)
    rec.ev("document.querySelector('dialog.tour-dialog')?.close()")
    check("conta tem confirmação", rec.ev("[...document.querySelectorAll('label')].some(l => l.textContent === 'Confirme a nova senha')"))
    rec.ev("[...document.querySelectorAll('label')].find(l => l.textContent === 'Confirme a nova senha').scrollIntoView({block: 'center'})"); time.sleep(.3)
    rec.shot("c08-conta-senha")

    # ---- e-mails bonitos? captura o HTML do convite
    # ---- semanas do resumo (Marina)
    mar = Browser(9403 if modo == "desktop" else 9413)
    mar.login(*MARINA)
    mar.go(B + "/index.html#/hoje", 3)
    mar.ev("document.querySelector('dialog.tour-dialog')?.close()")
    mar.wait("!!document.querySelector('.sum-week')", 8)
    mar.ev("document.querySelector('.sum-week').scrollIntoView({block: 'center'})"); time.sleep(.4)
    check("card da semana com setas", mar.ev("document.querySelector('.sum-week .day-nav-label')?.textContent") == "Esta semana")
    mar.click("document.querySelector('.sum-week [aria-label=\"Semana anterior\"]')")
    check("semana passada", mar.wait("document.querySelector('.sum-week .day-nav-label')?.textContent === 'Semana passada'"))
    mar.click("document.querySelector('.sum-week [aria-label=\"Semana anterior\"]')")
    check("duas semanas atrás", mar.wait("/\\d\\d\\/\\d\\d a \\d\\d\\/\\d\\d/.test(document.querySelector('.sum-week .day-nav-label')?.textContent)"))
    time.sleep(.3)
    mar.shot("c09-semanas")
    check("próxima volta", mar.click("document.querySelector('.sum-week [aria-label=\"Próxima semana\"]')") and
          mar.wait("document.querySelector('.sum-week .day-nav-label')?.textContent === 'Semana passada'"))

    # Limpeza.
    for u in adm.api("GET", "/admin/users")["j"]:
        if u["email"] == NOVO:
            adm.api("POST", f"/admin/users/{u['id']}/delete", {"confirm_email": NOVO})
finally:
    for p in procs: p.terminate()
    print("OK:", len(ok)); print("FALHAS:", falhas or "nenhuma"); print("ERROS JS:", erros or "nenhum")
