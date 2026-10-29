// Casca do app: sessão, rotas por hash (#/hoje, #/tarefas...), menu e títulos.
import { api, toLogin } from "./api.js";
import { h, icon, clear, setTimeZone, matchPasswords } from "./dom.js";
import * as today from "./today.js";
import * as board from "./board.js";
import * as projetos from "./projetos.js";
import * as dashboard from "./dashboard.js";
import * as reports from "./reports.js";
import * as history from "./history.js";
import * as settings from "./settings.js";
import * as admin from "./admin.js";
import * as equipe from "./equipe.js";
import * as atribuir from "./atribuir.js";
import { renewalsPanel } from "./renewals.js";
import * as search from "./search.js";
import { highlight } from "./search.js";
import { loadBranding } from "./branding.js";
import { avatar } from "./profile.js";
import { startIdle } from "./idle.js";
import { configure as configureAssistant } from "./assistant.js";
import { session } from "./session.js";
import { initTimer, stopTimer, timerState } from "./timer.js";
import { openWorklog } from "./board.js";
import { openTask, closeSidePanel } from "./task.js";
import { startTour } from "./tour.js";
import { modal, busy, initTooltips, syncRail, calmMotion } from "./ui.js";

let me = null;

// need: papel exigido (user = tem o próprio registro). O backend confere de novo.
const VIEWS = {
  hoje: { title: "Hoje", need: "user", mount: (el, ctx) => today.mount(el, ctx) },
  tarefas: { title: "Tarefas", need: "user", mount: (el, ctx) => board.mount(el, ctx) },
  projetos: { title: "Projetos", need: "user", mount: (el, ctx) => projetos.mount(el, ctx) },
  vencimentos: { title: "Vencimentos", need: "user", eyebrow: "certificados · licenças · domínios · garantias", mount: (el) => mountRenewals(el) },
  dashboard: { title: "Retrospectiva", need: "user", eyebrow: "rotinas · fluxo · tempo · backlog", mount: (el, ctx) => dashboard.mount(el, { me: ctx.me, setAssist: ctx.setAssist }) },
  relatorios: { title: "Relatórios", need: "user", eyebrow: "PDF · exportar dados", mount: (el, ctx) => reports.mount(el, { me: ctx.me }) },
  historico: { title: "Histórico", eyebrow: "o que mudou, por quem", mount: (el) => history.mount(el) },
  config: { title: "Configurações", mount: (el, ctx) => settings.mount(el, ctx) },
  atribuir: { title: "Atribuir tarefas", need: "assigner", eyebrow: "para quem aceitou receber", mount: (el, ctx) => atribuir.mount(el, ctx) },
  equipe: { title: "Equipe", need: "viewer", eyebrow: "registros e relatórios de cada pessoa", mount: (el) => equipe.mount(el) },
  admin: { title: "Admin", need: "admin", eyebrow: "contas · permissões · configurações", mount: (el, ctx) => admin.mount(el, ctx) },
  mais: { title: "Mais", mount: (el) => mountMore(el) },
  busca: { title: "Busca", need: "user", eyebrow: "tarefas · anotações · checklist · projetos", mount: (el, ctx) => search.mount(el, ctx) },
};

const has = (role) => !!me && (me.roles || []).includes(role);
const allowed = (name) => VIEWS[name] && (!VIEWS[name].need || has(VIEWS[name].need));
// Primeira tela: Hoje para quem tem registro; senão, a primeira função da conta.
const home = () => ["hoje", "atribuir", "equipe", "admin", "historico"].find(allowed);

function setActions(...nodes) {
  const box = document.getElementById("page-actions");
  clear(box);
  box.append(...nodes.filter(Boolean));
  // Celular: a ação principal da tela (data-fab) vira o botão flutuante.
  const main = box.querySelector("[data-fab]");
  const fab = document.getElementById("fab");
  fab.classList.toggle("hidden", !main);
  fab.onclick = main ? () => main.click() : null;
  // O rótulo é o da ação principal da tela ("Tarefa", "Objetivo", "Projeto"...).
  if (main) {
    document.getElementById("fab-label").textContent = main.textContent.trim();
    fab.setAttribute("aria-label", main.getAttribute("aria-label") || main.textContent.trim());
  }
}

async function route() {
  let name = (location.hash.replace(/^#\/?/, "") || home()).split("?")[0];
  if (!allowed(name)) name = home();
  const view = VIEWS[name];

  for (const key of Object.keys(VIEWS)) {
    document.getElementById("view-" + key).classList.toggle("hidden", key !== name);
  }
  for (const a of document.querySelectorAll("[data-view]")) {
    a.classList.toggle("active", a.dataset.view === name);
    if (a.dataset.view === name) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  // Na volta a uma tela, a fala do assistente, a linha acima do título e os
  // botões ao lado dele ficam como estavam até a resposta chegar, sem a página
  // pular (os botões podem quebrar linha e mudar a altura do cabeçalho).
  const eyebrow = document.getElementById("page-eyebrow");
  const changed = shownView !== name;
  if (changed) closeSidePanel(); // o detalhe lateral é da tela que ficou para trás
  if (shownView) kept[shownView] = { assist: document.getElementById("assist-slot").firstChild, eyebrow: eyebrow.textContent,
    actions: [...document.getElementById("page-actions").childNodes] };
  shownView = name;
  const prev = kept[name] || {};
  document.getElementById("page-title").textContent = view.title;
  document.getElementById("appbar-title").textContent = view.title;
  eyebrow.textContent = view.eyebrow || prev.eyebrow || "";
  document.title = `${view.title} · Nexus Worklog`;
  setActions(...(prev.actions || []));

  const el = document.getElementById("view-" + name);
  const seq = ++routeSeq;
  // A fala do assistente fica acima do título; uma tela antiga que termina de
  // carregar depois da troca não sobrescreve a da tela atual.
  setAssist(prev.assist || null);
  let assisted = false;
  const assist = (node) => { if (seq === routeSeq) { assisted = true; setAssist(node); } };
  let acted = false;
  const actions = (...nodes) => { if (seq === routeSeq) { acted = true; setActions(...nodes); } };
  // Tela já visitada: aparece na hora com o que mostrava e se atualiza quando a
  // resposta chega (esmaecida se demorar). Primeira visita: título e tela só
  // aparecem prontos, juntos com a fala do assistente, sem descer quando ela
  // chega. Passando de 250 ms, a barra fina no topo (as duas); a tela nova só
  // fica escondida: pode já ter montado a estrutura antes da API responder.
  el.setAttribute("aria-busy", "true");
  const loadingMsg = document.getElementById("view-loading");
  const head = document.querySelector(".page-head");
  const visited = el.childElementCount > 0;
  el.classList.toggle("hidden", !visited);
  head.classList.toggle("hidden", !visited);
  if (visited && changed) enter(el);
  const loading = setTimeout(() => {
    if (seq !== routeSeq) return;
    if (visited) el.classList.add("refreshing");
    loadingMsg.classList.remove("hidden");
  }, 250);
  try {
    await view.mount(el, { me, setActions: actions, setEyebrow, setAssist: assist, go });
  } catch (e) {
    clear(el);
    el.append(h("p", { class: "empty", text: e && e.status === 0 ? e.message : "Erro ao carregar. Tente de novo." }));
  } finally {
    clearTimeout(loading);
    el.removeAttribute("aria-busy");
    el.classList.remove("refreshing");
    if (seq === routeSeq) {
      el.classList.remove("hidden"); head.classList.remove("hidden"); loadingMsg.classList.add("hidden");
      if (!visited && changed) enter(el);
      if (!assisted) setAssist(null);
      if (!acted) setActions();
    }
  }
  window.scrollTo(0, 0);
  // Link direto para uma tarefa (#/tarefas?id=N: e-mail de atribuição, calendário).
  const taskId = Number(new URLSearchParams(location.hash.split("?")[1] || "").get("id"));
  if (name === "tarefas" && taskId > 0 && seq === routeSeq) {
    window.history.replaceState(null, "", "#/tarefas"); // "history" aqui é a tela de Histórico
    openTask(taskId, route);
  }
}

// Troca de tela (Material 3, "fade through"): a nova tela e o título surgem
// esmaecendo e crescendo um pouco. Quem pediu menos movimento só vê a troca.
function enter(el) {
  if (calmMotion()) return;
  for (const n of [document.querySelector(".page-head"), document.getElementById("assist-slot"), el])
    n.animate([{ opacity: 0, transform: "scale(.985)" }, { opacity: 1, transform: "none" }],
      { duration: 220, easing: "cubic-bezier(.2, 0, 0, 1)" });
}

let routeSeq = 0;
let shownView = null;
const kept = {};
function setAssist(node) {
  const slot = document.getElementById("assist-slot");
  clear(slot);
  if (node) slot.append(node);
}

function setEyebrow(text) {
  document.getElementById("page-eyebrow").textContent = text;
}

function go(name) {
  location.hash = "#/" + name;
}

async function logout() {
  try { await api.post("/auth/logout"); } catch { /* ignora */ }
  location.href = "/login.html";
}

// Vencimentos: item próprio no menu (importante demais para ficar em Configurações).
async function mountRenewals(el) {
  const render = async () => {
    const panel = await renewalsPanel(render);
    clear(el);
    el.append(h("div", { class: "settings-grid" }, panel));
  };
  await render();
}

// Celular: "Mais" reúne o que não cabe na barra inferior.
function mountMore(el) {
  clear(el);
  const items = [
    ["projetos", "route", "Projetos"],
    ["vencimentos", "calendar", "Vencimentos"],
    ["dashboard", "dashboard", "Retrospectiva"],
    ["historico", "history", "Histórico"],
    // Quem atribui tem Atribuir na barra; a Busca vem para cá.
    has("assigner") ? ["busca", "search", "Busca"] : ["atribuir", "send", "Atribuir tarefas"],
    ["equipe", "team", "Equipe"],
    ["admin", "admin", "Admin"],
    ["config", "settings", "Configurações"],
  ].filter(([v]) => allowed(v));
  el.append(
    h("a", { href: "#/config?aba=conta", class: "more-me" }, avatar(me, "md"),
      h("span", { class: "who-text" }, h("span", { class: "who-name", text: me.name }), h("span", { class: "who-email", text: me.email }))),
    h("div", { class: "menu-list" },
      ...items.map(([v, ic, label]) => h("a", { href: "#/" + v }, icon(ic), h("span", { text: label }))),
      h("button", { type: "button", class: "nav-btn", onClick: showHelp }, icon("help"), h("span", { text: "Ajuda" })),
      h("button", { type: "button", class: "nav-btn logout", onClick: logout }, icon("logout"), h("span", { text: "Sair" }))
    )
  );
}

// Ajuda em seções: começar (tour e manual), onde fica cada coisa, marcadores do
// registro rápido, atalhos (só no computador) e a quem recorrer (Admin > Geral).
function showHelp() {
  const user = has("user");
  const sec = (ic, title, ...body) => h("section", { class: "help-sec" }, h("h3", {}, icon(ic), h("span", { text: title })), ...body);
  const list = (rows) => h("dl", { class: "help-list" }, ...rows.flatMap(([k, v, code]) =>
    [h("dt", {}, code ? h("code", { text: k }) : k), h("dd", { text: v })]));
  const desk = !matchMedia("(max-width: 860px)").matches;
  const dlg = modal(h("h2", { text: "Ajuda" }),
    sec("spark", "Começar",
      h("div", { class: "help-start" },
        user ? h("button", { type: "button", class: "btn btn-primary btn-sm", onClick: () => { dlg.close(); startTour(me); } }, icon("help"), "Fazer o tour guiado") : null,
        h("a", { class: "btn btn-ghost btn-sm", href: "https://shadow.tec.br/nexus-manual.html", target: "_blank", rel: "noopener noreferrer" }, icon("reports"), "Manual, tela por tela")),
      user ? h("p", { class: "help-example dialog-note", text: "O tour configura o seu Nexus (nome, dias úteis, projetos, rotinas) e mostra a tela Hoje em poucos minutos." }) : null),
    sec("today", "Onde fica cada coisa", list([
      ...(user ? [["Hoje", "Rotinas do dia, tarefas em aberto (com filtro) e o registro rápido."],
        ["Tarefas", "O quadro completo e o detalhe de cada tarefa: anotações, checklist, cronômetro, tempo."],
        ["Projetos", "Cada projeto com os objetivos em ordem de execução e as tarefas de cada um."],
        ["Retrospectiva", "A semana e o mês em números."],
        ["Relatórios", "PDF do período ou de um projeto, e a exportação dos dados."]] : []),
      ["Histórico", "Tudo o que mudou, com desfazer."],
      ["Configurações", user ? "Modelos, avisos, calendário, IA e a sua conta (projeto padrão, dias úteis)." : "IA e API, e a sua conta."],
    ])),
    user ? sec("add", "Registro rápido (no Hoje)",
      h("p", { class: "help", text: "Escreva o que fez e aperte Enter. Marcadores opcionais no fim, em qualquer ordem:" }),
      list([
        ["@Projeto", "projeto; um segundo @ põe a tarefa nos dois", true],
        ["#4821", "número do chamado", true],
        ["!alta", "prioridade alta", true],
        ["!plantão", "fora do horário", true],
        ["^amanhã", "prazo: ^hoje, ^sex, ^25/10…", true],
        ["!bloq motivo", "bloqueada, aguardando o motivo (sempre por último)", true],
        ["— 45min", "já conclui, com o tempo apontado", true],
      ]),
      h("p", { class: "help-example" }, "Ex.: ", h("code", { text: "Troca do switch @Matriz #4821 — 45min" }))) : null,
    user && desk ? sec("key", "Atalhos de teclado", list([
      ["n", "nova tarefa", true], ["/", "buscar", true], ["h t r l", "Hoje, Tarefas, Retrospectiva, Relatórios", true],
      ["s", "parar o cronômetro", true], ["?", "ver todos os atalhos", true],
    ])) : null,
    sec("mail", "Suporte", me.support_contact
      ? h("p", { class: "help" }, "Fale com ", h("strong", { text: me.support_contact }), ".")
      : h("p", { class: "help", text: "Dúvidas ou problemas: fale com quem administra o Nexus na sua equipe." })),
    h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-primary", text: "Fechar", onClick: () => dlg.close() })));
  dlg.classList.add("help-dialog");
}

// Erros de JavaScript vão para o log do servidor (sem terceiros). Poucos por página.
let reported = 0;
function reportError(message, where) {
  if (reported++ >= 5 || !me) return;
  api.post("/client-errors", { message: String(message || "erro").slice(0, 300), where: String(where || location.hash).slice(0, 200) }).catch(() => {});
}
window.addEventListener("error", (ev) => reportError(ev.message, `${ev.filename || ""}:${ev.lineno || ""} ${location.hash}`));
window.addEventListener("unhandledrejection", (ev) => {
  const r = ev.reason;
  if (r && "status" in r) return; // erro de API já mostrado na tela
  reportError(r && (r.stack || r.message) || r, location.hash);
});

// Rodapé do menu: foto (ou iniciais), nome e e-mail; leva ao perfil.
function renderWho() {
  const who = document.getElementById("who");
  clear(who);
  who.append(avatar(me, "sm"), h("span", { class: "who-text" },
    h("span", { class: "who-name", text: me.name }), h("span", { class: "who-email", text: me.email })));
}

function showChangePassword() {
  document.getElementById("view-change-password").classList.remove("hidden");
  document.getElementById("cp-logout").addEventListener("click", logout);
  matchPasswords(document.getElementById("cp-new"), document.getElementById("cp-new2"));
  document.getElementById("form-change-password").addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    const err = document.getElementById("cp-error");
    err.textContent = "";
    try {
      await api.post("/auth/change-password", {
        current_password: document.getElementById("cp-current").value,
        new_password: document.getElementById("cp-new").value,
      });
      location.reload();
    } catch (e) {
      err.textContent = e.message || "Erro ao trocar a senha.";
    }
  }));
}

async function boot() {
  loadBranding();
  try {
    me = await api.get("/auth/me");
  } catch (e) {
    // Só sessão inválida vai ao login; sem rede ou servidor fora, avisa e deixa tentar de novo.
    if (e.status === 401 || e.message === "nao autenticado") { toLogin(); return; }
    document.body.append(h("div", { class: "auth-wrap" }, h("p", { class: "empty", text: e.message || "Não foi possível abrir o Nexus." }),
      h("button", { type: "button", class: "btn btn-primary", text: "Tentar de novo", onClick: () => location.reload() })));
    return;
  }
  api.setCsrf(me.csrf_token);
  setTimeZone(me.tz);
  if (me.must_change_password) {
    showChangePassword();
    return;
  }
  document.getElementById("app").classList.remove("hidden");
  session.me = me;
  renderWho();
  configureAssistant(me);
  if (has("user")) {
    initTimer(route);
    startIdle(me, route);
  }
  // Perfil ou assistente mudou (Configurações, convite do assistente): atualiza o menu e o lembrete.
  window.addEventListener("nexus:me", () => { renderWho(); configureAssistant(me); if (has("user")) startIdle(me, route); });
  // Menu: cada item aparece só para quem tem o papel (data-need).
  for (const el of document.querySelectorAll("[data-need]")) el.classList.toggle("hidden", !has(el.dataset.need));
  initTooltips();
  syncRail();
  // Celular: rolando para baixo, o botão flutuante encolhe para o ícone; para cima, volta.
  const fab = document.getElementById("fab");
  let lastY = scrollY;
  addEventListener("scroll", () => {
    const y = scrollY;
    if (Math.abs(y - lastY) < 6) return;
    fab.classList.toggle("compact", y > lastY && y > 80);
    lastY = y;
  }, { passive: true });
  // Barra inferior: no máximo 5 itens; quem atribui troca a Busca por Atribuir.
  if (has("assigner")) document.querySelector('#tabbar [data-view="busca"]').classList.add("hidden");
  // Celular: rolando a página, o título vira uma barra fina no topo.
  const pageTitle = document.getElementById("page-title");
  new IntersectionObserver(([e]) => {
    const shown = !pageTitle.closest(".hidden");
    document.getElementById("appbar").classList.toggle("show", shown && !e.isIntersecting && e.boundingClientRect.top < 0);
  }).observe(pageTitle);
  document.getElementById("btn-logout").addEventListener("click", logout);
  document.getElementById("btn-help").addEventListener("click", showHelp);
  // Busca na barra lateral; "/" foca a busca de qualquer tela.
  const sideQ = document.getElementById("side-search-q");
  document.getElementById("side-search").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const v = sideQ.value.trim();
    hideSugg();
    if (v.length >= 2) location.hash = "#/busca?q=" + encodeURIComponent(v);
  });
  // Resultados enquanto digita (até 5 tarefas e 2 projetos); Enter abre a Busca completa.
  const sugg = h("div", { class: "side-sugg hidden", id: "side-sugg", "aria-label": "Sugestões da busca" });
  document.getElementById("side-search").append(sugg);
  let suggTimer = null, suggSeq = 0;
  // Idempotente: tirar da tela a sugestão com foco dispara o focusout, que chama de novo.
  function hideSugg() {
    clearTimeout(suggTimer); suggSeq++;
    if (sugg.classList.contains("hidden")) return;
    sugg.classList.add("hidden");
    sugg.replaceChildren();
  }
  const suggItems = () => [...sugg.querySelectorAll(".sugg-item")];
  sideQ.addEventListener("input", () => {
    clearTimeout(suggTimer);
    const q = sideQ.value.trim();
    if (q.length < 2) { hideSugg(); return; }
    suggTimer = setTimeout(async () => {
      const my = ++suggSeq;
      let r;
      try { r = await api.get("/search?q=" + encodeURIComponent(q)); } catch { return; }
      if (my !== suggSeq) return;
      clear(sugg);
      const tasks = r.tasks.slice(0, 5), projs = r.projects.slice(0, 2);
      for (const t of tasks)
        sugg.append(h("button", { type: "button", class: "sugg-item", onClick: () => { hideSugg(); sideQ.value = ""; openTask(t.id, route); } },
          icon("tasks"), h("span", { class: "sugg-t" }, ...highlight(t.title, q)), t.status === "done" ? h("small", { text: "concluída" }) : null));
      for (const p of projs)
        sugg.append(h("button", { type: "button", class: "sugg-item", onClick: () => {
          hideSugg(); sideQ.value = "";
          sessionStorage.setItem("nexus.board.project", String(p.id));
          if (location.hash.startsWith("#/tarefas")) route(); else location.hash = "#/tarefas";
        } }, icon("folder"), h("span", { class: "sugg-t" }, ...highlight(p.name, q)), h("small", { text: "projeto" })));
      if (!tasks.length && !projs.length) sugg.append(h("p", { class: "sugg-empty", text: "Nada encontrado." }));
      sugg.append(h("button", { type: "submit", class: "sugg-all", text: "Ver todos os resultados" }));
      sugg.classList.remove("hidden");
    }, 250);
  });
  // Setas andam entre as sugestões; Esc fecha e volta ao campo.
  document.getElementById("side-search").addEventListener("keydown", (ev) => {
    const items = suggItems();
    if (sugg.classList.contains("hidden") || !items.length) return;
    const i = items.indexOf(document.activeElement);
    if (ev.key === "ArrowDown") { ev.preventDefault(); items[Math.min(i + 1, items.length - 1)].focus(); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); if (i <= 0) sideQ.focus(); else items[i - 1].focus(); }
    else if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); hideSugg(); sideQ.focus(); }
  });
  document.getElementById("side-search").addEventListener("focusout", (ev) => {
    if (!ev.currentTarget.contains(ev.relatedTarget)) hideSugg();
  });
  // Atalhos de teclado (fora de campos e diálogos). "?" mostra a lista.
  const SHORTCUTS = {
    "/": ["Buscar", () => {
      if (getComputedStyle(sideQ).display !== "none" && sideQ.offsetParent) sideQ.focus();
      else location.hash = "#/busca";
    }],
    n: ["Nova tarefa", () => openWorklog(route)],
    h: ["Ir para Hoje", () => go("hoje")],
    t: ["Ir para Tarefas", () => go("tarefas")],
    r: ["Ir para Retrospectiva", () => go("dashboard")],
    l: ["Ir para Relatórios", () => go("relatorios")],
    s: ["Parar o cronômetro (e apontar)", () => { if (timerState()) stopTimer(); }],
    "?": ["Mostrar estes atalhos", showShortcuts],
  };
  function showShortcuts() {
    const dlg = modal(h("h2", { text: "Atalhos de teclado" }),
      h("dl", { class: "shortcuts" }, ...Object.entries(SHORTCUTS).flatMap(([k, [label]]) => [h("dt", {}, h("kbd", { text: k })), h("dd", { text: label })])),
      h("p", { class: "dialog-note", text: "Funcionam fora dos campos de texto. Esc fecha qualquer janela." }),
      h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-primary", text: "Fechar", onClick: () => dlg.close() })));
  }
  document.addEventListener("keydown", (ev) => {
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const sc = SHORTCUTS[ev.key.length === 1 ? ev.key.toLowerCase() : ""] || SHORTCUTS[ev.key];
    if (!sc || !has("user")) return;  // atalhos são do registro próprio
    const tag = (document.activeElement && document.activeElement.tagName) || "";
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || document.activeElement?.isContentEditable || document.querySelector("dialog[open]:not(.side)")) return;
    ev.preventDefault();
    sc[1]();
  });
  window.addEventListener("hashchange", route);
  route();
  // Primeiro acesso: o tour guiado abre sozinho (uma vez; a Ajuda reabre).
  if (has("user") && !me.tour_done_at) setTimeout(() => startTour(me), 700);
}

boot();
