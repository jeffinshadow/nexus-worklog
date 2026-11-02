// "Primeiro amanhã": no fechamento do dia (o resumo do dia do assistente e a
// Passagem de turno), escolher até 3 tarefas para começar o próximo dia útil.
// Nesse dia elas abrem as abertas do Hoje com o selo "primeiro hoje"; passado
// o dia, ou concluídas, saem sozinhas. Fica no servidor (vale em todos os
// aparelhos). A revisão da semana grava no mesmo campo (as prioridades
// escolhidas viram o primeiro do próximo dia útil): não há outra escolha.
import { api } from "./api.js";
import { h, icon, clear, shortDate, addDays } from "./dom.js";
import { errorToast, modal, pager, pageSlice, toast } from "./ui.js";
import { projectChip } from "./projects.js";

const FIRST_MAX = 3;
const PAGE = 8;
const WEEK = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"];

// "amanhã" ou "na segunda (03/11)": o próximo dia útil, dito como se fala.
function firstDayLabel(day, today) {
  if (day === addDays(today, 1)) return "amanhã";
  const wd = new Date(day + "T12:00:00").getDay();
  return `${wd === 0 || wd === 6 ? "no" : "na"} ${WEEK[wd]} (${shortDate(day)})`;
}

// O texto do botão que abre a escolha (com o que já está escolhido).
export function firstLabel(b) {
  const n = b.in_progress.filter((t) => t.first_on === b.first_day).length;
  const quando = firstDayLabel(b.first_day, b.today);
  return n ? `Primeiro ${quando}: ${n} ${n === 1 ? "escolhida" : "escolhidas"}` : `Escolher o primeiro de ${quando}`;
}

// b: o /board já carregado (opcional). onDone: depois de salvar.
export async function pickFirst(onDone, b = null) {
  try { b = b || await api.get("/board"); } catch (e) { errorToast(e, "Não foi possível abrir as tarefas."); return; }
  const day = b.first_day, quando = firstDayLabel(day, b.today);
  // Aguardando depende de outra pessoa: não entra. A ordem é a do Hoje (prazo e prioridade primeiro).
  const lista = b.in_progress.filter((t) => t.status !== "blocked" && !t.pending);
  const chosen = new Set(lista.filter((t) => t.first_on === day).map((t) => t.id));
  let page = 1;

  const title = h("h2", { text: `Primeiro ${quando}` });
  title.tabIndex = -1;
  const count = h("p", { class: "review-count", "aria-live": "polite" });
  const box = h("div", { class: "review-list" });
  const body = h("div", { class: "review-body" }, count, box);
  const save = h("button", { type: "submit", class: "btn btn-primary", text: "Salvar" });
  const close = h("button", { type: "button", class: "icon review-close", title: "Fechar", "aria-label": "Fechar sem salvar",
    onClick: () => dlg.close() }, icon("close"));
  const form = h("form", { class: "review-form" }, close, title,
    h("p", { class: "review-intro", text: lista.length
      ? `Marque até ${FIRST_MAX} tarefas para começar ${quando}. Elas abrem o Hoje desse dia, no topo das abertas, e saem sozinhas depois.`
      : "Não há tarefas em aberto para escolher. O que surgir, registre no Hoje." }),
    body,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
      lista.length ? save : null));

  const paint = () => {
    count.textContent = `${chosen.size} de ${FIRST_MAX} escolhidas`;
    clear(box);
    const { rows, page: p } = pageSlice(lista, page, PAGE);
    page = p;
    for (const t of rows) {
      const on = chosen.has(t.id);
      const pick = h("button", { type: "button", class: "btn btn-sm btn-ghost review-pick", "aria-pressed": String(on),
        "aria-label": `Escolher: ${t.title}`, text: on ? "Escolhida" : "Escolher", // o estado vai só no aria-pressed (não lido duas vezes)
        onClick: () => {
          if (chosen.has(t.id)) chosen.delete(t.id);
          else if (chosen.size < FIRST_MAX) chosen.add(t.id);
          else { toast(`Até ${FIRST_MAX}. Desmarque uma para trocar.`); return; }
          paint();
          box.querySelector(`[data-id="${t.id}"] .review-pick`)?.focus();
        } });
      const chips = [];
      if (t.due_date) chips.push(h("span", { class: "chip" + (t.due_date < b.today ? " late" : t.due_date === b.today ? " today" : ""),
        text: t.due_date < b.today ? `atrasada · ${shortDate(t.due_date)}` : t.due_date === b.today ? "vence hoje" : `prazo ${shortDate(t.due_date)}` }));
      if (t.priority === 1) chips.push(h("span", { class: "chip prio-1", text: "alta" }));
      // O projeto como nos cartões (ícone e nome, sem a pílula): a coluna alinha com ou sem selo.
      if (t.project_name) chips.push(projectChip({ project_name: t.project_name, project_color: t.project_color, project_icon: t.project_icon }));
      box.append(h("div", { class: "review-row" + (on ? " decided" : ""), "data-id": String(t.id) },
        h("div", { class: "review-t" }, h("span", { class: "review-title", text: t.title }),
          chips.length ? h("span", { class: "card-meta" }, ...chips) : null),
        h("div", { class: "review-acts" }, pick)));
    }
    const nav = pager({ page, total: lista.length, size: PAGE, label: "tarefas em aberto", compact: true,
      onPage: (n) => { page = n; paint(); }, focus: title });
    if (nav) box.append(nav);
  };
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    save.disabled = true;
    try {
      // Na ordem da lista (a do Hoje): é a ordem em que elas aparecem no dia.
      const ids = lista.filter((t) => chosen.has(t.id)).map((t) => t.id);
      await api.put("/board/first", { day, ids });
      dlg.close();
      toast(ids.length ? `Pronto: ${ids.length === 1 ? "ela abre" : "elas abrem"} o Hoje ${quando}.` : `Nada escolhido para ${quando}.`);
      if (onDone) onDone();
    } catch (e) { save.disabled = false; errorToast(e, "Não foi possível salvar."); }
  });
  const dlg = modal(form);
  dlg.classList.add("review-dialog", "first-dialog");
  paint();
  (box.querySelector(".review-pick") || title).focus();
}
