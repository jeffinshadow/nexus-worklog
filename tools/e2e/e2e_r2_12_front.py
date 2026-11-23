"""Rodada 2, pacote r2-12 (front): atalhos, busca lateral e acabamentos no celular.

Uso (com o app no ar e os dados de demonstração):
    NX_BASE=http://localhost:8112 NX_SESSAO=<cookie session> python tools/e2e/e2e_r2_12_front.py

Só lê: não cria nem altera nada na conta. Sai com 1 se algum caso falhar.
"""
import os, sys
from playwright.sync_api import sync_playwright

BASE = os.environ.get("NX_BASE", "http://localhost:8112")
SESS = os.environ.get("NX_SESSAO", "EtXwcTXJMNVkarON_jv0cCQ0Jvkrs4FsFVD-SwTmSNA")  # Lucas (semeadura do laboratório)
falhas, erros_console = [], []


def ok(nome, cond, extra=""):
    print(("ok   " if cond else "FALHA"), nome, ("" if cond else "-> " + str(extra)))
    if not cond:
        falhas.append(nome)


def pagina(b, w, h, mobile=False, tema="dark", atalhos=None):
    ctx = b.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo", service_workers="block",
                        viewport={"width": w, "height": h}, has_touch=mobile, is_mobile=mobile)
    ctx.add_cookies([{"name": "session", "value": SESS, "url": BASE}])
    init = f"try{{localStorage.setItem('nexus.tema','{tema}')}}catch(e){{}}"
    if atalhos is not None:
        init += f"try{{localStorage.setItem('nexus.atalhos','{atalhos}')}}catch(e){{}}"
    ctx.add_init_script(init)
    pg = ctx.new_page()
    pg.set_default_timeout(8000)
    pg.on("console", lambda m: erros_console.append(f"{w}px {m.text}") if m.type == "error" and "Failed to load resource" not in m.text else None)
    pg.on("pageerror", lambda e: erros_console.append(f"{w}px pageerror: {e}"))
    return ctx, pg


def abre(pg, rota, seletor, tema=None):
    pg.goto(BASE + rota)
    pg.wait_for_selector(seletor)
    if tema:  # a conta guarda o tema e sobrepõe o do aparelho: força o do caso
        pg.evaluate("t => window.nexusTheme && window.nexusTheme.set(t)", tema)
    pg.wait_for_timeout(700)


LISTA = "() => { const d = document.querySelector('dialog[open] dl.shortcuts'); return d ? [...d.children].map(e => e.textContent.trim()) : null }"


def atalhos(b):
    """'Ver os atalhos' (Configurações) abre a janela do '?', com os atalhos ligados e desligados."""
    ctx, pg = pagina(b, 1440, 900, atalhos="on")
    abre(pg, "/#/hoje", "#view-hoje:not(.hidden)")
    pg.keyboard.press("?")
    pg.wait_for_selector("dialog[open] dl.shortcuts")
    ref = pg.evaluate(LISTA)
    ok("a janela do '?' lista os atalhos", bool(ref) and len(ref) >= 16 and "Nova tarefa" in ref, ref)
    ctx.close()
    for estado in ("on", "off"):
        ctx, pg = pagina(b, 1440, 900, atalhos=estado)
        abre(pg, "/#/config?aba=conta", "text=Ver os atalhos")
        marcado = pg.locator("label.notice-main:has-text('Atalhos de uma tecla') input").is_checked()
        ok(f"[{estado}] a caixa 'Atalhos de uma tecla' reflete o aparelho", marcado == (estado == "on"), marcado)
        pg.click("text=Ver os atalhos")
        pg.wait_for_selector("dialog[open] dl.shortcuts")
        ok(f"[{estado}] 'Ver os atalhos' mostra a mesma lista do '?'", pg.evaluate(LISTA) == ref, pg.evaluate(LISTA))
        ok(f"[{estado}] abre uma janela só", pg.locator("dialog[open]").count() == 1, pg.locator("dialog[open]").count())
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        if estado == "off":
            pg.keyboard.press("?")
            pg.wait_for_timeout(400)
            ok("[off] com os atalhos desligados a tecla ? não abre nada", pg.locator("dialog[open]").count() == 0)
        ctx.close()


def busca(b):
    """Busca lateral no padrão combobox: foco no campo, setas marcam, Enter abre, Esc fecha."""
    ctx, pg = pagina(b, 1440, 900)
    abre(pg, "/#/hoje", "#view-hoje:not(.hidden)")
    q = pg.locator("#side-search-q")
    a = lambda n: q.get_attribute(n)
    ok("campo: role=combobox, lista fechada", a("role") == "combobox" and a("aria-expanded") == "false" and a("aria-autocomplete") == "list", [a("role"), a("aria-expanded")])
    q.click()
    pg.keyboard.type("backup", delay=30)
    pg.wait_for_selector("#side-sugg-list [role=option]")
    n = pg.locator("#side-sugg-list [role=option]").count()
    ok("lista: role=listbox apontada pelo aria-controls, aberta", a("aria-controls") == "side-sugg-list" and a("aria-expanded") == "true"
       and pg.locator("#side-sugg-list").get_attribute("role") == "listbox" and n >= 1, n)
    pg.keyboard.press("ArrowDown")
    foco = pg.evaluate("document.activeElement.id")
    marcada = pg.locator("#side-sugg-list [aria-selected=true]")
    ok("seta para baixo marca a 1ª sugestão sem tirar o foco do campo", foco == "side-search-q" and marcada.count() == 1
       and marcada.get_attribute("id") == a("aria-activedescendant"), [foco, a("aria-activedescendant")])
    pg.keyboard.press("ArrowUp")
    ok("seta para cima volta ao campo (nenhuma marcada)", a("aria-activedescendant") is None and pg.locator("#side-sugg-list [aria-selected=true]").count() == 0)
    pg.keyboard.press("Escape")
    ok("Esc fecha a lista e o foco fica no campo", a("aria-expanded") == "false" and pg.locator("#side-sugg").is_hidden() and pg.evaluate("document.activeElement.id") == "side-search-q")
    q.fill("")
    pg.keyboard.type("backup", delay=30)
    pg.wait_for_selector("#side-sugg-list [role=option]")
    titulo = pg.locator("#side-sugg-list [role=option] .sugg-t").first.inner_text()
    pg.keyboard.press("ArrowDown")
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(900)
    aberto = pg.locator("dialog[open]").count() == 1 or "projetos?id=" in pg.url
    ok("Enter abre a sugestão marcada (não a Busca completa)", aberto and "#/busca" not in pg.url, [titulo, pg.url])
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(300)
    q.click()
    q.fill("")
    pg.keyboard.type("zzqxw", delay=30)
    pg.wait_for_selector("#side-sugg .sugg-empty")
    ok("sem sugestão: aviso, sem listbox vazia", a("aria-expanded") == "false" and pg.locator("#side-sugg-list").count() == 0)
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(600)
    ok("Enter sem sugestão marcada abre a Busca completa", "#/busca?q=zzqxw" in pg.url, pg.url)
    ctx.close()


SOBRA = "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"


def celular(b):
    """Tarefas com o detalhe em edição a 390 e 320 px, tema escuro e claro: sem rolagem lateral."""
    for w, h in ((390, 844), (320, 640)):
        for tema in ("dark", "light"):
            ctx, pg = pagina(b, w, h, mobile=True, tema=tema)
            abre(pg, "/#/tarefas", "#view-tarefas:not(.hidden) .card-open", tema)
            ok(f"[{w} {tema}] Tarefas sem rolagem lateral", pg.evaluate(SOBRA) <= 0, pg.evaluate(SOBRA))
            pg.locator("#view-tarefas .column:not(.column-done) .card-open").first.evaluate("e => e.click()")
            pg.wait_for_selector("dialog[open] .edit-toggle")
            pg.locator("dialog[open] .edit-toggle").click()
            pg.wait_for_selector("dialog[open] .props")
            pg.wait_for_timeout(400)
            ok(f"[{w} {tema}] detalhe em edição sem rolagem lateral", pg.evaluate(SOBRA) <= 0 and pg.evaluate(
                "() => { const d = document.querySelector('dialog[open]'); return [d, ...d.querySelectorAll('.task-body, .props')].every(e => e.scrollWidth <= e.clientWidth + 1) }"))
            if w == 390:
                # Cada linha da grade fica cheia: nenhum campo sozinho numa metade.
                buracos = pg.evaluate("""() => { const g = document.querySelector('dialog[open] .props'), W = g.clientWidth, linhas = {};
                  for (const f of g.children) { if (!f.offsetParent) continue; const r = f.getBoundingClientRect(); (linhas[Math.round(r.top)] ||= []).push([f.textContent.trim().slice(0, 20), r.width]); }
                  return Object.values(linhas).slice(0, 4).filter(l => l.reduce((s, x) => s + x[1], 0) < W * .8).map(l => l.map(x => x[0])) }""")
                ok(f"[{w} {tema}] Situação, Prazo, Lembrete e Prioridade sem meia linha vazia", not buracos, buracos)
            ctx.close()
    # Tempo por projeto (Hoje): o nome do projeto usa a largura que houver.
    ctx, pg = pagina(b, 390, 844, mobile=True)
    abre(pg, "/#/hoje", "#view-hoje:not(.hidden)")
    cortados = pg.evaluate("() => [...document.querySelectorAll('.sum-bar-l')].filter(e => e.offsetParent && e.scrollWidth > e.clientWidth + 1).map(e => e.textContent)")
    ok("[390] nome do projeto inteiro no tempo por projeto", not cortados and pg.evaluate(SOBRA) <= 0, cortados)
    ctx.close()


def janela_baixa(b):
    """Tarefas no computador: uma rolagem só, na janela baixa (a página) e na normal (as colunas)."""
    medida = """() => { const d = document.documentElement, c = [...document.querySelectorAll('#view-tarefas .column-body')];
      return { pagina: d.scrollHeight - d.clientHeight, colunas: c.filter(e => e.scrollHeight > e.clientHeight + 1).length } }"""
    for w, h in ((1440, 500), (1280, 360)):
        ctx, pg = pagina(b, w, h)
        abre(pg, "/#/tarefas", "#view-tarefas:not(.hidden) .card-open")
        m = pg.evaluate(medida)
        ok(f"[{w}x{h}] só a página rola (colunas soltas)", m["colunas"] == 0 and m["pagina"] > 0, m)
        ctx.close()
    for w, h in ((1440, 900), (1024, 768), (900, 700)):
        ctx, pg = pagina(b, w, h)
        abre(pg, "/#/tarefas", "#view-tarefas:not(.hidden) .card-open")
        m = pg.evaluate(medida)
        ok(f"[{w}x{h}] a página não rola (a coluna rola por dentro)", m["pagina"] <= 1, m)
        ctx.close()


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("NX_CHROMIUM", "/usr/bin/chromium"), args=["--no-sandbox"])
    for caso in (atalhos, busca, celular, janela_baixa):
        try:
            caso(b)
        except Exception as e:  # um caso quebrado não esconde os outros
            ok(f"{caso.__name__}: roteiro até o fim", False, repr(e)[:300])
    b.close()

ok("sem erro de console", not erros_console, erros_console[:5])
print("\n%d falha(s)" % len(falhas))
sys.exit(1 if falhas else 0)
