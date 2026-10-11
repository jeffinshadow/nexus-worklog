import { api } from "./api.js";
import { h, icon, clear, formatDate } from "./dom.js";

const WEEKDAYS_SHORT = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];

// Datas ISO (YYYY-MM-DD) tratadas em UTC: o "hoje" vem do servidor (fuso do
// app), então o navegador só soma/subtrai dias, sem depender do fuso local.
function addDays(iso, n) {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + n));
  return dt.toISOString().slice(0, 10);
}
function dayLabel(iso, today) {
  if (iso === today) return "Hoje";
  if (iso === addDays(today, -1)) return "Ontem";
  const [y, m, d] = iso.split("-").map(Number);
  const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return `${WEEKDAYS_SHORT[wd]}, ${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}`;
}

const STATUS_LABELS = {
  todo: "A fazer",
  in_progress: "Em andamento",
  blocked: "Bloqueado",
  done: "Concluído",
};

// root: elemento onde o board sera montado.
// opts.readOnly: esconde controles (visao de admin).
// opts.boardUrl: endpoint GET do board (default a propria conta).
export async function mount(root, opts = {}) {
  const readOnly = !!opts.readOnly;
  const boardUrl = opts.boardUrl || "/board";

  clear(root);
  let day = null; // dia das recorrentes (null = hoje, decidido pelo servidor)
  const daily = column("Tarefas Recorrentes Diárias", readOnly ? null : () => openRecurring(null));
  // Seletor de dia: volta até a janela que o servidor informa (min_day).
  const prevBtn = h("button", { class: "icon", title: "Dia anterior", "aria-label": "Dia anterior", text: "‹" });
  const nextBtn = h("button", { class: "icon", title: "Próximo dia", "aria-label": "Próximo dia", text: "›" });
  const dayText = h("span", { class: "day-nav-label", "aria-live": "polite" });
  const dayNote = h("p", { class: "day-note hidden" });
  daily.section.insertBefore(
    h("div", { class: "day-nav" }, prevBtn, dayText, nextBtn),
    daily.body
  );
  daily.section.insertBefore(dayNote, daily.body);
  let current = null;
  prevBtn.addEventListener("click", () => { day = addDays(current.day, -1); refresh(); });
  nextBtn.addEventListener("click", () => { day = addDays(current.day, 1); refresh(); });
  const wip = column("Tarefas Pontuais", readOnly ? null : () => openWorklog(null));
  // "Finalizadas" é colapsável: no mobile fica oculta num dropdown por padrão
  // (só o cabeçalho/contador aparece). No desktop o toggle some e a coluna rola.
  const done = column("Tarefas Finalizadas", null, { collapsible: true, className: "column-done" });
  root.append(h("div", { class: "columns" }, daily.section, wip.section, done.section));

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
    renderCards(wip, data.in_progress, false);
    renderCards(done, data.done, true);
  }

  function renderDaily(items) {
    clear(daily.body);
    daily.count.textContent =
      items.filter((i) => i.done_today).length + "/" + items.length;
    if (!items.length) {
      daily.body.append(h("p", { class: "empty", text: "Sem recorrentes neste dia." }));
      return;
    }
    for (const it of items) {
      const cb = h("input", { type: "checkbox" });
      cb.checked = it.done_today;
      if (readOnly) cb.disabled = true;
      else
        cb.addEventListener("change", async () => {
          try {
            await api.post(`/recurring/${it.id}/toggle`, { done: cb.checked, day: current.day });
            refresh();
          } catch (e) {
            cb.checked = !cb.checked;
            alert("Erro ao salvar.");
          }
        });
      const row = h(
        "div",
        { class: "check-row" + (it.done_today ? " done" : "") },
        cb,
        h("span", { class: "label", text: it.label })
      );
      if (!readOnly)
        row.append(
          h("button", { class: "icon", title: "Editar", onClick: () => openRecurring(it) }, icon("edit"))
        );
      daily.body.append(row);
    }
  }

  function renderCards(col, items, isDone) {
    clear(col.body);
    col.count.textContent = String(items.length);
    if (!items.length) {
      col.body.append(
        h("p", { class: "empty", text: isDone ? "Nada finalizado." : "Nada em andamento." })
      );
      return;
    }
    for (const it of items) {
      const card = h("div", { class: "card" }, h("h3", { text: it.title }));
      if (it.description) card.append(h("p", { text: it.description }));

      const meta = h(
        "div",
        { class: "card-meta" },
        h("span", { class: "chip " + it.status, text: STATUS_LABELS[it.status] })
      );
      if (it.due_date && !isDone)
        meta.append(h("span", { class: "chip", text: "Prev: " + formatDate(it.due_date) }));
      if (isDone && it.completed_at)
        meta.append(h("span", { class: "chip done", text: "Fim: " + formatDate(it.completed_at) }));
      card.append(meta);

      if (!readOnly) {
        const actions = h("div", { class: "card-actions" });
        if (!isDone)
          actions.append(
            h("button", { class: "icon", title: "Finalizar", onClick: () => finishTask(it) }, icon("check"))
          );
        actions.append(
          h("button", { class: "icon", title: "Editar", onClick: () => openWorklog(it) }, icon("edit"))
        );
        card.append(actions);
      }
      col.body.append(card);
    }
  }

  async function finishTask(it) {
    try {
      await api.post(`/worklog/${it.id}/finish`);
      refresh();
    } catch (e) {
      alert("Erro ao finalizar.");
    }
  }

  // ---- Dialogos (elementos globais em index.html) ----
  const dlgRec = document.getElementById("dialog-recurring");
  const dlgWl = document.getElementById("dialog-worklog");

  function openRecurring(item) {
    document.getElementById("dlg-rec-title").textContent = item
      ? "Editar recorrente"
      : "Nova recorrente";
    const input = document.getElementById("rec-label");
    input.value = item ? item.label : "";

    const del = document.getElementById("rec-delete");
    del.classList.toggle("hidden", !item);
    del.onclick = item
      ? async () => {
          if (!confirm("Remover esta recorrente? O histórico é preservado.")) return;
          try {
            await api.del(`/recurring/${item.id}`);
            dlgRec.close();
            refresh();
          } catch (e) {
            alert("Erro ao remover.");
          }
        }
      : null;

    document.getElementById("rec-cancel").onclick = () => dlgRec.close();
    document.getElementById("form-recurring").onsubmit = async (ev) => {
      ev.preventDefault();
      const label = input.value.trim();
      if (!label) return;
      try {
        if (item) await api.patch(`/recurring/${item.id}`, { label });
        else await api.post("/recurring", { label });
        dlgRec.close();
        refresh();
      } catch (e) {
        alert("Erro ao salvar.");
      }
    };
    dlgRec.showModal();
  }

  function openWorklog(item) {
    document.getElementById("dlg-wl-title").textContent = item ? "Editar tarefa" : "Nova tarefa";
    document.getElementById("wl-title").value = item ? item.title : "";
    document.getElementById("wl-desc").value = item && item.description ? item.description : "";
    document.getElementById("wl-status").value = item ? item.status : "todo";
    document.getElementById("wl-due").value = item && item.due_date ? item.due_date : "";

    const del = document.getElementById("wl-delete");
    del.classList.toggle("hidden", !item);
    del.onclick = item
      ? async () => {
          if (!confirm("Excluir esta tarefa?")) return;
          try {
            await api.del(`/worklog/${item.id}`);
            dlgWl.close();
            refresh();
          } catch (e) {
            alert("Erro ao excluir.");
          }
        }
      : null;

    document.getElementById("wl-cancel").onclick = () => dlgWl.close();
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
        dlgWl.close();
        refresh();
      } catch (e) {
        alert("Erro ao salvar.");
      }
    };
    dlgWl.showModal();
  }

  await refresh();
}

function column(title, onAdd, opts = {}) {
  const count = h("span", { class: "count-badge" });
  const head = h("div", { class: "column-head" }, h("h2", { text: title }), count);
  if (onAdd)
    head.append(h("button", { class: "icon", title: "Adicionar", onClick: onAdd }, icon("edit")));
  const body = h("div", { class: "column-body" });
  const section = h("section", { class: "column" + (opts.className ? " " + opts.className : "") }, head, body);
  if (opts.collapsible) {
    const toggle = h(
      "button",
      {
        class: "icon column-toggle",
        title: "Mostrar/ocultar",
        "aria-expanded": "false",
        onClick: () => {
          const open = section.classList.toggle("expanded");
          toggle.setAttribute("aria-expanded", open ? "true" : "false");
        },
      },
      icon("chevron")
    );
    head.append(toggle);
  }
  return { section, body, count };
}
