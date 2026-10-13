// Casca do app: sessão, rotas por hash (#/hoje, #/tarefas...), menu e títulos.
import { api } from "./api.js";
import { h, icon, clear, setTimeZone } from "./dom.js";
import * as today from "./today.js";
import * as board from "./board.js";
import * as dashboard from "./dashboard.js";
import * as reports from "./reports.js";
import * as history from "./history.js";
import * as settings from "./settings.js";
import * as admin from "./admin.js";
import * as search from "./search.js";
import { loadBranding } from "./branding.js";
import { avatar } from "./profile.js";
import { startIdle } from "./idle.js";
import { configure as configureAssistant } from "./assistant.js";

let me = null;

const VIEWS = {
  hoje: { title: "Hoje", mount: (el, ctx) => today.mount(el, ctx) },
  tarefas: { title: "Tarefas", mount: (el, ctx) => board.mount(el, ctx) },
  dashboard: { title: "Retrospectiva", eyebrow: "rotinas · fluxo · tempo · backlog", mount: (el, ctx) => dashboard.mount(el, { me: ctx.me, setAssist: ctx.setAssist }) },
  relatorios: { title: "Relatórios", eyebrow: "PDF · exportar dados", mount: (el, ctx) => reports.mount(el, { me: ctx.me }) },
  historico: { title: "Histórico", eyebrow: "o que mudou, por quem", mount: (el) => history.mount(el) },
  config: { title: "Configurações", mount: (el, ctx) => settings.mount(el, ctx) },
  admin: { title: "Admin", mount: (el) => admin.mount(el), adminOnly: true },
  mais: { title: "Mais", mount: (el) => mountMore(el) },
  busca: { title: "Busca", eyebrow: "tarefas · anotações · checklist · projetos", mount: (el, ctx) => search.mount(el, ctx) },
};

function setActions(...nodes) {
  const box = document.getElementById("page-actions");
  clear(box);
  box.append(...nodes.filter(Boolean));
}

async function route() {
  let name = (location.hash.replace(/^#\/?/, "") || "hoje").split("?")[0];
  if (!VIEWS[name] || (VIEWS[name].adminOnly && me.role !== "admin")) name = "hoje";
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
  try {
    await view.mount(el, { me, setActions, setEyebrow, setAssist: assist, go });
  } catch (e) {
    clear(el);
    el.append(h("p", { class: "empty", text: "Erro ao carregar. Tente de novo." }));
  }
  window.scrollTo(0, 0);
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
    ["config", "settings", "Configurações"],
  ];
  if (me.role === "admin") items.push(["admin", "admin", "Admin"]);
  el.append(
    h("a", { href: "#/config?aba=conta", class: "more-me" }, avatar(me, "md"),
      h("span", { class: "who-text" }, h("span", { class: "who-name", text: me.name }), h("span", { class: "who-email", text: me.email }))),
    h("div", { class: "menu-list" },
      ...items.map(([v, ic, label]) => h("a", { href: "#/" + v }, icon(ic), h("span", { text: label }))),
      h("button", { type: "button", class: "nav-btn logout", onClick: logout }, icon("logout"), h("span", { text: "Sair" }))
    )
  );
}

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
    location.href = "/login.html";
    return;
  }
  api.setCsrf(me.csrf_token);
  setTimeZone(me.tz);
  if (me.must_change_password) {
    showChangePassword();
    return;
  }
  document.getElementById("app").classList.remove("hidden");
  renderWho();
  configureAssistant(me);
  startIdle(me, route);
  // Perfil ou assistente mudou (Configurações, convite do assistente): atualiza o menu e o lembrete.
  window.addEventListener("nexus:me", () => { renderWho(); configureAssistant(me); startIdle(me, route); });
  if (me.role === "admin") document.getElementById("nav-admin").classList.remove("hidden");
  document.getElementById("btn-logout").addEventListener("click", logout);
  // Busca na barra lateral; "/" foca a busca de qualquer tela.
  const sideQ = document.getElementById("side-search-q");
  document.getElementById("side-search").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const v = sideQ.value.trim();
    if (v.length >= 2) location.hash = "#/busca?q=" + encodeURIComponent(v);
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "/" || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const tag = (document.activeElement && document.activeElement.tagName) || "";
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || document.querySelector("dialog[open]")) return;
    ev.preventDefault();
    if (getComputedStyle(sideQ).display !== "none" && sideQ.offsetParent) sideQ.focus();
    else location.hash = "#/busca";
  });
  window.addEventListener("hashchange", route);
  route();
}

boot();
