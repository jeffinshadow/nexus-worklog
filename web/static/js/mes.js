// Meu mês: o mês numa frase e três números (com o mês anterior ao lado, neutro),
// as rotinas que mais ficaram para trás, para onde foi o tempo e o que foi
// entregue. O PDF do mês é a ação principal; outro período, um projeto e as
// exportações ficam recolhidos em "Outro período ou formato" (reports.js).
// Os números vêm de /dashboard?month= (overview), os mesmos do PDF do mês.
// A Equipe usa view() com as rotas da pessoa. Links antigos: #/mes?aba=pdf,
// #/relatorios e o "Gerar relatório" da sexta (?periodo=semana) abrem a
// exportação; #/dashboard chega aqui pelo app.js.
import { api } from "./api.js";
import { h, icon, clear, addDays, localDay, shortDate } from "./dom.js";
import { errorToast } from "./ui.js";
import { projectBars } from "./summary.js";
import { projectChip } from "./projects.js";
import { duration, openTask } from "./task.js";
import * as reports from "./reports.js";

const MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const TOP = 5; // entregas visíveis antes de "ver todas"

// O mês da própria pessoa fica enquanto o app estiver aberto (voltar à tela mostra o mesmo).
const own = { month: null, months: null };

const thisMonth = () => localDay(Date.now()).slice(0, 7);
const nameOf = (m) => MONTHS[Number(m.slice(5)) - 1];
const prevOf = (m) => { const [y, n] = m.split("-").map(Number); return n === 1 ? `${y - 1}-12` : `${y}-${String(n - 1).padStart(2, "0")}`; };
const nextOf = (m) => { const [y, n] = m.split("-").map(Number); return n === 12 ? `${y + 1}-01` : `${y}-${String(n + 1).padStart(2, "0")}`; };
const pct = (done, total) => Math.round((100 * done) / total);
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
// Do dia 1 ao último dia do mês (o corrente, até hoje).
function rangeOf(m) {
  const today = localDay(Date.now());
  return [m + "-01", m === today.slice(0, 7) ? today : addDays(nextOf(m) + "-01", -1)];
}

export async function mount(root, ctx) {
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  const week = q.get("periodo") === "semana";
  const openExport = week || q.get("aba") === "pdf";
  if (location.hash.includes("?")) window.history.replaceState(null, "", "#/mes");
  ctx.setActions();
  ctx.setAssist(null); // a frase do topo já é a leitura do mês
  await view(root, { me: ctx.me, state: own, openExport, week });
}

// opts: state {month, months} (fica entre visitas), me; na Equipe, dashUrl,
// exportBase, projectsUrl e who (o nome da pessoa, para a frase).
export async function view(root, opts) {
  const st = opts.state;
  const team = !!opts.dashUrl;
  if (!st.month || st.month > thisMonth()) st.month = thisMonth(); // virou o mês com o app aberto

  const label = h("span", { class: "day-nav-label", "aria-live": "polite" });
  const prev = h("button", { type: "button", class: "icon", title: "Mês anterior", "aria-label": "Mês anterior", onClick: () => pick(prevOf(st.month)) }, icon("left"));
  const next = h("button", { type: "button", class: "icon", title: "Próximo mês", "aria-label": "Próximo mês", onClick: () => pick(nextOf(st.month)) }, icon("right"));
  const paintNav = () => {
    label.textContent = nameOf(st.month) + " de " + st.month.slice(0, 4) + (st.month === thisMonth() ? " · até hoje" : "");
    next.disabled = st.month >= thisMonth();
    prev.disabled = !!st.months && st.months.length > 0 && st.month <= st.months[st.months.length - 1];
  };
  const content = h("div", { class: "mes-content" });

  // Outro período ou formato: recolhido; o formulário só carrega ao abrir.
  const expBody = h("div", { class: "mes-export-body" });
  const exp = h("details", { class: "mes-export" },
    h("summary", {}, icon("download"), h("span", { text: "Outro período ou formato" }),
      h("small", { text: team ? "outras datas ou um projeto" : "outras datas, um projeto, CSV, cópia completa, fotos" })),
    expBody);
  let ctl = null, mounting = null;
  const mountExport = (week) => mounting || (mounting = (async () => {
    const [start, end] = rangeOf(st.month);
    try {
      ctl = await reports.mount(expBody, { me: opts.me, range: { start, end }, week,
        ...(team ? { exportBase: opts.exportBase, projectsUrl: opts.projectsUrl } : {}) });
    } catch (e) { mounting = null; errorToast(e); }
  })());
  exp.addEventListener("toggle", () => { if (exp.open) mountExport(false); });

  let seq = 0;
  async function load() {
    const my = ++seq;
    content.classList.add("refreshing");
    const base = opts.dashUrl || "/dashboard";
    try {
      const a = (await api.get(`${base}?month=${st.month}`)) || {};
      if (my !== seq) return;
      st.months = a.months || [];
      paintNav();
      clear(content);
      content.append(...screen(a, opts, load));
    } finally {
      if (my === seq) content.classList.remove("refreshing");
    }
  }
  async function pick(m) {
    st.month = m;
    paintNav();
    if (ctl) { const [start, end] = rangeOf(m); ctl.setRange(start, end); }
    try { await load(); } catch (e) { errorToast(e); }
  }

  paintNav();
  await load();
  if (opts.openExport) { exp.open = true; await mountExport(opts.week); }
  clear(root);
  root.append(h("div", { class: "day-nav dash-period mes-nav" }, prev, label, next), content, exp);
  if (opts.openExport) requestAnimationFrame(() => exp.scrollIntoView({ block: "start" }));
}

// ------------------------------------------------------------------ a tela --

function screen(a, opts, reload) {
  const ov = a.overview;
  const m = ov.month, mes = nameOf(a.period.month);
  const empty = !m.recurring_total && !m.pontual_done && !m.minutes;
  const nodes = [hero(ov, mes, opts)];
  if (empty) return nodes;
  nodes.push(h("div", { class: "mes-grid" }, routinesCard(ov, a.heatmap, mes), timeCard(ov, mes)),
    deliveriesCard(ov, mes, opts, reload));
  return nodes;
}

// "Em outubro você fez 50 das 81 rotinas previstas (62%), concluiu 20 tarefas e apontou 31h43."
function sentence(m, mes, who) {
  const quando = `Em ${mes}${m.now ? ", até agora," : ""}`;
  const sujeito = who ? ` ${who}` : " você";
  if (!m.recurring_total && !m.pontual_done && !m.minutes)
    return `${quando} nada registrado${who ? ` por ${who}` : ""}.`;
  const partes = [];
  if (m.recurring_total) partes.push(`fez ${m.recurring_done} das ${m.recurring_total} rotinas previstas (${pct(m.recurring_done, m.recurring_total)}%)`);
  partes.push(m.pontual_done ? `concluiu ${plural(m.pontual_done, "tarefa", "tarefas")}` : "não concluiu tarefas");
  partes.push(m.minutes ? `apontou ${duration(m.minutes)}` : "não apontou tempo");
  return `${quando}${sujeito} ${partes.slice(0, -1).join(", ")} e ${partes[partes.length - 1]}.`;
}

// "em setembro: 62%, 17 tarefas, 28h10" — sem setas nem cor: só para situar.
function previousLine(p) {
  if (!p) return null;
  const partes = [];
  if (p.recurring_total) partes.push(`${pct(p.recurring_done, p.recurring_total)}% das rotinas`);
  partes.push(plural(p.pontual_done, "tarefa", "tarefas"));
  partes.push(p.minutes ? duration(p.minutes) : "sem tempo apontado");
  return h("p", { class: "mes-prev", text: `em ${nameOf(p.month)}: ${partes.join(", ")}` });
}

function hero(ov, mes, opts) {
  const m = ov.month;
  const fig = (value, lbl) => h("div", { class: "fig" }, h("p", { class: "fig-n", text: value }), h("p", { class: "fig-l", text: lbl }));
  const empty = !m.recurring_total && !m.pontual_done && !m.minutes;
  const base = opts.exportBase || "/reports/export";
  const btn = h("button", { type: "button", class: "btn btn-primary", onClick: async () => {
    btn.disabled = true;
    try { await api.download(`${base}?start=${m.start}&end=${m.end}`); }
    catch (e) { errorToast(e, "Não foi possível gerar o PDF."); } finally { btn.disabled = false; }
  } }, icon("reports"), `Baixar o PDF de ${mes}`);
  return h("section", { class: "mes-hero" },
    h("p", { class: "mes-sentence", text: sentence(m, mes, opts.who) }),
    empty ? (opts.dashUrl ? null : h("p", { class: "mes-prev", text: "O que você registrar no Hoje (rotinas, tarefas e tempo) aparece aqui." }))
      : h("div", { class: "figs" },
        fig(m.recurring_total ? `${pct(m.recurring_done, m.recurring_total)}%` : "—", m.recurring_total ? `rotinas · ${m.recurring_done} de ${m.recurring_total}` : "sem rotinas previstas"),
        fig(String(m.pontual_done), m.pontual_done === 1 ? "tarefa concluída" : "tarefas concluídas"),
        fig(m.minutes ? duration(m.minutes) : "—", "tempo apontado")),
    previousLine(ov.previous),
    empty ? null : h("div", { class: "mes-actions" }, btn));
}

function card(title, sub, ...body) {
  return h("section", { class: "chart-card mes-card" },
    h("h2", { class: "chart-title", text: title }),
    sub ? h("p", { class: "chart-sub", text: sub }) : null,
    ...body);
}

// a) Rotinas: as que mais ficaram para trás (dias feitos de previstos); o
// calendário dia a dia fica recolhido.
function routinesCard(ov, hm, mes) {
  let body;
  if (!ov.routines) body = h("p", { class: "mes-ok", text: `Nenhuma rotina na agenda em ${mes}.` });
  else if (!ov.behind.length) body = h("p", { class: "mes-ok" }, icon("check"),
    h("span", { text: ov.routines === 1 ? "A rotina foi feita em todos os dias previstos." : `As ${ov.routines} rotinas foram feitas em todos os dias previstos.` }));
  else body = h("div", { class: "mes-rows" }, ...ov.behind.map((r) => {
    const fill = h("span");
    fill.style.width = pct(r.done, r.due) + "%";
    return h("div", { class: "mes-rot", title: `${r.label}: feita em ${r.done} de ${r.due} dias previstos` },
      h("span", { class: "mes-rot-l", text: r.label }),
      h("span", { class: "mes-track" }, fill),
      h("span", { class: "mes-rot-n", text: `${r.done} de ${r.due} dias` }));
  }));
  const days = h("div", { class: "mes-days" });
  const det = h("details", { class: "mes-more" }, h("summary", { text: "ver dia a dia" }), days);
  det.addEventListener("toggle", () => { if (det.open && !days.firstChild) days.append(heatmap(hm)); });
  return card("Rotinas", ov.behind.length ? "as que mais ficaram para trás" : null, body, ov.routines ? det : null);
}

// b) Para onde foi o tempo.
function timeCard(ov, mes) {
  if (!ov.projects.length) return card("Para onde foi o tempo", null, h("p", { class: "mes-ok", text: `Nada apontado em ${mes}.` }));
  return card("Para onde foi o tempo", ov.multi_project ? "tarefa em mais de um projeto conta em cada um" : null,
    h("div", { class: "mes-bars" }, ...projectBars(ov.projects)));
}

// c) O que foi entregue: as de mais tempo primeiro; "ver todas" abre o resto.
function deliveriesCard(ov, mes, opts, reload) {
  const all = ov.deliveries, total = ov.month.pontual_done;
  if (!all.length) return card("O que foi entregue", null, h("p", { class: "mes-ok", text: `Nenhuma tarefa concluída em ${mes}.` }));
  const row = (d) => h("li", { class: "mes-del" },
    h("div", { class: "mes-del-top" },
      opts.dashUrl ? h("span", { class: "mes-del-t", text: d.title })
        : h("button", { type: "button", class: "card-open mes-del-t", text: d.title, onClick: () => openTask(d.id, () => reload().catch(() => {})) }),
      projectChip({ project_name: d.project, project_color: d.project_color }),
      d.minutes ? h("span", { class: "tag" }, icon("clock"), duration(d.minutes)) : null),
    d.resolution ? h("p", { class: "mes-res", text: d.resolution }) : null);
  const list = h("ul", { class: "mes-dels" }, ...all.slice(0, TOP).map(row));
  const sub = total > TOP ? `as ${TOP} com mais tempo, de ${total}` : null;
  let more = null;
  if (all.length > TOP) {
    more = h("button", { type: "button", class: "btn btn-text mes-all", "aria-expanded": "false", text: `ver todas as ${total}`, onClick: () => {
      list.append(...all.slice(TOP).map(row));
      if (total > all.length) list.append(h("li", { class: "mes-res", text: `e mais ${total - all.length} com menos tempo (todas estão no PDF)` }));
      more.remove();
    } });
  }
  return card("O que foi entregue", sub, list, more);
}

// --------------------------------------------- calendário (ver dia a dia) --

const NS = "http://www.w3.org/2000/svg";
const MON = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const WEEKDAYS = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];

function svgEl(tag, attrs) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

function heatmap(hm) {
  const box = (msg) => h("p", { class: "chart-empty", text: msg });
  if (!hm || !hm.days || hm.days.every((d) => d.slots === 0)) return box("nenhuma rotina na agenda neste mês");
  const inMonth = hm.days.filter((d) => !d.out).length;
  if (inMonth < 7) return box(inMonth === 1 ? "o mês começou hoje: o calendário aparece a partir da primeira semana"
    : `só ${inMonth} dias do mês até agora: o calendário aparece a partir da primeira semana`);
  const days = hm.days; // semanas inteiras, começando num domingo
  const lead = Math.max(0, days.findIndex((d) => !d.out));
  const cols = Math.ceil(days.length / 7);
  const cell = 24, gap = 3, step = cell + gap, padL = 34, padT = 21;
  const w = padL + cols * step + 2, height = padT + 7 * step + 2;
  const s = svgEl("svg", { viewBox: `0 0 ${w} ${height}`, class: "chart-svg heatmap", width: w, height, role: "img",
    "aria-label": "Calendário das rotinas feitas em cada dia" });
  let prevMonth = -1;
  for (let col = 0; col < cols; col++) {
    const dt = new Date(days[Math.min(days.length - 1, col * 7 + (col ? 0 : lead))].date + "T00:00:00");
    if (dt.getMonth() !== prevMonth) {
      const t = svgEl("text", { x: padL + col * step, y: padT - 6, class: "heat-axis" });
      t.textContent = MON[dt.getMonth()];
      s.appendChild(t);
      prevMonth = dt.getMonth();
    }
  }
  for (const row of [1, 3, 5]) {
    const t = svgEl("text", { x: 0, y: padT + row * step + cell - 6, class: "heat-axis" });
    t.textContent = WEEKDAYS[row];
    s.appendChild(t);
  }
  days.forEach((d, i) => {
    if (d.out) return;
    const r = svgEl("rect", { x: padL + Math.floor(i / 7) * step, y: padT + (i % 7) * step, width: cell, height: cell, rx: 2 });
    if (d.slots === 0) { r.style.fill = "none"; r.style.stroke = "var(--outline-variant)"; }
    else if (d.done === 0) r.style.fill = "var(--surface-container-high)";
    else {
      const f = Math.min(1, d.done / d.slots);
      r.style.fill = "var(--primary)";
      if (f < 1) r.style.opacity = f >= 0.67 ? 0.75 : f >= 0.34 ? 0.5 : 0.28;
    }
    const title = svgEl("title", {});
    title.textContent = d.slots === 0 ? `${shortDate(d.date)}: sem rotina prevista` : `${shortDate(d.date)}: ${d.done} de ${d.slots} feitas`;
    r.appendChild(title);
    s.appendChild(r);
  });
  const legend = h("div", { class: "heat-legend" }, h("span", { text: "menos" }));
  for (const op of [null, 0.28, 0.5, 0.75, 1]) {
    const sw = h("span", { class: "heat-cell" });
    sw.style.background = op === null ? "var(--surface-container-high)" : "var(--primary)";
    if (op !== null) sw.style.opacity = op;
    legend.append(sw);
  }
  legend.append(h("span", { text: "mais" }));
  return h("div", {}, s, legend);
}
