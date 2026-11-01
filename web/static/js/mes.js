// Meu mês: o mês numa frase com o PDF, um PAINEL (indicadores com os últimos
// 6 meses e a palavra neutra da média da própria pessoa, o calendário do mês,
// o ritmo por semana, o tempo por projeto e as rotinas que pedem atenção) e,
// embaixo, o que foi entregue. Outro período, um projeto e as exportações ficam
// recolhidos em "Outro período ou formato" (reports.js). Os números vêm de
// /dashboard?month= (overview), a mesma conta do PDF do mês. A Equipe usa
// view() com as rotas da pessoa: sem tendência, sem média e sem ranking de
// rotinas (o servidor nem manda). Links antigos: #/mes?aba=pdf, #/relatorios e
// o "Gerar relatório" da sexta (?periodo=semana) abrem a exportação;
// #/dashboard chega aqui pelo app.js.
import { api } from "./api.js";
import { h, icon, clear, addDays, localDay } from "./dom.js";
import { errorToast } from "./ui.js";
import { projectChip, corProjeto, iconeProjeto } from "./projects.js";
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
  // O endereço acompanha a exportação aberta (recarregar volta igual); a semana da sexta vale uma vez.
  window.history.replaceState(null, "", openExport ? "#/mes?aba=pdf" : "#/mes");
  ctx.setActions();
  ctx.setAssist(null); // a frase do topo já é a leitura do mês
  await view(root, { me: ctx.me, state: own, openExport, week,
    onExport: (open) => { if (/^#\/mes\b/.test(location.hash)) window.history.replaceState(null, "", open ? "#/mes?aba=pdf" : "#/mes"); } });
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
    const focused = document.activeElement;
    next.disabled = st.month >= thisMonth();
    prev.disabled = !!st.months && st.months.length > 0 && st.month <= st.months[st.months.length - 1];
    // Chegou à ponta com o foco no botão que desligou: o foco passa para o outro (não cai no topo).
    if (focused === prev && prev.disabled && !next.disabled) next.focus();
    else if (focused === next && next.disabled && !prev.disabled) prev.focus();
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
  exp.addEventListener("toggle", () => {
    if (exp.open) mountExport(false);
    if (opts.onExport) opts.onExport(exp.open);
  });

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
// Ao redor: a frase do mês e o PDF (em cima), o que foi entregue e "Outro
// período ou formato" (embaixo). No meio, o PAINEL: um contêiner próprio numa
// grade de 12 colunas (no celular, uma coluna na mesma ordem):
//   [Rotinas em dia 4][Tarefas concluídas 4][Horas apontadas 4]
//   [Calendário do mês 8                   ][Ritmo do mês 4   ]
//   [Tempo por projeto 8                   ][Rotinas: atenção 4]

function screen(a, opts, reload) {
  const ov = a.overview;
  const m = ov.month, mes = nameOf(a.period.month);
  const empty = !m.recurring_total && !m.pontual_done && !m.minutes;
  const nodes = [hero(ov, mes, opts)];
  // Mês ainda vazio: o painel só aparece se houver meses anteriores para situar (a própria pessoa).
  const history = ov.trend.slice(0, -1).some((t) => t.recurring_total || t.pontual_done || t.minutes);
  if (empty && !history) return nodes;
  nodes.push(panel(ov, a.period.month, mes, !!opts.dashUrl));
  if (!empty) nodes.push(deliveriesCard(ov, mes, opts, reload));
  return nodes;
}

// "Em outubro você fez 50 das 81 rotinas previstas (62%), concluiu 20 tarefas e apontou 31h43."
function sentence(m, mes, who) {
  const quando = `Em ${mes}${m.now ? ", até agora," : ""}`;
  const sujeito = who ? ` ${who}` : " você";
  if (!m.recurring_total && !m.pontual_done && !m.minutes)
    return `${quando} nada registrado${who ? ` por ${who}` : ""}.`;
  // Só o que aconteceu (o zero aparece nos números, sem virar cobrança na frase).
  const partes = [];
  if (m.recurring_total) partes.push(`fez ${m.recurring_done} das ${m.recurring_total} rotinas previstas (${pct(m.recurring_done, m.recurring_total)}%)`);
  if (m.pontual_done) partes.push(`concluiu ${plural(m.pontual_done, "tarefa", "tarefas")}`);
  if (m.minutes) partes.push(`apontou ${duration(m.minutes)}`);
  const lista = partes.length > 1 ? `${partes.slice(0, -1).join(", ")} e ${partes[partes.length - 1]}` : partes[0];
  return `${quando}${sujeito} ${lista}.`;
}

function hero(ov, mes, opts) {
  const m = ov.month;
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
      : h("div", { class: "mes-actions" }, btn));
}

function card(title, sub, ...body) {
  return h("section", { class: "chart-card mes-card" },
    h("h2", { class: "chart-title", text: title }),
    sub ? h("p", { class: "chart-sub", text: sub }) : null,
    ...body);
}

// ---------------------------------------------------------------- o painel --

function tile(span, cls, title, sub, ...body) {
  return h("section", { class: `mm-tile mm-${span} ${cls}` },
    h("h2", { class: "mm-title", text: title }),
    sub ? h("p", { class: "mm-sub", text: sub }) : null,
    ...body);
}

function panel(ov, month, mes, team) {
  // O calendário aparece com rotina no mês; no mês corrente, também se os meses anteriores tinham.
  const hasRoutines = ov.routines > 0 || ov.days.some((d) => d.due || d.extra || d.paused)
    || (ov.month.now && ov.trend.slice(0, -1).some((t) => t.recurring_total));
  const tiles = [...kpis(ov, month, team)];
  if (hasRoutines) tiles.push(calendarTile(ov, month));
  tiles.push(rhythmTile(ov, month), projectsTile(ov, mes, 8));
  if (hasRoutines) tiles.push(attentionTile(ov, mes, team));
  return h("section", { class: "mm-panel", "aria-label": `Painel de ${mes}` }, ...tiles);
}

// --------------------------------------------------------- 1) indicadores --

// A palavra neutra: só situa o mês na média da própria pessoa (sem cor, sem seta).
const WORDS = { "acima": "acima da sua média", "na média": "na sua média", "abaixo": "abaixo da sua média" };

function monthsBack(month, n) { // os n meses que terminam em `month`, do mais antigo ao mais novo
  const out = [month];
  while (out.length < n) out.unshift(prevOf(out[0]));
  return out;
}

function foot(ov, key, avgText) {
  const word = ov.compare && ov.compare[key];
  if (word) return h("p", { class: "mm-foot" }, h("span", { class: "chip mm-word", text: WORDS[word] }), h("span", { class: "mm-avg", text: avgText }));
  if (ov.average && ov.month.now && !ov.average.scale) return h("p", { class: "mm-foot" }, h("span", { class: "mm-avg", text: "cedo para comparar com a sua média" }));
  if (!ov.average && ov.trend.length) return h("p", { class: "mm-foot" }, h("span", { class: "mm-avg", text: "a média aparece com dois meses inteiros de registro" }));
  return null;
}

function kpis(ov, month, team) {
  const m = ov.month, avg = ov.average;
  const slots = monthsBack(month, 6);
  const byMonth = Object.fromEntries(ov.trend.map((t) => [t.month, t]));
  const trend = !team && ov.trend.length > 1;
  const days = ov.days;
  const taskDays = days.filter((d) => d.pontual_done).length;
  const timeDays = days.filter((d) => d.minutes).length;

  // Rotinas em dia: o anel do mês + a linha dos 6 meses.
  const p = m.recurring_total ? pct(m.recurring_done, m.recurring_total) : null;
  const rot = tile(4, "mm-kpi", "Rotinas em dia", null,
    h("div", { class: "mm-kpi-main" }, ring(p),
      h("p", { class: "mm-fact", text: m.recurring_total ? `${m.recurring_done} de ${m.recurring_total} previstas` : "sem rotinas previstas" })),
    trend ? lineChart(slots, byMonth, avg && avg.recurring_pct, month) : null,
    trend ? foot(ov, "routines", avg && avg.recurring_pct != null ? `média: ${Math.round(avg.recurring_pct)}%` : "") : null);

  const tasks = tile(4, "mm-kpi", "Tarefas concluídas", null,
    h("div", { class: "mm-kpi-main" }, h("p", { class: "mm-n", text: String(m.pontual_done) }),
      h("p", { class: "mm-fact", text: m.pontual_done ? `em ${plural(taskDays, "dia", "dias")}` : "nenhuma no mês" })),
    trend ? barChart(slots, byMonth, "pontual_done", avg && avg.pontual_done, month, (v) => String(v), "tarefas") : null,
    trend ? foot(ov, "tasks", avg ? `média: ${fmtAvg(avg.pontual_done)} por mês` : "") : null);

  const hours = tile(4, "mm-kpi", "Horas apontadas", null,
    h("div", { class: "mm-kpi-main" }, h("p", { class: "mm-n", text: m.minutes ? duration(m.minutes) : "—" }),
      h("p", { class: "mm-fact", text: m.minutes ? `em ${plural(timeDays, "dia", "dias")}, ${duration(Math.round(m.minutes / timeDays))} por dia` : "nada apontado" })),
    trend ? barChart(slots, byMonth, "minutes", avg && avg.minutes, month, (v) => duration(v), "horas") : null,
    trend ? foot(ov, "minutes", avg ? `média: ${duration(Math.round(avg.minutes))} por mês` : "") : null);
  return [rot, tasks, hours];
}

const fmtAvg = (n) => (Number.isInteger(n) ? String(n) : n.toFixed(1).replace(".", ","));
const monLabel = (key) => MON[Number(key.slice(5)) - 1];

function ring(p) {
  const r = 30, c = 2 * Math.PI * r;
  const s = svgEl("svg", { viewBox: "0 0 76 76", class: "mm-ring", "aria-hidden": "true" });
  s.append(svgEl("circle", { cx: 38, cy: 38, r, class: "mm-ring-track" }));
  if (p) {
    const v = svgEl("circle", { cx: 38, cy: 38, r, class: "mm-ring-val", transform: "rotate(-90 38 38)" });
    v.setAttribute("stroke-dasharray", `${(c * p) / 100} ${c}`);
    s.append(v);
  }
  const t = svgEl("text", { x: 38, y: 39, class: "mm-ring-n" });
  t.textContent = p === null ? "—" : `${p}%`;
  s.append(t);
  return h("div", { class: "mm-ring-box" }, s);
}

// Geometria comum às duas miniaturas de 6 meses (viewBox 240 × 74).
const MW = 240, TOPY = 14, BASEY = 50, LBLY = 68;
const slotX = (i) => 20 + i * 40; // centro de cada um dos 6 meses

function monthAxis(s, slots, month) {
  slots.forEach((k, i) => {
    const t = svgEl("text", { x: slotX(i), y: LBLY, class: "mm-axis" + (k === month ? " cur" : "") });
    t.textContent = monLabel(k);
    s.append(t);
  });
}

function avgLine(s, y) {
  s.append(svgEl("line", { x1: 2, x2: MW - 2, y1: y, y2: y, class: "mm-avg-line" }));
}

function lineChart(slots, byMonth, avgPct, month) {
  const pts = slots.map((k, i) => {
    const t = byMonth[k];
    return t && t.recurring_total ? { i, k, v: pct(t.recurring_done, t.recurring_total) } : null;
  }).filter(Boolean);
  // Escala de um piso (dezena abaixo do menor valor, com folga) a 100%: a variação aparece sem exagero.
  const lo = Math.max(0, Math.floor((Math.min(...pts.map((q) => q.v), avgPct ?? 100) - 10) / 10) * 10);
  const y = (v) => BASEY - ((BASEY - TOPY) * (v - lo)) / (100 - lo || 1);
  const desc = pts.map((q) => `${MONTHS[Number(q.k.slice(5)) - 1]} ${q.v}%`).join(", ");
  const s = svgEl("svg", { viewBox: `0 0 ${MW} 74`, class: "mm-spark", role: "img",
    "aria-label": `Rotinas em dia nos últimos meses: ${desc || "sem rotinas"}${avgPct != null ? `; sua média ${Math.round(avgPct)}%` : ""}.` });
  s.append(svgEl("line", { x1: 2, x2: MW - 2, y1: BASEY, y2: BASEY, class: "mm-base" }));
  if (avgPct != null) avgLine(s, y(avgPct));
  // A linha só liga meses vizinhos (mês sem rotina = interrupção).
  let run = [];
  const flush = () => { if (run.length > 1) s.append(svgEl("polyline", { points: run.map((q) => `${slotX(q.i)},${y(q.v)}`).join(" "), class: "mm-line" })); run = []; };
  pts.forEach((q, j) => { if (j && q.i !== pts[j - 1].i + 1) flush(); run.push(q); });
  flush();
  for (const q of pts) {
    const cur = q.k === month;
    const dot = svgEl("circle", { cx: slotX(q.i), cy: y(q.v), r: cur ? 4.5 : 3, class: "mm-dot" + (cur ? " cur" : "") });
    const ti = svgEl("title", {});
    ti.textContent = `${MONTHS[Number(q.k.slice(5)) - 1]}: ${q.v}%`;
    dot.append(ti);
    s.append(dot);
  }
  monthAxis(s, slots, month);
  return s;
}

function barChart(slots, byMonth, key, avg, month, fmt, what) {
  const vals = slots.map((k) => (byMonth[k] ? byMonth[k][key] : null));
  const top = Math.max(1, avg || 0, ...vals.filter((v) => v != null));
  const y = (v) => BASEY - ((BASEY - TOPY) * v) / top;
  const desc = slots.map((k, i) => (vals[i] == null ? null : `${MONTHS[Number(k.slice(5)) - 1]} ${fmt(vals[i])}`)).filter(Boolean).join(", ");
  const s = svgEl("svg", { viewBox: `0 0 ${MW} 74`, class: "mm-spark", role: "img",
    "aria-label": `${what[0].toUpperCase() + what.slice(1)} nos últimos meses: ${desc}${avg ? `; sua média ${fmt(key === "minutes" ? Math.round(avg) : fmtAvg(avg))}` : ""}.` });
  s.append(svgEl("line", { x1: 2, x2: MW - 2, y1: BASEY, y2: BASEY, class: "mm-base" }));
  slots.forEach((k, i) => {
    const v = vals[i];
    if (v == null || !v) return;
    const cur = k === month;
    const top_ = y(v);
    const r = svgEl("rect", { x: slotX(i) - 11, y: top_, width: 22, height: Math.max(2, BASEY - top_), rx: 3, class: "mm-bar" + (cur ? " cur" : "") });
    const ti = svgEl("title", {});
    ti.textContent = `${MONTHS[Number(k.slice(5)) - 1]}: ${fmt(v)}${byMonth[k].now ? " (até hoje)" : ""}`;
    r.append(ti);
    s.append(r);
    if (cur) {
      const t = svgEl("text", { x: slotX(i), y: top_ - 4, class: "mm-val" });
      t.textContent = fmt(v);
      s.append(t);
    }
  });
  if (avg) avgLine(s, y(avg));
  monthAxis(s, slots, month);
  return s;
}

// --------------------------------------------------- 2) calendário do mês --

const WEEKDAYS = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const WEEKDAYS_FULL = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"];

// Degrau de cada dia: 0 (nada feito), 1–33%, 34–66%, 67–99%, 100% das rotinas previstas.
function level(d) {
  if (d.done >= d.due) return 4;
  if (!d.done) return 0;
  const f = Math.floor((100 * d.done) / d.due);
  return f <= 33 ? 1 : f <= 66 ? 2 : 3;
}

function dayInfo(d, iso, mes, today) {
  const n = Number(iso.slice(8));
  const when = `${n} de ${mes}`;
  if (!d) return { cls: "fut", label: `${when}: ainda não chegou` };
  const extra = d.extra ? `, mais ${plural(d.extra, "extra", "extras")}` : "";
  if (d.due) return { cls: "l" + level(d), label: `${when}: ${d.done} de ${plural(d.due, "rotina", "rotinas")}${extra}` };
  if (d.extra) return { cls: "extra", label: `${when}: nenhuma prevista, ${plural(d.extra, "extra feita", "extras feitas")}` };
  if (d.paused) return { cls: "paused", label: `${when}: rotinas pausadas` };
  if (iso === today) return { cls: "none", label: `${when}: hoje, nada marcado ainda` };
  return { cls: "none", label: `${when}: sem rotina prevista` };
}

function calendarTile(ov, month) {
  const mes = nameOf(month);
  const today = localDay(Date.now());
  const byDate = Object.fromEntries(ov.days.map((d) => [d.date, d]));
  const first = month + "-01";
  const size = Number(addDays(nextOf(month) + "-01", -1).slice(8));
  const lead = new Date(first + "T12:00:00Z").getUTCDay();
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push(null);
  for (let n = 1; n <= size; n++) cells.push(`${month}-${String(n).padStart(2, "0")}`);
  while (cells.length % 7) cells.push(null);

  const head = h("tr", {}, ...WEEKDAYS.map((w, i) => h("th", { scope: "col", abbr: WEEKDAYS_FULL[i], text: w })));
  const rows = [];
  for (let r = 0; r < cells.length; r += 7) {
    rows.push(h("tr", {}, ...cells.slice(r, r + 7).map((iso) => {
      if (!iso) return h("td", { class: "out" });
      const info = dayInfo(byDate[iso], iso, mes, today);
      return h("td", { class: `${info.cls}${iso === today ? " today" : ""}`, title: info.label },
        h("span", { class: "mm-dn", "aria-hidden": "true", text: String(Number(iso.slice(8))) }),
        h("span", { class: "sr-only", text: info.label }));
    })));
  }
  // O resumo do mês em texto (para todo mundo, e é o que o leitor ouve primeiro).
  const due = ov.days.filter((d) => d.due);
  const all = due.filter((d) => d.done >= d.due).length, none = due.filter((d) => !d.done).length;
  const partes = [];
  if (all) partes.push(`${all} com todas feitas`);
  if (due.length - all - none) partes.push(`${due.length - all - none} com parte feita`);
  if (none) partes.push(`${none} sem nenhuma marcada`);
  const extras = ov.days.filter((d) => !d.due && d.extra).length;
  const resumo = due.length
    ? `${plural(due.length, "dia com rotina prevista", "dias com rotina prevista")}: ${partes.join(", ")}${extras ? `; ${plural(extras, "dia", "dias")} só com extras` : ""}.`
    : `Nenhum dia com rotina prevista${extras ? `; ${plural(extras, "dia", "dias")} só com extras` : ""}.`;
  const sub = h("p", { class: "mm-sub", id: `mm-cal-${month}`, text: resumo });
  const table = h("table", { class: "mm-cal", "aria-describedby": sub.id },
    h("caption", { class: "sr-only", text: `Rotinas dia a dia em ${mes}` }), h("thead", {}, head), h("tbody", {}, ...rows));

  const sw = (cls, text) => h("span", { class: `mm-sw ${cls}`, title: text });
  const legend = h("div", { class: "mm-legend", "aria-hidden": "true" },
    h("span", { class: "mm-leg-scale" }, h("span", { text: "menos" }), sw("l0", "nenhuma feita"), sw("l1", "até um terço"),
      sw("l2", "até dois terços"), sw("l3", "quase todas"), sw("l4", "todas"), h("span", { text: "mais" })),
    h("span", { class: "mm-leg-item" }, sw("extra", "só extras"), h("span", { text: "só extras" })),
    h("span", { class: "mm-leg-item" }, sw("none", "sem rotina prevista"), h("span", { text: "sem previsão" })));
  return tile(8, "mm-cal-tile", "Rotinas no mês, dia a dia", null, sub, table, legend);
}

// ------------------------------------------------------ 3) ritmo do mês --

// As semanas do mês inteiro (domingo a sábado, cortadas no mês): as que ainda
// não chegaram ficam com o lugar marcado, para o gráfico não mudar de forma.
function monthWeeks(month) {
  const size = Number(addDays(nextOf(month) + "-01", -1).slice(8));
  const out = [];
  for (let n = 1; n <= size; n++) {
    const iso = `${month}-${String(n).padStart(2, "0")}`;
    if (n === 1 || new Date(iso + "T12:00:00Z").getUTCDay() === 0) out.push({ start: iso, end: iso });
    else out[out.length - 1].end = iso;
  }
  return out;
}

function weekBars(weeks, key, fmt, title, mes) {
  const W = 300, base = 92, topY = 18, slot = W / weeks.length;
  const vals = weeks.map((w) => (w.data ? w.data[key] : null));
  const top = Math.max(1, ...vals.filter((v) => v != null));
  const desc = weeks.map((w, i) => `${w.label}: ${vals[i] == null ? "ainda não chegou" : fmt(vals[i])}`).join("; ");
  const s = svgEl("svg", { viewBox: `0 0 ${W} 114`, class: "mm-weeks", role: "img", "aria-label": `${title} por semana em ${mes}: ${desc}.` });
  s.append(svgEl("line", { x1: 2, x2: W - 2, y1: base, y2: base, class: "mm-base" }));
  weeks.forEach((w, i) => {
    const cx = slot * i + slot / 2, v = vals[i];
    if (v) {
      const y = base - ((base - topY) * v) / top;
      const r = svgEl("rect", { x: cx - 13, y, width: 26, height: Math.max(2, base - y), rx: 3, class: "mm-bar cur" });
      const ti = svgEl("title", {});
      ti.textContent = `${w.label}: ${fmt(v)}`;
      r.append(ti);
      s.append(r);
    }
    if (v != null) {
      const t = svgEl("text", { x: cx, y: (v ? base - ((base - topY) * v) / top : base) - 5, class: "mm-val" });
      t.textContent = fmt(v);
      s.append(t);
    }
    const l = svgEl("text", { x: cx, y: 110, class: "mm-axis" });
    l.textContent = w.label;
    s.append(l);
  });
  return h("div", { class: "mm-week-chart" }, h("p", { class: "mm-chart-t", text: title }), s);
}

function rhythmTile(ov, month) {
  const mes = nameOf(month);
  const got = Object.fromEntries(ov.weeks.map((w) => [w.start, w]));
  const weeks = monthWeeks(month).map((w) => ({ ...w, data: got[w.start] || null,
    label: `${Number(w.start.slice(8))}–${Number(w.end.slice(8))}` }));
  return tile(4, "mm-rhythm", "Ritmo do mês", "por semana, de domingo a sábado",
    weekBars(weeks, "pontual_done", (v) => String(v), "Tarefas concluídas", mes),
    weekBars(weeks, "minutes", (v) => (v ? duration(v) : "0"), "Horas apontadas", mes));
}

// -------------------------------------------------- 4) tempo por projeto --

const DONUT_MAX = 6; // fatias; o resto vira "outros"

function projectsTile(ov, mes, span) {
  if (!ov.projects.length) return tile(span, "mm-proj", "Tempo por projeto", null, h("p", { class: "mes-ok", text: `Nada apontado em ${mes}.` }));
  let items = ov.projects.map((p) => ({ name: p.name || "Sem projeto", color: p.color, icon: p.name ? p.icon : null, minutes: p.minutes }));
  if (items.length > DONUT_MAX) {
    const rest = items.slice(DONUT_MAX - 1);
    items = [...items.slice(0, DONUT_MAX - 1), { name: `outros ${rest.length}`, color: null, minutes: rest.reduce((a, p) => a + p.minutes, 0) }];
  }
  const sum = items.reduce((a, p) => a + p.minutes, 0);
  const r = 46, c = 2 * Math.PI * r, gap = items.length > 1 ? 2 : 0;
  const s = svgEl("svg", { viewBox: "0 0 120 120", class: "mm-donut", "aria-hidden": "true" });
  s.append(svgEl("circle", { cx: 60, cy: 60, r, class: "mm-donut-track" }));
  let at = 0;
  for (const p of items) {
    const len = (c * p.minutes) / sum;
    const seg = svgEl("circle", { cx: 60, cy: 60, r, class: "mm-seg", transform: "rotate(-90 60 60)" });
    seg.setAttribute("stroke-dasharray", `${Math.max(0.5, len - gap)} ${c}`);
    seg.setAttribute("stroke-dashoffset", String(-at));
    seg.style.stroke = corProjeto(p.color);
    s.append(seg);
    at += len;
  }
  const n = svgEl("text", { x: 60, y: 57, class: "mm-donut-n" });
  n.textContent = duration(ov.month.minutes);
  const l = svgEl("text", { x: 60, y: 75, class: "mm-donut-l" });
  l.textContent = "no mês";
  s.append(n, l);
  const legend = h("ul", { class: "mm-proj-list" }, ...items.map((p) => {
    // Projeto: o ícone dele na cor da fatia; "Sem projeto" e "outros", a bolinha.
    const dot = p.icon ? iconeProjeto(p.icon) : h("span", { class: "mm-proj-dot", "aria-hidden": "true" });
    if (p.icon) { dot.classList.add("mm-proj-ico"); dot.style.color = corProjeto(p.color); }
    else dot.style.background = corProjeto(p.color);
    return h("li", {}, dot, h("span", { class: "mm-proj-name", text: p.name }),
      h("span", { class: "mm-proj-h", text: duration(p.minutes) }),
      h("span", { class: "mm-proj-p", text: `${Math.round((100 * p.minutes) / sum)}%` }));
  }));
  return tile(span, "mm-proj", "Tempo por projeto",
    ov.multi_project ? "tarefa em mais de um projeto conta em cada um" : null,
    h("div", { class: "mm-proj-body" }, h("div", { class: "mm-donut-box" }, s), legend));
}

// ------------------------------------------ 5) rotinas que pedem atenção --
// Na Equipe, só o resumo (sem ranking das rotinas de outra pessoa).

function attentionTile(ov, mes, team) {
  const full = ov.routines_full ?? ov.routines - ov.behind.length;
  const title = team ? "Rotinas do mês" : "Rotinas que pedem atenção";
  if (!ov.routines) return tile(4, "mm-att", title, null, h("p", { class: "mes-ok",
    text: ov.month.now ? "Nenhum dia de rotina previsto até agora." : `Nenhuma rotina na agenda em ${mes}.` }));
  if (full >= ov.routines) return tile(4, "mm-att", title, null, h("p", { class: "mes-ok" }, icon("check"),
    h("span", { text: ov.routines === 1 ? "A rotina foi feita em todos os dias previstos." : `As ${ov.routines} rotinas foram feitas em todos os dias previstos.` })));
  if (team || !ov.behind.length) {
    const fill = h("span");
    fill.style.width = pct(full, ov.routines) + "%";
    return tile(4, "mm-att", title, null, h("p", { class: "mes-ok",
      text: `${full} de ${plural(ov.routines, "rotina", "rotinas")} ${full === 1 ? "feita" : "feitas"} em todos os dias previstos.` }),
    h("span", { class: "mes-track mm-meter", "aria-hidden": "true" }, fill));
  }
  return tile(4, "mm-att", title, "dias feitos de previstos", h("div", { class: "mes-rows" }, ...ov.behind.map((r) => {
    const fill = h("span");
    fill.style.width = pct(r.done, r.due) + "%";
    return h("div", { class: "mes-rot", title: `${r.label}: feita em ${r.done} de ${r.due} dias previstos` },
      h("span", { class: "mes-rot-l", text: r.label }),
      h("span", { class: "mes-track" }, fill),
      h("span", { class: "mes-rot-n", text: `${r.done} de ${r.due}` }));
  })), full ? h("p", { class: "mes-res", text: `${full === 1 ? "A outra foi feita" : `As outras ${full} foram feitas`} em todos os dias previstos.` }) : null);
}

// ------------------------------------------- o que foi entregue (fora) --

function deliveriesCard(ov, mes, opts, reload) {
  const all = ov.deliveries, total = ov.month.pontual_done;
  if (!all.length) return card("O que foi entregue", null, h("p", { class: "mes-ok", text: `Nenhuma tarefa concluída em ${mes}.` }));
  // Título; embaixo, projeto e tempo; e o "como resolveu" curto, quando houver.
  const row = (d) => {
    const chip = projectChip({ project_name: d.project, project_color: d.project_color, project_icon: d.project_icon });
    const meta = chip || d.minutes ? h("div", { class: "mes-del-meta" }, chip,
      d.minutes ? h("span", { class: "tag" }, icon("clock"), duration(d.minutes)) : null) : null;
    return h("li", { class: "mes-del" },
      opts.dashUrl ? h("span", { class: "mes-del-t", text: d.title })
        : h("button", { type: "button", class: "card-open mes-del-t", text: d.title, onClick: () => openTask(d.id, () => reload().catch(() => {})) }),
      meta,
      d.resolution ? h("p", { class: "mes-res", text: d.resolution }) : null);
  };
  const list = h("ul", { class: "mes-dels" }, ...all.slice(0, TOP).map(row));
  const sub = total > TOP ? `as ${TOP} com mais tempo, de ${total}` : null;
  let more = null;
  if (all.length > TOP) {
    more = h("button", { type: "button", class: "btn btn-text mes-all", text: `ver todas as ${total}`, onClick: () => {
      list.append(...all.slice(TOP).map(row));
      if (total > all.length) list.append(h("li", { class: "mes-res", text: `e mais ${total - all.length} com menos tempo (todas estão no PDF)` }));
      // O foco segue para o primeiro item novo (o botão some; sem isso, cairia no topo).
      const first = list.children[TOP];
      const target = first.querySelector("button") || first;
      if (target === first) first.tabIndex = -1;
      target.focus();
      more.remove();
    } });
  }
  return card("O que foi entregue", sub, list, more);
}

// ------------------------------------------------------------------ SVG --

const NS = "http://www.w3.org/2000/svg";
const MON = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

function svgEl(tag, attrs) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}
