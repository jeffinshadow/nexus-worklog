// Resumo do Hoje: o último dia útil, só com os totais.
// Dados de /api/summary. (O passado fica em Meu mês e na revisão da semana.)
import { h, icon, longDate, shortDate, addDays } from "./dom.js";
import { projectChip, corProjeto } from "./projects.js";
import { duration, openTask } from "./task.js";

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

function card(title, sub, s, onChange) {
  const body = [figures(s)];
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
  if (!s.deliveries.length && !s.minutes && !s.recurring_done)
    body.push(h("p", { class: "empty", text: "Nada registrado." }));
  return h("div", { class: "sum-card" }, h("div", { class: "sum-title" }, h("h3", { text: title }), h("span", { class: "mono muted", text: sub })), ...body);
}

// Barras "tempo por projeto" (resumo do Hoje e Meu mês): {name, color, minutes}.
function projectBars(items) {
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

// Hoje: só o último dia útil (a semana vive em Meu mês e na revisão da semana).
export function summaryPanel(data, onChange) {
  const last = data.last_day;
  // Do último dia útil até ontem: na segunda, sexta a domingo (plantão incluso).
  const ontem = last.start === addDays(data.today, -1);
  const lastTitle = ontem ? "Ontem" : "Desde o último dia útil";
  const lastSub = ontem ? longDate(last.start) : `${shortDate(last.start)} a ${shortDate(last.end)}`;
  // Nada previsto nem feito no último dia útil (a conta nova, por exemplo): sem um cartão vazio.
  const vazio = !last.recurring_total && !last.recurring_done && !last.pontual_done && !last.minutes && !last.deliveries.length;
  if (vazio) return null;
  return h("section", { class: "panel t-sum" }, card(lastTitle, lastSub, last, onChange));
}
