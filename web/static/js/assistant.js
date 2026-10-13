// O assistente: falas curtas montadas por regras sobre os dados da própria
// pessoa, já carregados pela tela (nenhuma IA é chamada, nada é rastreado).
// Uma fala por tela, só quando há algo útil; desliga em Configurações > Conta.
import { api } from "./api.js";
import { h, icon, nowInTz, localDay, daysBetween, shortDate, addDays } from "./dom.js";
import { duration } from "./task.js";
import { errorToast, toast } from "./ui.js";

export const enabled = (me) => !!(me && me.assistant && me.assistant.enabled);

const plural = (n, um, varios, nenhum = null) => (n === 0 && nenhum ? nenhum : `${n} ${n === 1 ? um : varios}`);
const q = (t) => `«${t}»`;
const ASK_NAME = "nexus.ask.name";
const ASK_IDLE = "nexus.ask.idle";

// O cartão do assistente. parts: {hello, lines: [texto|nó], actions: [nó], extra: nó}
export function card({ hello, lines = [], actions = [], extra = null, compact = false }) {
  return h("section", { class: "panel assist" + (compact ? " compact" : ""), "aria-label": "Assistente" },
    h("span", { class: "assist-mark", "aria-hidden": "true" }, icon("spark")),
    h("div", { class: "assist-body" },
      hello ? h("p", { class: "assist-hello", text: hello }) : null,
      ...lines.filter(Boolean).map((l) => (typeof l === "string" ? h("p", { text: l }) : l)),
      actions.length ? h("div", { class: "assist-actions" }, ...actions) : null,
      extra));
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
    if (t.status === "blocked" && d >= 3) out.push(`${q(t.title)} está bloqueada e sem movimento há ${d} dias. Vale confirmar se ainda depende de alguém.`);
    else if (t.status === "in_progress" && d >= 7) out.push(`${q(t.title)} está em andamento sem movimento há ${d} dias.`);
    else if (t.due_date && daysBetween(today, t.due_date) === 1) out.push(`${q(t.title)} vence amanhã.`);
  }
  if (out.length < 2 && hour >= 16 && pendentes.length && pendentes.length <= 3)
    out.push(`Antes de encerrar o dia, ainda faltam: ${pendentes.map((r) => r.label).join(", ")}.`);
  return out;
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

// Pergunta o nome (uma vez) ou oferece o lembrete (uma vez). Um convite por vez.
function invite(me, onProfile, onAssistant) {
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
      action("Agora não", (ev) => { localStorage.setItem(ASK_NAME, "1"); ev.target.closest(".assist-ask").remove(); }));
  }
  if (!me.assistant.idle_on && !localStorage.getItem(ASK_IDLE)) {
    const mins = me.assistant.idle_minutes;
    return h("div", { class: "assist-ask" },
      h("p", { text: `Posso avisar quando passar ${mins} minutos sem nenhum registro. Deseja ativar?` }),
      action("Ativar lembrete", async (ev) => {
        try {
          const res = await api.put("/me/assistant", { ...me.assistant, idle_on: true });
          localStorage.setItem(ASK_IDLE, "1");
          toast(`Lembrete ativado: ${mins} min sem registro, nos seus dias úteis. Ajuste em Configurações > Conta.`);
          ev.target.closest(".assist-ask").remove();
          onAssistant(res);
        } catch (e) { errorToast(e, "Não foi possível ativar."); }
      }, true),
      action("Agora não", (ev) => { localStorage.setItem(ASK_IDLE, "1"); ev.target.closest(".assist-ask").remove(); }));
  }
  return null;
}

// b = /board (do dia de hoje), sum = /summary. ctx: { me, go, openTask, onProfile, onAssistant }
export function todayCard(b, sum, ctx) {
  const { me } = ctx;
  if (!enabled(me)) return null;
  const t = nowInTz();
  const today = b.today;
  const open = b.in_progress;
  const late = open.filter((x) => x.due_date && x.due_date < today).length;
  const pendentes = b.day === today ? b.recurring.filter((r) => r.due !== false && !r.done_today) : [];
  const lines = [];
  const actions = [];

  if (!b.work_day) {
    lines.push("Hoje não é um dia útil na sua agenda." +
      (open.length ? ` Há ${openLine(open.length, late)}, caso queira adiantar algo.` : " Aproveite o descanso."));
  } else if (pendentes.length || open.length) {
    const partes = [pendentes.length ? plural(pendentes.length, "rotina pendente", "rotinas pendentes") : "", openLine(open.length, late)];
    lines.push(`Para hoje: ${partes.filter(Boolean).join(" e ")}.`);
    if (open.length) {
      const first = open[0];
      lines.push(h("p", {}, "Sugiro começar por ", h("strong", { text: q(first.title) }), `${why(first, today)}.`));
      actions.push(action("Abrir tarefa", () => ctx.openTask(first.id)));
    }
  } else {
    lines.push(b.recurring.some((r) => r.due !== false)
      ? "As rotinas de hoje estão concluídas e não há tarefas em aberto. Tudo em dia."
      : "Nada pendente por aqui. O que surgir, registre no campo de registro rápido.");
  }
  if (b.work_day) lines.push(...notes(open, today, pendentes, t.hour));
  const r = recap(sum, t, ctx.go);
  if (r.line) lines.push(r.line);
  if (r.act) actions.push(r.act);

  return card({ hello: greeting(me.name), lines, actions, extra: invite(me, ctx.onProfile, ctx.onAssistant) });
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
  return lines.length ? card({ lines: lines.slice(0, 3), compact: true }) : null;
}

// ---------------------------------------------------------------- Tarefas --

export function boardLine(open, today, me) {
  if (!enabled(me)) return null;
  if (!open.length) return card({ lines: ["Nenhuma tarefa em aberto. Tudo em dia."], compact: true });
  const oldest = Math.max(...open.map((t) => daysBetween(localDay(t.created_at), today)));
  const late = open.filter((t) => t.due_date && t.due_date < today).length;
  const idade = oldest >= 2 ? `; a mais antiga foi criada há ${oldest} dias` : "";
  const txt = openLine(open.length, late);
  return card({ lines: [txt[0].toUpperCase() + txt.slice(1) + idade + "."], compact: true });
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
