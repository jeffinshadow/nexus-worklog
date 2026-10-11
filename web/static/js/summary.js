// Resumos da tela Hoje: o último dia útil e a semana até agora (comparada
// com os mesmos dias da semana passada). Dados de /api/summary.
import { h, icon, longDate, addDays } from "./dom.js";
import { projectChip } from "./projects.js";
import { duration, openTask } from "./task.js";

function pct(done, total) {
  return total ? Math.round((100 * done) / total) : null;
}

// "+3" / "−1h" comparando com o período anterior.
function delta(now, before, fmt = String) {
  const d = now - before;
  if (!d) return h("span", { class: "delta", text: "=" , title: "igual à semana passada" });
  const sign = d > 0 ? "+" : "−";
  return h("span", { class: "delta " + (d > 0 ? "up" : "down"), title: "comparado com os mesmos dias da semana passada", text: sign + fmt(Math.abs(d)) });
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

function card(title, sub, s, prev, onChange) {
  const body = [figures(s, prev)];
  if (s.deliveries.length) {
    body.push(h("p", { class: "sum-h", text: "Concluído" }));
    for (const d of s.deliveries.slice(0, 5))
      body.push(h("div", { class: "sum-row" },
        h("button", { type: "button", class: "card-open", text: d.title, onClick: () => openTask(d.id, onChange) }),
        projectChip({ project_name: d.project, project_color: d.project_color }),
        d.minutes ? h("span", { class: "tag" }, icon("clock"), duration(d.minutes)) : null));
    if (s.deliveries.length > 5) body.push(h("p", { class: "muted small", text: `+ ${s.deliveries.length - 5} outras` }));
  }
  if (s.projects.some((p) => p.minutes)) {
    body.push(h("p", { class: "sum-h", text: "Tempo por projeto" }));
    const top = Math.max(...s.projects.map((p) => p.minutes), 1);
    for (const p of s.projects.filter((x) => x.minutes)) {
      const bar = h("span");
      bar.style.width = `${Math.round((100 * p.minutes) / top)}%`;
      bar.style.background = p.color || "var(--dim)";
      body.push(h("div", { class: "sum-bar" }, h("span", { class: "sum-bar-l", text: p.name || "Sem projeto" }),
        h("span", { class: "sum-track" }, bar), h("span", { class: "mono sum-bar-v", text: duration(p.minutes) })));
    }
  }
  if (s.missed.length) {
    body.push(h("p", { class: "sum-h", text: "Rotinas que ficaram para trás" }),
      h("p", { class: "missed" }, ...s.missed.map((m) => h("span", { class: "chip late", text: m }))));
  }
  if (!s.deliveries.length && !s.minutes && !s.recurring_done && !s.missed.length)
    body.push(h("p", { class: "empty", text: "Nada registrado." }));
  return h("div", { class: "sum-card" }, h("div", { class: "sum-title" }, h("h3", { text: title }), h("span", { class: "mono muted", text: sub })), ...body);
}

export function summaryPanel(data, onChange) {
  const last = data.last_day;
  const ontem = last.start === addDays(data.today, -1);
  const lastTitle = ontem ? "Ontem" : "Último dia útil";
  const w = data.week;
  return h("section", { class: "panel t-sum" },
    h("div", { class: "sum-grid" },
      card(lastTitle, longDate(last.start), last, null, onChange),
      card("Esta semana", `desde ${longDate(w.start).split(",")[0]} · vs. semana passada`, w, w.previous, onChange)));
}
