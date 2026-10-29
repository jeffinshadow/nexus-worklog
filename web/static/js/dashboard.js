import { api } from "./api.js";
import { h, icon, clear, shortDate } from "./dom.js";
import { errorToast } from "./ui.js";
import { projectBars } from "./summary.js";
import { retroCard } from "./assistant.js";

const NS = "http://www.w3.org/2000/svg";
const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const WEEKDAYS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
const MONTHS_LONG = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

// Período escolhido (fica enquanto a aba estiver aberta): null = últimos 30 dias,
// ou "AAAA-MM". As setas andam por [null, mês corrente, mês anterior, ...].
let month = null;
const monthName = (m) => MONTHS_LONG[Number(m.slice(5)) - 1] + " de " + m.slice(0, 4);
// Como o período entra nas frases: "nos últimos 30 dias" / "em setembro".
function periodPhrase(p) {
  return p && p.month ? "em " + MONTHS_LONG[Number(p.month.slice(5)) - 1] : "nos últimos 30 dias";
}

// Todas as agregações vêm do backend (/dashboard). O frontend só desenha — SVG na mão,
// sem libs, coerente com a CSP rígida.
export async function mount(root, opts = {}) {
  const base = opts.dashUrl || "/dashboard";
  let a;
  try {
    a = (await api.get(month ? `${base}?month=${month}` : base)) || {};
  } catch (e) {
    if (!month) throw e;
    month = null; // mês que deixou de existir (outra pessoa, outro período): volta ao padrão
    a = (await api.get(base)) || {};
  }
  const p = a.period || {};
  const mes = p.month ? MONTHS_LONG[Number(p.month.slice(5)) - 1] : null;
  const ph = periodPhrase(p);

  clear(root);
  // Retrospectiva: o "hoje" e a semana ficam na tela Hoje. A leitura do
  // assistente só na própria (o admin vendo outra pessoa não recebe "sua rotina").
  if (!opts.dashUrl && opts.setAssist) opts.setAssist(retroCard(a, opts.me));
  root.append(
    periodNav(a, () => mount(root, opts), root),
    section("Rotinas · consistência", [
      h("div", { class: "consist-grid" },
        chartCard("Aderência diária", (mes ? `${cap(mes)}` : "Últimas 4 semanas") + " — % das rotinas feitas nos dias da agenda.", heatmap(a.heatmap), "compact heat"),
        chartCard("Aderência por rotina", (mes ? `${cap(mes)}` : "Últimos 30 dias") + " — dias feitos ÷ dias da agenda de cada rotina.", taskRanking(a.task_adherence, ph), "grow"),
      ),
    ]),
    section("Tarefas · fluxo", [
      h("div", { class: "chart-grid fluxo-grid" },
        chartCard("Concluídas por semana", mes ? `Semanas de ${mes} (as das pontas começam ou terminam no mês vizinho).` : "Vazão das últimas 4 semanas.", throughput(a.throughput, ph)),
        chartCard("Tempo por projeto", `Horas apontadas ${ph}. Tarefa em mais de um projeto conta em cada um.`, projectTime(a.projects, ph)),
      ),
    ]),
    a.backlog
      ? section("Backlog · saúde", [backlogHealth(a.backlog)])
      : h("p", { class: "chart-note dash-past-note", text: "Backlog e sequências são do momento: aparecem em “Últimos 30 dias” e no mês corrente." })
  );
}

const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

// ‹ Últimos 30 dias › — as setas voltam mês a mês até o primeiro registro.
function periodNav(a, rerender, root) {
  const steps = [null, ...(a.months || [])];
  const i = Math.max(0, steps.indexOf(month));
  const go = async (j) => {
    if (j < 0 || j >= steps.length) return;
    month = steps[j];
    root.classList.add("refreshing");
    try { await rerender(); } catch (e) { errorToast(e); } finally { root.classList.remove("refreshing"); }
  };
  const p = a.period || {};
  const label = !month ? "Últimos 30 dias" : monthName(month) + (p.now ? " · até hoje" : "");
  const prev = h("button", { type: "button", class: "icon", title: "Período anterior", "aria-label": "Período anterior", onClick: () => go(i + 1) }, icon("left"));
  const next = h("button", { type: "button", class: "icon", title: "Próximo período", "aria-label": "Próximo período", onClick: () => go(i - 1) }, icon("right"));
  prev.disabled = i >= steps.length - 1;
  next.disabled = i === 0;
  return h("div", { class: "day-nav dash-period" }, prev, h("span", { class: "day-nav-label", "aria-live": "polite", text: label }), next);
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
    return emptyBox(month ? "nenhuma rotina na agenda neste mês" : "sem rotinas ainda");
  const days = hm.days; // semanas inteiras, começando num domingo
  const lead = Math.max(0, days.findIndex((d) => !d.out)); // dias do mês anterior na 1ª coluna
  const cols = Math.ceil(days.length / 7);
  const cell = 24, gap = 3, step = cell + gap;
  const padL = 34, padT = 21; // espaço para os rótulos (dia da semana e mês) em 12px
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
    // 1º dia visível da coluna (na primeira, o 1º dia do mês)
    const dt = parseISO(days[Math.min(days.length - 1, col * 7 + (col ? 0 : lead))].date);
    if (dt.getMonth() !== prevMonth) {
      s.appendChild(textEl(padL + col * step, padT - 6, MONTHS[dt.getMonth()], "heat-axis"));
      prevMonth = dt.getMonth();
    }
  }
  // Rótulos de dia da semana (linhas 1/3/5 = seg/qua/sex).
  for (const row of [1, 3, 5]) {
    s.appendChild(textEl(0, padT + row * step + cell - 6, WEEKDAYS[row].toLowerCase().slice(0, 3), "heat-axis"));
  }

  days.forEach((d, i) => {
    if (d.out) return; // semana que começa no mês anterior: o dia fica em branco
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

function taskRanking(ta, ph = "nos últimos 30 dias") {
  const tasks = (ta && ta.tasks) || [];
  if (!tasks.length) return emptyBox(`nenhuma rotina vigente ${ph}`);
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

function throughput(tp, ph = "nos últimos 30 dias") {
  const weeks = (tp && tp.weeks) || [];
  if (!weeks.length) return emptyBox("sem dados");
  const total = weeks.reduce((a, w) => a + w.done, 0);
  const items = weeks.map((w) => ({
    value: w.done,
    label: shortDate(w.week_start),
    title: `semana de ${shortDate(w.week_start)}: ${w.done} concluída(s)`,
  }));
  const chart = verticalBars(items, { color: "var(--primary)" });
  if (total === 0) return h("div", { class: "fluxo-body" }, chart, h("p", { class: "chart-note", text: month ? `nenhuma tarefa concluída ${ph}` : "nenhuma tarefa concluída nas últimas 4 semanas" }));
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

function projectTime(pt, ph = "nos últimos 30 dias") {
  const items = (pt && pt.items) || [];
  if (!items.length) return emptyBox(`nada apontado ${ph}`);
  return h("div", { class: "fluxo-body" }, ...projectBars(items));
}
