// Equipe (papel "Vê a equipe"): um painel para COORDENAR, não para comparar.
// Ao redor: o seletor de mês, a frase da equipe e as ações no cabeçalho
// (Atribuir tarefa, Horas da equipe em CSV, PDF de uma pessoa ou projeto). No
// PAINEL (a mesma linguagem de Meu mês, grade de 12 colunas; no celular, uma
// coluna na mesma ordem): os quatro números da equipe SOMADOS com os últimos 6
// meses, "Precisa de atenção", o tempo por projeto e as pessoas em ordem
// alfabética. Tocar numa pessoa abre o mês dela na mesma tela de Meu mês (sem
// média, sem tendência, sem comparação: o servidor nem manda) e o quadro.
// Tudo vem só de quem permitiu ser visto (o servidor filtra, /viewer/team).
//
// Atribuir mora aqui (sem tela própria, sem abas): quem tem "Manda tarefas" vê
// o botão "Atribuir tarefa" no cabeçalho (diálogo por cima da tela) e, logo
// abaixo do painel, "Tarefas que atribuí" (atribuir.js). Quem só atribui vê só
// a lista e o botão: nada de números, painel ou pessoas.
import { api } from "./api.js";
import { h, icon, clear, field, localDay, dateTime, shortDate, addDays } from "./dom.js";
import { busy, errorToast, hashPage, modal, pager, pageSlice, setHashPage, toast } from "./ui.js";
import { session } from "./session.js";
import { assignDialog, sentPanel } from "./atribuir.js";
import { duration } from "./task.js";
import * as board from "./board.js";
import * as mes from "./mes.js";

// O mês escolhido vale para o painel e para o mês de cada pessoa (fica entre visitas).
const monthState = { month: null, months: null };
const SETTING = "Permitir que quem tem o papel “Vê a equipe” veja meu registro";
const PEOPLE_PAGE = 12; // cartões de pessoas por página
let peoplePage = 1;

export async function mount(root, ctx) {
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  const pid = Number(q.get("pessoa"));
  if (pid > 0) return personView(root, ctx, pid, q.get("aba") === "quadro" ? "board" : "mes", Number(q.get("tarefa")) || null);
  return panelView(root, ctx);
}

const roles = () => (session.me && session.me.roles) || [];

// ------------------------------------------------------------- o painel --

async function panelView(root, ctx) {
  const st = monthState;
  if (!st.month || st.month > mes.thisMonth()) st.month = mes.thisMonth();
  const canView = roles().includes("viewer"), canAssign = roles().includes("assigner");
  peoplePage = hashPage("pp");
  ctx.setEyebrow(canView ? "a equipe no mês" : "as tarefas que você atribuiu");
  let data = null;

  // Tarefas que atribuí (logo abaixo do painel) e o diálogo de atribuir, por cima da tela.
  const sent = canAssign ? sentPanel({ onChange: () => { if (canView) load().catch(errorToast); } }) : null;
  const afterAssign = () => { sent.load(); if (canView) load().catch(errorToast); };
  const assignBtn = canAssign ? h("button", { type: "button", class: "btn btn-primary", "data-fab": "",
    onClick: () => assignDialog({ onDone: afterAssign }) }, icon("send"), "Atribuir tarefa") : null;
  if (!canView) {
    // Só atribui: a lista e o botão, nada da equipe.
    ctx.setActions(assignBtn);
    const ready = await api.get("/assign/sent").catch((e) => e);
    await sent.load(ready);
    clear(root);
    root.append(sent.el);
    return;
  }

  const pdfBtn = h("button", { type: "button", class: "btn btn-ghost", onClick: () => pdfDialog(data) }, icon("reports"), "PDF");
  ctx.setActions(
    assignBtn,
    h("button", { type: "button", class: "btn btn-ghost", onClick: () => csvDialog(data) }, icon("download"), "Horas da equipe"),
    pdfBtn);

  const label = h("span", { class: "day-nav-label", "aria-live": "polite" });
  const prev = h("button", { type: "button", class: "icon", title: "Mês anterior", "aria-label": "Mês anterior", onClick: () => pick(mes.prevOf(st.month)) }, icon("left"));
  const next = h("button", { type: "button", class: "icon", title: "Próximo mês", "aria-label": "Próximo mês", onClick: () => pick(mes.nextOf(st.month)) }, icon("right"));
  const paintNav = () => {
    label.textContent = mes.nameOf(st.month) + " de " + st.month.slice(0, 4) + (st.month === mes.thisMonth() ? " · até hoje" : "");
    const focused = document.activeElement;
    next.disabled = st.month >= mes.thisMonth();
    prev.disabled = !!st.months && st.months.length > 0 && st.month <= st.months[st.months.length - 1];
    if (focused === prev && prev.disabled && !next.disabled) next.focus();
    else if (focused === next && next.disabled && !prev.disabled) prev.focus();
  };
  const content = h("div", { class: "mes-content" });

  let seq = 0;
  async function load() {
    const my = ++seq;
    content.classList.add("refreshing");
    try {
      const a = await api.get(`/viewer/team?month=${st.month}`);
      if (my !== seq) return;
      data = a;
      st.months = a.months || [];
      pdfBtn.disabled = !a.people.length;
      pdfBtn.title = a.people.length ? "" : "Ninguém compartilha o registro ainda";
      paintNav();
      clear(content);
      content.append(...screen(a, ctx, sent));
    } finally {
      if (my === seq) content.classList.remove("refreshing");
    }
  }
  async function pick(m) {
    st.month = m;
    paintNav();
    try { await load(); } catch (e) { errorToast(e); }
  }

  paintNav();
  // O painel e a lista juntos (uma espera só).
  const sentReady = sent ? api.get("/assign/sent").catch((e) => e) : null;
  await load();
  if (sent) await sent.load(await sentReady);
  clear(root); // só depois da resposta: na volta à tela, a visita anterior fica até chegar
  root.append(h("div", { class: "day-nav dash-period mes-nav" }, prev, label, next), content, sent ? sent.el : null);
}

function screen(a, ctx, sent) {
  const mesNome = mes.nameOf(a.period.month);
  const hero = h("section", { class: "mes-hero" }, h("p", { class: "mes-sentence", text: sentence(a, mesNome) }));
  if (a.hidden_count) {
    hero.append(h("p", { class: "eq-hidden", text: a.hidden_count === 1
      ? "1 pessoa da equipe não compartilha o dia a dia."
      : `${a.hidden_count} pessoas da equipe não compartilham o dia a dia.` }));
  }
  const panel = h("section", { class: "mm-panel eq-panel", "aria-label": `Painel da equipe em ${mesNome}` },
    ...kpis(a), attentionTile(a, sent), mes.projectsTile(a, mesNome, 5), peopleTile(a, ctx));
  return [hero, panel];
}

const empty = (m) => !m.recurring_total && !m.pontual_done && !m.minutes;

// "Em outubro, até agora, a equipe (4 pessoas) fez 120 das 150 rotinas previstas (80%), concluiu 30 tarefas e apontou 80h."
function sentence(a, mesNome) {
  const m = a.month;
  if (!a.people.length) return "Ninguém da equipe compartilha o dia a dia ainda.";
  const quem = a.people.length === 1 ? "a equipe (1 pessoa)" : `a equipe (${a.people.length} pessoas)`;
  if (empty(m)) return `Nada registrado pela equipe em ${mesNome}${m.now ? " até agora" : ""}.`;
  const partes = [];
  if (m.recurring_total) partes.push(`fez ${m.recurring_done} das ${m.recurring_total} rotinas previstas (${mes.pct(m.recurring_done, m.recurring_total)}%)`);
  if (m.pontual_done) partes.push(`concluiu ${mes.plural(m.pontual_done, "tarefa", "tarefas")}`);
  if (m.minutes) partes.push(`apontou ${duration(m.minutes)}`);
  const lista = partes.length > 1 ? `${partes.slice(0, -1).join(", ")} e ${partes[partes.length - 1]}` : partes[0];
  return `Em ${mesNome}${m.now ? ", até agora," : ""} ${quem} ${lista}.`;
}

// 1) Quatro números da equipe, somados, com os 6 meses da EQUIPE (nada por pessoa).
function kpis(a) {
  const m = a.month, month = a.period.month;
  const slots = mes.monthsBack(month, 6);
  const byMonth = Object.fromEntries(a.trend.map((t) => [t.month, t]));
  const p = m.recurring_total ? mes.pct(m.recurring_done, m.recurring_total) : null;
  const rot = mes.tile(3, "mm-kpi", "Rotinas em dia", null,
    h("div", { class: "mm-kpi-main" }, mes.ring(p),
      h("p", { class: "mm-fact", text: m.recurring_total ? `${m.recurring_done} de ${m.recurring_total} previstas` : "sem rotinas previstas" })),
    mes.lineChart(slots, byMonth, null, month));
  const tasks = mes.tile(3, "mm-kpi", "Tarefas concluídas", null,
    h("div", { class: "mm-kpi-main" }, h("p", { class: "mm-n", text: String(m.pontual_done) }),
      h("p", { class: "mm-fact", text: m.pontual_done ? "somando a equipe" : "nenhuma no mês" })),
    mes.barChart(slots, byMonth, "pontual_done", null, month, (v) => String(v), "tarefas concluídas pela equipe"));
  const hours = mes.tile(3, "mm-kpi", "Horas apontadas", null,
    h("div", { class: "mm-kpi-main" }, h("p", { class: "mm-n", text: m.minutes ? duration(m.minutes) : "—" }),
      h("p", { class: "mm-fact", text: m.minutes ? "somando a equipe" : "nada apontado" })),
    mes.barChart(slots, byMonth, "minutes", null, month, (v) => duration(v), "horas apontadas pela equipe"));
  // Aguardando é do momento (não tem histórico): a parte do que está em aberto.
  const fill = h("span");
  fill.style.width = (a.open ? Math.round((100 * a.waiting) / a.open) : 0) + "%";
  const waiting = mes.tile(3, "mm-kpi eq-wait", "Tarefas aguardando", null,
    h("div", { class: "mm-kpi-main" }, h("p", { class: "mm-n", text: String(a.waiting) }),
      h("p", { class: "mm-fact", text: a.open ? `de ${mes.plural(a.open, "tarefa", "tarefas")} em aberto` : "nada em aberto" })),
    h("div", { class: "eq-wait-foot" },
      h("span", { class: "mes-track mm-meter", "aria-hidden": "true" }, fill),
      h("p", { class: "mm-chart-t", text: "agora, não só no mês" })));
  return [rot, tasks, hours, waiting];
}

// 2) Precisa de atenção: o que destrava trabalho (sem vermelho, sem placar).
const KIND_ICON = { returned: "undo", assigned: "send", waiting: "clock", due: "calendar" };

function attentionLine(x) {
  const dias = (n) => (n == null ? "" : n === 0 ? " desde hoje" : n === 1 ? " há 1 dia" : ` há ${n} dias`);
  if (x.kind === "returned") return `devolveu${x.days === 0 ? " hoje" : x.days === 1 ? " ontem" : dias(x.days)} · «${x.reason || "sem motivo"}»`;
  if (x.kind === "assigned") {
    return x.status === "blocked" ? `você atribuiu · aguardando${dias(x.days)}` : `você atribuiu · ainda não começou (${dias(x.days).trim()})`;
  }
  if (x.kind === "waiting") return `aguardando${dias(x.days)}${x.blocked_reason ? ` · ${x.blocked_reason}` : ""}`;
  if (x.days < 0) return `o prazo era ${shortDate(x.due_date)}`;
  return x.days === 0 ? "vence hoje" : x.days === 1 ? "vence amanhã" : `vence em ${shortDate(x.due_date)}`;
}

function attentionTile(a, sent) {
  // Celular: "Tarefas que atribuí" fica a algumas telas daqui; um atalho leva até lá.
  const jump = sent ? h("button", { type: "button", class: "btn btn-text btn-sm eq-sent-jump", onClick: () => {
    sent.el.scrollIntoView({ block: "start", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    const t = sent.el.querySelector("h2"); if (t) { t.tabIndex = -1; t.focus({ preventScroll: true }); }
  } }, icon("send"), "Ver as tarefas que atribuí") : null;
  const tile = (...body) => mes.tile(7, "eq-att-tile", "Precisa de atenção", "agora: o que foi devolvido, está aguardando, vencendo ou ainda não começado", ...body, jump);
  if (!a.people.length && !a.attention.length) return tile(h("p", { class: "mes-ok", text: "Quando alguém compartilhar o dia a dia, aparece aqui o que está aguardando ou vencendo." }));
  if (!a.attention.length) return tile(h("p", { class: "mes-ok" }, icon("check"), h("span", { text: "Nada devolvido, aguardando, vencendo nos próximos 7 dias ou ainda não começado." })));
  // A devolvida não existe mais no quadro de ninguém: abre a linha dela em Tarefas que atribuí.
  const open = (x) => (x.kind === "returned" && sent ? sent.focusReturned(x.task_id) : openPerson(x.user_id, "quadro", x.task_id));
  return tile(h("ul", { class: "eq-att-list" }, ...a.attention.map((x) => h("li", {},
    h("button", { type: "button", class: "eq-att", onClick: () => open(x) },
      icon(KIND_ICON[x.kind]),
      h("span", { class: "eq-att-t", text: x.title }),
      h("span", { class: "eq-att-m", text: `${x.name} · ${attentionLine(x)}` }))))));
}

// 4) Pessoas: em ordem alfabética (o servidor já manda assim), nada de placar.
function lastSeen(ts) {
  if (!ts) return "sem registro ainda";
  const day = localDay(ts), today = localDay(Date.now());
  if (day === today) return "última atividade hoje";
  if (day === addDays(today, -1)) return "última atividade ontem";
  return `última atividade em ${shortDate(day)}`;
}

function initial(p) {
  if (p.avatar) return h("img", { class: "avatar avatar-md", src: p.avatar, alt: "" });
  return h("span", { class: "avatar avatar-md eq-ini", "aria-hidden": "true", text: (p.name || "?").trim().charAt(0).toUpperCase() });
}

function peopleTile(a, ctx) {
  if (!a.people.length) {
    const pedido = `Para eu acompanhar a equipe no Nexus, você pode ligar “${SETTING}” em Configurações > Conta. Só quem tem esse papel vê, sem editar, e você pode desligar quando quiser.`;
    return mes.tile(12, "eq-people-tile", "Pessoas", null,
      h("p", { class: "eq-empty-t", text: `Ninguém compartilha o dia a dia ainda. Cada pessoa decide em Configurações > Conta, em “${SETTING}”. Quando alguém permitir, o cartão dela aparece aqui e entra nos números.` }),
      h("div", { class: "eq-empty-actions" },
        h("button", { type: "button", class: "btn btn-tonal", onClick: async () => {
          try { await navigator.clipboard.writeText(pedido); toast("Pedido copiado. Mande para a equipe."); }
          catch { toast("Não foi possível copiar.", { error: true }); }
        } }, icon("copy"), "Copiar o pedido para a equipe"),
        roles().includes("admin") ? h("button", { type: "button", class: "btn btn-ghost", onClick: () => ctx.go("admin") }, icon("person"), "Convidar pessoa") : null),
      h("div", { class: "eq-people", "aria-hidden": "true" }, ...[0, 1, 2].map(() => h("div", { class: "eq-person eq-ghost" }))));
  }
  // 12 cartões por página (o pager comum; a página fica no endereço, ?pp=).
  const list = h("ul", { class: "eq-people" });
  const box = h("div", {}, list);
  const tile = mes.tile(12, "eq-people-tile", "Pessoas", "em ordem alfabética · toque para ver o mês e o quadro", box);
  const paint = () => {
    const slice = pageSlice(a.people, peoplePage, PEOPLE_PAGE);
    peoplePage = slice.page;
    setHashPage("pp", peoplePage, "equipe");
    list.replaceChildren(...slice.rows.map((p) => h("li", {},
      h("button", { type: "button", class: "eq-person", title: p.email, onClick: () => openPerson(p.id) },
        initial(p),
        h("span", { class: "eq-p-name", text: p.name }),
        h("span", { class: "eq-p-n", text: `${p.open} em aberto · ${p.waiting} aguardando` }),
        h("span", { class: "eq-p-last", title: p.last_activity ? dateTime(p.last_activity) : "", text: lastSeen(p.last_activity) })))));
    box.querySelector(".pager")?.remove();
    const nav = pager({ page: peoplePage, total: a.people.length, size: PEOPLE_PAGE, label: "pessoas",
      onPage: (n) => { peoplePage = n; paint(); }, focus: () => tile.querySelector(".mm-title") });
    if (nav) box.append(nav);
  };
  paint();
  return tile;
}


function openPerson(uid, aba, taskId) {
  const q = new URLSearchParams({ pessoa: String(uid) });
  if (aba) q.set("aba", aba);
  if (taskId) q.set("tarefa", String(taskId));
  location.hash = `#/equipe?${q}`;
}

// ------------------------------------------------- ações do cabeçalho --

function monthRange() {
  return mes.rangeOf(monthState.month || mes.thisMonth());
}

function csvDialog(a) {
  const [s, e] = monthRange();
  const today = localDay(Date.now());
  const start = h("input", { type: "date", value: s, max: today, required: "required" });
  const end = h("input", { type: "date", value: e, max: today, required: "required" });
  const err = h("p", { class: "error-text", role: "alert" });
  const form = h("form", {},
    h("div", { class: "field-row" }, field("De", start), field("Até", end)),
    h("p", { class: "dialog-note", text: `Horas de quem compartilha o dia a dia${a && a.people.length ? ` (${mes.plural(a.people.length, "pessoa", "pessoas")})` : ""}, com pessoa e projeto: some por cliente na planilha. Até um ano por vez.` }),
    err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Voltar", onClick: () => dlg.close() }),
      h("button", { type: "submit", class: "btn btn-primary" }, icon("download"), "Baixar o CSV")));
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    if (end.value < start.value) { err.textContent = "O fim vem antes do começo."; return; }
    try { await api.download(`/viewer/export/apontamentos.csv?start=${start.value}&end=${end.value}`); dlg.close(); }
    catch (x) { err.textContent = x.message || "Não foi possível exportar."; }
  }));
  const dlg = modal(h("h2", { text: "Horas da equipe (CSV)" }), form);
}

function pdfDialog(a) {
  if (!a || !a.people.length) return;
  const [s, e] = monthRange();
  const today = localDay(Date.now());
  const who = h("select", {}, ...a.people.map((p) => h("option", { value: p.id, text: p.name })));
  const proj = h("select", {}, h("option", { value: "", text: "Todos (o registro da pessoa)" }));
  const start = h("input", { type: "date", value: s, max: today, required: "required" });
  const end = h("input", { type: "date", value: e, max: today, required: "required" });
  const err = h("p", { class: "error-text", role: "alert" });
  let seq = 0;
  const loadProjects = async () => {
    const my = ++seq;
    proj.replaceChildren(h("option", { value: "", text: "Todos (o registro da pessoa)" }));
    try {
      const list = await api.get(`/viewer/users/${who.value}/projects`);
      if (my !== seq) return;
      proj.append(...list.map((p) => h("option", { value: p.id, text: p.archived ? `${p.name} (arquivado)` : p.name })));
    } catch { /* sem a lista, sai o PDF da pessoa */ }
  };
  who.addEventListener("change", loadProjects);
  const form = h("form", {},
    field("Pessoa", who),
    field("Projeto", proj),
    h("div", { class: "field-row" }, field("De", start), field("Até", end)),
    h("p", { class: "dialog-note", text: "O mesmo PDF que a pessoa tira em Meu mês: rotinas, tarefas e horas do período (com um projeto, só o dele)." }),
    err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Voltar", onClick: () => dlg.close() }),
      h("button", { type: "submit", class: "btn btn-primary" }, icon("reports"), "Baixar o PDF")));
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    if (end.value < start.value) { err.textContent = "O fim vem antes do começo."; return; }
    const q = new URLSearchParams({ start: start.value, end: end.value });
    if (proj.value) q.set("project", proj.value);
    try { await api.download(`/viewer/users/${who.value}/reports/export?${q}`); dlg.close(); }
    catch (x) { err.textContent = x.message || "Não foi possível gerar o PDF."; }
  }));
  const dlg = modal(h("h2", { text: "PDF de uma pessoa ou de um projeto" }), form);
  loadProjects();
}

// ------------------------------------------------- o mês de uma pessoa --
// A mesma tela de Meu mês (sem média, sem tendência, sem comparação) e o
// quadro, somente leitura.

const SUBVIEWS = [
  { key: "mes", label: "Mês e PDF" },
  { key: "board", label: "Quadro" },
];

async function personView(root, ctx, uid, tab, taskId) {
  ctx.setActions();
  const users = await api.get("/viewer/users");
  const p = users.find((u) => u.id === uid);
  const back = h("button", { type: "button", class: "btn btn-text eq-back", onClick: () => { location.hash = "#/equipe"; } }, icon("left"), "Equipe");
  clear(root);
  if (!p) {
    ctx.setEyebrow("a equipe no mês");
    root.append(back, h("p", { class: "empty", text: "Essa pessoa não compartilha o dia a dia com quem vê a equipe." }));
    return;
  }
  ctx.setEyebrow(`somente leitura · registro de ${p.name}`);
  let active = tab;
  const subtabs = h("div", { class: "seg seg-sm", role: "tablist", "aria-label": `Registro de ${p.name}` },
    ...SUBVIEWS.map((s) => h("button", {
      type: "button", class: "chip-btn", role: "tab", text: s.label, "data-key": s.key,
      "aria-selected": s.key === active ? "true" : "false",
      onClick: () => {
        if (active === s.key) return;
        active = s.key;
        taskId = null;
        for (const b of subtabs.children) b.setAttribute("aria-selected", b.dataset.key === active ? "true" : "false");
        window.history.replaceState(null, "", `#/equipe?pessoa=${uid}${active === "board" ? "&aba=quadro" : ""}`);
        render();
      },
    })));
  const content = h("div", {});
  root.append(h("div", { class: "eq-person-head" }, back, h("h2", { class: "eq-person-name" }, initial(p), h("span", { text: p.name }))),
    subtabs, content);

  let seq = 0;
  async function render() {
    const my = ++seq;
    const box = h("div", {});
    try {
      if (active === "board") await board.mount(box, { readOnly: true, boardUrl: `/viewer/users/${uid}/board` });
      else await mes.view(box, { state: monthState, who: p.name, dashUrl: `/viewer/users/${uid}/dashboard`,
        exportBase: `/viewer/users/${uid}/reports/export`, projectsUrl: `/viewer/users/${uid}/projects` });
    } catch (e) {
      clear(box);
      box.append(h("p", { class: "empty", text: e && e.status === 404
        ? `${p.name} não compartilha mais o dia a dia com quem vê a equipe.`
        : e && e.status === 0 ? e.message : "Não foi possível carregar. Tente de novo." }));
    }
    if (my !== seq) return;
    clear(content);
    content.append(box);
    // Veio de "Precisa de atenção": a tarefa em destaque no quadro.
    const card = taskId && box.querySelector(`.card[data-id="${taskId}"]`);
    if (card) {
      card.classList.add("eq-focus");
      card.tabIndex = -1;
      requestAnimationFrame(() => { card.scrollIntoView({ block: "center" }); card.focus({ preventScroll: true }); });
    }
  }
  await render();
}
