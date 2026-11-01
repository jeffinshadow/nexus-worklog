// Resumos do Hoje: o último dia útil e a semana até agora, só com os totais.
// Dados de /api/summary. As setas do card da semana voltam às semanas
// anteriores (/api/summary/week?back=N).
import { api } from "./api.js";
import { h, icon, clear, longDate, shortDate, addDays } from "./dom.js";
import { errorToast } from "./ui.js";
import { projectChip, corProjeto } from "./projects.js";
import { duration, openTask } from "./task.js";
import { openReview } from "./review.js";

function pct(done, total) {
  return total ? Math.round((100 * done) / total) : null;
}

function figures(s) {
  const p = pct(s.recurring_done, s.recurring_total);
  const fig = (value, label) => h("div", { class: "fig" }, h("p", { class: "fig-n", text: value }), h("p", { class: "fig-l", text: label }));
  return h("div", { class: "figs" },
    fig(s.recurring_total ? `${p}%` : "—", s.recurring_total ? `rotinas · ${s.recurring_done}/${s.recurring_total}` : "sem rotinas previstas"),
    fig(String(s.pontual_done), s.pontual_done === 1 ? "tarefa concluída" : "tarefas concluídas"),
    fig(s.minutes ? duration(s.minutes) : "—", "tempo apontado"));
}

function card(title, sub, s, onChange, nav = null) {
  const body = [nav, figures(s)].filter(Boolean);
  if (s.deliveries.length) {
    body.push(h("p", { class: "sum-h", text: "Concluído" }));
    for (const d of s.deliveries.slice(0, 5))
      body.push(h("div", { class: "sum-row" },
        h("button", { type: "button", class: "card-open", text: d.title, onClick: () => openTask(d.id, onChange) }),
        projectChip({ project_name: d.project, project_color: d.project_color, project_icon: d.project_icon }),
        d.minutes ? h("span", { class: "tag" }, icon("clock"), duration(d.minutes)) : null));
    if (s.deliveries.length > 5) body.push(h("p", { class: "muted small", text: `+ ${s.deliveries.length - 5} outras` }));
  }
  if (s.projects.some((p) => p.minutes))
    body.push(h("p", { class: "sum-h", text: "Tempo por projeto" }), ...projectBars(s.projects));
  if (s.missed.length) {
    body.push(h("p", { class: "sum-h", text: "Rotinas que ficaram para trás" }),
      h("p", { class: "missed" }, ...s.missed.map((m) => h("span", { class: "chip late", text: m }))));
  }
  if (!s.deliveries.length && !s.minutes && !s.recurring_done && !s.missed.length)
    body.push(h("p", { class: "empty", text: "Nada registrado." }));
  return h("div", { class: "sum-card" }, h("div", { class: "sum-title" }, h("h3", { text: title }), h("span", { class: "mono muted", text: sub })), ...body);
}

// Barras "tempo por projeto" (resumo do Hoje e Meu mês): {name, color, minutes}.
export function projectBars(items) {
  const comTempo = items.filter((p) => p.minutes);
  const top = Math.max(...comTempo.map((p) => p.minutes), 1);
  return comTempo.map((p) => {
    const bar = h("span");
    bar.style.width = `${Math.round((100 * p.minutes) / top)}%`;
    bar.style.background = corProjeto(p.color);
    return h("div", { class: "sum-bar" }, h("span", { class: "sum-bar-l", text: p.name || "Sem projeto" }),
      h("span", { class: "sum-track" }, bar), h("span", { class: "mono sum-bar-v", text: duration(p.minutes) }));
  });
}

// A semana com setas para as anteriores (só os totais, sem cara de cobrança).
function weekSlot(data, onChange) {
  const slot = h("div", { class: "sum-week" });
  let back = 0, oldest = null, seq = 0;
  const weeks = { 0: data.week };
  function paint() {
    const w = weeks[back];
    const atual = back === 0;
    const label = atual ? "Esta semana" : back === 1 ? "Semana passada" : `${shortDate(w.start)} a ${shortDate(w.end)}`;
    const prev = h("button", { type: "button", class: "icon", title: "Semana anterior", "aria-label": "Semana anterior", onClick: () => go(back + 1) }, icon("left"));
    const next = h("button", { type: "button", class: "icon", title: "Próxima semana", "aria-label": "Próxima semana", onClick: () => go(back - 1) }, icon("right"));
    prev.disabled = oldest !== null && back >= oldest;
    next.disabled = atual;
    const nav = h("div", { class: "day-nav" }, prev, h("span", { class: "day-nav-label", "aria-live": "polite", text: label }), next);
    const sub = atual ? `desde ${longDate(w.start).split(",")[0]}` : `${shortDate(w.start)} a ${shortDate(w.end)}`;
    clear(slot);
    slot.append(card(atual ? "Esta semana" : "Semana", sub, w, onChange, nav));
    // Revisão guiada (o que fechou, o que ficou, o que vem): em qualquer dia, daqui.
    if (atual) slot.querySelector(".sum-card").append(h("button", { type: "button", class: "btn btn-ghost btn-sm sum-review",
      onClick: () => openReview(onChange) }, icon("check"), data.review && data.review.reviewed ? "Revisar a semana de novo" : "Revisar a semana"));
  }
  async function go(n) {
    if (n < 0) return;
    const my = ++seq;
    if (!weeks[n]) {
      slot.classList.add("refreshing");
      try {
        const r = await api.get(`/summary/week?back=${n}`);
        weeks[n] = r.week;
        oldest = r.oldest;
      } catch (e) { errorToast(e); return; }
      finally { slot.classList.remove("refreshing"); }
    }
    if (my !== seq) return; // cliques rápidos: vale o último
    back = n;
    paint();
  }
  paint();
  return slot;
}

// Hoje: o último dia útil e a semana até agora, só com os totais.
export function summaryPanel(data, onChange) {
  const last = data.last_day;
  // Do último dia útil até ontem: na segunda, sexta a domingo (plantão incluso).
  const ontem = last.start === addDays(data.today, -1);
  const lastTitle = ontem ? "Ontem" : "Desde o último dia útil";
  const lastSub = ontem ? longDate(last.start) : `${shortDate(last.start)} a ${shortDate(last.end)}`;
  return h("section", { class: "panel t-sum" },
    h("div", { class: "sum-grid" }, card(lastTitle, lastSub, last, onChange), weekSlot(data, onChange)));
}
