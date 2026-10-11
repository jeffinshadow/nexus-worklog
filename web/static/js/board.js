// Quadro de tarefas: recorrentes (com seletor de dia), pontuais abertas e
// concluídas. Também exporta os diálogos de criar/editar, usados pela tela Hoje.
import { api } from "./api.js";
import { h, icon, clear, addDays, shortDate } from "./dom.js";
import { confirmDialog, errorToast, toast, undoLatest } from "./ui.js";

const WEEKDAYS_SHORT = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const DONE_PAGE = 10;

export const STATUS_LABELS = {
  todo: "a fazer",
  in_progress: "em andamento",
  blocked: "bloqueada",
  done: "concluída",
};

function dayLabel(iso, today) {
  if (iso === today) return "Hoje";
  if (iso === addDays(today, -1)) return "Ontem";
  const [y, m, d] = iso.split("-").map(Number);
  const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return `${WEEKDAYS_SHORT[wd]}, ${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}`;
}

// Chips de status e prazo de uma tarefa pontual (compartilhado com a tela Hoje).
export function taskChips(t, today) {
  const chips = [h("span", { class: "chip " + t.status, text: STATUS_LABELS[t.status] })];
  if (t.status === "done") {
    if (t.completed_at) chips.push(h("span", { class: "chip done", text: "fim " + shortDate(t.completed_at) }));
  } else if (t.due_date) {
    if (t.due_date < today) chips.push(h("span", { class: "chip late", text: "atrasada · " + shortDate(t.due_date) }));
    else if (t.due_date === today) chips.push(h("span", { class: "chip today", text: "vence hoje" }));
    else chips.push(h("span", { class: "chip", text: "prazo " + shortDate(t.due_date) }));
  }
  return chips;
}

export function isOverdue(t, today) {
  return t.status !== "done" && t.due_date && t.due_date < today;
}

// ------------------------------------------------------- diálogos (export) --

export function openWorklog(item, onDone) {
  const dlg = document.getElementById("dialog-worklog");
  document.getElementById("dlg-wl-title").textContent = item ? "Editar tarefa" : "Nova tarefa";
  document.getElementById("wl-title").value = item ? item.title : "";
  document.getElementById("wl-desc").value = item && item.description ? item.description : "";
  document.getElementById("wl-status").value = item ? item.status : "todo";
  document.getElementById("wl-due").value = item && item.due_date ? item.due_date : "";

  const del = document.getElementById("wl-delete");
  del.classList.toggle("hidden", !item);
  del.onclick = item
    ? async () => {
        dlg.close();
        if (!(await confirmDialog({ title: "Excluir tarefa?", text: `“${item.title}” sai do quadro. Dá para desfazer pelo histórico.`, confirm: "Excluir", danger: true }))) return;
        try {
          await api.del(`/worklog/${item.id}`);
          onDone && onDone();
          toast("Tarefa excluída.", { action: "Desfazer", onAction: () => undoLatest("worklog", item.id, onDone) });
        } catch (e) {
          errorToast(e, "Erro ao excluir.");
        }
      }
    : null;

  document.getElementById("wl-cancel").onclick = () => dlg.close();
  document.getElementById("form-worklog").onsubmit = async (ev) => {
    ev.preventDefault();
    const payload = {
      title: document.getElementById("wl-title").value.trim(),
      description: document.getElementById("wl-desc").value.trim() || null,
      status: document.getElementById("wl-status").value,
      due_date: document.getElementById("wl-due").value || null,
    };
    if (!payload.title) return;
    try {
      if (item) await api.patch(`/worklog/${item.id}`, payload);
      else await api.post("/worklog", payload);
      dlg.close();
      onDone && onDone();
    } catch (e) {
      errorToast(e, "Erro ao salvar.");
    }
  };
  dlg.showModal();
  document.getElementById("wl-title").focus();
}

export function openRecurring(item, onDone) {
  const dlg = document.getElementById("dialog-recurring");
  document.getElementById("dlg-rec-title").textContent = item ? "Editar recorrente" : "Nova recorrente";
  const input = document.getElementById("rec-label");
  input.value = item ? item.label : "";

  const del = document.getElementById("rec-delete");
  del.classList.toggle("hidden", !item);
  del.onclick = item
    ? async () => {
        dlg.close();
        if (!(await confirmDialog({ title: "Remover recorrente?", text: "Ela sai do quadro a partir de hoje. O histórico de dias feitos é preservado.", confirm: "Remover", danger: true }))) return;
        try {
          await api.del(`/recurring/${item.id}`);
          onDone && onDone();
          toast("Recorrente removida.", { action: "Desfazer", onAction: () => undoLatest("recurring", item.id, onDone) });
        } catch (e) {
          errorToast(e, "Erro ao remover.");
        }
      }
    : null;

  document.getElementById("rec-cancel").onclick = () => dlg.close();
  document.getElementById("form-recurring").onsubmit = async (ev) => {
    ev.preventDefault();
    const label = input.value.trim();
    if (!label) return;
    try {
      if (item) await api.patch(`/recurring/${item.id}`, { label });
      else await api.post("/recurring", { label });
      dlg.close();
      onDone && onDone();
    } catch (e) {
      errorToast(e, "Erro ao salvar.");
    }
  };
  dlg.showModal();
  input.focus();
}

export async function finishTask(t, onDone) {
  try {
    await api.post(`/worklog/${t.id}/finish`);
    onDone && onDone();
    toast(`Concluída: ${t.title}`, { action: "Desfazer", onAction: () => undoLatest("worklog", t.id, onDone) });
  } catch (e) {
    errorToast(e, "Erro ao concluir.");
  }
}

// ---------------------------------------------------------------- quadro --

// root: onde montar. opts.readOnly (visão do admin), opts.boardUrl.
export async function mount(root, opts = {}) {
  const readOnly = !!opts.readOnly;
  const boardUrl = opts.boardUrl || "/board";
  let day = null;
  let current = null;
  let doneShown = DONE_PAGE;

  clear(root);
  const daily = column("Recorrentes", readOnly ? null : () => openRecurring(null, refresh), "Nova recorrente");
  const wip = column("Pontuais", readOnly ? null : () => openWorklog(null, refresh), "Nova tarefa");
  const done = column("Concluídas", null, null, { collapsible: true, className: "column-done" });
  root.append(h("div", { class: "columns" }, daily.section, wip.section, done.section));

  if (opts.setActions && !readOnly) {
    opts.setActions(
      h("button", { type: "button", class: "btn btn-ghost", onClick: () => openRecurring(null, refresh) }, icon("add"), "Recorrente"),
      h("button", { type: "button", class: "btn btn-primary", onClick: () => openWorklog(null, refresh) }, icon("add"), "Tarefa")
    );
  }

  const prevBtn = h("button", { type: "button", class: "icon", title: "Dia anterior", "aria-label": "Dia anterior" }, icon("left"));
  const nextBtn = h("button", { type: "button", class: "icon", title: "Próximo dia", "aria-label": "Próximo dia" }, icon("right"));
  const dayText = h("span", { class: "day-nav-label", "aria-live": "polite" });
  const dayNote = h("p", { class: "day-note hidden" });
  daily.section.insertBefore(h("div", { class: "day-nav" }, prevBtn, dayText, nextBtn), daily.body);
  daily.section.insertBefore(dayNote, daily.body);
  prevBtn.addEventListener("click", () => { day = addDays(current.day, -1); refresh(); });
  nextBtn.addEventListener("click", () => { day = addDays(current.day, 1); refresh(); });

  async function refresh() {
    const sep = boardUrl.includes("?") ? "&" : "?";
    const data = await api.get(day ? `${boardUrl}${sep}day=${day}` : boardUrl);
    current = data;
    day = data.day === data.today ? null : data.day;
    dayText.textContent = dayLabel(data.day, data.today);
    prevBtn.disabled = data.day <= data.min_day;
    nextBtn.disabled = data.day >= data.today;
    dayNote.classList.toggle("hidden", data.work_day);
    dayNote.textContent = data.work_day ? "" : "Dia não útil: o que for marcado conta como extra.";
    renderDaily(data.recurring);
    renderCards(wip, data.in_progress, false, data.today);
    renderCards(done, data.done, true, data.today);
  }

  function renderDaily(items) {
    clear(daily.body);
    daily.count.textContent = `${items.filter((i) => i.done_today).length}/${items.length}`;
    if (!items.length) {
      daily.body.append(h("p", { class: "empty", text: "Sem recorrentes neste dia." }));
      return;
    }
    for (const it of items) {
      const cb = h("input", { type: "checkbox", "aria-label": it.label });
      cb.checked = it.done_today;
      if (readOnly) cb.disabled = true;
      else
        cb.addEventListener("change", async () => {
          try {
            await api.post(`/recurring/${it.id}/toggle`, { done: cb.checked, day: current.day });
            refresh();
          } catch (e) {
            cb.checked = !cb.checked;
            errorToast(e, "Erro ao salvar.");
          }
        });
      const row = h("label", { class: "check-row" + (it.done_today ? " done" : "") }, cb, h("span", { class: "label", text: it.label }));
      if (!readOnly)
        row.append(h("button", {
          type: "button", class: "icon", title: "Editar", "aria-label": "Editar " + it.label,
          onClick: (ev) => { ev.preventDefault(); openRecurring(it, refresh); },
        }, icon("edit")));
      daily.body.append(row);
    }
  }

  function renderCards(col, items, isDone, today) {
    clear(col.body);
    col.count.textContent = String(items.length);
    if (!items.length) {
      col.body.append(h("p", { class: "empty", text: isDone ? "Nada concluído ainda." : "Nada aberto. Bom sinal." }));
      return;
    }
    const list = isDone ? items.slice(0, doneShown) : items;
    for (const it of list) {
      const card = h("article", { class: "card" + (isOverdue(it, today) ? " overdue" : "") }, h("h3", { text: it.title }));
      if (it.description) card.append(h("p", { text: it.description }));
      card.append(h("div", { class: "card-meta" }, ...taskChips(it, today)));
      if (!readOnly) {
        const actions = h("div", { class: "card-actions" });
        if (!isDone)
          actions.append(h("button", { type: "button", class: "icon", title: "Concluir", "aria-label": "Concluir " + it.title, onClick: () => finishTask(it, refresh) }, icon("check")));
        actions.append(h("button", { type: "button", class: "icon", title: "Editar", "aria-label": "Editar " + it.title, onClick: () => openWorklog(it, refresh) }, icon("edit")));
        card.append(actions);
      }
      col.body.append(card);
    }
    if (isDone && items.length > doneShown) {
      col.body.append(h("button", {
        type: "button", class: "btn btn-text show-more", text: `ver mais ${Math.min(DONE_PAGE, items.length - doneShown)} de ${items.length - doneShown}`,
        onClick: () => { doneShown += DONE_PAGE; renderCards(col, items, true, today); },
      }));
    }
  }

  await refresh();
}

function column(title, onAdd, addLabel, opts = {}) {
  const count = h("span", { class: "count-badge" });
  const head = h("div", { class: "column-head" }, h("h2", { text: title }), count);
  if (onAdd)
    head.append(h("button", { type: "button", class: "icon accent", title: addLabel, "aria-label": addLabel, onClick: onAdd }, icon("add")));
  const body = h("div", { class: "column-body" });
  const section = h("section", { class: "column" + (opts.className ? " " + opts.className : "") }, head, body);
  if (opts.collapsible) {
    const toggle = h("button", {
      type: "button", class: "icon column-toggle", title: "Mostrar/ocultar", "aria-expanded": "false",
      onClick: () => {
        const open = section.classList.toggle("expanded");
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
      },
    }, icon("chevron"));
    head.append(toggle);
  }
  return { section, body, count };
}
