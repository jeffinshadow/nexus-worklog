// Tela inicial "Hoje": o dia em um olhar e as ações mais comuns sem trocar de tela.
import { api } from "./api.js";
import { h, icon, clear, longDate, localDay } from "./dom.js";
import { errorToast, toast } from "./ui.js";
import { openRecurring, openWorklog, finishTask, taskChips, isOverdue, scheduleLabel } from "./board.js";
import { openTask, parseDuration } from "./task.js";
import { summaryPanel } from "./summary.js";

// Duração no fim do registro rápido: "Troca de toner — 15min", "Loja X 2h",
// "Backup 1:30". Exige unidade (h, min ou h:mm) para não confundir "Rack 2".
const QUICK_DUR = /\s+[-–—]?\s*(\d+(?:[.,]\d+)?\s*h(?:\s*\d{1,2})?(?:\s*min)?|\d+\s*min|\d+:\d{2})$/i;

// opts.focusQuick: volta o cursor ao registro rápido (lote de itens seguidos);
// opts.summary: reaproveita o resumo (registrar uma tarefa aberta não o muda).
export async function mount(root, ctx, opts = {}) {
  const refresh = () => mount(root, ctx);
  const [b, sum] = await Promise.all([
    api.get("/board"),
    opts.summary ? Promise.resolve(opts.summary) : api.get("/summary").catch(() => null),
  ]);
  const today = b.today;
  ctx.setEyebrow(longDate(today) + (b.work_day ? "" : " · dia não útil"));
  ctx.setActions(
    h("button", { type: "button", class: "btn btn-primary", onClick: () => openWorklog(null, refresh) }, icon("add"), "Tarefa")
  );

  // Devidas hoje pela agenda de cada uma; feitas fora da agenda = extra (à parte,
  // como no quadro, no dashboard e no PDF).
  const due = b.recurring.filter((r) => r.due !== false);
  const extras = b.recurring.filter((r) => r.due === false && r.done_today);
  const rec = [...due, ...extras];
  const recDone = due.filter((r) => r.done_today).length;
  const extraTxt = extras.length ? ` +${extras.length} extra` : "";
  const open = b.in_progress; // já vem na ordem: atrasadas, vencem hoje, prioridade, prazo
  const late = open.filter((t) => isOverdue(t, today));
  const blocked = open.filter((t) => t.status === "blocked");
  const doneToday = b.done.filter((t) =>
    t.completed_at && localDay(t.completed_at) === today);

  clear(root);

  // ---- rotinas do dia
  const recPanel = h("section", { class: "panel t-rec" },
    h("div", { class: "panel-head" }, h("h2", { text: "Rotinas de hoje" }), h("span", { class: "count", text: `${recDone}/${due.length}${extraTxt}` }),
      h("button", { type: "button", class: "icon accent", title: "Nova rotina", "aria-label": "Nova rotina", onClick: () => openRecurring(null, refresh) }, icon("add"))));
  if (due.length) {
    const bar = h("span");
    bar.style.width = `${Math.round((recDone / due.length) * 100)}%`;
    recPanel.append(h("div", { class: "progress", role: "img", "aria-label": `${recDone} de ${due.length} feitas` }, bar));
  }
  if (!rec.length)
    recPanel.append(h("p", { class: "empty", text: b.recurring.length ? "Nenhuma rotina na agenda de hoje." : "Nenhuma rotina ainda. Crie as verificações que você repete (backups, alertas, fila…)." }));
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
    const hint = r.due === false ? "extra" : scheduleLabel(r);
    recPanel.append(h("label", { class: "check-row" + (r.done_today ? " done" : "") }, cb,
      h("span", { class: "label" }, r.label, hint ? h("small", { text: hint }) : null),
      // Achou algo na verificação? Vira tarefa (com anotações e tempo).
      h("button", { type: "button", class: "icon", title: "Registrar um achado como tarefa", "aria-label": "Registrar achado de " + r.label,
        onClick: (ev) => { ev.preventDefault(); openWorklog(null, refresh, { title: `Achado: ${r.label}` }); } }, icon("alert"))));
  }

  // ---- abertas, por urgência + registro rápido
  const quick = h("input", { type: "text", placeholder: "Registrar tarefa e Enter (ex.: Troca de toner sala 3 — 15min)", maxlength: "200", "aria-label": "Registrar tarefa rápida" });
  quick.addEventListener("keydown", async (ev) => {
    if (ev.key !== "Enter" || !quick.value.trim()) return;
    ev.preventDefault();
    let title = quick.value.trim();
    const m = title.match(QUICK_DUR);
    const minutes = m ? parseDuration(m[1].replace(/\s+/g, "")) : null;
    if (minutes && minutes <= 1440) title = title.slice(0, m.index).trim();
    quick.disabled = true;
    try {
      const created = await api.post("/worklog", { title });
      if (minutes && minutes <= 1440) await api.post(`/worklog/${created.id}/time`, { minutes });
      toast(minutes ? `Tarefa registrada com ${m[1].trim()}.` : "Tarefa registrada.");
      mount(root, ctx, { focusQuick: true, summary: sum });
    } catch (e) {
      quick.disabled = false;
      errorToast(e, "Erro ao registrar.");
    }
  });
  const openPanel = h("section", { class: "panel t-open" },
    h("div", { class: "panel-head" }, h("h2", { text: "Em aberto" }),
      h("span", { class: "count" + (late.length || blocked.length ? " warn" : ""), text: [String(open.length),
        late.length ? `${late.length} atrasada${late.length > 1 ? "s" : ""}` : "",
        blocked.length ? `${blocked.length} bloqueada${blocked.length > 1 ? "s" : ""}` : ""].filter(Boolean).join(" · ") })),
    h("div", { class: "field" }, quick));
  if (!open.length) openPanel.append(h("p", { class: "empty", text: "Nada em aberto." }));
  for (const t of open) {
    openPanel.append(h("div", { class: "list-row" },
      h("button", { type: "button", class: "icon", title: "Concluir", "aria-label": "Concluir " + t.title, onClick: () => finishTask(t, refresh) }, icon("check")),
      h("div", { class: "t" },
        h("button", { type: "button", class: "card-open", text: t.title, onClick: () => openTask(t.id, refresh) }),
        h("small", {}, h("span", { class: "card-meta" }, ...taskChips(t, today)))),
      h("button", { type: "button", class: "icon", title: "Editar", "aria-label": "Editar " + t.title, onClick: () => openWorklog(t, refresh) }, icon("edit"))));
  }

  // ---- concluídas hoje
  const donePanel = h("section", { class: "panel t-done" },
    h("div", { class: "panel-head" }, h("h2", { text: "Concluídas hoje" }), h("span", { class: "count", text: String(doneToday.length) })));
  if (!doneToday.length) donePanel.append(h("p", { class: "empty", text: "Ainda nada hoje." }));
  for (const t of doneToday) {
    donePanel.append(h("div", { class: "list-row" }, h("span", { class: "chip done", text: "concluída" }),
      h("div", { class: "t" }, h("button", { type: "button", class: "card-open", text: t.title, onClick: () => openTask(t.id, refresh) }))));
  }

  if (opts.focusQuick) setTimeout(() => quick.focus(), 0);
  root.append(h("div", { class: "today-grid" }, recPanel, openPanel, donePanel, sum ? summaryPanel(sum, refresh) : null));
}
