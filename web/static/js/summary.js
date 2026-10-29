// Resumos da tela Hoje: o último dia útil e a semana até agora (comparada
// com os mesmos dias da semana passada). Dados de /api/summary. As setas do
// card da semana voltam às semanas anteriores (/api/summary/week?back=N),
// cada uma comparada com a semana inteira antes dela.
import { api } from "./api.js";
import { h, icon, clear, longDate, shortDate, addDays } from "./dom.js";
import { errorToast } from "./ui.js";
import { projectChip } from "./projects.js";
import { duration, openTask } from "./task.js";

function pct(done, total) {
  return total ? Math.round((100 * done) / total) : null;
}

// "+3" / "−1h" comparando com o período anterior.
let compared = "os mesmos dias da semana passada";
function delta(now, before, fmt = String) {
  const d = now - before;
  if (!d) return h("span", { class: "delta", text: "=" , title: "igual a " + compared });
  const sign = d > 0 ? "+" : "−";
  return h("span", { class: "delta " + (d > 0 ? "up" : "down"), title: "comparado com " + compared, text: sign + fmt(Math.abs(d)) });
}

function figures(s, prev) {
  const p = pct(s.recurring_done, s.recurring_total);
  const fig = (value, label, d) => h("div", { class: "fig" }, h("p", { class: "fig-n" }, value, d || null), h("p", { class: "fig-l", text: label }));
  return h("div", { class: "figs" },
    fig(s.recurring_total ? `${p}%` : "—", s.recurring_total ? `rotinas · ${s.recurring_done}/${s.recurring_total}` : "sem rotinas devidas",
      prev && prev.recurring_total && s.recurring_total ? delta(p, pct(prev.recurring_done, prev.recurring_total), (x) => x + "pp") : null),
    fig(String(s.pontual_done), s.pontual_done === 1 ? "tarefa concluída" : "tarefas concluídas", prev ? delta(s.pontual_done, prev.pontual_done) : null),
    fig(s.minutes ? duration(s.minutes) : "—", "tempo apontado", prev && (s.minutes || prev.minutes) ? delta(s.minutes, prev.minutes, duration) : null));
}

function card(title, sub, s, prev, onChange, nav = null) {
  const body = [nav, figures(s, prev)].filter(Boolean);
  if (s.deliveries.length) {
    body.push(h("p", { class: "sum-h", text: "Concluído" }));
    for (const d of s.deliveries.slice(0, 5))
      body.push(h("div", { class: "sum-row" },
        h("button", { type: "button", class: "card-open", text: d.title, onClick: () => openTask(d.id, onChange) }),
        projectChip({ project_name: d.project, project_color: d.project_color }),
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

// Barras "tempo por projeto" (resumo do Hoje e Retrospectiva): {name, color, minutes}.
export function projectBars(items) {
  const comTempo = items.filter((p) => p.minutes);
  const top = Math.max(...comTempo.map((p) => p.minutes), 1);
  return comTempo.map((p) => {
    const bar = h("span");
    bar.style.width = `${Math.round((100 * p.minutes) / top)}%`;
    bar.style.background = p.color || "var(--dim)";
    return h("div", { class: "sum-bar" }, h("span", { class: "sum-bar-l", text: p.name || "Sem projeto" }),
      h("span", { class: "sum-track" }, bar), h("span", { class: "mono sum-bar-v", text: duration(p.minutes) }));
  });
}

export function summaryPanel(data, onChange) {
  const last = data.last_day;
  // Do último dia útil até ontem: na segunda, sexta a domingo (plantão incluso).
  const ontem = last.start === addDays(data.today, -1);
  const lastTitle = ontem ? "Ontem" : "Desde o último dia útil";
  const lastSub = ontem ? longDate(last.start) : `${shortDate(last.start)} a ${shortDate(last.end)}`;
  const slot = h("div", { class: "sum-week" });
  let back = 0, oldest = null, seq = 0;
  const weeks = { 0: data.week };
  function paint() {
    const w = weeks[back];
    const atual = back === 0;
    compared = atual ? "os mesmos dias da semana passada" : "a semana anterior";
    const label = atual ? "Esta semana" : back === 1 ? "Semana passada" : `${shortDate(w.start)} a ${shortDate(w.end)}`;
    const prev = h("button", { type: "button", class: "icon", title: "Semana anterior", "aria-label": "Semana anterior", onClick: () => go(back + 1) }, icon("left"));
    const next = h("button", { type: "button", class: "icon", title: "Próxima semana", "aria-label": "Próxima semana", onClick: () => go(back - 1) }, icon("right"));
    prev.disabled = oldest !== null && back >= oldest;
    next.disabled = atual;
    const nav = h("div", { class: "day-nav" }, prev, h("span", { class: "day-nav-label", "aria-live": "polite", text: label }), next);
    const sub = atual ? `desde ${longDate(w.start).split(",")[0]} · vs. semana passada`
      : `${shortDate(w.start)} a ${shortDate(w.end)} · vs. semana anterior`;
    clear(slot);
    slot.append(card(atual ? "Esta semana" : "Semana", sub, w, w.previous, onChange, nav));
    compared = "os mesmos dias da semana passada";
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
  return h("section", { class: "panel t-sum" },
    h("div", { class: "sum-grid" }, card(lastTitle, lastSub, last, null, onChange), slot));
}
