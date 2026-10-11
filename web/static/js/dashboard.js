import { api } from "./api.js";
import { h, clear, formatDate } from "./dom.js";

const NS = "http://www.w3.org/2000/svg";
const KPI_LABELS = ["Dia", "Semana", "Mês"];
const KPI_KEYS = ["day", "week", "month"];
const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const WEEKDAYS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];

// Todas as agregações vêm do backend (/dashboard): as pizzas (visão geral) e o
// bloco `analytics` (séries e recortes). O frontend só desenha — SVG na mão,
// sem libs, coerente com a CSP rígida.
export async function mount(root, opts = {}) {
  const dashUrl = opts.dashUrl || "/dashboard";
  const data = await api.get(dashUrl);
  const a = data.analytics || {};

  clear(root);
  root.append(
    section("Visão geral", [
      h("div", { class: "overview-grid" },
        kpiGroup("Tarefas recorrentes", data.recurring, true),
        kpiGroup("Pontuais concluídas", data.pontual, false),
      ),
    ]),
    section("Recorrentes · consistência", [
      h("div", { class: "consist-grid" },
        chartCard("Aderência diária", "Últimas 4 semanas — % concluído por dia útil.", heatmap(a.heatmap), "compact heat"),
        chartCard("Tendência semanal", "Últimas 8 semanas — % de aderência.", weeklyTrend(a.heatmap), "compact trend"),
        chartCard("Aderência por tarefa", "Últimos 30 dias — dias úteis concluídos ÷ dias úteis vigentes.", taskRanking(a.task_adherence), "grow"),
      ),
    ]),
    section("Pontuais · fluxo", [
      h("div", { class: "chart-grid fluxo-grid" },
        chartCard("Concluídas por semana", "Vazão das últimas 4 semanas.", throughput(a.throughput)),
        chartCard("Tempo de conclusão", "Da criação até concluída (últimos 90 dias).", cycleTime(a.cycle_time)),
        chartCard("Por dia da semana", "Conclusões (recorrentes + pontuais) nas últimas 8 semanas.", weekdayChart(a.weekday)),
      ),
    ]),
    section("Backlog · saúde", [
      backlogHealth(a.backlog),
    ])
  );
}

// ---------------------------------------------------------------- estrutura --

function section(title, children) {
  return h("section", { class: "dash-section" },
    h("h2", { class: "dash-section-title", text: title }),
    ...children);
}

function grid(cards) {
  return h("div", { class: "chart-grid" }, ...cards);
}

function chartCard(title, sub, body, extra) {
  return h("div", { class: "chart-card" + (extra ? " " + extra : "") },
    h("h3", { class: "chart-title", text: title }),
    sub ? h("p", { class: "chart-sub", text: sub }) : null,
    body);
}

function emptyBox(msg) {
  return h("div", { class: "chart-empty", text: msg });
}

// ------------------------------------------------------------- helpers SVG --

function svg(w, height, cls) {
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("viewBox", `0 0 ${w} ${height}`);
  s.setAttribute("class", cls || "chart-svg");
  s.setAttribute("preserveAspectRatio", "xMidYMid meet");
  return s;
}

function rect(x, y, w, hh, fill, extra = {}) {
  const r = document.createElementNS(NS, "rect");
  r.setAttribute("x", x);
  r.setAttribute("y", y);
  r.setAttribute("width", Math.max(0, w));
  r.setAttribute("height", Math.max(0, hh));
  if (fill) r.style.fill = fill;
  for (const [k, v] of Object.entries(extra)) r.setAttribute(k, v);
  return r;
}

function lineEl(x1, y1, x2, y2, color) {
  const l = document.createElementNS(NS, "line");
  l.setAttribute("x1", x1); l.setAttribute("y1", y1);
  l.setAttribute("x2", x2); l.setAttribute("y2", y2);
  l.style.stroke = color;
  return l;
}

function textEl(x, y, str, cls, anchor) {
  const t = document.createElementNS(NS, "text");
  t.setAttribute("x", x); t.setAttribute("y", y);
  if (anchor) t.setAttribute("text-anchor", anchor);
  if (cls) t.setAttribute("class", cls);
  t.textContent = str;
  return t;
}

function withTitle(node, str) {
  const t = document.createElementNS(NS, "title");
  t.textContent = str;
  node.appendChild(t);
  return node;
}

function parseISO(s) {
  return new Date(s + "T00:00:00");
}

// ------------------------------------------------- visão geral (KPIs) --------

// Cabeçalho de indicadores: 3 horizontes (dia/semana/mês) por grupo.
// Recorrentes = razão concluídas/slots (barra + %), um parte-de-todo honesto.
// Pontuais = contagem de concluídas no período (o "em aberto" é da seção de
// backlog, não daqui — evita o denominador-snapshot enganoso das pizzas).
function kpiGroup(title, g, isRatio) {
  const tiles = KPI_LABELS.map((label, i) => {
    const cell = g[KPI_KEYS[i]];
    return isRatio ? ratioTile(label, cell.done, cell.open, cell.extra) : countTile(label, cell.done);
  });
  return h("div", { class: "dash-group" },
    h("h3", { class: "dash-group-title", text: title }),
    h("div", { class: "kpi-row" }, ...tiles));
}

function ratioTile(label, done, open, extra = 0) {
  const total = done + open;
  const empty = total === 0;
  const pct = empty ? 0 : Math.round((done / total) * 100);
  const fill = h("span", { class: "kpi-fill" });
  fill.style.width = pct + "%";
  return h("div", { class: "kpi-tile" },
    h("span", { class: "kpi-label", text: label }),
    h("span", { class: "kpi-value" + (empty ? " muted" : ""), text: empty ? "—" : pct + "%" }),
    h("div", { class: "kpi-track", role: "img", "aria-label": `${pct}% concluídas` }, fill),
    h("span", {
      class: "kpi-sub",
      text: (empty ? "nenhuma devida" : `${done} de ${total}`) + (extra ? ` · +${extra} extra` : ""),
      title: extra ? "Concluídas em dia não útil: ficam salvas, mas não entram no percentual." : null,
    }));
}

function countTile(label, done) {
  return h("div", { class: "kpi-tile" },
    h("span", { class: "kpi-label", text: label }),
    h("span", { class: "kpi-value", text: String(done) }),
    h("span", { class: "kpi-sub", text: "concluída(s)" }));
}

function legendItem(label, count, color) {
  const swatch = h("span", { class: "swatch" });
  swatch.style.background = color;
  return h("span", { class: "item" }, swatch, `${label}: ${count}`);
}

// ------------------------------------------------------ heatmap (calendário) --

function heatColor(d) {
  // Dia sem tarefa vigente (todos são <= hoje, pois a série vai só até hoje):
  // quadrado vazio (só contorno), não um bloco cheio.
  if (d.slots === 0) return { fill: "none", op: 1, empty: true };
  if (d.done === 0) return { fill: "var(--surface-container-high)", op: 1 };
  const frac = Math.min(1, d.done / d.slots);
  const op = frac >= 1 ? 1 : frac >= 0.67 ? 0.75 : frac >= 0.34 ? 0.5 : 0.28;
  return { fill: "var(--primary)", op };
}

function heatmap(hm) {
  if (!hm || !hm.days || !hm.days.length || hm.days.every((d) => d.slots === 0))
    return emptyBox("sem recorrentes ainda");
  // A série vem com 8 semanas (para a tendência); o calendário mostra só as 4
  // últimas. Recorta em múltiplos de 7 (heat_start é domingo) p/ manter colunas.
  const HEAT_WEEKS = 4;
  let days = hm.days;
  const totalCols = Math.ceil(days.length / 7);
  if (totalCols > HEAT_WEEKS) days = days.slice((totalCols - HEAT_WEEKS) * 7);
  const start = parseISO(days[0].date);
  const cols = Math.ceil(days.length / 7);
  const cell = 24, gap = 3, step = cell + gap;
  const padL = 26, padT = 16;
  const w = padL + cols * step + 2;
  const height = padT + 7 * step + 2;
  const s = svg(w, height, "chart-svg heatmap");
  // Renderiza em tamanho natural (não estica): mantém os rótulos legíveis e
  // coerentes com os outros gráficos, em vez de escalar a fonte junto do SVG.
  s.setAttribute("width", w);
  s.setAttribute("height", height);
  s.setAttribute("role", "img");
  s.setAttribute("aria-label", "Calendário de aderência das tarefas recorrentes");

  // Rótulos de mês (quando a coluna inicia um mês diferente da anterior).
  let prevMonth = -1;
  for (let col = 0; col < cols; col++) {
    const dt = new Date(start.getTime() + col * 7 * 86400000);
    if (dt.getMonth() !== prevMonth) {
      s.appendChild(textEl(padL + col * step, padT - 5, MONTHS[dt.getMonth()], "heat-axis"));
      prevMonth = dt.getMonth();
    }
  }
  // Rótulos de dia da semana (linhas 1/3/5 = seg/qua/sex).
  for (const row of [1, 3, 5]) {
    s.appendChild(textEl(0, padT + row * step + cell - 2, WEEKDAYS[row].toLowerCase().slice(0, 3), "heat-axis"));
  }

  days.forEach((d, i) => {
    const col = Math.floor(i / 7), row = i % 7;
    const { fill, op, empty } = heatColor(d);
    const r = rect(padL + col * step, padT + row * step, cell, cell, fill, { rx: 2 });
    if (op !== 1) r.style.opacity = op;
    if (empty) { r.style.stroke = "var(--outline-variant)"; r.style.strokeWidth = "1"; }
    const label = formatDate(d.date);
    withTitle(r, d.slots === 0 ? `${label}: sem tarefas` : `${label}: ${d.done}/${d.slots} concluídas`);
    s.appendChild(r);
  });

  return h("div", {}, s, heatLegend());
}

function heatLegend() {
  const box = h("div", { class: "heat-legend" }, h("span", { text: "menos" }));
  for (const op of [null, 0.28, 0.5, 0.75, 1]) {
    const sw = h("span", { class: "heat-cell" });
    if (op === null) sw.style.background = "var(--surface-container-high)";
    else { sw.style.background = "var(--primary)"; sw.style.opacity = op; }
    box.append(sw);
  }
  box.append(h("span", { text: "mais" }));
  return box;
}

// ------------------------------------------------- tendência semanal (linha) --

function weeklyTrend(hm) {
  if (!hm || !hm.days || !hm.days.length || hm.days.every((d) => d.slots === 0))
    return emptyBox("sem dados");
  // Agrupa a série diária por semana (7 dias contíguos a partir de um domingo).
  const weeks = [];
  for (let i = 0; i < hm.days.length; i += 7) {
    const chunk = hm.days.slice(i, i + 7);
    const done = chunk.reduce((a, d) => a + d.done, 0);
    const slots = chunk.reduce((a, d) => a + d.slots, 0);
    weeks.push({ date: chunk[0].date, pct: slots ? (done / slots) * 100 : 0, slots });
  }
  const W = 300, H = 176, padL = 30, padR = 12, padT = 16, padB = 28;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const n = weeks.length;
  const x = (i) => padL + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (pct) => padT + (1 - pct / 100) * plotH;

  const s = svg(W, H, "chart-svg");
  s.setAttribute("role", "img");
  s.setAttribute("aria-label", "Tendência semanal de aderência");

  // Grades 0/50/100%.
  for (const pct of [0, 50, 100]) {
    s.appendChild(lineEl(padL, y(pct), W - padR, y(pct), "var(--outline-variant)"));
    s.appendChild(textEl(padL - 5, y(pct) + 3, pct + "%", "chart-axis", "end"));
  }

  const pts = weeks.map((w, i) => `${x(i)},${y(w.pct)}`);
  // Área sob a curva.
  const area = document.createElementNS(NS, "path");
  area.setAttribute("d", `M ${x(0)},${y(0)} L ${pts.join(" L ")} L ${x(n - 1)},${y(0)} Z`);
  area.setAttribute("class", "trend-area");
  s.appendChild(area);
  // Linha.
  const poly = document.createElementNS(NS, "polyline");
  poly.setAttribute("points", pts.join(" "));
  poly.setAttribute("class", "trend-line");
  s.appendChild(poly);
  // Pontos.
  weeks.forEach((w, i) => {
    const c = document.createElementNS(NS, "circle");
    c.setAttribute("cx", x(i)); c.setAttribute("cy", y(w.pct)); c.setAttribute("r", 2.5);
    c.setAttribute("class", "trend-dot");
    withTitle(c, `semana de ${formatDate(w.date)}: ${Math.round(w.pct)}%`);
    s.appendChild(c);
  });
  // Rótulos do eixo x (primeira, meio, última semana).
  for (const i of [0, Math.floor((n - 1) / 2), n - 1]) {
    s.appendChild(textEl(x(i), H - 6, formatDate(weeks[i].date), "chart-axis", "middle"));
  }
  return h("div", { class: "trend-wrap" }, s);
}

// -------------------------------------------------- ranking por tarefa (HTML) --

function taskRanking(ta) {
  const tasks = (ta && ta.tasks) || [];
  if (!tasks.length) return emptyBox("nenhuma recorrente vigente nos últimos 30 dias");
  const rows = tasks.map((t) => {
    const pct = Math.round((t.done / t.slots) * 100);
    const fill = h("span", { class: "rank-fill" });
    fill.style.width = pct + "%";
    const parts = [
      h("span", { class: "rank-label", text: t.label, title: t.label }),
      h("span", { class: "rank-track" }, fill),
      h("span", { class: "rank-value", text: `${pct}%` }),
      h("span", { class: "rank-count", text: `${t.done}/${t.slots}` }),
    ];
    if (t.streak > 0) {
      parts.push(h("span", {
        class: "rank-streak",
        title: `sequência atual: ${t.streak} dia(s)`,
        text: `▲ ${t.streak}`,
      }));
    } else {
      parts.push(h("span", { class: "rank-streak empty" }));
    }
    return h("div", { class: "rank-row" }, ...parts);
  });
  return h("div", { class: "rank-list" }, ...rows);
}

// ------------------------------------------------------ barras verticais base --

// Desenha um gráfico de barras verticais a partir de itens {value, label, title,
// highlight}. viewBox FIXO (mesmo W/H para todos): esticados para a largura do
// card, os gráficos da linha "fluxo" ficam na MESMA escala e com a mesma linha
// de base. As barras se distribuem para preencher a largura útil.
function verticalBars(items, opts = {}) {
  if (!items.length) return emptyBox(opts.emptyMsg || "sem dados");
  const max = Math.max(1, ...items.map((it) => it.value));
  const n = items.length;
  const W = 300, plotH = 128, padT = 16, padB = 28, padL = 8, padR = 8;
  const H = padT + plotH + padB;
  const plotW = W - padL - padR;
  const slot = plotW / n;
  // Largura de barra FIXA (mesma em todos os gráficos da linha), distribuída
  // pelos slots para preencher a largura. Só encolhe se houver barras demais.
  const barW = Math.min(32, slot * 0.8);
  const baseY = padT + plotH;
  const s = svg(W, H, "chart-svg");
  items.forEach((it, i) => {
    const cx = padL + slot * (i + 0.5);
    const bh = (it.value / max) * plotH;
    const y = baseY - bh;
    const color = it.highlight ? "var(--primary)" : (opts.color || "var(--primary-container)");
    const bar = rect(cx - barW / 2, y, barW, bh, color, { rx: 3 });
    withTitle(bar, it.title || `${it.label}: ${it.value}`);
    s.appendChild(bar);
    if (it.value > 0) s.appendChild(textEl(cx, y - 5, String(it.value), "chart-val", "middle"));
    s.appendChild(textEl(cx, H - 8, it.label, "chart-axis", "middle"));
  });
  return s;
}

// --------------------------------------------------------------- throughput --

function throughput(tp) {
  const weeks = (tp && tp.weeks) || [];
  if (!weeks.length) return emptyBox("sem dados");
  const total = weeks.reduce((a, w) => a + w.done, 0);
  const items = weeks.map((w) => ({
    value: w.done,
    label: formatDate(w.week_start),
    title: `semana de ${formatDate(w.week_start)}: ${w.done} concluída(s)`,
  }));
  const chart = verticalBars(items, { color: "var(--primary)" });
  if (total === 0) return h("div", { class: "fluxo-body" }, chart, h("p", { class: "chart-note", text: "nenhuma pontual concluída nas últimas 4 semanas" }));
  return h("div", { class: "fluxo-body" }, chart);
}

// ---------------------------------------------------------------- cycle time --

function median(arr) {
  if (!arr.length) return 0;
  const s = [...arr].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function fmtDuration(hours) {
  if (hours < 24) return `${Math.round(hours)} h`;
  const d = hours / 24;
  return d < 10 ? `${d.toFixed(1).replace(".", ",")} d` : `${Math.round(d)} d`;
}

const CYCLE_BUCKETS = [
  { label: "<1d", max: 24 },
  { label: "1–3d", max: 72 },
  { label: "3–7d", max: 168 },
  { label: "1–2sem", max: 336 },
  { label: ">2sem", max: Infinity },
];

function cycleTime(ct) {
  const durs = (ct && ct.durations_h) || [];
  if (!durs.length) return emptyBox("nenhuma pontual concluída em 90 dias");
  const med = median(durs);
  const counts = CYCLE_BUCKETS.map((b) => 0);
  for (const hVal of durs) {
    const idx = CYCLE_BUCKETS.findIndex((b) => hVal < b.max);
    counts[idx === -1 ? CYCLE_BUCKETS.length - 1 : idx]++;
  }
  const items = CYCLE_BUCKETS.map((b, i) => ({
    value: counts[i], label: b.label, title: `${b.label}: ${counts[i]} tarefa(s)`,
  }));
  return h("div", { class: "fluxo-body" },
    h("div", { class: "stat-inline" },
      h("span", { class: "stat-big", text: fmtDuration(med) }),
      h("span", { class: "stat-cap", text: `mediana · ${durs.length} concluída(s)` })),
    verticalBars(items, { color: "var(--primary-container)" }));
}

// ------------------------------------------------------------------- weekday --

function weekdayChart(wd) {
  const counts = (wd && wd.counts) || [];
  if (!counts.length || counts.every((c) => c === 0)) return emptyBox("sem conclusões nas últimas 8 semanas");
  const max = Math.max(...counts);
  // counts vem indexado por domingo=0..sábado=6; exibimos Seg→Dom (fim de
  // semana no fim) para leitura de dia útil.
  const ORDER = [1, 2, 3, 4, 5, 6, 0];
  const items = ORDER.map((i) => ({
    value: counts[i], label: WEEKDAYS[i], highlight: counts[i] === max && counts[i] > 0,
    title: `${WEEKDAYS[i]}: ${counts[i]} conclusão(ões)`,
  }));
  return h("div", { class: "fluxo-body" }, verticalBars(items));
}

// -------------------------------------------------------------- backlog saúde --

function backlogHealth(b) {
  if (!b) return emptyBox("sem dados");
  const open = b.todo + b.in_progress + b.blocked;

  const tiles = h("div", { class: "stat-tiles" },
    statTile("Em aberto", open, null),
    statTile("Bloqueadas", b.blocked, b.blocked > 0 ? "error" : null),
    statTile("Atrasadas", b.overdue, b.overdue > 0 ? "error" : null));

  const statusBody = open === 0
    ? emptyBox("nada em aberto")
    : h("div", {},
        stackedBar([
          { value: b.todo, color: "var(--surface-container-high)", label: "A fazer" },
          { value: b.in_progress, color: "var(--primary)", label: "Em andamento" },
          { value: b.blocked, color: "var(--error)", label: "Bloqueado" },
        ], open),
        h("div", { class: "bar-legend" },
          legendItem("A fazer", b.todo, "var(--surface-container-high)"),
          legendItem("Em andamento", b.in_progress, "var(--primary)"),
          legendItem("Bloqueado", b.blocked, "var(--error)")));

  const ag = b.aging || { new: 0, mid: 0, old: 0 };
  const agingBody = (ag.new + ag.mid + ag.old) === 0
    ? emptyBox("nada em aberto")
    : h("div", { class: "aging-list" },
        agingRow("menos de 1 semana", ag.new, "var(--success)"),
        agingRow("1 a 4 semanas", ag.mid, "var(--warning)"),
        agingRow("mais de 4 semanas", ag.old, "var(--error)"));

  return h("div", {},
    tiles,
    h("div", { class: "chart-grid backlog-grid" },
      chartCard("Backlog por status", "Tarefas em aberto agora.", statusBody),
      chartCard("Envelhecimento", "Há quanto tempo as abertas existem.", agingBody)));
}

function statTile(label, value, tone) {
  return h("div", { class: "stat-tile" + (tone ? " " + tone : "") },
    h("span", { class: "stat-tile-value", text: String(value) }),
    h("span", { class: "stat-tile-label", text: label }));
}

function stackedBar(segs, total) {
  const bar = h("div", { class: "stacked-bar" });
  for (const seg of segs) {
    if (seg.value <= 0) continue;
    const part = h("span", { class: "stacked-seg", title: `${seg.label}: ${seg.value}` });
    part.style.width = (seg.value / total) * 100 + "%";
    part.style.background = seg.color;
    bar.append(part);
  }
  return bar;
}

function agingRow(label, count, color) {
  const dot = h("span", { class: "aging-dot" });
  dot.style.background = color;
  return h("div", { class: "aging-row" },
    dot,
    h("span", { class: "aging-label", text: label }),
    h("span", { class: "aging-count", text: String(count) }));
}
