// Detalhe de uma tarefa pontual: checklist, tempo apontado e anotações.
// Abre por cima do quadro/Hoje; ao fechar, quem abriu recarrega (onChange).
import { api } from "./api.js";
import { h, icon, clear, addDays, shortDate, dateTime } from "./dom.js";
import { errorToast, toast, undoLatest } from "./ui.js";
import { projectChip } from "./projects.js";
import { STATUS_LABELS, openWorklog, finishTask } from "./board.js";

const PRIO = { 1: "prioridade alta", 3: "prioridade baixa" };

export function duration(min) {
  if (!min) return "0 min";
  const hh = Math.floor(min / 60), mm = min % 60;
  return hh ? `${hh}h${mm ? String(mm).padStart(2, "0") : ""}` : `${mm} min`;
}

// "1h30", "1:30", "90", "45m", "2h" → minutos (null se inválido).
export function parseDuration(text) {
  const s = String(text).trim().toLowerCase().replace(",", ".");
  let m;
  if ((m = s.match(/^(\d+):(\d{1,2})$/))) return +m[1] * 60 + +m[2];
  if ((m = s.match(/^(\d+(?:\.\d+)?)\s*h\s*(\d{1,2})?\s*(?:m|min)?$/))) return Math.round(+m[1] * 60) + (+m[2] || 0);
  if ((m = s.match(/^(\d+)\s*(?:m|min)?$/))) return +m[1];
  return null;
}

function actorBadge(row) {
  if (!row.actor || row.actor === "web") return null;
  return h("span", { class: "who-badge", title: "Feito por chave de API" }, icon("spark"), row.token_name || row.actor);
}

export async function openTask(taskId, onChange) {
  let changed = false;
  const body = h("div", { class: "task-body" });
  const dlg = h("dialog", { class: "task-dialog", "aria-label": "Detalhe da tarefa" }, body);
  document.body.append(dlg);
  dlg.addEventListener("close", () => { dlg.remove(); if (changed) onChange && onChange(); });
  const touch = () => { changed = true; return render(); };
  // Desfazer pelo aviso pode chegar com o detalhe já fechado: aí recarrega quem abriu.
  const after = () => (dlg.open ? touch() : onChange && onChange());

  async function render() {
    let t;
    try {
      t = await api.get(`/worklog/${taskId}`);
    } catch (e) {
      errorToast(e, "Tarefa não encontrada.");
      dlg.close();
      return;
    }
    const today = (await api.get("/board")).today;
    clear(body);

    // ---- cabeçalho
    const chips = [h("span", { class: "chip " + t.status, text: STATUS_LABELS[t.status] })];
    if (PRIO[t.priority]) chips.push(h("span", { class: "chip prio-" + t.priority, text: PRIO[t.priority] }));
    const pc = projectChip(t);
    if (pc) chips.push(pc);
    if (t.due_date && t.status !== "done")
      chips.push(h("span", { class: "chip" + (t.due_date < today ? " late" : ""), text: "prazo " + shortDate(t.due_date) }));
    if (t.completed_at) chips.push(h("span", { class: "chip done", text: "fim " + shortDate(t.completed_at) }));

    const head = h("div", { class: "task-head" },
      h("div", { class: "task-title" },
        h("h2", { text: t.title }),
        t.description ? h("p", { text: t.description }) : null,
        h("div", { class: "card-meta" }, ...chips)),
      h("div", { class: "task-tools" },
        t.status !== "done"
          ? h("button", { type: "button", class: "icon", title: "Concluir", "aria-label": "Concluir", onClick: () => finishTask(t, after) }, icon("check"))
          : null,
        h("button", { type: "button", class: "icon", title: "Editar", "aria-label": "Editar", onClick: () => {
          dlg.close();
          openWorklog(t, () => { onChange && onChange(); openTask(taskId, onChange); });
        } }, icon("edit")),
        h("button", { type: "button", class: "icon", title: "Fechar", "aria-label": "Fechar", onClick: () => dlg.close() }, icon("close"))));

    body.append(head, checklist(t), timePanel(t, today), notesPanel(t));
  }

  // ---- checklist
  function checklist(t) {
    const done = t.checklist.filter((c) => c.done).length;
    const sec = h("section", { class: "task-sec" },
      h("div", { class: "task-sec-head" }, icon("list"), h("h3", { text: "Checklist" }),
        t.checklist.length ? h("span", { class: "count", text: `${done}/${t.checklist.length}` }) : null));
    if (t.checklist.length) {
      const bar = h("span");
      bar.style.width = `${Math.round((done / t.checklist.length) * 100)}%`;
      sec.append(h("div", { class: "progress thin" }, bar));
    }
    for (const c of t.checklist) {
      const cb = h("input", { type: "checkbox", "aria-label": c.label });
      cb.checked = c.done;
      cb.addEventListener("change", async () => {
        try { await api.patch(`/checklist/${c.id}`, { done: cb.checked }); touch(); }
        catch (e) { cb.checked = !cb.checked; errorToast(e); }
      });
      sec.append(h("label", { class: "check-row" + (c.done ? " done" : "") }, cb, h("span", { class: "label", text: c.label }),
        h("button", { type: "button", class: "icon", title: "Remover item", "aria-label": "Remover " + c.label, onClick: async (ev) => {
          ev.preventDefault();
          try {
            await api.del(`/checklist/${c.id}`);
            touch();
            toast("Item removido.", { action: "Desfazer", onAction: () => undoLatest("checklist", c.id, after) });
          } catch (e) { errorToast(e); }
        } }, icon("trash"))));
    }
    const input = h("input", { type: "text", maxlength: "200", placeholder: "Adicionar item e Enter", "aria-label": "Novo item do checklist" });
    input.addEventListener("keydown", async (ev) => {
      if (ev.key !== "Enter") return;
      ev.preventDefault();
      const label = input.value.trim();
      if (!label) return;
      input.disabled = true;
      try { await api.post(`/worklog/${t.id}/checklist`, { label }); await touch(); focusLast(".task-sec input[type=text]"); }
      catch (e) { input.disabled = false; errorToast(e); }
    });
    sec.append(h("div", { class: "task-add" }, input));
    return sec;
  }

  function focusLast(sel) {
    const el = dlg.querySelector(sel);
    if (el) el.focus();
  }

  // ---- tempo
  function timePanel(t, today) {
    const sec = h("section", { class: "task-sec" },
      h("div", { class: "task-sec-head" }, icon("clock"), h("h3", { text: "Tempo" }),
        h("span", { class: "count", text: duration(t.minutes) })));
    const dur = h("input", { type: "text", placeholder: "ex.: 1h30", "aria-label": "Duração", class: "dur" });
    const day = h("input", { type: "date", value: today, max: today, min: addDays(today, -60), "aria-label": "Dia" });
    const note = h("input", { type: "text", maxlength: "200", placeholder: "o que foi feito (opcional)", "aria-label": "Observação" });
    const form = h("form", { class: "time-form" }, dur, day, note,
      h("button", { type: "submit", class: "btn btn-ghost btn-sm" }, icon("add"), "Apontar"));
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const minutes = parseDuration(dur.value);
      if (!minutes || minutes > 1440) { toast("Duração inválida. Ex.: 45, 1h30, 2:15.", { error: true }); dur.focus(); return; }
      try {
        await api.post(`/worklog/${t.id}/time`, { minutes, day: day.value || today, note: note.value.trim() || null });
        toast(`Apontado ${duration(minutes)}.`);
        touch();
      } catch (e) { errorToast(e); }
    });
    sec.append(form);
    for (const e of t.time) {
      sec.append(h("div", { class: "mini-row" },
        h("span", { class: "mono when", text: shortDate(e.day) }),
        h("span", { class: "mono amount", text: duration(e.minutes) }),
        h("span", { class: "what" }, e.note || "", actorBadge(e)),
        h("button", { type: "button", class: "icon", title: "Remover apontamento", "aria-label": "Remover apontamento", onClick: async () => {
          try {
            await api.del(`/time/${e.id}`);
            touch();
            toast("Apontamento removido.", { action: "Desfazer", onAction: () => undoLatest("time", e.id, after) });
          } catch (err) { errorToast(err); }
        } }, icon("trash"))));
    }
    return sec;
  }

  // ---- anotações
  function notesPanel(t) {
    const sec = h("section", { class: "task-sec" },
      h("div", { class: "task-sec-head" }, icon("note"), h("h3", { text: "Anotações" }),
        t.notes.length ? h("span", { class: "count", text: String(t.notes.length) }) : null));
    const text = h("textarea", { rows: "2", maxlength: "2000", placeholder: "Progresso, decisão, pendência… (Ctrl+Enter salva)", "aria-label": "Nova anotação" });
    const send = async () => {
      const v = text.value.trim();
      if (!v) return;
      try { await api.post(`/worklog/${t.id}/notes`, { body: v }); touch(); }
      catch (e) { errorToast(e); }
    };
    text.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); send(); } });
    sec.append(h("div", { class: "note-form" }, text,
      h("button", { type: "button", class: "btn btn-ghost btn-sm", onClick: send }, "Anotar")));
    for (const n of t.notes) {
      sec.append(h("div", { class: "note" },
        h("div", { class: "note-meta" }, h("span", { class: "mono", text: dateTime(n.created_at) }), actorBadge(n),
          h("button", { type: "button", class: "icon", title: "Apagar anotação", "aria-label": "Apagar anotação", onClick: async () => {
            try {
              await api.del(`/notes/${n.id}`);
              touch();
              toast("Anotação apagada.", { action: "Desfazer", onAction: () => undoLatest("note", n.id, after) });
            } catch (e) { errorToast(e); }
          } }, icon("trash"))),
        h("p", { text: n.body })));
    }
    if (!t.notes.length) sec.append(h("p", { class: "empty", text: "Nada anotado ainda." }));
    return sec;
  }

  await render();
  dlg.showModal();
}
