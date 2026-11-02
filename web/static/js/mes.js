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
import { errorToast, modal, pager, pageSlice, toast } from "./ui.js";
import { projectChip, corProjeto, iconeProjeto } from "./projects.js";
import { duration, openTask } from "./task.js";
import * as reports from "./reports.js";

const MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const TOP = 5;   // entregas visíveis no cartão (as com mais tempo)
const PAGE = 10; // depois de "ver todas", páginas de 10 dentro do próprio cartão

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

// Rotinas extras do mês (feitas fora da agenda): contam na frase e no "mês vazio", como no PDF.
const extrasOf = (ov) => ov.days.reduce((a, d) => a + (d.extra || 0), 0);
const isEmpty = (m, extras) => !m.recurring_total && !m.pontual_done && !m.minutes && !extras;

function screen(a, opts, reload) {
  const ov = a.overview;
  const mes = nameOf(a.period.month);
  const extras = extrasOf(ov);
  const nodes = [hero(ov, mes, opts, extras, reload)];
  // Mês sem nenhum registro (rotina, extra, tarefa ou tempo): a frase "Nada
  // registrado" e o MESMO painel, zerado (a geometria do dashboard não muda).
  const empty = isEmpty(ov.month, extras);
  nodes.push(panel(ov, a.period.month, mes, !!opts.dashUrl, empty));
  if (!empty) nodes.push(deliveriesCard(ov, mes, opts, reload));
  return nodes;
}

// "Em outubro você fez 50 das 81 rotinas previstas (62%), mais 3 extras, concluiu 20 tarefas e apontou 31h43."
function sentence(m, mes, who, extras) {
  if (isEmpty(m, extras)) return `Nada registrado${who ? ` por ${who}` : ""} em ${mes}${m.now ? " até agora" : ""}.`;
  const quando = `Em ${mes}${m.now ? ", até agora," : ""}`;
  const sujeito = who ? ` ${who}` : " você";
  // Só o que aconteceu (o zero aparece nos números, sem virar cobrança na frase).
  const partes = [];
  const mais = extras ? `, mais ${plural(extras, "extra", "extras")}` : ""; // o mesmo texto do PDF
  if (m.recurring_total) partes.push(`fez ${m.recurring_done} das ${m.recurring_total} rotinas previstas (${pct(m.recurring_done, m.recurring_total)}%)${mais}`);
  else if (extras) partes.push(`marcou ${plural(extras, "rotina extra", "rotinas extras")}`);
  if (m.pontual_done) partes.push(`concluiu ${plural(m.pontual_done, "tarefa", "tarefas")}`);
  if (m.minutes) partes.push(`apontou ${duration(m.minutes)}`);
  const lista = partes.length > 1 ? `${partes.slice(0, -1).join(", ")} e ${partes[partes.length - 1]}` : partes[0];
  return `${quando}${sujeito} ${lista}.`;
}

function hero(ov, mes, opts, extras, reload) {
  const m = ov.month;
  const empty = isEmpty(m, extras);
  const base = opts.exportBase || "/reports/export";
  const download = async () => {
    btn.disabled = true;
    try { await api.download(`${base}?start=${m.start}&end=${m.end}`); }
    catch (e) { errorToast(e, "Não foi possível gerar o PDF."); } finally { btn.disabled = false; }
  };
  // "Antes do PDF" (só da própria pessoa): com concluídas sem tempo ou sem
  // "como resolveu", o botão abre antes a lista para completar (dá para pular).
  const falta = !opts.dashUrl && ov.incomplete_total ? ov.incomplete_total : 0;
  const btn = h("button", { type: "button", class: "btn btn-primary",
    onClick: () => (falta ? beforePdf(ov, mes, download, reload) : download()) }, icon("reports"), `Baixar o PDF de ${mes}`);
  const hint = falta ? h("p", { class: "mes-incomplete" },
    h("span", { text: `${plural(falta, "concluída", "concluídas")} sem tempo ou sem “como resolveu”.` }),
    h("button", { type: "button", class: "btn btn-text btn-sm", text: "Completar", onClick: () => beforePdf(ov, mes, download, reload) })) : null;
  return h("section", { class: "mes-hero" },
    h("p", { class: "mes-sentence", text: sentence(m, mes, opts.who, extras) }),
    // O convite a registrar só no mês corrente da própria pessoa.
    empty ? (opts.dashUrl || !m.now ? null : h("p", { class: "mes-prev", text: "O que você registrar no Hoje (rotinas, tarefas e tempo) aparece aqui." }))
      : h("div", { class: "mes-actions" }, btn, hint));
}

// ------------------------------------------------------- antes do PDF --
// As concluídas do mês (as mesmas do PDF) sem tempo apontado ou sem "como
// resolveu", 5 por página, cada uma com o que falta ali mesmo: o tempo (15,
// 30, 60 ou outro número; vai no dia da conclusão) e o como resolveu. Nada é
// obrigatório: "Baixar assim mesmo" sai com o que tem.
const PDF_PAGE = 5;
const MINS = [15, 30, 60];

function beforePdf(ov, mes, download, reload) {
  const items = ov.incomplete.map((x) => ({ ...x }));
  const extra = ov.incomplete_total - items.length; // passou de 300: o resto fica para depois
  const missing = (x) => !x.minutes || !x.resolution;
  let page = 1, changed = false;

  const title = h("h2", { text: `Antes do PDF de ${mes}` });
  title.tabIndex = -1;
  const count = h("p", { class: "review-count", "aria-live": "polite" });
  const box = h("div", { class: "review-list" });
  const go = h("button", { type: "button", class: "btn btn-primary" }, icon("reports"));
  const goText = h("span");
  go.append(goText);
  const close = h("button", { type: "button", class: "icon review-close", title: "Fechar", "aria-label": "Fechar sem baixar",
    onClick: () => dlg.close() }, icon("close"));
  const paintCount = () => {
    const left = items.filter(missing).length + Math.max(0, extra);
    count.textContent = left ? `Faltam ${plural(left, "tarefa", "tarefas")}` : "Tudo completo";
    goText.textContent = left ? "Baixar assim mesmo" : "Baixar o PDF";
  };

  const row = (x) => {
    const el = h("div", { class: "review-row pdf-row", "data-id": String(x.id) });
    const paint = () => {
      clear(el);
      const chip = projectChip({ project_name: x.project, project_color: x.project_color, project_icon: x.project_icon });
      const tags = [h("span", { class: "chip", text: `concluída ${shortDay(x.done_date)}` })];
      if (!missing(x)) tags.push(h("span", { class: "chip pdf-done", text: "completa" }));
      else {
        if (!x.minutes) tags.push(h("span", { class: "chip", text: "sem tempo" }));
        if (!x.resolution) tags.push(h("span", { class: "chip", text: "sem como resolveu" }));
      }
      el.append(h("div", { class: "review-t" }, h("span", { class: "review-title", text: x.title }),
        h("span", { class: "card-meta" }, chip, ...tags)));
      if (!missing(x)) return;
      const fill = h("div", { class: "pdf-fill" });
      let mins = null, res = null;
      if (!x.minutes) {
        mins = h("input", { type: "number", min: "1", max: "1440", inputmode: "numeric", placeholder: "min",
          "aria-label": `Minutos em ${x.title}` });
        const quick = MINS.map((n) => h("button", { type: "button", class: "btn btn-sm btn-ghost", "aria-pressed": "false",
          text: `${n} min`, onClick: (ev) => {
            mins.value = String(n);
            for (const b of quick) b.setAttribute("aria-pressed", String(b === ev.currentTarget));
          } }));
        mins.addEventListener("input", () => { for (const b of quick) b.setAttribute("aria-pressed", String(b.textContent === `${mins.value} min`)); });
        fill.append(h("div", { class: "pdf-mins", role: "group", "aria-label": `Tempo de ${x.title}` },
          h("span", { class: "field-label", text: "Tempo" }), ...quick, mins));
      }
      if (!x.resolution) {
        res = h("input", { type: "text", maxlength: "1000", placeholder: "Como resolveu (ex.: troquei o cabo e testei)",
          "aria-label": `Como resolveu: ${x.title}` });
        res.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); save.click(); } });
      }
      const save = h("button", { type: "button", class: "btn btn-sm btn-primary", text: "Salvar", onClick: async () => {
        const n = mins && mins.value ? Number(mins.value) : null;
        const text = res ? res.value.trim() : "";
        if (!n && !text) { (mins || res).focus(); return; }
        if (n !== null && !(n >= 1 && n <= 1440)) { toast("Tempo de 1 a 1440 minutos.", { error: true }); mins.focus(); return; }
        save.disabled = true;
        try {
          // O tempo vai no dia da conclusão (conta no mesmo mês do PDF).
          if (n) { await api.post(`/worklog/${x.id}/time`, { minutes: n, day: x.done_date }); x.minutes = n; changed = true; }
          if (text) { await api.patch(`/worklog/${x.id}`, { resolution: text }); x.resolution = true; changed = true; }
          paint();
          paintCount();
          // O foco segue para a próxima que falta (ou para o botão de baixar).
          const next = box.querySelector(".pdf-row input");
          (next || go).focus();
        } catch (e) { save.disabled = false; errorToast(e, "Não foi possível salvar."); }
      } });
      // O Salvar fica na linha do como resolveu (ou, sem ele, ao lado do tempo).
      if (res) fill.append(h("div", { class: "review-inline" }, res, save));
      else fill.querySelector(".pdf-mins").append(save);
      el.append(h("div", { class: "review-acts" }, fill));
    };
    paint();
    return el;
  };

  const paintPage = () => {
    clear(box);
    const { rows, page: p } = pageSlice(items, page, PDF_PAGE);
    page = p;
    box.append(...rows.map(row));
    if (extra > 0 && page === Math.ceil(items.length / PDF_PAGE))
      box.append(h("p", { class: "review-res", text: `e mais ${extra}: complete estas e abra de novo para ver as outras.` }));
    const nav = pager({ page, total: items.length, size: PDF_PAGE, label: "tarefas para completar", compact: true,
      onPage: (n) => { page = n; paintPage(); }, focus: title });
    if (nav) box.append(nav);
  };

  go.addEventListener("click", () => { dlg.close(); download(); });
  const dlg = modal(h("div", { class: "review-form" }, close, title,
    h("p", { class: "review-intro", text: "O PDF mostra o tempo e o como resolveu de cada tarefa. Estas concluídas do mês estão sem um deles: complete o que lembrar, ou baixe assim mesmo." }),
    count,
    h("div", { class: "review-body" }, box),
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }), go)));
  dlg.classList.add("review-dialog", "pdf-dialog");
  dlg.addEventListener("close", () => { if (changed) reload().catch(() => {}); });
  paintCount();
  paintPage();
  (box.querySelector("input") || title).focus();
}

const shortDay = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

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

function panel(ov, month, mes, team, empty) {
  // O calendário é das rotinas com rotina no mês (no mês corrente, também se os
  // meses anteriores tinham); sem rotina, é pintado pelas tarefas concluídas;
  // mês vazio: o calendário com todas as células neutras.
  const hasRoutines = ov.routines > 0 || ov.days.some((d) => d.due || d.extra || d.paused)
    || (ov.month.now && ov.trend.slice(0, -1).some((t) => t.recurring_total));
  const tiles = [...kpis(ov, month, team)];
  tiles.push(empty ? emptyCalendarTile(ov, month) : hasRoutines ? calendarTile(ov, month) : tasksCalendarTile(ov, month));
  tiles.push(rhythmTile(ov, month, empty), projectsTile(ov, mes, 8));
  if (hasRoutines || empty) tiles.push(attentionTile(ov, mes, team));
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
  // Sem rotina em nenhum dos 6 meses, a linha ficaria vazia: no lugar dela, quando
  // o mês é anterior à primeira rotina, uma linha diz quando elas começaram.
  const rotTrend = trend && slots.some((k) => byMonth[k] && byMonth[k].recurring_total);
  const fr = ov.first_routine;
  const began = !m.recurring_total && fr && fr.slice(0, 7) > month
    ? h("p", { class: "mm-began", text: `As rotinas começaram em ${ddmm(fr, month)}.` }) : null;
  const rot = tile(4, "mm-kpi", "Rotinas em dia", null,
    h("div", { class: "mm-kpi-main" }, ring(p),
      h("p", { class: "mm-fact", text: m.recurring_total ? `${m.recurring_done} de ${m.recurring_total} previstas` : "sem rotinas previstas" })),
    began,
    rotTrend ? lineChart(slots, byMonth, avg && avg.recurring_pct, month) : null,
    rotTrend ? foot(ov, "routines", avg && avg.recurring_pct != null ? `média: ${Math.round(avg.recurring_pct)}%` : "") : null);

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

// A grade do mês (domingo a sábado) com um rótulo por dia; cellOf(dia, iso, hoje) => {cls, label}.
function calTable(ov, month, caption, describedBy, cellOf) {
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
      const info = cellOf(byDate[iso], iso, today);
      return h("td", { class: `${info.cls}${iso === today ? " today" : ""}`, title: info.label },
        h("span", { class: "mm-dn", "aria-hidden": "true", text: String(Number(iso.slice(8))) }),
        h("span", { class: "sr-only", text: info.label }));
    })));
  }
  return h("table", { class: "mm-cal", "aria-describedby": describedBy },
    h("caption", { class: "sr-only", text: caption }), h("thead", {}, head), h("tbody", {}, ...rows));
}

function calendarTile(ov, month) {
  const mes = nameOf(month);
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
  const table = calTable(ov, month, `Rotinas dia a dia em ${mes}`, sub.id, (d, iso, today) => dayInfo(d, iso, mes, today));
  const legend = h("div", { class: "mm-legend", "aria-hidden": "true" },
    h("span", { class: "mm-leg-scale" }, h("span", { text: "menos" }), sw("l0", "nenhuma feita"), sw("l1", "até um terço"),
      sw("l2", "até dois terços"), sw("l3", "quase todas"), sw("l4", "todas"), h("span", { text: "mais" })),
    h("span", { class: "mm-leg-item" }, sw("extra", "só extras"), h("span", { text: "só extras" })),
    h("span", { class: "mm-leg-item" }, sw("none", "sem rotina prevista"), h("span", { text: "sem previsão" })));
  return tile(8, "mm-cal-tile", "Rotinas no mês, dia a dia", null, sub, table, legend);
}

const sw = (cls, text) => h("span", { class: `mm-sw ${cls}`, title: text });

// "11/10" (com o ano quando não é o do mês mostrado).
const ddmm = (iso, month) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}${iso.slice(0, 4) !== month.slice(0, 4) ? "/" + iso.slice(0, 4) : ""}`;

// Mês sem rotina, mas com tarefas ou tempo: o calendário pintado pelas tarefas
// concluídas em cada dia, em degraus relativos ao próprio mês (o dia com mais é
// o degrau cheio).
function tasksCalendarTile(ov, month) {
  const mes = nameOf(month);
  const max = Math.max(0, ...ov.days.map((d) => d.pontual_done));
  const cellOf = (d, iso, today) => {
    const when = `${Number(iso.slice(8))} de ${mes}`;
    if (!d) return { cls: "fut", label: `${when}: ainda não chegou` };
    const n = d.pontual_done;
    const tempo = d.minutes ? `, ${duration(d.minutes)} de tempo apontado` : "";
    if (n) return { cls: "l" + Math.max(1, Math.ceil((4 * n) / max)), label: `${when}: ${plural(n, "tarefa concluída", "tarefas concluídas")}${tempo}` };
    return { cls: "none", label: `${when}: ${iso === today ? "hoje, nenhuma tarefa concluída ainda" : "nenhuma tarefa concluída"}${tempo}` };
  };
  const taskDays = ov.days.filter((d) => d.pontual_done).length;
  const timeDays = ov.days.filter((d) => d.minutes).length;
  const resumo = taskDays
    ? `${plural(taskDays, "dia com tarefa concluída", "dias com tarefa concluída")}; no dia com mais, ${plural(max, "tarefa", "tarefas")}.`
    : `Nenhuma tarefa concluída; tempo apontado em ${plural(timeDays, "dia", "dias")}.`;
  const sub = h("p", { class: "mm-sub", id: `mm-cal-${month}`, text: resumo });
  const table = calTable(ov, month, `Tarefas concluídas dia a dia em ${mes}`, sub.id, cellOf);
  const legend = h("div", { class: "mm-legend", "aria-hidden": "true" },
    h("span", { class: "mm-leg-scale" }, h("span", { text: "menos" }), sw("l1", "menos tarefas"), sw("l2", "mais tarefas"),
      sw("l3", "mais tarefas"), sw("l4", "o dia com mais tarefas"), h("span", { text: "mais" }),
      h("span", { class: "mm-leg-what", text: "· tarefas concluídas" })));
  return tile(8, "mm-cal-tile", "Tarefas no mês, dia a dia", null, sub, table, legend);
}

// Mês sem nenhum registro: o mesmo calendário, com todas as células neutras
// (só o número do dia) e a mesma legenda, para o painel não mudar de forma.
function emptyCalendarTile(ov, month) {
  const mes = nameOf(month);
  const cellOf = (d, iso, today) => {
    const when = `${Number(iso.slice(8))} de ${mes}`;
    if (!d) return { cls: "fut", label: `${when}: ainda não chegou` };
    return { cls: "blank", label: `${when}: ${iso === today ? "hoje, nada registrado ainda" : "nada registrado"}` };
  };
  const sub = h("p", { class: "mm-sub", id: `mm-cal-${month}`, text: `Nenhuma rotina, tarefa ou tempo registrado em ${mes}.` });
  const table = calTable(ov, month, `O mês de ${mes} dia a dia`, sub.id, cellOf);
  const legend = h("div", { class: "mm-legend", "aria-hidden": "true" },
    h("span", { class: "mm-leg-scale" }, h("span", { text: "menos" }), sw("l0", "nenhuma feita"), sw("l1", "até um terço"),
      sw("l2", "até dois terços"), sw("l3", "quase todas"), sw("l4", "todas"), h("span", { text: "mais" })),
    h("span", { class: "mm-leg-item" }, sw("blank", "nada registrado"), h("span", { text: "nada registrado" })));
  return tile(8, "mm-cal-tile", "O mês, dia a dia", null, sub, table, legend);
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

function weekBars(weeks, key, fmt, title, mes, empty) {
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
    if (v != null && !empty) {
      const t = svgEl("text", { x: cx, y: (v ? base - ((base - topY) * v) / top : base) - 5, class: "mm-val" });
      t.textContent = fmt(v);
      s.append(t);
    }
    const l = svgEl("text", { x: cx, y: 110, class: "mm-axis" });
    l.textContent = w.label;
    s.append(l);
  });
  if (empty) s.setAttribute("aria-label", `${title} por semana em ${mes}: nada registrado.`);
  return h("div", { class: "mm-week-chart" }, h("p", { class: "mm-chart-t", text: title }), s);
}

function rhythmTile(ov, month, empty) {
  const mes = nameOf(month);
  const got = Object.fromEntries(ov.weeks.map((w) => [w.start, w]));
  const weeks = monthWeeks(month).map((w) => ({ ...w, data: got[w.start] || null,
    label: `${Number(w.start.slice(8))}–${Number(w.end.slice(8))}` }));
  // Mês vazio: as mesmas duas linhas de semanas, sem barras, e a frase no quadro.
  return tile(4, "mm-rhythm", "Ritmo do mês", "por semana, de domingo a sábado",
    empty ? h("p", { class: "mes-ok mm-empty", text: `Sem tarefas concluídas nem horas em ${mes}.` }) : null,
    weekBars(weeks, "pontual_done", (v) => String(v), "Tarefas concluídas", mes, empty),
    weekBars(weeks, "minutes", (v) => (v ? duration(v) : "0"), "Horas apontadas", mes, empty));
}

// -------------------------------------------------- 4) tempo por projeto --

const DONUT_MAX = 6; // fatias; o resto vira "outros"

function projectsTile(ov, mes, span) {
  if (!ov.projects.length) { // a rosca vazia no lugar (mesma altura) e a frase no lugar da legenda
    const s = svgEl("svg", { viewBox: "0 0 120 120", class: "mm-donut", "aria-hidden": "true" });
    const n = svgEl("text", { x: 60, y: 57, class: "mm-donut-n" });
    n.textContent = "0h";
    const l = svgEl("text", { x: 60, y: 75, class: "mm-donut-l" });
    l.textContent = "no mês";
    s.append(svgEl("circle", { cx: 60, cy: 60, r: 46, class: "mm-donut-track" }), n, l);
    return tile(span, "mm-proj", "Tempo por projeto", null,
      h("div", { class: "mm-proj-body" }, h("div", { class: "mm-donut-box" }, s),
        h("p", { class: "mes-ok mm-empty", text: `Nada apontado em ${mes}.` })));
  }
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
    const frase = h("p", { class: "mes-ok",
      text: `${full} de ${plural(ov.routines, "rotina", "rotinas")} ${full === 1 ? "feita" : "feitas"} em todos os dias previstos.` });
    if (team) return tile(4, "mm-att", title, null, frase); // de outra pessoa: só a frase, sem medidor
    const fill = h("span");
    fill.style.width = pct(full, ov.routines) + "%";
    return tile(4, "mm-att", title, null, frase, h("span", { class: "mes-track mm-meter", "aria-hidden": "true" }, fill));
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
  // As 5 com mais tempo; "ver todas" troca para páginas de 10 no mesmo cartão
  // (a altura fica estável na grade). O servidor manda até 300 (as com mais
  // tempo); passando disso, a última página diz que as outras estão no PDF.
  const list = h("ul", { class: "mes-dels" }, ...all.slice(0, TOP).map(row));
  const sub = total > TOP ? `as ${TOP} com mais tempo, de ${total}` : null;
  const foot = h("div", { class: "mes-del-foot" });
  const showPage = (n) => {
    const pages = Math.max(1, Math.ceil(all.length / PAGE));
    clear(list); clear(foot);
    list.append(...all.slice((n - 1) * PAGE, n * PAGE).map(row));
    if (n === pages && total > all.length)
      list.append(h("li", { class: "mes-res", text: `e mais ${total - all.length} com menos tempo (todas estão no PDF do mês)` }));
    const subEl = list.closest(".mes-card")?.querySelector(".chart-sub");
    if (subEl) subEl.textContent = `todas as ${total}, da que levou mais tempo à que levou menos`;
    const nav = pager({ page: n, total: all.length, size: PAGE, label: "entregas do mês", compact: true,
      onPage: (k) => showPage(k), focus: () => list.closest(".mes-card")?.querySelector("h2, h3") || list });
    if (nav) foot.append(nav);
  };
  if (all.length > TOP) {
    foot.append(h("button", { type: "button", class: "btn btn-text mes-all", text: `ver todas as ${total}`, onClick: () => {
      showPage(1);
      // O foco segue para a primeira da lista (o botão some; sem isso, cairia no topo).
      const first = list.firstElementChild;
      const target = first && (first.querySelector("button") || first);
      if (target === first) first.tabIndex = -1;
      target?.focus();
    } }));
  }
  return card("O que foi entregue", sub, list, foot);
}

// ------------------------------------------------------------------ SVG --

const NS = "http://www.w3.org/2000/svg";
const MON = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

function svgEl(tag, attrs) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

// Peças que o painel da Equipe (equipe.js) usa: a mesma linguagem, sem a média da pessoa.
export { thisMonth, nameOf, prevOf, nextOf, pct, plural, rangeOf, tile, ring, lineChart, barChart, projectsTile, monthsBack };
