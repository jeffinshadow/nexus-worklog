// Casca do app: sessão, rotas por hash (#/hoje, #/tarefas...), menu e títulos.
import { api } from "./api.js";
import { h, icon, clear, longDate } from "./dom.js";
import * as today from "./today.js";
import * as board from "./board.js";
import * as dashboard from "./dashboard.js";
import * as reports from "./reports.js";
import * as history from "./history.js";
import * as settings from "./settings.js";
import * as admin from "./admin.js";

let me = null;

const VIEWS = {
  hoje: { title: "Hoje", mount: (el, ctx) => today.mount(el, ctx) },
  tarefas: { title: "Tarefas", eyebrow: "recorrentes · pontuais · concluídas", mount: (el, ctx) => board.mount(el, ctx) },
  dashboard: { title: "Dashboard", eyebrow: "consistência e fluxo", mount: (el) => dashboard.mount(el) },
  relatorios: { title: "Relatórios", eyebrow: "exportar em PDF", mount: (el) => reports.mount(el) },
  historico: { title: "Histórico", eyebrow: "o que mudou, por quem", mount: (el) => history.mount(el) },
  config: { title: "Configurações", eyebrow: "dias úteis · chaves de API · IA · conta", mount: (el, ctx) => settings.mount(el, ctx) },
  admin: { title: "Admin", eyebrow: "somente leitura", mount: (el) => admin.mount(el), adminOnly: true },
  mais: { title: "Mais", mount: (el) => mountMore(el) },
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
  try {
    await view.mount(el, { me, setActions, setEyebrow, go });
  } catch (e) {
    clear(el);
    el.append(h("p", { class: "empty", text: "Erro ao carregar. Tente de novo." }));
  }
  window.scrollTo(0, 0);
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
    ["historico", "history", "Histórico"],
    ["config", "settings", "Configurações"],
  ];
  if (me.role === "admin") items.push(["admin", "admin", "Admin"]);
  el.append(
    h("p", { class: "muted mono", text: me.email }),
    h("div", { class: "menu-list" },
      ...items.map(([v, ic, label]) => h("a", { href: "#/" + v }, icon(ic), h("span", { text: label }))),
      h("button", { type: "button", class: "nav-btn logout", onClick: logout }, icon("logout"), h("span", { text: "Sair" }))
    )
  );
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
  try {
    me = await api.get("/auth/me");
  } catch {
    location.href = "/login.html";
    return;
  }
  api.setCsrf(me.csrf_token);
  if (me.must_change_password) {
    showChangePassword();
    return;
  }
  document.getElementById("app").classList.remove("hidden");
  document.getElementById("who").textContent = me.email;
  if (me.role === "admin") document.getElementById("nav-admin").classList.remove("hidden");
  document.getElementById("btn-logout").addEventListener("click", logout);
  window.addEventListener("hashchange", route);
  route();
}

boot();
