// Quadro de tarefas: rotinas (com seletor de dia), tarefas abertas e
// concluídas. Também exporta os diálogos de criar/editar, usados pela tela Hoje.
import { api } from "./api.js";
import { h, icon, clear, addDays, shortDate } from "./dom.js";
import { confirmDialog, errorToast, toast, undoLatest } from "./ui.js";
import { fillProjectSelect, listProjects, projectChip } from "./projects.js";
import { openTask, duration, parseDuration } from "./task.js";

const WEEKDAYS_SHORT = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const DONE_PAGE = 10;
const BOARD_DONE_LIMIT = 200; // o servidor manda só as 200 concluídas mais recentes

const STATUS_LABELS = {
  todo: "a fazer",
  in_progress: "em andamento",
  blocked: "bloqueada",
  done: "concluída",
};

export function dayLabel(iso, today) {
  if (iso === today) return "Hoje";
  if (iso === addDays(today, -1)) return "Ontem";
  const [y, m, d] = iso.split("-").map(Number);
  const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return `${WEEKDAYS_SHORT[wd]}, ${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}`;
}

// Chips de uma tarefa (compartilhado com a tela Hoje): status,
// prioridade, prazo, projeto e os contadores de checklist/tempo/anotações.
export function taskChips(t, today) {
  // Concluída: a coluna já diz; fica só a data de fim.
  const chips = t.status === "done" ? [] : [h("span", { class: "chip " + t.status, text: STATUS_LABELS[t.status] })];
  if (t.priority === 1 && t.status !== "done") chips.push(h("span", { class: "chip prio-1", text: "alta" }));
  if (t.status === "done") {
    if (t.completed_at) chips.push(h("span", { class: "chip done", text: "fim " + shortDate(t.completed_at) }));
  } else if (t.due_date) {
    if (t.due_date < today) chips.push(h("span", { class: "chip late", text: "atrasada · " + shortDate(t.due_date) }));
    else if (t.due_date === today) chips.push(h("span", { class: "chip today", text: "vence hoje" }));
    else chips.push(h("span", { class: "chip", text: "prazo " + shortDate(t.due_date) }));
  }
  const pc = projectChip(t);
  if (pc) chips.push(pc);
  if (t.check_total) chips.push(h("span", { class: "tag" + (t.check_done === t.check_total ? " ok" : ""), title: "Checklist" }, icon("list"), `${t.check_done}/${t.check_total}`));
  if (t.minutes) chips.push(h("span", { class: "tag", title: "Tempo apontado" }, icon("clock"), duration(t.minutes)));
  if (t.notes_count) chips.push(h("span", { class: "tag", title: "Anotações" }, icon("note"), String(t.notes_count)));
  return chips;
}

// Resumo da agenda de uma rotina ("seg, qua", "todo dia 5", "a cada 15 dias").
const WD_ORDER = [1, 2, 3, 4, 5, 6, 0];
export function scheduleLabel(r) {
  if (r.freq === "weekly") {
    const days = WD_ORDER.filter((b) => (r.weekdays >> b) & 1).map((b) => WEEKDAYS_SHORT[b]);
    return days.length === 7 ? "todo dia" : days.join(", ");
  }
  if (r.freq === "monthly") return r.month_day >= 31 ? "último dia do mês" : `todo dia ${r.month_day}`;
  if (r.freq === "interval") return `a cada ${r.interval_days} dias`;
  return "";
}

export function isOverdue(t, today) {
  return t.status !== "done" && t.due_date && t.due_date < today;
}

// ------------------------------------------------------- diálogos (export) --

export function openWorklog(item, onDone, opts = {}) {
  const dlg = document.getElementById("dialog-worklog");
  document.getElementById("dlg-wl-title").textContent = item ? "Editar tarefa" : "Nova tarefa";
  document.getElementById("wl-title").value = item ? item.title : opts.title || "";
  document.getElementById("wl-desc").value = item && item.description ? item.description : "";
  document.getElementById("wl-status").value = item ? item.status : "todo";
  document.getElementById("wl-due").value = item && item.due_date ? item.due_date : "";
  document.getElementById("wl-prio").value = String(item ? item.priority || 2 : 2);
  // Tempo já na criação (técnico em campo: "Loja X, 2h"); depois, pelo detalhe.
  const timeInput = document.getElementById("wl-time");
  timeInput.value = "";
  document.getElementById("wl-time-wrap").classList.toggle("hidden", !!item);
  const projSel = document.getElementById("wl-project");
  fillProjectSelect(projSel, item ? item.project_id : null).catch(() => {});

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
      priority: Number(document.getElementById("wl-prio").value),
      project_id: projSel.value && projSel.value !== "__new" ? Number(projSel.value) : null,
    };
    if (!payload.title) return;
    const minutes = !item && timeInput.value.trim() ? parseDuration(timeInput.value) : null;
    if (minutes === null && !item && timeInput.value.trim()) { toast("Tempo inválido. Ex.: 45, 1h30, 2:15.", { error: true }); timeInput.focus(); return; }
    try {
      if (item) await api.patch(`/worklog/${item.id}`, payload);
      else {
        const created = await api.post("/worklog", payload);
        if (minutes) await api.post(`/worklog/${created.id}/time`, { minutes });
      }
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
  document.getElementById("dlg-rec-title").textContent = item ? "Editar rotina" : "Nova rotina";
  const input = document.getElementById("rec-label");
  input.value = item ? item.label : "";
  const sched = scheduleForm(item);

  const del = document.getElementById("rec-delete");
  del.classList.toggle("hidden", !item);
  del.onclick = item
    ? async () => {
        dlg.close();
        if (!(await confirmDialog({ title: "Excluir rotina?", text: "Ela sai do quadro a partir de hoje. O histórico de dias feitos é preservado.", confirm: "Excluir", danger: true }))) return;
        try {
          await api.del(`/recurring/${item.id}`);
          onDone && onDone();
          toast("Rotina excluída.", { action: "Desfazer", onAction: () => undoLatest("recurring", item.id, onDone) });
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
    const agenda = sched.value();
    if (!agenda) return;
    try {
      if (item) await api.patch(`/recurring/${item.id}`, { label, ...agenda });
      else await api.post("/recurring", { label, ...agenda });
      dlg.close();
      onDone && onDone();
    } catch (e) {
      errorToast(e, "Erro ao salvar.");
    }
  };
  dlg.showModal();
  input.focus();
}

// Campos de agenda do diálogo de rotina. value() devolve o corpo da API
// ({freq, weekdays|month_day|interval_days}) ou null se inválido.
function scheduleForm(item) {
  const freq = document.getElementById("rec-freq");
  const wdBox = document.getElementById("rec-weekdays");
  const md = document.getElementById("rec-monthday");
  const iv = document.getElementById("rec-interval");
  const wraps = { weekly: wdBox, monthly: document.getElementById("rec-monthday-wrap"), interval: document.getElementById("rec-interval-wrap") };

  if (!md.options.length) {
    for (let d = 1; d <= 30; d++) md.append(h("option", { value: String(d), text: `Dia ${d}` }));
    md.append(h("option", { value: "31", text: "Último dia do mês" }));
  }
  clear(wdBox);
  const mask = item && item.freq === "weekly" ? item.weekdays : 0b0111110;
  const boxes = WD_ORDER.map((bit) => {
    const cb = h("input", { type: "checkbox" });
    cb.checked = ((mask >> bit) & 1) === 1;
    wdBox.append(h("label", { class: "weekday-option" }, cb, h("span", { text: WEEKDAYS_SHORT[bit] })));
    return { bit, cb };
  });
  freq.value = item ? item.freq || "daily" : "daily";
  md.value = String(item && item.month_day ? item.month_day : 1);
  iv.value = String(item && item.interval_days ? item.interval_days : 15);
  const sync = () => { for (const [k, el] of Object.entries(wraps)) el.classList.toggle("hidden", freq.value !== k); };
  freq.onchange = sync;
  sync();

  return {
    value() {
      const f = freq.value;
      if (f === "weekly") {
        const m = boxes.reduce((acc, { bit, cb }) => (cb.checked ? acc | (1 << bit) : acc), 0);
        if (!m) { toast("Escolha pelo menos um dia da semana.", { error: true }); return null; }
        return { freq: f, weekdays: m };
      }
      if (f === "monthly") return { freq: f, month_day: Number(md.value) };
      if (f === "interval") {
        const n = Number(iv.value);
        if (!(n >= 2 && n <= 365)) { toast("Intervalo entre 2 e 365 dias.", { error: true }); return null; }
        return { freq: f, interval_days: n };
      }
      return { freq: "daily" };
    },
  };
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
  let doneShown = DONE_PAGE;
  let project = readOnly ? "" : sessionStorage.getItem("nexus.board.project") || "";

  clear(root);
  // Tarefas (as rotinas ficam na tela Hoje).
  const wip = column("Em aberto");
  const done = column("Concluídas", { collapsible: true, className: "column-done" });
  root.append(h("div", { class: "columns" }, wip.section, done.section));

  // Filtro por projeto (só no quadro do próprio usuário).
  const filter = h("select", { class: "select-sm", "aria-label": "Filtrar por projeto" });
  if (!readOnly) {
    try {
      const list = await listProjects(true);
      filter.append(h("option", { value: "", text: "Todos os projetos" }), h("option", { value: "0", text: "Sem projeto" }),
        ...list.map((p) => h("option", { value: String(p.id), text: p.name })));
      if (![...filter.options].some((o) => o.value === project)) project = "";
      filter.value = project;
      filter.addEventListener("change", () => {
        project = filter.value;
        sessionStorage.setItem("nexus.board.project", project);
        refresh();
      });
    } catch { /* sem filtro */ }
  }

  if (opts.setActions && !readOnly) {
    opts.setActions(
      filter.options.length > 2 ? filter : null,
      h("button", { type: "button", class: "btn btn-primary", onClick: () => openWorklog(null, refresh) }, icon("add"), "Tarefa")
    );
  }

  async function refresh() {
    const sep = boardUrl.includes("?") ? "&" : "?";
    const data = await api.get(project !== "" ? `${boardUrl}${sep}project=${project}` : boardUrl);
    renderCards(wip, data.in_progress, false, data.today);
    renderCards(done, data.done, true, data.today);
  }

  function renderCards(col, items, isDone, today) {
    clear(col.body);
    col.count.textContent = String(items.length);
    if (!items.length) {
      col.body.append(h("p", { class: "empty", text: isDone ? "Nada concluído ainda." : "Nada em aberto." }));
      return;
    }
    const list = isDone ? items.slice(0, doneShown) : items;
    for (const it of list) {
      const card = h("article", { class: "card" + (isOverdue(it, today) ? " overdue" : "") + (it.priority === 1 && !isDone ? " high" : "") },
        h("h3", {}, readOnly ? it.title : h("button", { type: "button", class: "card-open", text: it.title, onClick: () => openTask(it.id, refresh) })));
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
    if (isDone && items.length >= BOARD_DONE_LIMIT && doneShown >= items.length)
      col.body.append(h("p", { class: "muted small", text: `Mostrando as ${BOARD_DONE_LIMIT} mais recentes; as anteriores estão nos relatórios e na busca.` }));
    if (isDone && items.length > doneShown) {
      col.body.append(h("button", {
        type: "button", class: "btn btn-text show-more", text: `ver mais ${Math.min(DONE_PAGE, items.length - doneShown)} de ${items.length - doneShown}`,
        onClick: () => { doneShown += DONE_PAGE; renderCards(col, items, true, today); },
      }));
    }
  }

  await refresh();
}

function column(title, opts = {}) {
  const count = h("span", { class: "count-badge" });
  const head = h("div", { class: "column-head" }, h("h2", { text: title }), count);
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
