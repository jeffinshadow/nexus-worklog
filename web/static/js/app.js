// Casca do app: sessão, rotas por hash (#/hoje, #/tarefas...), menu e títulos.
import { api, toLogin } from "./api.js";
import { h, icon, clear, setTimeZone } from "./dom.js";
import * as today from "./today.js";
import * as board from "./board.js";
import * as dashboard from "./dashboard.js";
import * as reports from "./reports.js";
import * as history from "./history.js";
import * as settings from "./settings.js";
import * as admin from "./admin.js";
import * as equipe from "./equipe.js";
import * as atribuir from "./atribuir.js";
import * as search from "./search.js";
import { loadBranding } from "./branding.js";
import { avatar } from "./profile.js";
import { startIdle } from "./idle.js";
import { configure as configureAssistant } from "./assistant.js";
import { session } from "./session.js";
import { initTimer, stopTimer, timerState } from "./timer.js";
import { openWorklog } from "./board.js";
import { openTask } from "./task.js";
import { modal } from "./ui.js";

let me = null;

// need: papel exigido (user = tem o próprio registro). O backend confere de novo.
const VIEWS = {
  hoje: { title: "Hoje", need: "user", mount: (el, ctx) => today.mount(el, ctx) },
  tarefas: { title: "Tarefas", need: "user", mount: (el, ctx) => board.mount(el, ctx) },
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
  document.getElementById("page-title").textContent = view.title;
  document.getElementById("page-eyebrow").textContent = view.eyebrow || "";
  document.title = `${view.title} · Nexus Worklog`;
  setActions();

  const el = document.getElementById("view-" + name);
  const seq = ++routeSeq;
  setAssist(null);
  // A fala do assistente fica acima do título; uma tela antiga que termina de
  // carregar depois da troca não sobrescreve a da tela atual.
  const assist = (node) => { if (seq === routeSeq) setAssist(node); };
  // Carregando: a tela antiga não fica parecendo a nova enquanto a resposta não vem.
  el.setAttribute("aria-busy", "true");
  const loading = setTimeout(() => { if (seq === routeSeq) { clear(el); el.append(h("p", { class: "empty", text: "Carregando…" })); } }, 250);
  try {
    await view.mount(el, { me, setActions, setEyebrow, setAssist: assist, go });
  } catch (e) {
    clear(el);
    el.append(h("p", { class: "empty", text: e && e.status === 0 ? e.message : "Erro ao carregar. Tente de novo." }));
  } finally {
    clearTimeout(loading);
    el.removeAttribute("aria-busy");
  }
  window.scrollTo(0, 0);
  // Link direto para uma tarefa (#/tarefas?id=N: e-mail de atribuição, calendário).
  const taskId = Number(new URLSearchParams(location.hash.split("?")[1] || "").get("id"));
  if (name === "tarefas" && taskId > 0 && seq === routeSeq) {
    window.history.replaceState(null, "", "#/tarefas"); // "history" aqui é a tela de Histórico
    openTask(taskId, route);
  }
}

let routeSeq = 0;
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

// Celular: "Mais" reúne o que não cabe na barra inferior.
function mountMore(el) {
  clear(el);
  const items = [
    ["dashboard", "dashboard", "Retrospectiva"],
    ["historico", "history", "Histórico"],
    ["atribuir", "send", "Atribuir tarefas"],
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

// Ajuda: atalhos, onde está o guia e a quem recorrer (contato do Admin > Geral).
function showHelp() {
  const dlg = modal(h("h2", { text: "Ajuda" }),
    h("p", { class: "help", text: "Tarefas, rotinas e tempo ficam em Hoje e Tarefas; a Retrospectiva e os Relatórios mostram o período. Tudo que muda fica no Histórico, com desfazer." }),
    has("user") ? h("p", { class: "help", text: "Atalhos: n nova tarefa, / buscar, h t r l trocam de tela, s para o cronômetro, ? mostra todos." }) : null,
    h("p", { class: "help" }, "Guia completo: ", h("a", { href: "https://github.com/jeffinshadow/shadow-nexus-worklog#readme", target: "_blank", rel: "noopener noreferrer", text: "README do Nexus" }), "."),
    me.support_contact ? h("p", { class: "help" }, "Suporte: ", h("strong", { text: me.support_contact })) : h("p", { class: "dialog-note", text: "Dúvidas ou problemas: fale com quem administra o Nexus na sua equipe." }),
    h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-primary", text: "Fechar", onClick: () => dlg.close() })));
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
  document.getElementById("form-change-password").addEventListener("submit", async (ev) => {
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
  });
}

async function boot() {
  loadBranding();
  try {
    me = await api.get("/auth/me");
  } catch {
    toLogin();
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
  document.getElementById("btn-logout").addEventListener("click", logout);
  document.getElementById("btn-help").addEventListener("click", showHelp);
  // Busca na barra lateral; "/" foca a busca de qualquer tela.
  const sideQ = document.getElementById("side-search-q");
  document.getElementById("side-search").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const v = sideQ.value.trim();
    if (v.length >= 2) location.hash = "#/busca?q=" + encodeURIComponent(v);
  });
  // Atalhos de teclado (fora de campos e diálogos). "?" mostra a lista.
  const SHORTCUTS = {
    "/": ["Buscar", () => {
      if (getComputedStyle(sideQ).display !== "none" && sideQ.offsetParent) sideQ.focus();
      else location.hash = "#/busca";
    }],
    n: ["Nova tarefa", () => openWorklog(null, route)],
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
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || document.activeElement?.isContentEditable || document.querySelector("dialog[open]")) return;
    ev.preventDefault();
    sc[1]();
  });
  window.addEventListener("hashchange", route);
  route();
}

boot();
