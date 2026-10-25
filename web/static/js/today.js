// Tela inicial "Hoje": o dia em um olhar e as ações mais comuns sem trocar de
// tela. É o único lugar das rotinas (marcar até 7 dias atrás, editar, achado).
import { api } from "./api.js";
import { h, icon, clear, longDate, localDay, addDays } from "./dom.js";
import { errorToast, modal, toast, busy } from "./ui.js";
import { openRecurring, openWorklog, finishTask, taskChips, isOverdue, scheduleLabel, dayLabel } from "./board.js";
import { openTask } from "./task.js";
import { fillProjectSelect } from "./projects.js";
import { summaryPanel } from "./summary.js";
import { quickRegister } from "./quick.js";
import { todayCard } from "./assistant.js";
import { timerButton } from "./timer.js";
import { todayRenewals } from "./renewals.js";

const LAST_PROJECT = "nexus.quick.project";

// opts.day: dia das rotinas (padrão hoje); opts.focusQuick: volta o cursor ao
// registro rápido (lote de itens seguidos); opts.summary: reaproveita o resumo.
export async function mount(root, ctx, opts = {}) {
  const day = opts.day || null;
  const refresh = () => mount(root, ctx, { day });
  const [b, sum] = await Promise.all([
    api.get(day ? `/board?day=${day}` : "/board"),
    opts.summary ? Promise.resolve(opts.summary) : api.get("/summary").catch(() => null),
  ]);
  const today = b.today;
  ctx.setEyebrow(longDate(today) + (b.work_day ? "" : " · dia não útil"));
  ctx.setActions(
    h("button", { type: "button", class: "btn btn-ghost", title: "Texto pronto com o que fica aberto, bloqueado e feito hoje", onClick: showHandoff }, icon("copy"), "Passagem de turno"),
    h("button", { type: "button", class: "btn btn-primary", onClick: () => openWorklog(null, refresh) }, icon("add"), "Tarefa")
  );

  // Devidas no dia pela agenda de cada uma; as de fora da agenda vêm depois,
  // esmaecidas (marcar = extra, fora do %), como no relatório.
  const due = b.recurring.filter((r) => r.due !== false);
  const off = b.recurring.filter((r) => r.due === false);
  const extras = off.filter((r) => r.done_today).length;
  const recDone = due.filter((r) => r.done_today).length;
  const extraTxt = extras ? ` +${extras} extra` : "";
  const open = b.in_progress; // já vem na ordem: atrasadas, vencem hoje, prioridade, prazo
  const late = open.filter((t) => isOverdue(t, today));
  const blocked = open.filter((t) => t.status === "blocked");
  const doneToday = b.done.filter((t) => t.completed_at && localDay(t.completed_at) === today);

  clear(root);

  // ---- rotinas (do dia escolhido)
  const go = (d) => mount(root, ctx, { day: d === today ? null : d, summary: sum });
  const prev = h("button", { type: "button", class: "icon", title: "Dia anterior", "aria-label": "Dia anterior", onClick: () => go(addDays(b.day, -1)) }, icon("left"));
  const next = h("button", { type: "button", class: "icon", title: "Próximo dia", "aria-label": "Próximo dia", onClick: () => go(addDays(b.day, 1)) }, icon("right"));
  prev.disabled = b.day <= b.min_day;
  next.disabled = b.day >= today;
  const recPanel = h("section", { class: "panel t-rec" },
    h("div", { class: "panel-head" }, h("h2", { text: "Rotinas" }), h("span", { class: "count", text: `${recDone}/${due.length}${extraTxt}` }),
      h("button", { type: "button", class: "icon accent", title: "Nova rotina", "aria-label": "Nova rotina", onClick: () => openRecurring(null, refresh) }, icon("add"))),
    h("div", { class: "day-nav" }, prev, h("span", { class: "day-nav-label", "aria-live": "polite", text: dayLabel(b.day, today) }), next));
  if (due.length) {
    const bar = h("span");
    bar.style.width = `${Math.round((recDone / due.length) * 100)}%`;
    recPanel.append(h("div", { class: "progress", role: "img", "aria-label": `${recDone} de ${due.length} feitas` }, bar));
  }
  if (!b.recurring.length)
    recPanel.append(h("p", { class: "empty", text: "Nenhuma rotina ainda. Crie as verificações que você repete (backups, alertas, fila…)." }));
  else if (!due.length)
    recPanel.append(h("p", { class: "empty", text: "Nenhuma rotina na agenda deste dia." }));
  if (off.length) recPanel.append(h("p", { class: "day-note", text: "Esmaecidas: fora da agenda deste dia (se marcar, conta como extra)." }));
  for (const r of [...due, ...off]) {
    const cb = h("input", { type: "checkbox", "aria-label": r.label });
    cb.checked = r.done_today;
    cb.addEventListener("change", async () => {
      // Rotina que exige evidência: marcar abre o campo antes de salvar.
      if (cb.checked && r.require_note && !r.note) {
        cb.checked = false;
        editEvidence(r, b.day, refresh);
        return;
      }
      try {
        await api.post(`/recurring/${r.id}/toggle`, { done: cb.checked, day: b.day }); // o dia da tela, não o do relógio
        refresh();
      } catch (e) {
        cb.checked = !cb.checked;
        errorToast(e, "Erro ao salvar.");
      }
    });
    const hint = [scheduleLabel(r), r.require_note && !r.done_today ? "exige evidência" : ""].filter(Boolean).join(" · ");
    recPanel.append(h("label", { class: "check-row" + (r.done_today ? " done" : "") + (r.due === false ? " off" : "") }, cb,
      h("span", { class: "label" }, r.label, hint ? h("small", { text: hint }) : null,
        r.note ? h("small", { class: "evidence", text: "evidência: " + r.note }) : null),
      // Marcada: anota o que foi conferido (vai pro relatório, pra auditoria).
      r.done_today ? h("button", { type: "button", class: "icon", title: r.note ? "Editar a evidência" : "Anotar a evidência (o que foi conferido)",
        "aria-label": "Evidência de " + r.label, onClick: (ev) => { ev.preventDefault(); editEvidence(r, b.day, refresh); } }, icon("note")) : null,
      // Achou algo na verificação? Vira tarefa (com anotações e tempo).
      h("button", { type: "button", class: "icon", title: "Registrar um achado como tarefa", "aria-label": "Registrar achado de " + r.label,
        onClick: (ev) => { ev.preventDefault(); openWorklog(null, refresh, { title: `Achado: ${r.label}` }); } }, icon("alert")),
      h("button", { type: "button", class: "icon", title: "Editar rotina", "aria-label": "Editar " + r.label,
        onClick: (ev) => { ev.preventDefault(); openRecurring(r, refresh); } }, icon("edit"))));
  }

  // ---- abertas + registro rápido (com projeto; com "— 15min" já sai concluída)
  const proj = h("select", { class: "select-sm", "aria-label": "Projeto do registro rápido" });
  fillProjectSelect(proj, Number(sessionStorage.getItem(LAST_PROJECT)) || null)
    .then(() => proj.addEventListener("change", () => sessionStorage.setItem(LAST_PROJECT, proj.value)))
    .catch(() => {});
  const quick = h("input", { type: "text", placeholder: "Registrar e Enter · @projeto #chamado !plantão ^sex !bloq motivo — 15min", maxlength: "200", "aria-label": "Registrar tarefa rápida" });
  quick.addEventListener("keydown", async (ev) => {
    if (ev.key !== "Enter" || !quick.value.trim()) return;
    ev.preventDefault();
    const project_id = proj.value && proj.value !== "__new" ? Number(proj.value) : null;
    quick.disabled = true;
    try {
      toast(await quickRegister(quick.value, project_id));
    } catch (e) {
      quick.disabled = false;
      errorToast(e, "Erro ao registrar.");
      return;
    }
    mount(root, ctx, { day, focusQuick: true, summary: sum });
  });
  const openPanel = h("section", { class: "panel t-open" },
    h("div", { class: "panel-head" }, h("h2", { text: "Em aberto" }),
      h("span", { class: "count" + (late.length || blocked.length ? " warn" : ""), text: [String(open.length),
        late.length ? `${late.length} atrasada${late.length > 1 ? "s" : ""}` : "",
        blocked.length ? `${blocked.length} bloqueada${blocked.length > 1 ? "s" : ""}` : ""].filter(Boolean).join(" · ") })),
    h("div", { class: "quick-row" }, quick, proj));
  if (!open.length) openPanel.append(h("p", { class: "empty", text: "Nada em aberto." }));
  for (const t of open) {
    openPanel.append(h("div", { class: "list-row" },
      h("button", { type: "button", class: "icon", title: "Concluir", "aria-label": "Concluir " + t.title, onClick: () => finishTask(t, refresh) }, icon("check")),
      h("div", { class: "t" },
        h("button", { type: "button", class: "card-open", text: t.title, onClick: () => openTask(t.id, refresh) }),
        h("small", {}, h("span", { class: "card-meta" }, ...taskChips(t, today)))),
      timerButton(t, refresh),
      h("button", { type: "button", class: "icon", title: "Editar", "aria-label": "Editar " + t.title, onClick: () => openWorklog(t, refresh) }, icon("edit"))));
  }

  // ---- concluídas hoje (com projeto e tempo, para conferir no fim do dia)
  const donePanel = h("section", { class: "panel t-done" },
    h("div", { class: "panel-head" }, h("h2", { text: "Concluídas hoje" }), h("span", { class: "count", text: String(doneToday.length) })));
  if (!doneToday.length) donePanel.append(h("p", { class: "empty", text: "Ainda nada hoje." }));
  for (const t of doneToday) {
    donePanel.append(h("div", { class: "list-row" },
      h("div", { class: "t" },
        h("button", { type: "button", class: "card-open", text: t.title, onClick: () => openTask(t.id, refresh) }),
        h("small", {}, h("span", { class: "card-meta" }, ...taskChips(t, today))))));
  }

  if (opts.focusQuick) setTimeout(() => quick.focus(), 0);
  // Assistente: a saudação e o que pede atenção (desliga em Configurações > Conta).
  const meChanged = (res) => { Object.assign(ctx.me, res); window.dispatchEvent(new Event("nexus:me")); refresh(); };
  const assist = todayCard(b, sum, {
    me: ctx.me, go: ctx.go, openTask: (id) => openTask(id, refresh), onChanged: refresh,
    onProfile: meChanged,
  });
  ctx.setAssist(assist);
  const venc = await todayRenewals(refresh); // só aparece com algo no aviso
  root.append(h("div", { class: "today-grid" }, venc, recPanel, openPanel, donePanel, sum ? summaryPanel(sum, refresh) : null));
}


// Evidência da rotina: uma linha curta do que foi conferido ("backup OK, 2,1 TB").
function editEvidence(r, day, refresh) {
  const input = h("input", { type: "text", maxlength: "200", value: r.note || "", placeholder: "ex.: backup OK, 2,1 TB, 0 erros" });
  const err = h("p", { class: "error-text" });
  const form = h("form", {}, h("h2", { text: "Evidência" }),
    h("p", { class: "dialog-note", text: `${r.label}: o que foi conferido. Aparece no relatório em PDF e na exportação.${r.require_note ? " Esta rotina só é marcada com a evidência." : ""}` }),
    h("label", { class: "field" }, "Evidência", input), err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
      h("button", { type: "submit", class: "btn btn-primary", text: "Salvar" })));
  form.addEventListener("submit", busy(async () => {
    try {
      await api.post(`/recurring/${r.id}/toggle`, { done: true, day, note: input.value.trim() || null });
      dlg.close();
      refresh();
    } catch (e) { err.textContent = e.message || "Não foi possível salvar."; }
  }));
  const dlg = modal(form);
  input.focus();
}

// Passagem de turno/plantão: texto pronto (calculado no servidor) pra colar no chat.
async function showHandoff() {
  let text;
  try { text = (await api.get("/summary/handoff")).text; } catch (e) { errorToast(e); return; }
  const area = h("textarea", { rows: "14", readonly: "readonly", class: "handoff-text", "aria-label": "Texto da passagem de turno" });
  area.value = text;
  const dlg = modal(h("h2", { text: "Passagem de turno" }),
    h("p", { class: "dialog-note", text: "O que fica aberto, o que está bloqueado e por quê, o que saiu hoje. Cole no chat da equipe." }),
    area,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Fechar", onClick: () => dlg.close() }),
      h("button", { type: "button", class: "btn btn-primary", onClick: async () => {
        try { await navigator.clipboard.writeText(text); toast("Copiado."); dlg.close(); }
        catch { area.select(); toast("Selecione e copie (Ctrl+C).", { error: true }); }
      } }, icon("copy"), "Copiar")));
  area.focus();
}
