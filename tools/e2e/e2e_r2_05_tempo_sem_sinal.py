"""Rodada 2, pacote 05: tempo apontado sem sinal (Meu mês, quadro e registro rápido).

Uso (com o app no ar e os dados de demonstração):
    NX_BASE=http://localhost:8105 NX_SESSAO=<cookie session> python tools/e2e/e2e_r2_05_tempo_sem_sinal.py

Roda no computador (1440x900) e no celular (390x844). Em cada um:
  1. sem rede (context.set_offline): aponta no "Antes do PDF" do Meu mês, cria tarefa com tempo
     pelo quadro e pelo registro rápido "— 20min"; confere o aviso de fila em cada tela;
  2. com a tarefa criada e o sinal caindo só na hora do tempo (POST .../time abortado): quadro e
     registro rápido avisam que o tempo ficou na fila;
  3. religa e confere no servidor 1 apontamento de cada, sem duplicar;
  4. a frase de uma mutação fora da fila: sem rede x servidor fora (503).
Cria tarefas "R205 ..." na conta e apaga no fim (e o apontamento feito no Meu mês). Sai com 1 se algum caso falhar.
"""
import json, os, sys, time, urllib.request, urllib.error
from playwright.sync_api import sync_playwright

BASE = os.environ.get("NX_BASE", "http://localhost:8105")
SESS = os.environ.get("NX_SESSAO", "Fi3HAKKBl34tozd0NGGEiiVnK4-joUtKlQDCTLG9bQY")  # Juliana (semeadura do laboratório)
falhas, erros_console = [], []
FILA_TEMPO = "Sem sinal: o tempo sai quando a conexão voltar."


def api(method, path, body=None, _csrf=[]):
    req = urllib.request.Request(BASE + "/api" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "Cookie": "session=" + SESS})
    if method != "GET":
        if not _csrf:
            _csrf.append(api("GET", "/auth/me")["csrf_token"])
        req.add_header("X-CSRF-Token", _csrf[0])
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return {"_status": e.code, "_body": e.read().decode()[:300]}


def ok(nome, cond, extra=""):
    print(("ok   " if cond else "FALHA"), nome, ("" if cond else "-> " + str(extra)))
    if not cond:
        falhas.append(nome)


def toasts(pg):
    return " ".join(pg.evaluate("[...document.querySelectorAll('.toast')].map(t => t.innerText.replace(/\\n/g, ' | '))"))


def limpa_toasts(pg):
    pg.evaluate("document.querySelectorAll('.toast').forEach(t => t.remove())")


def espera_toast(pg, trecho):
    try:
        pg.wait_for_function("t => [...document.querySelectorAll('.toast')].some(x => x.innerText.includes(t))", arg=trecho, timeout=8000)
    except Exception:
        pass
    return toasts(pg)


def tarefas(tag):
    hoje = time.strftime("%Y-%m-%d")
    rows = api("GET", f"/worklog?from={hoje}&to={hoje}&limit=500")
    return [t for t in rows if tag in t["title"]]


def tempos(task_id):
    return [t["minutes"] for t in api("GET", f"/worklog/{task_id}")["time"]]


def quadro(pg, titulo, tempo="20min"):
    """Nova tarefa com tempo, pelo botão do quadro."""
    pg.goto(BASE + "/#/hoje")
    pg.goto(BASE + "/#/tarefas")
    pg.wait_for_selector("button[data-fab]", state="attached")
    pg.wait_for_timeout(900)
    return lambda: (pg.evaluate("document.querySelector('button[data-fab]').click()"),
                    pg.locator("#wl-title").fill(titulo), pg.locator("#wl-time").fill(tempo),
                    limpa_toasts(pg),
                    pg.locator("#dialog-worklog button[type=submit]:visible").first.click())


def rapido(pg):
    pg.goto(BASE + "/#/tarefas")
    pg.goto(BASE + "/#/hoje")
    q = pg.locator('input[aria-label="Registrar tarefa rápida"]')
    q.wait_for()
    pg.wait_for_timeout(1200)

    def registra(texto):
        limpa_toasts(pg)
        q = pg.locator('input[aria-label="Registrar tarefa rápida"]')
        q.fill(texto)
        q.press("Enter")
    return registra


def rodada(b, mobile):
    onde = "390" if mobile else "1440"
    tag = "R205 %d %s" % (int(time.time()), onde)
    kw = dict(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True) if mobile else dict(viewport={"width": 1440, "height": 900})
    ctx = b.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo", service_workers="block", **kw)
    ctx.add_cookies([{"name": "session", "value": SESS, "url": BASE}])
    pg = ctx.new_page()
    pg.set_default_timeout(8000)
    # Sem rede o navegador reclama de cada pedido que não saiu: não é erro do app.
    pg.on("console", lambda m: erros_console.append(f"[{onde}] {m.text}") if m.type == "error" and "Failed to load resource" not in m.text and "net::ERR_" not in m.text else None)
    # O roteiro bloqueia o service worker (sem cópia guardada): a releitura da tela depois de salvar
    # sem rede rejeita com "Sem conexão com o servidor" (board.js refresh, today.js mount). Com o
    # service worker, essa leitura vem da cópia; aqui ela não conta como erro.
    pg.on("pageerror", lambda e: erros_console.append(f"[{onde}] pageerror: {e}") if "Sem conexão com o servidor" not in str(e) else None)
    mes_id, mes_antes = None, []
    try:
        # ---- 1a. Meu mês, sem rede
        api("POST", "/worklog", {"title": f"{tag} mes", "status": "done", "resolution": "troquei o cabo"})
        pg.goto(BASE + "/#/mes?aba=pdf")
        pg.locator("button", has_text="Completar").first.click()
        linha = pg.locator(".pdf-row:has(.pdf-mins)").first
        linha.wait_for()
        mes_id = int(linha.get_attribute("data-id"))
        mes_antes = tempos(mes_id)
        ctx.set_offline(True)
        limpa_toasts(pg)
        linha.locator(".pdf-quick", has_text="15 min").click()
        linha.locator(".pdf-save").click()
        t = espera_toast(pg, FILA_TEMPO)
        ok(f"[{onde}] Meu mês sem rede: aviso de fila", FILA_TEMPO in t, t)
        linha = pg.locator(f'.pdf-row[data-id="{mes_id}"]')
        chips = linha.locator(".chip").all_inner_texts()
        ok(f"[{onde}] Meu mês sem rede: marca 'esperando conexão' com o valor", any("15min" in c.replace(" ", "") and "esperando conexão" in c for c in chips), chips)
        ok(f"[{onde}] Meu mês sem rede: não diz 'completa' nem pede o tempo de novo",
           not any(c == "completa" for c in chips) and linha.locator(".pdf-mins").count() == 0, chips)
        ok(f"[{onde}] Meu mês sem rede: o topo não diz 'Tudo completo'", "Tudo completo" not in pg.locator(".review-count").inner_text(), pg.locator(".review-count").inner_text())
        ok(f"[{onde}] Meu mês sem rede: nada no servidor ainda", tempos_seguro(mes_id) == mes_antes)
        pg.screenshot(path=os.path.join(SAIDA, f"r2-05-mes-{onde}.png")) if SAIDA else None
        ctx.set_offline(False)
        espera(lambda: len(tempos(mes_id)) == len(mes_antes) + 1)
        pg.keyboard.press("Escape")

        # ---- 1b. Quadro, sem rede
        salva = quadro(pg, f"{tag} quadro off")
        ctx.set_offline(True)
        salva()
        t = espera_toast(pg, "Sem conexão: tarefa guardada")
        ok(f"[{onde}] quadro sem rede: aviso de fila, sem 'Tarefa criada' nem 'Apontado'",
           "Sem conexão: tarefa guardada no aparelho" in t and "Tarefa criada" not in t and "Apontado" not in t, t)
        ctx.set_offline(False)
        espera(lambda: len(tarefas(f"{tag} quadro off")) == 1 and tempos(tarefas(f"{tag} quadro off")[0]["id"]) == [20])

        # ---- 1c. Registro rápido, sem rede
        registra = rapido(pg)
        ctx.set_offline(True)
        registra(f"{tag} rapido off — 20min")
        t = espera_toast(pg, "Sem conexão: tarefa guardada")
        ok(f"[{onde}] registro rápido sem rede: aviso de fila", "Sem conexão: tarefa guardada" in t and "Registrada e concluída" not in t, t)
        ctx.set_offline(False)
        espera(lambda: len(tarefas(f"{tag} rapido off")) == 1 and tempos(tarefas(f"{tag} rapido off")[0]["id"]) == [20])

        # ---- 2. A tarefa entra e o sinal cai só no tempo
        cai = lambda route: route.abort("internetdisconnected")
        salva = quadro(pg, f"{tag} quadro meio")
        pg.route("**/api/worklog/*/time", cai)
        salva()
        t = espera_toast(pg, FILA_TEMPO)
        ok(f"[{onde}] quadro, sinal cai no tempo: 'Tarefa criada' + aviso de fila, sem 'não foi salvo'",
           "Tarefa criada" in t and FILA_TEMPO in t and "não foi salvo" not in t and "Apontado" not in t, t)
        pg.screenshot(path=os.path.join(SAIDA, f"r2-05-quadro-{onde}.png")) if SAIDA else None
        achadas = tarefas(f"{tag} quadro meio")
        ok(f"[{onde}] quadro, sinal cai no tempo: tarefa no servidor, tempo ainda não", len(achadas) == 1 and tempos(achadas[0]["id"]) == [], achadas)
        pg.unroute("**/api/worklog/*/time", cai)
        pg.evaluate("window.dispatchEvent(new Event('online'))")
        espera(lambda: tempos(tarefas(f"{tag} quadro meio")[0]["id"]) == [20])

        registra = rapido(pg)
        pg.route("**/api/worklog/*/time", cai)
        registra(f"{tag} rapido meio — 20min")
        esperado = "Sem sinal: o tempo (20min) sai quando a conexão voltar."
        t = espera_toast(pg, esperado)
        ok(f"[{onde}] registro rápido, sinal cai no tempo: aviso de fila", esperado in t and "Registrada e concluída com" not in t, t)
        ok(f"[{onde}] registro rápido, sinal cai no tempo: o texto não casa com /conclu/i (destino do 'Ver')",
           "conclu" not in t.split(" | ")[0].lower(), t)
        pg.screenshot(path=os.path.join(SAIDA, f"r2-05-rapido-{onde}.png")) if SAIDA else None
        pg.unroute("**/api/worklog/*/time", cai)
        pg.evaluate("window.dispatchEvent(new Event('online'))")
        espera(lambda: len(tarefas(f"{tag} rapido meio")) == 1 and tempos(tarefas(f"{tag} rapido meio")[0]["id"]) == [20])

        # ---- 2c. Lista colada (uma tarefa por linha), sinal cai só no tempo; depois Desfazer
        rapido(pg)
        pg.route("**/api/worklog/*/time", cai)
        limpa_toasts(pg)
        pg.evaluate("""linhas => { const dt = new DataTransfer(); dt.setData('text/plain', linhas);
            document.querySelector('input[aria-label="Registrar tarefa rápida"]').dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true })); }""",
                    f"{tag} lote um — 20min\n{tag} lote dois — 20min")
        pg.locator(".paste-dialog button[type=submit]").click()
        esperado = "Sem sinal: o tempo de 2 delas sai quando a conexão voltar."
        t = espera_toast(pg, esperado)
        ok(f"[{onde}] lista colada, sinal cai no tempo: aviso de fila", "2 tarefas criadas." in t and esperado in t, t)
        lote = tarefas(f"{tag} lote")
        ok(f"[{onde}] lista colada: 2 tarefas no servidor, tempo ainda não", len(lote) == 2 and all(tempos(x["id"]) == [] for x in lote), lote)
        pg.locator(".toast button", has_text="Desfazer").click()
        t = espera_toast(pg, "Desfeitas as 2 tarefas.")
        ok(f"[{onde}] lista colada: Desfazer tira as 2 tarefas (e o tempo da fila)", "Desfeitas as 2 tarefas." in t, t)
        pg.unroute("**/api/worklog/*/time", cai)
        pg.evaluate("window.dispatchEvent(new Event('online'))")
        pg.wait_for_timeout(3000)
        ok(f"[{onde}] lista colada: depois do Desfazer nada fica no servidor", tarefas(f"{tag} lote") == [], tarefas(f"{tag} lote"))
        fila = pg.evaluate("import('/js/fila.js').then(m => m.all()).then(a => a.length)")
        falhou = pg.evaluate("import('/js/fila.js').then(m => m.failures()).then(a => a.length)")
        ok(f"[{onde}] lista colada: fila vazia e sem falha de envio", fila == 0 and falhou == 0, (fila, falhou))

        # ---- 3. No servidor: 1 tarefa e 1 apontamento de cada, sem duplicar (espera um ciclo a mais da fila)
        pg.evaluate("window.dispatchEvent(new Event('online'))")
        pg.wait_for_timeout(6000)
        depois = tempos(mes_id)
        ok(f"[{onde}] servidor: Meu mês gravou 1 apontamento de 15 min", len(depois) == len(mes_antes) + 1 and sum(depois) == sum(mes_antes) + 15, (mes_antes, depois))
        for nome in ("quadro off", "rapido off", "quadro meio", "rapido meio"):
            achadas = tarefas(f"{tag} {nome}")
            ok(f"[{onde}] servidor: '{nome}' = 1 tarefa com 1 apontamento de 20 min",
               len(achadas) == 1 and tempos(achadas[0]["id"]) == [20], [(a["id"], tempos(a["id"])) for a in achadas])

        # ---- 4. A frase de uma mutação que não entra na fila
        alvo = tarefas(f"{tag} quadro meio")[0]["id"]
        chama = "id => import('/js/api.js').then(m => m.api.patch('/worklog/' + id, { title: 'x' })).then(() => 'passou', e => e.message)"
        fora = lambda route: route.fulfill(status=503, body="fora")
        pg.route(f"**/api/worklog/{alvo}", fora)
        msg = pg.evaluate(chama, alvo)
        ok(f"[{onde}] servidor fora (503): frase própria", msg == "O servidor está fora do ar: faça de novo em instantes.", msg)
        pg.unroute(f"**/api/worklog/{alvo}", fora)
        pg.route(f"**/api/worklog/{alvo}", cai)
        msg = pg.evaluate(chama, alvo)
        ok(f"[{onde}] sem rede: frase de sempre", msg == "Sem sinal: faça quando a conexão voltar.", msg)
        pg.unroute(f"**/api/worklog/{alvo}", cai)
    except Exception as e:  # um caso que travou não esconde os outros
        ok(f"[{onde}] roteiro até o fim", False, repr(e)[:400])
    finally:
        try:
            ctx.set_offline(False)
        except Exception:
            pass
        ctx.close()
        if mes_id:  # a linha usada pode ser de uma tarefa que já existia (ela não tinha tempo): tira o que o roteiro pôs
            for e in (api("GET", f"/worklog/{mes_id}") or {}).get("time", []):
                api("DELETE", f"/time/{e['id']}")
        for t in tarefas(tag):
            api("DELETE", f"/worklog/{t['id']}")


def tempos_seguro(task_id):
    try:
        return tempos(task_id)
    except Exception as e:
        return repr(e)


def espera(cond, segundos=45):
    """A fila sai sozinha quando a rede volta (na hora, em 2 s, em 5 s e a cada 30 s)."""
    fim = time.time() + segundos
    while time.time() < fim:
        try:
            if cond():
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


SAIDA = os.environ.get("NX_PRINTS", "")

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("NX_CHROMIUM", "/usr/bin/chromium"), args=["--no-sandbox"])
    for mobile in (False, True):
        rodada(b, mobile)
    b.close()

ok("sem erro de console", not erros_console, erros_console[:5])
print("\n%d falha(s)" % len(falhas))
sys.exit(1 if falhas else 0)
