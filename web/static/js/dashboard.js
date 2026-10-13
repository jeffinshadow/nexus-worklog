import { api } from "./api.js";
import { h, clear, shortDate } from "./dom.js";
import { projectBars } from "./summary.js";
import { retroCard } from "./assistant.js";

const NS = "http://www.w3.org/2000/svg";
const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const WEEKDAYS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];

// Todas as agregações vêm do backend (/dashboard). O frontend só desenha — SVG na mão,
// sem libs, coerente com a CSP rígida.
export async function mount(root, opts = {}) {
  const dashUrl = opts.dashUrl || "/dashboard";
  const data = await api.get(dashUrl);
  const a = data || {};

  clear(root);
  // Retrospectiva: o "hoje" e a semana ficam na tela Hoje. A leitura do
  // assistente só na própria (o admin vendo outra pessoa não recebe "sua rotina").
  if (!opts.dashUrl && opts.setAssist) opts.setAssist(retroCard(a, opts.me));
  root.append(
    section("Rotinas · consistência", [
      h("div", { class: "consist-grid" },
        chartCard("Aderência diária", "Últimas 4 semanas — % das rotinas feitas nos dias da agenda.", heatmap(a.heatmap), "compact heat"),
        chartCard("Aderência por rotina", "Últimos 30 dias — dias feitos ÷ dias da agenda de cada rotina.", taskRanking(a.task_adherence), "grow"),
      ),
    ]),
    section("Tarefas · fluxo", [
      h("div", { class: "chart-grid fluxo-grid" },
        chartCard("Concluídas por semana", "Vazão das últimas 4 semanas.", throughput(a.throughput)),
        chartCard("Tempo por projeto", "Horas apontadas nos últimos 30 dias.", projectTime(a.projects)),
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
    return emptyBox("sem rotinas ainda");
  const days = hm.days; // 4 semanas, começando num domingo
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
  s.setAttribute("aria-label", "Calendário de aderência das rotinas");

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
    const label = shortDate(d.date);
    withTitle(r, d.slots === 0 ? `${label}: sem rotina devida` : `${label}: ${d.done}/${d.slots} feitas`);
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

// -------------------------------------------------- ranking por tarefa (HTML) --

function taskRanking(ta) {
  const tasks = (ta && ta.tasks) || [];
  if (!tasks.length) return emptyBox("nenhuma rotina vigente nos últimos 30 dias");
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
    const color = it.highlight ? "var(--primary)" : (opts.color || "var(--chart-muted)");
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
    label: shortDate(w.week_start),
    title: `semana de ${shortDate(w.week_start)}: ${w.done} concluída(s)`,
  }));
  const chart = verticalBars(items, { color: "var(--primary)" });
  if (total === 0) return h("div", { class: "fluxo-body" }, chart, h("p", { class: "chart-note", text: "nenhuma tarefa concluída nas últimas 4 semanas" }));
  return h("div", { class: "fluxo-body" }, chart);
}

// -------------------------------------------------------------- backlog saúde --

function backlogHealth(b) {
  if (!b) return emptyBox("sem dados");
  const open = b.todo + b.in_progress + b.blocked;

  const statusBody = open === 0
    ? emptyBox("nada em aberto")
    : h("div", {},
        stackedBar([
          { value: b.todo, color: "var(--surface-container-high)", label: "A fazer" },
          { value: b.in_progress, color: "var(--primary)", label: "Em andamento" },
          { value: b.blocked, color: "var(--error)", label: "Bloqueada" },
        ], open),
        h("div", { class: "bar-legend" },
          legendItem("A fazer", b.todo, "var(--surface-container-high)"),
          legendItem("Em andamento", b.in_progress, "var(--primary)"),
          legendItem("Bloqueada", b.blocked, "var(--error)")));

  const ag = b.aging || { new: 0, mid: 0, old: 0 };
  const agingBody = (ag.new + ag.mid + ag.old) === 0
    ? emptyBox("nada em aberto")
    : h("div", { class: "aging-list" },
        agingRow("menos de 1 semana", ag.new, "var(--success)"),
        agingRow("1 a 4 semanas", ag.mid, "var(--warning)"),
        agingRow("mais de 4 semanas", ag.old, "var(--error)"));

  return h("div", {},
    h("div", { class: "chart-grid backlog-grid" },
      chartCard("Backlog por status", "Tarefas em aberto agora.", statusBody),
      chartCard("Envelhecimento", "Há quanto tempo as abertas existem.", agingBody)));
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

// ------------------------------------------------------------ tempo/projeto --

function projectTime(pt) {
  const items = (pt && pt.items) || [];
  if (!items.length) return emptyBox("nada apontado nos últimos 30 dias");
  return h("div", { class: "fluxo-body" }, ...projectBars(items));
}
