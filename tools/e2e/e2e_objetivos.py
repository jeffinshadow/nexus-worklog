"""E2E na homologação: menu Projetos, objetivos em ordem de execução, tarefas
vinculadas, arrastar (computador) e o ⋮ (celular). Uso: e2e_objetivos.py SAIDA [desktop|mobile]"""
import base64, json, os, subprocess, sys, tempfile, time, urllib.request
import websocket


def _cred(var):
    v = os.environ.get(var)
    if not v or ":" not in v:
        sys.exit(f"defina {var}=email:senha (conta da homologação)")
    return tuple(v.split(":", 1))


B = os.environ.get("NEXUS_E2E_URL", "http://127.0.0.1:8090")
OUT, modo = sys.argv[1], sys.argv[2]
EMAIL, PW = _cred("NEXUS_E2E_USER")
PROJ = "E2E Objetivos"
ok, falhas, erros = [], [], []


def check(nome, cond, extra=""):
    (ok if cond else falhas).append(nome + (f" ({extra})" if extra and not cond else ""))


port = 9480 if modo == "desktop" else 9481
p = subprocess.Popen(["chromium", "--headless=new", f"--remote-debugging-port={port}", f"--remote-allow-origins=http://127.0.0.1:{port}",
                      "--hide-scrollbars", f"--user-data-dir={tempfile.mkdtemp()}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:
            tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json")); break
        except Exception:
            time.sleep(.2)
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
        if "exceptionDetails" in r: raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", js)[:300])
        return r["result"].get("value")

    def wait(js, t=8):
        end = time.time() + t
        while time.time() < end:
            if ev(js): return True
            time.sleep(.15)
        return False

    def shot(nome):
        open(f"{OUT}/{nome}{'-m' if modo == 'mobile' else ''}.png", "wb").write(base64.b64decode(cmd("Page.captureScreenshot", format="png")["data"]))

    def api(method, path, body=None):
        return ev(f"fetch('/api/auth/me').then(r=>r.json()).then(m=>fetch('/api{path}',{{method:'{method}',headers:{{'Content-Type':'application/json','X-CSRF-Token':m.csrf_token}},"
                  f"body:{json.dumps(json.dumps(body)) if body is not None else 'undefined'}}})).then(async r=>({{s:r.status,j:await r.json().catch(()=>null)}}))")

    def drop_project(pid):  # o projeto e as tarefas dele (excluir só o projeto deixa as tarefas soltas na conta)
        o = api("GET", f"/projects/{pid}/overview")["j"]
        for b in o["objectives"] + [o["unassigned"]]:
            for t in b["tasks"] + b["done_tasks"]:
                api("DELETE", f"/worklog/{t['id']}")
        api("DELETE", f"/projects/{pid}")

    def btn(texto, scope="document"):
        return f"[...{scope}.querySelectorAll('button')].find(b => b.textContent.trim() === {json.dumps(texto)} && b.offsetParent)"

    def menu_item(texto):  # popup (computador) ou sheet (celular)
        return ev(f"(() => {{ const b = [...document.querySelectorAll('.pop-menu button, dialog[open] .menu-list button')].find(b => b.textContent.trim() === {json.dumps(texto)}); if (!b) return false; b.click(); return true; }})()")

    def titles(block_index):
        return ev(f"[...document.querySelectorAll('.obj-block')[{block_index}].querySelectorAll('.obj-task[data-task] .card-open')].map(b => b.textContent)")

    cmd("Page.enable"); cmd("Runtime.enable")
    w, h_, mob = (390, 844, True) if modo == "mobile" else (1440, 1000, False)
    cmd("Emulation.setDeviceMetricsOverride", width=w, height=h_, deviceScaleFactor=2 if mob else 1, mobile=mob)
    cmd("Page.navigate", url=B + "/login.html"); time.sleep(1)
    ev(f"fetch('/api/auth/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email:{json.dumps(EMAIL)},password:{json.dumps(PW)}}})}})")
    for x in api("GET", "/projects?include_archived=true")["j"]:  # limpa execução anterior
        if x["name"] == PROJ:
            drop_project(x["id"])
    pid = api("POST", "/projects", {"name": PROJ})["j"]["id"]

    cmd("Page.navigate", url=B + "/index.html#/projetos"); time.sleep(2.5)
    ev("document.querySelector('dialog.tour-dialog')?.close()")
    check("menu Projetos", ev("!!document.querySelector('[data-view=projetos]')"))
    check("lista mostra o projeto", wait(f"[...document.querySelectorAll('.proj-card h2')].some(e => e.textContent === {json.dumps(PROJ)})"))
    shot("o01-lista")
    ev(f"[...document.querySelectorAll('.proj-card')].find(c => c.textContent.includes({json.dumps(PROJ)})).click()")
    check("abre o projeto (título da página = nome)", wait(f"!!document.querySelector('.proj-bar') && document.getElementById('page-title').textContent === {json.dumps(PROJ)}"))

    # Objetivos pela tela.
    for nome in ("Login", "Pagamentos", "Relatórios"):
        ev("document.querySelector('[data-fab]').click()" if not mob else "document.getElementById('fab').click()")
        wait("!!document.querySelector('dialog[open] form')")
        ev(f"(() => {{ const i = document.querySelector('dialog[open] input[type=text]'); i.value = {json.dumps(nome)}; }})()")
        ev("document.querySelector('dialog[open] form').requestSubmit()")
        wait(f"[...document.querySelectorAll('.obj-block h3')].some(e => e.textContent === {json.dumps(nome)})")
    check("três objetivos em ordem", ev("[...document.querySelectorAll('.obj-block[data-id] h3')].map(e => e.textContent).join('|')") == "Login|Pagamentos|Relatórios")

    # Tarefas pelo campo do bloco (Enter), em sequência.
    for t in ("Tela de login", "Recuperar senha", "Login social"):
        ev(f"(() => {{ const i = document.querySelector('.obj-block[data-id] .obj-add'); i.value = {json.dumps(t)}; i.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', bubbles: true}})); }})()")
        wait(f"[...document.querySelectorAll('.obj-block')[0].querySelectorAll('.card-open')].some(b => b.textContent === {json.dumps(t)})")
    check("tarefas no objetivo, na ordem", titles(0) == ["Tela de login", "Recuperar senha", "Login social"], titles(0))
    check("progresso 0 de 3", "0 de 3" in ev("document.querySelector('.obj-block[data-id] .obj-progress-l').textContent"))

    if not mob:
        # Arrastar "Login social" para o topo do mesmo objetivo e "Recuperar senha" para Pagamentos.
        def drag(src_sel, dst_list_sel, before_sel=None):
            ev(f"""(() => {{
              const src = document.querySelector({json.dumps(src_sel)}); const list = document.querySelector({json.dumps(dst_list_sel)});
              src.querySelector('.grip').dispatchEvent(new PointerEvent('pointerdown', {{bubbles: true}}));
              const dt = new DataTransfer();
              src.dispatchEvent(new DragEvent('dragstart', {{bubbles: true, dataTransfer: dt}}));
              const tgt = {f"document.querySelector({json.dumps(before_sel)})" if before_sel else "null"};
              const r = (tgt || list).getBoundingClientRect();
              const y = tgt ? r.top + 2 : r.bottom - 2;
              list.dispatchEvent(new DragEvent('dragover', {{bubbles: true, cancelable: true, dataTransfer: dt, clientY: y}}));
              list.dispatchEvent(new DragEvent('drop', {{bubbles: true, cancelable: true, dataTransfer: dt, clientY: y}}));
              src.dispatchEvent(new DragEvent('dragend', {{bubbles: true, dataTransfer: dt}}));
            }})()""")
            time.sleep(1.5)
        ids = api("GET", f"/projects/{pid}/overview")["j"]
        tid = {t["title"]: t["id"] for t in ids["objectives"][0]["tasks"]}
        oid = [o["id"] for o in ids["objectives"]]
        drag(f".obj-task[data-task='{tid['Login social']}']", f".obj-tasks[data-objective='{oid[0]}']", f".obj-task[data-task='{tid['Tela de login']}']")
        check("arrastar dentro do objetivo", titles(0) == ["Login social", "Tela de login", "Recuperar senha"], titles(0))
        drag(f".obj-task[data-task='{tid['Recuperar senha']}']", f".obj-tasks[data-objective='{oid[1]}']")
        check("arrastar para outro objetivo", titles(1) == ["Recuperar senha"] and "Recuperar senha" not in titles(0), titles(1))
        # Arrastar o objetivo Relatórios para o topo.
        ev(f"""(() => {{
          const blocks = document.querySelector('.obj-list'); const src = blocks.querySelector(".obj-block[data-id='{oid[2]}']");
          src.querySelector('.obj-head .grip').dispatchEvent(new PointerEvent('pointerdown', {{bubbles: true}}));
          const dt = new DataTransfer();
          src.dispatchEvent(new DragEvent('dragstart', {{bubbles: true, dataTransfer: dt}}));
          const y = blocks.querySelector('.obj-block[data-id]').getBoundingClientRect().top + 2;
          blocks.dispatchEvent(new DragEvent('dragover', {{bubbles: true, cancelable: true, dataTransfer: dt, clientY: y}}));
          blocks.dispatchEvent(new DragEvent('drop', {{bubbles: true, cancelable: true, dataTransfer: dt, clientY: y}}));
          src.dispatchEvent(new DragEvent('dragend', {{bubbles: true, dataTransfer: dt}}));
        }})()""")
        time.sleep(1.5)
        check("arrastar objetivo", ev("[...document.querySelectorAll('.obj-block[data-id] h3')].map(e => e.textContent).join('|')") == "Relatórios|Login|Pagamentos")
        api("POST", f"/projects/{pid}/objectives/order", {"ids": oid})  # volta à ordem original
        cmd("Page.reload"); time.sleep(2.5)  # mesmo endereço: navegar não recarrega
    else:
        # Celular: pelo ⋮ — descer "Tela de login" e mover "Recuperar senha" para Pagamentos.
        ev("document.querySelectorAll('.obj-block')[0].querySelector('.obj-task [aria-label^=\"Ordem e objetivo\"]').click()"); time.sleep(.6)
        menu_item("Descer na ordem"); time.sleep(1.8)
        check("descer pelo ⋮", titles(0) == ["Recuperar senha", "Tela de login", "Login social"], titles(0))
        ev("document.querySelectorAll('.obj-block')[0].querySelector('.obj-task [aria-label^=\"Ordem e objetivo\"]').click()"); time.sleep(.6)
        menu_item("Mover para outro objetivo…"); time.sleep(.6)
        menu_item("Pagamentos"); time.sleep(1.8)
        check("mover pelo ⋮", titles(1) == ["Recuperar senha"], titles(1))
        ev("document.querySelectorAll('.obj-block[data-id]')[2].querySelector('.obj-head [aria-label^=\"Ações de\"]').click()"); time.sleep(.6)
        menu_item("Subir na ordem"); time.sleep(1.8)
        check("subir objetivo pelo ⋮", ev("[...document.querySelectorAll('.obj-block[data-id] h3')].map(e => e.textContent).join('|')") == "Login|Relatórios|Pagamentos")
        ov = api("GET", f"/projects/{pid}/overview")["j"]
        api("POST", f"/projects/{pid}/objectives/order", {"ids": sorted(o["id"] for o in ov["objectives"])})
        cmd("Page.reload"); time.sleep(2.5)  # mesmo endereço: navegar não recarrega

    # Concluir uma tarefa: progresso e status mudam.
    wait("!!document.querySelector('.obj-block[data-id] .obj-task[data-task]')")
    ev("document.querySelectorAll('.obj-block')[0].querySelector('.obj-task [aria-label^=\"Concluir\"]').click()"); time.sleep(.8)
    if ev("!!document.querySelector('dialog[open] form')"):
        ev("document.querySelector('dialog[open] form').requestSubmit()")
    time.sleep(1.8)
    check("status em andamento", ev("document.querySelector('.obj-block[data-id] .obj-status').textContent") == "em andamento")
    check("1 concluída recolhida", wait("!!document.querySelector('.obj-block[data-id] .obj-done-toggle')"))
    shot("o02-projeto")

    # Concluída também muda de objetivo: pelo ⋮ (para "Sem objetivo").
    ev("document.querySelector('.obj-block[data-id] .obj-done-toggle').click()"); time.sleep(.4)
    feita = ev("document.querySelector('.obj-block[data-id] .obj-done .card-open').textContent")
    ev("document.querySelector('.obj-block[data-id] .obj-done [aria-label^=\"Objetivo de\"]').click()"); time.sleep(.6)
    menu_item("Mover para outro objetivo…"); time.sleep(.6)
    menu_item("Sem objetivo"); time.sleep(1.8)
    ov = api("GET", f"/projects/{pid}/overview")["j"]
    check("concluída movida pelo ⋮", any(t["title"] == feita for t in ov["unassigned"]["done_tasks"]), feita)
    if not mob:  # e arrastando para um objetivo
        ev("document.querySelector('.obj-block.unassigned .obj-done-toggle').click()"); time.sleep(.4)
        tid_feita = next(t["id"] for t in ov["unassigned"]["done_tasks"] if t["title"] == feita)
        alvo = ov["objectives"][1]["id"]
        ev(f"""(() => {{
          const src = document.querySelector(".obj-task[data-task='{tid_feita}']"); const list = document.querySelector(".obj-tasks[data-objective='{alvo}']");
          src.querySelector('.grip').dispatchEvent(new PointerEvent('pointerdown', {{bubbles: true}}));
          const dt = new DataTransfer();
          src.dispatchEvent(new DragEvent('dragstart', {{bubbles: true, dataTransfer: dt}}));
          const y = list.getBoundingClientRect().bottom - 2;
          list.dispatchEvent(new DragEvent('dragover', {{bubbles: true, cancelable: true, dataTransfer: dt, clientY: y}}));
          list.dispatchEvent(new DragEvent('drop', {{bubbles: true, cancelable: true, dataTransfer: dt, clientY: y}}));
          src.dispatchEvent(new DragEvent('dragend', {{bubbles: true, dataTransfer: dt}}));
        }})()""")
        time.sleep(1.8)
        ov = api("GET", f"/projects/{pid}/overview")["j"]
        check("concluída arrastada para objetivo", any(t["id"] == tid_feita for t in ov["objectives"][1]["done_tasks"]))
        check("abertas do destino intactas", [t["title"] for t in ov["objectives"][1]["tasks"]] == ["Recuperar senha"])

    # Detalhe da tarefa: campo Objetivo e etiqueta.
    ev("document.querySelectorAll('.obj-block')[0].querySelector('.obj-task[data-task] .card-open').click()"); time.sleep(1.6)
    check("etiqueta do objetivo no detalhe", ev("!!document.querySelector('dialog[open] .chip.objective')"))
    ev("document.querySelector('dialog[open] .edit-toggle')?.click()"); time.sleep(.8)
    check("campo Objetivo no detalhe", ev("[...document.querySelectorAll('dialog[open] select')].some(s => s.getAttribute('aria-label') === 'Objetivo' && s.value)"))
    shot("o03-detalhe")
    ev("document.querySelectorAll('dialog[open]').forEach(d => d.close())"); time.sleep(.4)

    # Nova tarefa pela barra do projeto: projeto já vem escolhido, objetivo dos dele.
    ev(btn("Tarefa") + (".click()" if not mob else "?.click()"))
    if mob:
        ev("[...document.querySelectorAll('#page-actions button')].find(b => b.textContent.includes('Tarefa'))?.click()")
    time.sleep(1.2)
    check("nova tarefa com o projeto", wait(f"document.getElementById('wl-project').value === '{pid}'"))
    check("objetivos no seletor", wait("document.getElementById('wl-objective').options.length === 4"),
          ev("[...document.getElementById('wl-objective').options].map(o => o.text).join('|') + ' disabled=' + document.getElementById('wl-objective').disabled + ' proj=' + document.getElementById('wl-project').value"))
    ev("document.querySelectorAll('dialog[open]').forEach(d => d.close())")

    # Objetivo excluído: tarefas vão para "Sem objetivo".
    ev("document.querySelectorAll('.obj-block[data-id]')[1].querySelector('.obj-head [aria-label^=\"Ações de\"]').click()"); time.sleep(.6)
    menu_item("Excluir objetivo"); time.sleep(.6)
    ev(btn("Excluir", "document.querySelector('dialog[open]')") + ".click()"); time.sleep(1.8)
    check("excluir objetivo devolve as tarefas", "Recuperar senha" in ev("[...document.querySelector('.obj-block.unassigned').querySelectorAll('.card-open')].map(b => b.textContent).join('|')"))
    shot("o04-sem-objetivo")
    # Configurações > Projetos (link antigo) leva à tela nova.
    cmd("Page.navigate", url=B + "/index.html#/config?aba=projetos"); time.sleep(2.5)
    check("link antigo leva a Projetos", ev("location.hash") == "#/projetos", ev("location.hash"))
    drop_project(pid)
finally:
    p.terminate()
    print("OK:", len(ok)); print("FALHAS:", falhas or "nenhuma"); print("ERROS JS:", erros or "nenhum")
