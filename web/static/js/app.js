// Casca do app: sessão, rotas por hash (#/hoje, #/tarefas...), menu e títulos.
import { api, toLogin } from "./api.js";
import { h, icon, clear, setTimeZone, matchPasswords } from "./dom.js";
import * as today from "./today.js";
import * as board from "./board.js";
import * as projetos from "./projetos.js";
import * as mes from "./mes.js";
import * as history from "./history.js";
import * as settings from "./settings.js";
import * as admin from "./admin.js";
import * as equipe from "./equipe.js";
import * as atribuir from "./atribuir.js";
import { newRenewal, renewalsPanel } from "./renewals.js";
import * as search from "./search.js";
import { highlight } from "./search.js";
import { loadBranding } from "./branding.js";
import { avatar } from "./profile.js";
import { startIdle } from "./idle.js";
import { startReminders } from "./lembretes.js";
import { canOfferInstall, install, offerInstall, sharedTask, stashShare, takeShortcut } from "./instalar.js";
import { offerNotifications, syncOnBoot } from "./notificacoes.js";
import { pendingCount, startQueue, wipe } from "./fila.js";
import { configure as configureAssistant } from "./assistant.js";
import { session } from "./session.js";
import { initTimer, stopTimer, timerState } from "./timer.js";
import { openWorklog } from "./board.js";
import { openTask, closeSidePanel } from "./task.js";
import { startTour, visibilityNotice, roleNotice } from "./tour.js";
import { openReview } from "./review.js";
import { modal, busy, initTooltips, initRailPeek, syncRail, calmMotion, toast, singleKeysOn, repaintBadges } from "./ui.js";

let me = null;

// need: papel exigido (user = tem o próprio registro). O backend confere de novo.
const VIEWS = {
  hoje: { title: "Hoje", need: "user", mount: (el, ctx) => today.mount(el, ctx) },
  tarefas: { title: "Tarefas", need: "user", mount: (el, ctx) => board.mount(el, ctx) },
  projetos: { title: "Projetos", need: "user", mount: (el, ctx) => projetos.mount(el, ctx) },
  vencimentos: { title: "Vencimentos", need: "user", eyebrow: "o que renovar", mount: (el, ctx) => mountRenewals(el, ctx) },
  mes: { title: "Meu mês", need: "user", eyebrow: "como foi o mês", mount: (el, ctx) => mes.mount(el, ctx) },
  historico: { title: "Histórico", eyebrow: "o que mudou", mount: (el) => history.mount(el) },
  config: { title: "Configurações", mount: (el, ctx) => settings.mount(el, ctx) },
  atribuir: { title: "Atribuir tarefas", need: "assigner", eyebrow: "para a equipe", mount: (el, ctx) => atribuir.mount(el, ctx) },
  equipe: { title: "Equipe", need: "viewer", eyebrow: "a equipe no mês", mount: (el, ctx) => equipe.mount(el, ctx) },
  admin: { title: "Admin", need: "admin", eyebrow: "contas e papéis", mount: (el, ctx) => admin.mount(el, ctx) },
  mais: { title: "Mais", mount: (el) => mountMore(el) },
  busca: { title: "Busca", need: "user", eyebrow: "em tudo", mount: (el, ctx) => search.mount(el, ctx) },
};

// Telas que viraram Meu mês: links antigos (favoritos, e-mails) continuam valendo;
// os Relatórios chegam com a exportação aberta.
const MOVED = { dashboard: "mes", relatorios: "mes?aba=pdf" };

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

// Troca de tela pedida agora pelo menu ou por atalho: ao terminar, o foco vai
// para o título da tela nova (o leitor anuncia onde chegou). Recargas e o
// carregamento inicial não mexem no foco.
let navAt = 0;
document.addEventListener("click", (ev) => { if (ev.target.closest && ev.target.closest("a[data-view]")) navAt = Date.now(); }, true);

async function route() {
  const wantFocus = Date.now() - navAt < 1500;
  navAt = 0;
  let name = (location.hash.replace(/^#\/?/, "") || home()).split("?")[0];
  if (MOVED[name]) { window.history.replaceState(null, "", "#/" + MOVED[name]); name = "mes"; }
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
  setEyebrow(view.eyebrow || prev.eyebrow || "");
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
    // Servidor fora (ou o app abriu do cache do aparelho): a frase e o botão, como na abertura.
    el.append(h("div", { class: "auth-card view-error", role: "alert" },
      h("p", { class: "sub", text: e && e.status === 0 ? e.message : "Não foi possível carregar." }),
      h("button", { type: "button", class: "btn btn-primary full", text: "Tentar de novo", onClick: () => route() })));
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
  if (wantFocus && seq === routeSeq) document.getElementById("page-title").focus({ preventScroll: true });
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

// A linha abaixo do título.
function setEyebrow(text) {
  document.getElementById("page-eyebrow").textContent = text;
}

function go(name) {
  navAt = Date.now();
  location.hash = "#/" + name;
}

// Sair com coisas ainda na fila: elas se perdem (o aparelho pode ser de outra pessoa).
async function confirmLeave(n) {
  const { confirmDialog } = await import("./ui.js");
  return confirmDialog({ title: "Sair sem enviar?", text: `${n} ${n > 1 ? "alterações feitas" : "alteração feita"} sem conexão ainda não ${n > 1 ? "foram" : "foi"} para o servidor. Saindo agora, ${n > 1 ? "elas se perdem" : "ela se perde"}.`, confirm: "Sair mesmo assim", danger: true });
}

async function logout() {
  const n = pendingCount();
  if (n && !(await confirmLeave(n))) return;
  try { await api.post("/auth/logout"); } catch { /* ignora */ }
  await wipe();  // fila e leituras guardadas não ficam no aparelho
  if ("clearAppBadge" in navigator) navigator.clearAppBadge().catch(() => {});
  location.href = "/login";
}

// Vencimentos: item próprio no menu (importante demais para ficar em Configurações).
async function mountRenewals(el, ctx) {
  // Ação principal no cabeçalho, como nas outras telas (no celular vira o botão flutuante).
  ctx.setActions(h("button", { type: "button", class: "btn btn-primary", "data-fab": "", onClick: () => newRenewal(render) }, icon("add"), "Vencimento"));
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
    ["vencimentos", "calendar", "Vencimentos"],
    ["historico", "history", "Histórico"],
    // A Busca fica sempre na barra; Atribuir vem para cá (na barra só para quem não tem registro próprio).
    has("user") ? ["atribuir", "send", "Atribuir tarefas"] : null,
    ["equipe", "team", "Equipe"],
    ["admin", "admin", "Admin"],
    ["config", "settings", "Configurações"],
  ].filter((it) => it && allowed(it[0]));
  el.append(
    h("a", { href: "#/config?aba=conta", class: "more-me" }, avatar(me, "md"),
      h("span", { class: "who-text" }, h("span", { class: "who-name", text: me.name, title: me.name }), h("span", { class: "who-email", text: me.email, title: me.email }))),
    h("div", { class: "menu-list" },
      ...items.map(([v, ic, label]) => h("a", { href: "#/" + v, "data-view": v }, icon(ic), h("span", { text: label }))),
      // A revisão guiada da semana (também no card "Esta semana" do Hoje).
      has("user") ? h("button", { type: "button", class: "nav-btn", onClick: () => openReview() }, icon("check"), h("span", { text: "Revisão da semana" })) : null,
      h("button", { type: "button", class: "nav-btn", onClick: showHelp }, icon("help"), h("span", { text: "Ajuda" })),
      h("button", { type: "button", class: "nav-btn logout", onClick: logout }, icon("logout"), h("span", { text: "Sair" }))
    )
  );
  repaintBadges(); // ex.: pedidos de convite no item Admin
}

// Ajuda em seções: começar (tour e manual), onde fica cada coisa, marcadores do
// registro rápido, atalhos (só no computador) e a quem recorrer (Admin > Geral).
function showHelp(focus) {
  const user = has("user");
  const sec = (ic, title, ...body) => h("section", { class: "help-sec" }, h("h3", {}, icon(ic), h("span", { text: title })), ...body);
  const list = (rows) => h("dl", { class: "help-list" }, ...rows.flatMap(([k, v, code]) =>
    [h("dt", {}, code ? h("code", { text: k }) : k), h("dd", { text: v })]));
  const desk = !matchMedia("(max-width: 860px)").matches;
  const dlg = modal(h("h2", { text: "Ajuda" }),
    sec("spark", "Começar",
      h("div", { class: "help-start" },
        user ? h("button", { type: "button", class: "btn btn-primary btn-sm", onClick: () => { dlg.close(); startTour(me); } }, icon("help"), "Fazer o tour guiado") : null,
        h("a", { class: "btn btn-ghost btn-sm", href: "https://shadow.tec.br/nexus-manual", target: "_blank", rel: "noopener noreferrer" }, icon("reports"), "Manual, tela por tela"),
        canOfferInstall() ? h("button", { type: "button", class: "btn btn-ghost btn-sm", onClick: () => { dlg.close(); install(); } }, icon("download"), "Instalar o app") : null),
      user ? h("p", { class: "help-example dialog-note", text: "O tour configura o seu Nexus (nome, dias úteis, projetos, rotinas) e mostra a tela Hoje em poucos minutos." }) : null),
    sec("today", "Onde fica cada coisa", list([
      ...(user ? [["Hoje", "Rotinas do dia, tarefas em aberto (com filtro) e o registro rápido."],
        ["Tarefas", "O quadro completo e o detalhe de cada tarefa: anotações, checklist, cronômetro, tempo."],
        ["Projetos", "Cada projeto com os objetivos em ordem de execução e as tarefas de cada um."],
        ["Meu mês", "Como foi o mês numa frase, com o PDF do mês. Embaixo, o painel: rotinas em dia, tarefas concluídas e horas apontadas, cada um com os últimos 6 meses e uma palavra que situa o mês na sua própria média (acima, na média, abaixo — só para você ver o seu ritmo; quem acompanha a equipe não vê); o calendário do mês, com cada dia pintado pela parte das rotinas feitas (mais forte = mais feitas); o ritmo por semana; o tempo por projeto; e as rotinas que pedem atenção. Depois, o que foi entregue. Outro período, um projeto e a exportação dos dados ficam em “Outro período ou formato”."]] : []),
      ["Histórico", "Tudo o que mudou, com desfazer."],
      ...(has("assigner") ? [["Atribuir", "Do papel “Manda tarefas”. Manda uma tarefa para quem aceitou receber. Enquanto ela está a fazer, você ainda corrige ou cancela; depois, é da pessoa."]] : []),
      ...(has("viewer") ? [["Equipe", "Do papel “Vê a equipe”. Um painel para coordenar, não para comparar: os números da equipe somados (rotinas em dia, tarefas concluídas, horas, aguardando), o que precisa de atenção, o tempo por projeto e as pessoas em ordem alfabética. Tocar numa pessoa abre o mês e o quadro dela, só para ver. Entra só quem permitiu (cada pessoa decide em Configurações > Conta). No topo: Atribuir tarefa, Horas da equipe (CSV) e PDF."]] : []),
      ...(has("admin") ? [["Admin", "Convites e pedidos de convite, contas (senha, bloquear, excluir), papéis, configurações gerais e identidade visual."]] : []),
      ["Configurações", user ? "A sua conta (dias úteis, projeto padrão, quem vê e quem manda tarefas), modelos, avisos, calendário e IA." : "A sua conta, e IA e API."],
    ])),
    user ? sec("add", "Registro rápido (no Hoje)",
      h("p", { class: "help", text: "Escreva o que fez e aperte Enter. Marcadores opcionais no fim, em qualquer ordem:" }),
      list([
        ["@Projeto", "projeto; um segundo @ põe a tarefa nos dois", true],
        ["#4821", "número do chamado", true],
        ["!alta", "prioridade alta", true],
        ["!plantão", "fora do horário", true],
        ["^amanhã", "prazo: ^hoje, ^sex, ^25/10…", true],
        ["!aguarda motivo", "fica aguardando o motivo (sempre por último)", true],
        ["— 45min", "já conclui, com o tempo apontado", true],
      ]),
      h("p", { class: "help-example" }, "Ex.: ", h("code", { text: "Troca do switch @Matriz #4821 — 45min" }))) : null,
    user && desk ? sec("key", "Atalhos de teclado", list([
      ["n", "nova tarefa", true], ["q", "registro rápido", true], ["/", "buscar", true], ["h t", "Hoje, Tarefas", true], ["r l", "Meu mês: números, relatórios", true],
      ["s", "parar o cronômetro", true], ["?", "ver todos os atalhos", true],
    ])) : null,
    // Para o admin, o Suporte é ele mesmo: diz onde fica o contato que os outros veem.
    has("admin")
      ? sec("mail", "Suporte", h("p", { class: "help", text: me.support_contact
          ? `As pessoas veem aqui: “${me.support_contact}”. Você muda em Admin > Geral.`
          : "Você administra este Nexus. Em Admin > Geral, ponha o contato de suporte que as pessoas vão ver aqui." }))
      : sec("mail", "Suporte", me.support_contact
        ? h("p", { class: "help" }, "Fale com ", h("strong", { text: me.support_contact }), ".")
        : h("p", { class: "help", text: "Dúvidas ou problemas: fale com quem administra o Nexus na sua equipe." })),
    h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-text", text: "Fechar", onClick: () => dlg.close() })));
  dlg.classList.add("help-dialog");
  // Só o meio rola (título e Fechar ficam fixos): a barra de rolagem não passa por cima dos cantos arredondados.
  const helpBody = h("div", { class: "help-body" }, ...[...dlg.children].filter((el) => el.tagName !== "H2" && !el.classList.contains("dialog-actions")));
  dlg.querySelector(".dialog-actions").before(helpBody);
  // Pedido de uma seção (ex.: "ver marcadores" no Hoje): rola até ela.
  if (focus === "marcadores") [...dlg.querySelectorAll(".help-sec")].find((s) => /Registro rápido/.test(s.textContent))?.scrollIntoView({ block: "start" });
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
  const meBtn = document.getElementById("appbar-me");  // celular: a foto no topo leva à conta
  meBtn.replaceChildren(avatar(me, "sm"));
  meBtn.setAttribute("aria-label", `Sua conta (${me.name})`);
  who.append(avatar(me, "sm"), h("span", { class: "who-text" },
    h("span", { class: "who-name", text: me.name, title: me.name }), h("span", { class: "who-email", text: me.email, title: me.email })));
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
      err.textContent = e.message || "Não foi possível trocar a senha.";
    }
  }));
}

async function boot() {
  stashShare(); // compartilhado de outro app: guarda antes de um eventual login
  loadBranding();
  try {
    // Servidor fora: o cartão de erro vem em segundos (o service worker, sem rede, responde antes com a cópia guardada).
    me = await api.get("/auth/me", { timeout: 6500 });
  } catch (e) {
    // Só sessão inválida vai ao login; sem rede ou servidor fora, avisa e deixa tentar de novo.
    if (e.status === 401 || e.message === "nao autenticado") { toLogin(); return; }
    document.getElementById("boot-splash")?.remove();
    document.querySelector(".skip-link")?.remove(); // o <main> está escondido: o atalho não levaria a nada
    // O mesmo cartão do login: a marca, a frase e o botão juntos, no meio da tela.
    const retry = h("button", { type: "button", class: "btn btn-primary full", text: "Tentar de novo", onClick: () => location.reload() });
    document.body.append(h("div", { class: "auth-wrap" }, h("div", { class: "auth-card boot-error", role: "alert" },
      h("div", { class: "lockup lockup--center" }, h("img", { class: "lockup-mark", src: "/img/dragon-mark.svg", alt: "", width: "26", height: "30" }),
        h("span", { class: "lockup-type" }, h("span", { text: "nexus" }), h("span", { text: "worklog" }))),
      h("p", { class: "sub", text: e.message || "Não foi possível abrir o Nexus." }),
      retry)));
    retry.focus();
    loadBranding();  // o logo da equipe, se o servidor responder
    return;
  }
  document.getElementById("boot-splash")?.remove();
  api.setCsrf(me.csrf_token);
  setTimeZone(me.tz);
  if (window.nexusTheme && me.theme && me.theme !== window.nexusTheme.get()) window.nexusTheme.set(me.theme);  // a escolha da conta vale aqui também
  // Outra conta neste aparelho: nada do que ficou guardado da anterior serve.
  try {
    if (localStorage.getItem("nexus.uid") !== String(me.id)) { await wipe(); localStorage.setItem("nexus.uid", String(me.id)); }
  } catch { /* sem armazenamento */ }
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
    startReminders(route);
  }
  // Perfil ou assistente mudou (Configurações, convite do assistente): atualiza o menu e o lembrete.
  window.addEventListener("nexus:me", () => { renderWho(); configureAssistant(me); if (has("user")) startIdle(me, route); });
  // Menu: cada item aparece só para quem tem o papel (data-need).
  for (const el of document.querySelectorAll("[data-need]")) el.classList.toggle("hidden", !has(el.dataset.need));
  initTooltips();
  initRailPeek();
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
  // Barra inferior: no máximo 5 itens; a Busca fica sempre e Atribuir vai para "Mais"
  // (fica na barra só para quem atribui sem ter registro próprio).
  if (has("user")) document.querySelector('#tabbar [data-view="atribuir"]').classList.add("hidden");
  // Celular: quando o título da tela passa por baixo da barra do topo, ela ganha a linha de baixo.
  const pageTitle = document.getElementById("page-title");
  const barH = () => document.getElementById("appbar").getBoundingClientRect().height || 56;
  new IntersectionObserver(([e]) => {
    const shown = !pageTitle.closest(".hidden");
    document.getElementById("appbar").classList.toggle("show", shown && e.intersectionRatio < 1 && e.boundingClientRect.top < barH());
  }, { rootMargin: `-${Math.round(barH())}px 0px 0px 0px`, threshold: [0, 1] }).observe(pageTitle);
  document.getElementById("btn-logout").addEventListener("click", logout);
  document.getElementById("btn-help").addEventListener("click", () => showHelp());
  window.addEventListener("nexus:help", (ev) => showHelp(ev.detail));
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
          location.hash = "#/projetos?id=" + p.id;  // a tela do projeto, como na Busca
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
    // O registro rápido fica depois das rotinas na ordem do Tab: uma tecla leva até ele.
    q: ["Registro rápido (no Hoje)", () => {
      const el = document.querySelector('#view-hoje [aria-label="Registrar tarefa rápida"]');
      if (el && el.offsetParent) el.focus(); else go("hoje?acao=rapido");
    }],
    h: ["Ir para Hoje", () => go("hoje")],
    t: ["Ir para Tarefas", () => go("tarefas")],
    r: ["Ir para Meu mês", () => go("mes")],
    l: ["Ir para Meu mês (outro período ou formato)", () => go("mes?aba=pdf")],
    s: ["Parar o cronômetro (e apontar)", () => { if (timerState()) stopTimer(); }],
    "?": ["Mostrar estes atalhos", showShortcuts],
  };
  function showShortcuts() {
    const dlg = modal(h("h2", { text: "Atalhos de teclado" }),
      h("dl", { class: "shortcuts" }, ...Object.entries(SHORTCUTS).flatMap(([k, [label]]) => [h("dt", {}, h("kbd", { text: k })), h("dd", { text: label })])),
      h("p", { class: "dialog-note", text: "Funcionam fora dos campos de texto. Esc fecha qualquer janela. Dá para desligá-los em Configurações." }),
      h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-text", text: "Fechar", onClick: () => dlg.close() })));
  }
  document.addEventListener("keydown", (ev) => {
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const sc = SHORTCUTS[ev.key.length === 1 ? ev.key.toLowerCase() : ""] || SHORTCUTS[ev.key];
    if (!sc || !has("user") || !singleKeysOn()) return;  // atalhos são do registro próprio; desligáveis em Configurações
    const tag = (document.activeElement && document.activeElement.tagName) || "";
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag) || document.activeElement?.isContentEditable || document.querySelector("dialog[open]:not(.side)")) return;
    ev.preventDefault();
    sc[1]();
  });
  // Atalho do ícone (#/hoje?acao=...): sai do endereço antes da tela montar.
  const shortcut = () => {
    const acao = takeShortcut();
    return () => {
      if (!has("user")) return;
      if (acao === "nova") openWorklog(route);
      else if (acao === "rapido") document.querySelector('#view-hoje [aria-label="Registrar tarefa rápida"]')?.focus();
    };
  };
  window.addEventListener("hashchange", () => { const run = shortcut(); route().then(run); });
  const run = shortcut();
  await route();
  run();
  // Texto ou link compartilhado de outro app: abre a Nova tarefa já preenchida (salva só ao confirmar).
  const shared = has("user") ? await sharedTask() : null;
  if (shared) {
    openWorklog(route, shared);
    if (shared.files.length) toast(`${shared.files.length > 1 ? `As ${shared.files.length} fotos entram` : "A foto entra"} na tarefa ao salvar.`);
    else if (shared.note) toast("O texto compartilhado é longo: ao salvar, ele entra inteiro como anotação da tarefa.");
  } else {
    offerInstall(me);        // no navegador: instalar
    offerNotifications(me);  // já instalado: ligar as notificações deste aparelho
  }
  syncOnBoot();
  // Admin: pedidos de convite abertos viram um número no item Admin do menu.
  if (has("admin")) api.get("/admin/invite-requests").then((l) => import("./admin.js").then((m) => m.setRequestsBadge(l.filter((r) => r.status === "pending").length))).catch(() => {});
  startQueue(route);  // sem sinal: a fila do aparelho vai quando a conexão voltar
  // Primeiro acesso: o tour guiado abre sozinho (uma vez; a Ajuda reabre).
  if (has("user") && !me.tour_done_at) setTimeout(() => startTour(me), 700);
  // Quem já usava quando a administração ligou "Visível para quem gerencia": aviso único.
  else if (me.visibility_notice) setTimeout(() => visibilityNotice(me), 700);
  // Papel ganho ou retirado pela administração: aviso único (Admin › Contas › Papéis).
  else if (me.role_notice) setTimeout(() => roleNotice(me), 700);
}

boot();
