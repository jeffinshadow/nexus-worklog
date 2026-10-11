// Tela inicial "Hoje": o dia em um olhar e as ações mais comuns sem trocar de tela.
import { api } from "./api.js";
import { h, icon, clear, longDate } from "./dom.js";
import { errorToast, toast } from "./ui.js";
import { openRecurring, openWorklog, finishTask, taskChips, isOverdue } from "./board.js";

// Ordem de urgência das abertas: atrasadas, vencem hoje, bloqueadas, em andamento, a fazer.
function urgency(t, today) {
  if (isOverdue(t, today)) return 0;
  if (t.due_date === today) return 1;
  return { blocked: 2, in_progress: 3, todo: 4 }[t.status] ?? 5;
}

export async function mount(root, ctx) {
  const refresh = () => mount(root, ctx);
  const b = await api.get("/board");
  const today = b.today;
  ctx.setEyebrow(longDate(today) + (b.work_day ? "" : " · dia não útil"));
  ctx.setActions(
    h("button", { type: "button", class: "btn btn-primary", onClick: () => openWorklog(null, refresh) }, icon("add"), "Tarefa")
  );

  const rec = b.recurring;
  const recDone = rec.filter((r) => r.done_today).length;
  const open = [...b.in_progress].sort((x, y) => urgency(x, today) - urgency(y, today));
  const late = open.filter((t) => isOverdue(t, today));
  const doneToday = b.done.filter((t) =>
    t.completed_at && new Date(t.completed_at).toLocaleDateString("sv-SE", { timeZone: "America/Sao_Paulo" }) === today);

  clear(root);

  // ---- números do dia
  const stat = (n, label, cls = "", small = "") =>
    h("div", { class: "stat " + cls }, h("p", { class: "stat-n" }, String(n), small ? h("small", { text: small }) : null), h("p", { class: "stat-l", text: label }));
  const stats = h("div", { class: "stats" },
    stat(rec.length ? recDone : "—", rec.length ? "recorrentes feitas" : "sem recorrentes hoje", rec.length && recDone === rec.length ? "ok" : "", rec.length ? `/${rec.length}` : ""),
    stat(open.length, "tarefas abertas"),
    stat(late.length, late.length === 1 ? "atrasada" : "atrasadas", late.length ? "warn" : ""),
    stat(doneToday.length, "concluídas hoje", doneToday.length ? "ok" : ""));

  // ---- recorrentes do dia
  const recPanel = h("section", { class: "panel t-rec" },
    h("div", { class: "panel-head" }, h("h2", { text: "Recorrentes de hoje" }), h("span", { class: "count", text: `${recDone}/${rec.length}` }),
      h("button", { type: "button", class: "icon accent", title: "Nova recorrente", "aria-label": "Nova recorrente", onClick: () => openRecurring(null, refresh) }, icon("add"))));
  if (rec.length) {
    const bar = h("span");
    bar.style.width = `${Math.round((recDone / rec.length) * 100)}%`;
    recPanel.append(h("div", { class: "progress", role: "img", "aria-label": `${recDone} de ${rec.length} feitas` }, bar));
  }
  if (!b.work_day) recPanel.append(h("p", { class: "day-note", text: "Hoje não é dia útil: o que marcar conta como extra." }));
  if (!rec.length) recPanel.append(h("p", { class: "empty", text: "Nenhuma recorrente. Crie as rotinas que você faz todo dia." }));
  for (const r of rec) {
    const cb = h("input", { type: "checkbox", "aria-label": r.label });
    cb.checked = r.done_today;
    cb.addEventListener("change", async () => {
      try {
        await api.post(`/recurring/${r.id}/toggle`, { done: cb.checked });
        refresh();
      } catch (e) {
        cb.checked = !cb.checked;
        errorToast(e, "Erro ao salvar.");
      }
    });
    recPanel.append(h("label", { class: "check-row" + (r.done_today ? " done" : "") }, cb, h("span", { class: "label", text: r.label })));
  }

  // ---- abertas, por urgência + registro rápido
  const quick = h("input", { type: "text", placeholder: "Registrar tarefa rápida e apertar Enter", maxlength: "200", "aria-label": "Registrar tarefa rápida" });
  quick.addEventListener("keydown", async (ev) => {
    if (ev.key !== "Enter" || !quick.value.trim()) return;
    ev.preventDefault();
    const title = quick.value.trim();
    quick.disabled = true;
    try {
      await api.post("/worklog", { title, status: "in_progress" });
      toast("Tarefa registrada.");
      refresh();
    } catch (e) {
      quick.disabled = false;
      errorToast(e, "Erro ao registrar.");
    }
  });
  const openPanel = h("section", { class: "panel t-open" },
    h("div", { class: "panel-head" }, h("h2", { text: "Em aberto" }), h("span", { class: "count", text: String(open.length) })),
    h("div", { class: "field" }, quick));
  if (!open.length) openPanel.append(h("p", { class: "empty", text: "Nada em aberto." }));
  for (const t of open) {
    openPanel.append(h("div", { class: "list-row" },
      h("button", { type: "button", class: "icon", title: "Concluir", "aria-label": "Concluir " + t.title, onClick: () => finishTask(t, refresh) }, icon("check")),
      h("div", { class: "t" }, t.title, h("small", {}, h("span", { class: "card-meta" }, ...taskChips(t, today)))),
      h("button", { type: "button", class: "icon", title: "Editar", "aria-label": "Editar " + t.title, onClick: () => openWorklog(t, refresh) }, icon("edit"))));
  }

  // ---- concluídas hoje
  const donePanel = h("section", { class: "panel t-done" },
    h("div", { class: "panel-head" }, h("h2", { text: "Concluídas hoje" }), h("span", { class: "count", text: String(doneToday.length) })));
  if (!doneToday.length) donePanel.append(h("p", { class: "empty", text: "Ainda nada hoje." }));
  for (const t of doneToday) {
    donePanel.append(h("div", { class: "list-row" }, h("span", { class: "chip done", text: "feita" }), h("div", { class: "t", text: t.title })));
  }

  root.append(h("div", { class: "today-grid" }, stats, recPanel, openPanel, donePanel));
}
