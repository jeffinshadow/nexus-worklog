// O assistente: falas curtas montadas por regras sobre os dados da própria
// pessoa, já carregados pela tela (nenhuma IA é chamada, nada é rastreado).
// Uma fala por tela, só quando há algo útil; desliga em Configurações > Conta.
import { api } from "./api.js";
import { h, icon, nowInTz, localDay, daysBetween, shortDate, addDays } from "./dom.js";
import { duration } from "./task.js";
import { errorToast, modal, toast } from "./ui.js";

export const enabled = (me) => !!(me && me.assistant && me.assistant.enabled);

const plural = (n, um, varios, nenhum = null) => (n === 0 && nenhum ? nenhum : `${n} ${n === 1 ? um : varios}`);
const q = (t) => `«${t}»`;
const ASK_NAME = "nexus.ask.name";

// Falas fechadas no X, por tela (some ao recarregar a página). Com "reabrir
// sozinha" ligado (Conta), a fala volta depois de N minutos se a página
// continuar aberta.
let ME = null;
const closed = new Map(); // key -> quando foi fechada (ms)
export function configure(me) { ME = me; }

function reopenMs() {
  const a = ME && ME.assistant;
  return a && a.reopen_on ? a.reopen_minutes * 60000 : null;
}

function isClosed(key) {
  if (!closed.has(key)) return false;
  const ms = reopenMs();
  if (ms !== null && Date.now() - closed.get(key) >= ms) { closed.delete(key); return false; }
  return true;
}

function closeCard(key, el) {
  closed.set(key, Date.now());
  el.classList.add("hidden");
  const ms = reopenMs();
  if (ms === null) return;
  const at = closed.get(key);
  setTimeout(() => {
    if (closed.get(key) !== at) return; // fechada de novo depois: vale o novo prazo
    closed.delete(key);
    for (const n of document.querySelectorAll(`[data-key="${key}"]`)) n.classList.remove("hidden");
  }, ms);
}

// O cartão do assistente. parts: {key (tela, para fechar no X), hello, lines, actions: [nó], extra: nó}.
// Cada linha é texto, um nó ou { line: texto|nó, actions: [botões] }: os botões
// aparecem logo abaixo da frase que sugere a ação.
function renderLines(lines) {
  return lines.filter(Boolean).flatMap((l) => {
    const item = l.line !== undefined ? l : { line: l, actions: [] };
    const p = typeof item.line === "string" ? h("p", { text: item.line }) : item.line;
    return item.actions && item.actions.length ? [p, h("div", { class: "assist-actions" }, ...item.actions)] : [p];
  });
}

// main: a fala com avisos dentro; o X dela fecha tudo.
export function card({ key = null, hello, lines = [], actions = [], extra = null, compact = false, main = false }) {
  const el = h("section", { class: "panel assist" + (compact ? " compact" : "") + (key && isClosed(key) ? " hidden" : ""),
    "aria-label": "Assistente", "data-key": key },
    h("span", { class: "assist-mark", "aria-hidden": "true" }, icon("spark")),
    h("div", { class: "assist-body" },
      hello ? h("p", { class: "assist-hello", text: hello }) : null,
      ...renderLines(lines),
      actions.length ? h("div", { class: "assist-actions" }, ...actions) : null,
      extra));
  if (key) el.append(h("button", { type: "button", class: "icon assist-close",
    title: main ? "Fechar o assistente por enquanto" : "Fechar esta fala por enquanto",
    "aria-label": main ? "Fechar o assistente e todos os avisos" : "Fechar esta fala do assistente",
    onClick: () => closeCard(key, el) }, icon("close")));
  return el;
}

// Um aviso dentro da fala principal: sem moldura própria, só um fundo leve, o
// símbolo do assistente (é ele falando, não um aviso geral do app) e um X
// discreto para dispensá-lo sem fechar o resto.
function noticeItem({ key, lines = [], extra = null }) {
  const el = h("div", { class: "assist-item" + (isClosed(key) ? " hidden" : ""), "data-key": key },
    h("span", { class: "assist-mark", "aria-hidden": "true" }, icon("spark")),
    h("div", { class: "assist-item-body" }, ...renderLines(lines), extra),
    h("button", { type: "button", class: "icon assist-item-close", title: "Dispensar este aviso por enquanto",
      "aria-label": "Dispensar este aviso", onClick: () => closeCard(key, el) }, icon("close")));
  return el;
}

// A fala principal com os avisos dentro dela: tudo uma coisa só.
function stack(key, mainParts, items) {
  const notices = items.filter(Boolean).map(noticeItem);
  return card({ ...mainParts, key, main: notices.length > 0,
    extra: notices.length ? h("div", { class: "assist-items" }, ...notices) : null });
}

function greeting(name) {
  const { hour } = nowInTz();
  return `${hour < 5 ? "Boa noite" : hour < 12 ? "Bom dia" : hour < 18 ? "Boa tarde" : "Boa noite"}, ${name}.`;
}

const action = (label, onClick, primary = false) =>
  h("button", { type: "button", class: "btn btn-sm " + (primary ? "btn-primary" : "btn-ghost"), text: label, onClick });

// ------------------------------------------------------------------- Hoje --

function openLine(open, late) {
  if (!open) return "";
  const base = plural(open, "tarefa em aberto", "tarefas em aberto");
  if (!late) return base;
  if (open === 1) return `${base}, já atrasada`;
  return `${base}, ${late === 1 ? "uma delas atrasada" : `${late} delas atrasadas`}`;
}

function why(t, today) {
  if (t.due_date && t.due_date < today) return `, atrasada desde ${shortDate(t.due_date)}`;
  if (t.due_date === today) return ", que vence hoje";
  if (t.priority === 1) return ", de prioridade alta";
  if (t.status === "in_progress") return ", já em andamento";
  return "";
}

// Avisos discretos sobre tarefas paradas ou com prazo próximo (no máximo 2).
function notes(open, today, pendentes, hour) {
  const out = [];
  const idle = (t) => daysBetween(localDay(t.touched_at || t.created_at), today);
  for (const t of open) {
    if (out.length >= 2) break;
    const d = idle(t);
    const nota = (text) => out.push({ key: `hoje:tarefa:${t.id}`, text, task: t });
    if (t.status === "blocked" && d >= 3) nota(`${q(t.title)} está bloqueada e sem movimento há ${d} dias. Vale confirmar se ainda depende de alguém.`);
    else if (t.status === "in_progress" && d >= 7) nota(`${q(t.title)} está em andamento sem movimento há ${d} dias.`);
    else if (t.due_date && daysBetween(today, t.due_date) === 1) nota(`${q(t.title)} vence amanhã.`);
  }
  return out;
}

// Resumo do dia: o que saiu hoje e o que falta (quando aparece: ver todayCard).
function closing(sum, pendentes) {
  const s = sum && sum.today_stats;
  if (!s) return null;
  const tempo = s.minutes ? ` e ${duration(s.minutes)} apontadas` : ", sem tempo apontado";
  const falta = pendentes.length
    ? `; ainda ${pendentes.length === 1 ? "falta" : "faltam"} ${pendentes.length <= 3 ? pendentes.map((r) => r.label).join(", ") : plural(pendentes.length, "rotina", "rotinas")}`
    : "";
  return `Resumo do dia: ${plural(s.pontual_done, "tarefa concluída", "tarefas concluídas", "nenhuma tarefa concluída")}${tempo} hoje${falta}.`;
}

// Texto da daily: Ontem (desde o último dia útil), Hoje e Impedimentos.
export function dailyText(b, sum) {
  const today = b.today;
  const lines = [];
  const last = sum && sum.last_day;
  const quando = last ? (last.start === addDays(today, -1) ? "Ontem" : `Desde ${shortDate(last.start)}`) : "Ontem";
  lines.push(`${quando}:`);
  const feitas = last ? last.deliveries.slice(0, 10) : [];
  lines.push(...(feitas.length ? feitas.map((d) => `- ${d.title}${d.project ? ` [${d.project}]` : ""}${d.minutes ? ` (${duration(d.minutes)})` : ""}`) : ["- nada registrado"]));
  lines.push("", "Hoje:");
  const hoje = b.in_progress.filter((t) => t.status !== "blocked").slice(0, 6);
  lines.push(...(hoje.length ? hoje.map((t) => `- ${t.title}${t.ticket ? ` (#${t.ticket})` : ""}${t.due_date && t.due_date < today ? " — atrasada" : t.due_date === today ? " — vence hoje" : ""}`) : ["- sem tarefas em aberto"]));
  lines.push("", "Impedimentos:");
  const bloq = b.in_progress.filter((t) => t.status === "blocked");
  lines.push(...(bloq.length ? bloq.map((t) => `- ${t.title}${t.ticket ? ` (#${t.ticket})` : ""}`) : ["- nenhum"]));
  return lines.join("\n");
}

async function copyDaily(b, sum) {
  const text = dailyText(b, sum);
  try {
    await navigator.clipboard.writeText(text);
    toast("Texto da daily copiado. É só colar no chat da equipe.");
  } catch {
    // Área de transferência bloqueada: mostra o texto selecionado para copiar à mão.
    const area = h("textarea", { class: "daily-text", rows: "12", readonly: "readonly" });
    area.value = text;
    const dlg = modal(h("h2", { text: "Texto da daily" }),
      h("p", { class: "dialog-note", text: "Não consegui copiar sozinho. O texto já está selecionado: use Ctrl+C." }), area,
      h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-primary", text: "Fechar", onClick: () => dlg.close() })));
    setTimeout(() => area.select(), 0);
  }
}

// O que aconteceu desde o último dia útil (manhã) e o fechamento da sexta (tarde).
function recap(sum, t, go) {
  if (!sum) return { line: null, act: null };
  if (t.hour < 12 && sum.last_day) {
    const s = sum.last_day;
    if (s.pontual_done || s.minutes) {
      const quando = s.start === addDays(sum.today, -1) ? "Ontem" : "Desde o último dia útil";
      const tempo = s.minutes ? ` e apontou ${duration(s.minutes)}` : "";
      return { line: `${quando}, você concluiu ${plural(s.pontual_done, "tarefa", "tarefas")}${tempo}.`, act: null };
    }
  }
  if (t.weekday === 5 && t.hour >= 14 && sum.week) {
    const w = sum.week;
    return {
      line: `Nesta semana: ${plural(w.pontual_done, "tarefa concluída", "tarefas concluídas", "nenhuma tarefa concluída")}${w.minutes ? ` e ${duration(w.minutes)} apontadas` : ""}. O relatório da semana já pode ser gerado.`,
      act: action("Gerar relatório", () => go("relatorios")),
    };
  }
  return { line: null, act: null };
}

// Pergunta o nome, uma vez.
function invite(me, onProfile) {
  if (!me.display_name && !localStorage.getItem(ASK_NAME)) {
    const input = h("input", { type: "text", maxlength: "60", placeholder: me.name, "aria-label": "Seu nome de exibição" });
    const save = async () => {
      try {
        const res = await api.put("/me/profile", { display_name: input.value.trim() || me.name });
        localStorage.setItem(ASK_NAME, "1");
        onProfile(res);
      } catch (e) { errorToast(e, "Não foi possível salvar o nome."); }
    };
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); save(); } });
    return h("div", { class: "assist-ask" },
      h("p", { text: "Qual nome devo usar com você?" }), input,
      action("Salvar", save, true),
      action("Agora não", (ev) => { localStorage.setItem(ASK_NAME, "1"); (ev.target.closest(".assist-item") || ev.target.closest(".assist-ask")).remove(); }));
  }
  return null;
}

// b = /board (do dia de hoje), sum = /summary. ctx: { me, go, openTask, onProfile }
export function todayCard(b, sum, ctx) {
  const { me } = ctx;
  if (!enabled(me)) return null;
  const t = nowInTz();
  const today = b.today;
  const open = b.in_progress;
  const late = open.filter((x) => x.due_date && x.due_date < today).length;
  const pendentes = b.day === today ? b.recurring.filter((r) => r.due !== false && !r.done_today) : [];
  const items = [];
  let resumo;

  if (!b.work_day) {
    resumo = "Hoje não é um dia útil na sua agenda." +
      (open.length ? ` Há ${openLine(open.length, late)}, caso queira adiantar algo.` : " Aproveite o descanso.");
  } else if (pendentes.length || open.length) {
    const partes = [pendentes.length ? plural(pendentes.length, "rotina pendente", "rotinas pendentes") : "", openLine(open.length, late)];
    resumo = `Para hoje: ${partes.filter(Boolean).join(" e ")}.`;
    if (open.length) {
      const first = open[0];
      items.push({ key: "hoje:sugestao", lines: [{ line: h("p", {}, "Sugiro começar por ", h("strong", { text: q(first.title) }), `${why(first, today)}.`),
        actions: [action("Abrir tarefa", () => ctx.openTask(first.id))] }] });
    }
  } else {
    resumo = b.recurring.some((r) => r.due !== false)
      ? "As rotinas de hoje estão concluídas e não há tarefas em aberto. Tudo em dia."
      : "Nada pendente por aqui. O que surgir, registre no campo de registro rápido.";
  }
  if (b.work_day) for (const n of notes(open, today, pendentes, t.hour)) items.push({ key: n.key, lines: [n.text] });

  // Tempo esquecido: concluídas hoje sem nenhum apontamento.
  const semTempo = b.done.filter((x) => x.completed_at && localDay(x.completed_at) === today && !x.minutes);
  if (semTempo.length) {
    items.push({ key: "hoje:sem-tempo", lines: [{ line: h("p", {}, `${semTempo.length === 1 ? "Uma tarefa concluída hoje está" : `${semTempo.length} tarefas concluídas hoje estão`} sem tempo apontado: `,
      ...semTempo.slice(0, 3).flatMap((x, i) => [i ? ", " : "", h("strong", { text: q(x.title) })]), semTempo.length > 3 ? " e outras." : "."),
      actions: semTempo.slice(0, 2).map((x) => action(`Apontar em ${q(x.title.length > 24 ? x.title.slice(0, 23) + "…" : x.title)}`, () => ctx.openTask(x.id))) }] });
  }
  // Resumo do dia: com a primeira tarefa ou rotina concluída hoje; sem nada
  // concluído, a partir do horário escolhido em Conta (padrão 14:00), em dia útil.
  const st = sum && sum.today_stats;
  const algo = st && (st.pontual_done || st.recurring_done || st.recurring_extra);
  const desde = me.assistant.summary_from ?? 840;
  const fechamento = algo || (b.work_day && t.hour * 60 + t.minute >= desde) ? closing(sum, pendentes) : null;
  // Recapitulação: "Ontem, você concluiu…" vai no texto principal; o fechamento
  // da sexta (com o botão do relatório) é um aviso.
  const r = recap(sum, t, ctx.go);
  if (r.line && r.act) items.push({ key: "hoje:recap", lines: [{ line: r.line, actions: [r.act] }] });
  if (b.work_day) items.push({ key: "hoje:daily", lines: [{ line: "Posso montar o texto da daily: ontem, hoje e impedimentos, pronto para colar no chat da equipe.",
    actions: [action("Copiar para a daily", () => copyDaily(b, sum))] }] });
  const ask = invite(me, ctx.onProfile);
  if (ask) items.push({ key: "hoje:nome", lines: [], extra: ask });

  return stack("hoje", { hello: greeting(me.name), lines: [resumo, r.line && !r.act ? r.line : null, fechamento] }, items);
}

// --------------------------------------------------------- Retrospectiva --

export function retroCard(a, me) {
  if (!enabled(me)) return null;
  const lines = [];
  const rot = (a.task_adherence && a.task_adherence.tasks) || [];
  const pct = (r) => Math.round((100 * r.done) / r.slots);
  if (rot.length >= 2) {
    const best = rot.reduce((x, y) => (y.done / y.slots > x.done / x.slots ? y : x));
    const worst = rot[0]; // vem ordenado: a mais pulada primeiro
    if (pct(best) > pct(worst))
      lines.push(`Sua rotina mais consistente nos últimos 30 dias é ${q(best.label)} (${pct(best)}%). ` +
        `A que mais escapa é ${q(worst.label)} (${pct(worst)}%)${pct(worst) < 50 ? "; talvez a agenda dela mereça uma revisão" : ""}.`);
  } else if (rot.length === 1) {
    lines.push(`Sua rotina ${q(rot[0].label)} foi feita em ${pct(rot[0])}% dos dias da agenda nos últimos 30 dias.`);
  }
  const streak = rot.filter((r) => r.streak >= 3).sort((x, y) => y.streak - x.streak)[0];
  if (streak) lines.push(`${q(streak.label)} está em dia há ${streak.streak} dias seguidos.`);
  const proj = ((a.projects && a.projects.items) || []).filter((p) => p.minutes);
  const total = proj.reduce((s, p) => s + p.minutes, 0);
  if (proj.length >= 2 && total) {
    const top = proj[0];
    const share = Math.round((100 * top.minutes) / total);
    if (share >= 40) lines.push(`${share}% do tempo apontado nos últimos 30 dias foi para ${top.name ? q(top.name) : "tarefas sem projeto"}.`);
  }
  const weeks = (a.throughput && a.throughput.weeks) || [];
  const done = weeks.reduce((s, w) => s + w.done, 0);
  if (weeks.length && !lines.length)
    lines.push(done ? `Nas últimas 4 semanas, você concluiu ${plural(done, "tarefa", "tarefas")}.` : "Ainda não há tarefas concluídas nas últimas 4 semanas para analisar.");
  if (!lines.length) return null;
  const [first, ...rest] = lines.slice(0, 3);
  return stack("retro", { lines: [first], compact: true }, rest.map((l, i) => ({ key: `retro:${i}`, lines: [l] })));
}

// ---------------------------------------------------------------- Tarefas --

export function boardLine(open, today, me) {
  if (!enabled(me)) return null;
  if (!open.length) return card({ key: "tarefas", lines: ["Nenhuma tarefa em aberto. Tudo em dia."], compact: true });
  const oldest = Math.max(...open.map((t) => daysBetween(localDay(t.created_at), today)));
  const late = open.filter((t) => t.due_date && t.due_date < today).length;
  const idade = oldest >= 2 ? `; a mais antiga foi criada há ${oldest} dias` : "";
  const txt = openLine(open.length, late);
  return card({ key: "tarefas", lines: [txt[0].toUpperCase() + txt.slice(1) + idade + "."], compact: true });
}

// ------------------------------------------------------------- Relatórios --

export function previewText(p) {
  if (!p.pontual_done && !p.minutes && !p.recurring_done)
    return "Não há registros neste período; o relatório sairia vazio.";
  const partes = [plural(p.pontual_done, "tarefa concluída", "tarefas concluídas", "nenhuma tarefa concluída")];
  if (p.minutes) partes.push(`${duration(p.minutes)} apontadas`);
  if (p.recurring_total) partes.push(`${Math.round((100 * p.recurring_done) / p.recurring_total)}% das rotinas cumpridas`);
  const lista = partes.length > 1 ? `${partes.slice(0, -1).join(", ")} e ${partes[partes.length - 1]}` : partes[0];
  return `Este período tem ${lista}, em ${plural(p.active_days, "dia", "dias")} com atividade.`;
}
