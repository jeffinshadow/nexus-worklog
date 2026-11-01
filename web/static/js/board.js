// Quadro de tarefas: rotinas (com seletor de dia), tarefas abertas e
// concluídas. Também exporta o diálogo de nova tarefa, usado pela tela Hoje.
import { api } from "./api.js";
import { h, icon, clear, field, addDays, addWorkDays, shortDate, localDay, localDateTime, daysBetween, markInvalid } from "./dom.js";
import { confirmDialog, errorToast, toast, undoLatest, busy, modal, sheet, navBadge, popupMenu, focusAfterRemoval, keepFocus, pager, pageSlice, hashPage, setHashPage } from "./ui.js";
import { extraProjectsField, fillObjectiveSelect, fillProjectSelect, listProjects, projectChips } from "./projects.js";
import { openTask, openTaskId, editingTaskId, duration, parseDuration } from "./task.js";
import { boardLine } from "./assistant.js";
import { session } from "./session.js";
import { timerButton, timerState, startTimer, stopTimer } from "./timer.js";
import { refreshReminders } from "./lembretes.js";
import { appBadge } from "./instalar.js";
import { prepare, upload } from "./fotos.js";
import { openPacks } from "./pacotes.js";

const WEEKDAYS_SHORT = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
// Páginas do quadro: a lista de trabalho cabe numa olhada até 25; as concluídas
// vêm do servidor de 20 em 20 (com o total real).
const OPEN_PAGE = 25;
const DONE_PAGE = 20;

export const STATUS_LABELS = {
  todo: "a fazer",
  in_progress: "em andamento",
  blocked: "aguardando",
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
// "aguardando há 3 d": há quanto tempo a espera existe.
// Dias de calendário no fuso da app (marcada ontem às 18h = 1 d hoje), como no servidor.
function blockedDays(t, today) {
  if (t.status !== "blocked" || !t.blocked_at || !today) return "";
  const d = daysBetween(localDay(t.blocked_at), today);
  return d >= 1 ? ` há ${d} d` : "";
}

export function taskChips(t, today) {
  // Só o estado que informa: "a fazer" é o normal de quem está em aberto (sem chip);
  // concluída, a coluna já diz e fica só a data de fim.
  const chips = t.status === "done" || t.status === "todo" ? [] : [h("span", { class: "chip " + t.status, text: STATUS_LABELS[t.status] + blockedDays(t, today) })];
  if (t.status === "blocked" && t.follow_up_on)
    chips.push(h("span", { class: "chip " + (t.follow_up_on <= today ? "late" : "blocked-reason"), title: "Dia combinado para cobrar",
      text: t.follow_up_on < today ? "cobrança atrasada · " + shortDate(t.follow_up_on)
        : t.follow_up_on === today ? "cobrar hoje" : "cobrar " + shortDate(t.follow_up_on) }));
  if (t.status === "blocked" && t.blocked_reason)
    chips.push(h("span", { class: "chip blocked-reason", title: "Aguardando: " + t.blocked_reason, text: short(t.blocked_reason.replace(/^aguardando\s+/i, "")) }));
  if (t.priority === 1 && t.status !== "done") chips.push(h("span", { class: "chip prio-1", text: "alta" }));
  if (t.status === "done") {
    // O dia da conclusão no fuso da app (o timestamp vem em UTC: à noite já seria "amanhã").
    if (t.pending_done) chips.push(h("span", { class: "chip today", text: "concluída · esperando conexão" }));  // feito sem sinal
    else if (t.completed_at) chips.push(h("span", { class: "chip done", text: "fim " + shortDate(localDay(t.completed_at)) }));
  } else if (t.due_date) {
    if (t.due_date < today) chips.push(h("span", { class: "chip late", text: "atrasada · " + shortDate(t.due_date) }));
    else if (t.due_date === today) chips.push(h("span", { class: "chip today", text: "vence hoje" }));
    else chips.push(h("span", { class: "chip", text: "prazo " + shortDate(t.due_date) }));
  }
  // Contexto (projeto, objetivo, chamado, quem mandou, plantão): uma linha de texto
  // com o ponto de cor, sem borda; em pílula fica só o estado (atrasada, aguardando...).
  const ctx = [...projectChips(t)];
  if (t.objective_title) ctx.push(h("span", { class: "chip objective", title: "Objetivo" }, icon("target"), t.objective_title));
  if (t.ticket) ctx.push(ticketChip(t.ticket));
  if (t.assigned_by_name) ctx.push(h("span", { class: "chip assigned", title: "Atribuída por " + t.assigned_by_name, text: "de " + t.assigned_by_name }));
  if (t.after_hours) ctx.push(h("span", { class: "chip after-hours", title: "Plantão / fora do horário", text: "plantão" }));
  if (ctx.length) chips.push(h("span", { class: "task-ctx" }, ...ctx));
  if (t.check_total) chips.push(h("span", { class: "tag" + (t.check_done === t.check_total ? " ok" : ""), title: "Checklist" }, icon("list"), `${t.check_done}/${t.check_total}`));
  if (t.minutes) chips.push(h("span", { class: "tag", title: "Tempo apontado" }, icon("clock"), duration(t.minutes)));
  if (t.notes_count) chips.push(h("span", { class: "tag", title: "Anotações" }, icon("note"), String(t.notes_count)));
  if (t.photos_count) chips.push(h("span", { class: "tag", title: "Fotos" }, icon("image"), String(t.photos_count)));
  return chips;
}

// Número do chamado; com o endereço do sistema (Configurações > Conta), vira link.
export function ticketUrl(ticket) {
  const base = session.me && session.me.ticket_url;
  if (!base) return null;
  const id = encodeURIComponent(ticket);
  return base.includes("{id}") ? base.split("{id}").join(id) : base + id;
}

function ticketChip(ticket) {
  const url = ticketUrl(ticket);
  return url
    ? h("a", { class: "chip ticket", href: url, target: "_blank", rel: "noopener noreferrer", title: "Abrir o chamado", text: "#" + ticket })
    : h("span", { class: "chip ticket", title: "Chamado ou OS", text: "#" + ticket });
}

// Resumo da agenda de uma rotina ("seg, qua", "todo dia 5", "a cada 15 dias",
// "30 dias depois da última vez · próxima em 12/12"). day: o dia que a tela mostra.
const WD_ORDER = [1, 2, 3, 4, 5, 6, 0];
export function scheduleLabel(r, day) {
  if (r.freq === "weekly") {
    const days = WD_ORDER.filter((b) => (r.weekdays >> b) & 1).map((b) => WEEKDAYS_SHORT[b]);
    return days.length === 7 ? "todo dia" : days.join(", ");
  }
  if (r.freq === "monthly") return r.month_day >= 31 ? "último dia do mês" : `todo dia ${r.month_day}`;
  if (r.freq === "interval") return `a cada ${r.interval_days} dias`;
  if (r.freq === "after") {
    const base = `${r.interval_days} dias depois da última vez`;
    if (!r.next_due) return base;
    if (day && r.next_due < day) return `${base} · venceu em ${shortDate(r.next_due)}`;
    return `${base} · ${day && r.next_due === day ? "vence hoje" : "próxima em " + shortDate(r.next_due)}`;
  }
  return "";
}

// Pausar até uma data (férias, folga, prédio fechado) ou retomar agora. Nos
// dias pausados a rotina não é devida (nem falta, nem lembrete); marcar = extra.
export function pauseRecurring(r, onDone) {
  const today = localDay(Date.now());
  const done = (msg) => {
    refreshReminders();
    onDone && onDone();
    toast(msg, { action: "Desfazer", onAction: () => undoLatest("recurring", r.id, onDone) });
  };
  const until = h("input", { type: "date", min: today, max: addDays(today, 366), value: r.paused_until || addDays(today, 7), required: "" });
  const dlg = modal(
    h("h2", { text: r.paused_until ? "Rotina pausada" : "Pausar rotina" }),
    h("p", { text: `“${r.label}” não conta como falta nem avisa até o dia escolhido (inclusive) e volta sozinha no dia seguinte. Marcar durante a pausa conta como extra.` }),
    field("Pausar até", until),
    h("div", { class: "dialog-actions" },
      r.paused_until ? h("button", { type: "button", class: "btn btn-text", text: "Retomar agora", onClick: async () => {
        dlg.close();
        try {
          await api.del(`/recurring/${r.id}/pause`);
          done(`Rotina retomada: ${r.label}`);
        } catch (e) {
          errorToast(e, "Não foi possível retomar.");
        }
      } }) : null,
      h("div", { class: "spacer" }),
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
      h("button", { type: "button", class: "btn btn-primary", text: r.paused_until ? "Mudar a data" : "Pausar", onClick: async () => {
        if (!until.value || until.value < today) { toast("Escolha hoje ou um dia depois.", { error: true }); return; }
        dlg.close();
        try {
          await api.post(`/recurring/${r.id}/pause`, { until: until.value });
          done(`Pausada até ${shortDate(until.value)}: ${r.label}`);
        } catch (e) {
          errorToast(e, "Não foi possível pausar.");
        }
      } })));
  until.focus();
}

const short = (s) => (s.length > 40 ? s.slice(0, 39) + "…" : s);

export function isOverdue(t, today) {
  return t.status !== "done" && t.due_date && t.due_date < today;
}

// Celular: o cronômetro sai da linha e vai para um menu (⋮) que sobe de
// baixo; na linha ficam só concluir e este botão, com alvo de 48 px.
export function moreButton(t, onDone) {
  return h("button", { type: "button", class: "icon only-mob", title: "Mais ações", "aria-label": "Mais ações de " + t.title,
    onClick: () => {
      const running = (timerState() || {}).task_id === t.id;
      sheet(t.title, [
        t.status === "done" ? null : running
          ? ["Parar o cronômetro e apontar", "stop", () => stopTimer(onDone)]
          : ["Iniciar o cronômetro", "play", () => startTimer(t, onDone)],
        canBlock(t) ? ["Marcar como aguardando…", "clock", () => blockTask(t, onDone)] : null,
        ["Duplicar tarefa", "add", () => duplicateTask(t, onDone)],
        ["Abrir (ver e editar)", "right", () => openTask(t.id, onDone)],
        ["Excluir", "trash", () => deleteTask(t, onDone)],
      ]);
    } }, icon("more-v"));
}

// Clique direito (ou tecla de menu) num cartão ou linha de tarefa: as ações
// dela num menu; no celular (toque longo), no menu que sobe de baixo.
export function withMenu(el, t, onDone) {
  el.dataset.taskId = String(t.id);
  if (openTaskId() === t.id) el.classList.add("selected");
  if (editingTaskId() === t.id) el.classList.add("editing");
  el.addEventListener("contextmenu", (ev) => {
    if (ev.target.closest("a, input, select, textarea")) return; // nesses, o menu do navegador
    ev.preventDefault();
    const running = (timerState() || {}).task_id === t.id;
    const items = [
      ["Abrir", "right", () => openTask(t.id, onDone)],
      t.status === "done" ? null : running
        ? ["Parar o cronômetro e apontar", "stop", () => stopTimer(onDone)]
        : ["Iniciar o cronômetro", "play", () => startTimer(t, onDone)],
      t.status === "done" ? ["Reabrir", "undo", () => reopenTask(t, onDone)] : ["Concluir", "check", () => finishTask(t, onDone)],
      canBlock(t) ? ["Marcar como aguardando…", "clock", () => blockTask(t, onDone)] : null,
      ["Duplicar tarefa", "add", () => duplicateTask(t, onDone)],
      ["Excluir", "trash", () => deleteTask(t, onDone)],
    ];
    if (matchMedia("(max-width: 860px)").matches) { sheet(t.title, items); return; }
    let { clientX: x, clientY: y } = ev;
    if (!x && !y) { el.scrollIntoView({ block: "nearest" }); const r = el.getBoundingClientRect(); x = r.left + 24; y = r.top + 24; } // pela tecla de menu
    popupMenu(x, y, items);
  });
  return el;
}

// Esconde no celular (o botão vai para o menu ⋮).
export const desk = (el) => { if (el) el.classList.add("only-desk"); return el; };

// Tarefas atrasadas no item do menu (Hoje e Tarefas sem filtro atualizam).
export const lateBadge = (open, today) => {
  const n = open.filter((t) => isOverdue(t, today)).length;
  navBadge("tarefas", n, n === 1 ? "1 tarefa atrasada" : `${n} tarefas atrasadas`);
  appBadge("atrasadas", n);
};

// ------------------------------------------------------- diálogos (export) --

// Dia para cobrar uma tarefa aguardando: o lembrete só aparece em dia útil, então
// um dia não útil vira o dia útil anterior (com aviso).
export function followUpDay(day) {
  const today = localDateTime(Date.now()).slice(0, 10);
  const mask = (session.me && session.me.work_days) || 62;
  let fd = day;
  while (fd && !((mask >> new Date(fd + "T12:00:00Z").getUTCDay()) & 1) && fd > today) fd = addDays(fd, -1);
  if (fd && fd !== day) toast(`Cobrança antecipada para ${shortDate(fd)}, o dia útil anterior.`);
  return fd;
}

export const canBlock = (t) => t.status !== "done" && t.status !== "blocked";

// "Marcar como aguardando…" direto do menu: pergunta o que falta e, se quiser, quando cobrar.
export function blockTask(t, onDone) {
  const back = keepFocus(); // depois do redesenho, o foco volta ao cartão
  const reason = h("input", { type: "text", maxlength: "120", required: "required", placeholder: "Ex.: peça do fornecedor, acesso à sala, aprovação" });
  const follow = h("input", { type: "date", min: localDateTime(Date.now()).slice(0, 10) });
  const err = h("p", { class: "error-text", role: "alert" });
  const form = h("form", {},
    h("h2", { text: "Aguardando" }),
    h("p", { class: "dialog-note", text: t.title }),
    field("Aguardando o quê?", reason), field("Lembrar de cobrar em (opcional)", follow), err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
      h("button", { type: "submit", class: "btn btn-primary", text: "Marcar como aguardando" })));
  const dlg = modal(form);
  reason.addEventListener("input", () => markInvalid([reason], err, false));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const body = { status: "blocked", blocked_reason: reason.value.trim().replace(/^aguardando\s+/i, "") };
    if (follow.value) body.follow_up_on = followUpDay(follow.value);
    try {
      await api.patch(`/worklog/${t.id}`, body);
      dlg.close();
      toast(`Aguardando: ${body.blocked_reason}.`);
      Promise.resolve(onDone && onDone()).then(back);
    } catch (e) { err.textContent = e.message; markInvalid([reason], err); }
  });
  setTimeout(() => reason.focus(), 0);
}

// "Lembrar de cobrar em" direto (assistente do Hoje, revisão da semana): só o dia,
// sugerido para daqui a 2 dias úteis. A tarefa continua aguardando o mesmo motivo.
export function followUpTask(t, onDone) {
  const today = localDateTime(Date.now()).slice(0, 10);
  const follow = h("input", { type: "date", min: today, required: "required" });
  follow.value = t.follow_up_on && t.follow_up_on >= today ? t.follow_up_on : addWorkDays(today, 2, (session.me && session.me.work_days) || 62);
  const err = h("p", { class: "error-text", role: "alert" });
  const form = h("form", {},
    h("h2", { text: "Quando cobrar?" }),
    h("p", { class: "dialog-note", text: t.blocked_reason ? `${t.title}: aguardando ${t.blocked_reason}.` : t.title }),
    field("Lembrar de cobrar em", follow),
    h("p", { class: "dialog-note", text: "No dia, o assistente do Hoje lembra (e a notificação da manhã, se estiver ligada)." }), err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
      h("button", { type: "submit", class: "btn btn-primary", text: "Salvar" })));
  const dlg = modal(form);
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    const day = followUpDay(follow.value);
    try {
      await api.patch(`/worklog/${t.id}`, { follow_up_on: day });
      dlg.close();
      toast(`Lembrete para cobrar em ${shortDate(day)}.`);
      if (onDone) onDone(day);
    } catch (e) { err.textContent = e.message || "Não foi possível salvar."; }
  }));
  setTimeout(() => follow.focus(), 0);
}

// Duplicar: tarefa nova "a fazer" com título, descrição, projetos, prioridade e
// checklist (desmarcado); sem tempo, fotos, anotações nem datas. Abre a nova
// com o título em edição, selecionado: dá para trocar o nome na hora.
export async function duplicateTask(t, onDone) {
  try {
    const { id } = await api.post(`/worklog/${t.id}/duplicate`);
    toast("Tarefa duplicada.", { action: "Desfazer", onAction: () => undoLatest("worklog", id, onDone) });
    if (onDone) onDone();
    openTask(id, onDone, { editTitle: true });
  } catch (e) { errorToast(e, "Não foi possível duplicar."); }
}

export async function deleteTask(t, onDone) {
  const refocus = focusAfterRemoval(); // o foco vai para a tarefa que ficar no lugar
  if (!(await confirmDialog({ title: "Excluir tarefa?", text: `“${t.title}” sai do quadro. Dá para desfazer pelo histórico.`, confirm: "Excluir", danger: true }))) return false;
  try {
    await api.del(`/worklog/${t.id}`);
    Promise.resolve(onDone && onDone()).then(refocus);
    toast("Tarefa excluída.", { action: "Desfazer", onAction: () => undoLatest("worklog", t.id, onDone) });
    return true;
  } catch (e) {
    errorToast(e, "Não foi possível excluir.");
    return false;
  }
}

// Nova tarefa (editar é no próprio detalhe, task.js).
export function openWorklog(onDone, opts = {}) {
  const dlg = document.getElementById("dialog-worklog");
  document.getElementById("wl-title").value = opts.title || "";
  document.getElementById("wl-desc").value = opts.description || "";
  document.getElementById("wl-status").value = "todo";
  document.getElementById("wl-due").value = "";
  document.getElementById("wl-prio").value = "2";
  // Tempo já na criação (técnico em campo: "Loja X, 2h"); depois, pelo detalhe.
  const timeInput = document.getElementById("wl-time");
  timeInput.value = "";
  timeInput.setCustomValidity("");
  timeInput.oninput = () => timeInput.setCustomValidity(""); // erro some ao corrigir
  const projSel = document.getElementById("wl-project");
  const pickedProject = () => (projSel.value && projSel.value !== "__new" ? Number(projSel.value) : null);
  const extraBox = document.getElementById("wl-extra");
  const extras = extraProjectsField([], pickedProject, () => {});
  clear(extraBox);
  extraBox.append(extras.el);
  // Objetivo: os do projeto escolhido (aberto pela tela do projeto, já vem com ele).
  const objSel = document.getElementById("wl-objective");
  // Sem projeto, a linha some; o objetivo só aparece se o projeto tiver objetivos.
  const syncObjectives = (sel = null) => {
    document.getElementById("wl-project-more").classList.toggle("hidden", !pickedProject());
    return fillObjectiveSelect(objSel, pickedProject(), sel)
      .then((list) => document.getElementById("wl-objective-wrap").classList.toggle("hidden", !(list || []).length))
      .catch(() => {});
  };
  // Já vem com o projeto padrão (Configurações > Conta), ou o da tela de onde veio; "Sem projeto" tira.
  // project_id null (quadro filtrado em "Sem projeto"): sem projeto, mesmo com um padrão.
  const startProject = opts.project_id !== undefined ? opts.project_id : (session.me && session.me.default_project_id) || null;
  const projReady = fillProjectSelect(projSel, startProject,
    () => { extras.sync(); syncObjectives(); })
    .then(() => { extras.sync(); return syncObjectives(opts.objective_id || null); }).catch(() => {});
  const ticket = document.getElementById("wl-ticket");
  const after = document.getElementById("wl-after");
  // Datas retroativas: "Concluída em" aparece com o status Concluída (vazio =
  // agora). Limites: nada no futuro, até retro_days.
  const statusSel = document.getElementById("wl-status");
  const dates = document.getElementById("wl-dates");
  const createdAt = document.getElementById("wl-created-at");
  const doneAt = document.getElementById("wl-done-at");
  const me = session.me || {};
  const now = localDateTime(Date.now());
  const minDay = addDays(now.slice(0, 10), -(me.retro_days || 60)) + "T00:00";
  for (const el of [createdAt, doneAt]) { el.max = now; el.min = minDay; }
  createdAt.value = "";
  doneAt.value = "";
  const blockedWrap = document.getElementById("wl-blocked-wrap");
  const blocked = document.getElementById("wl-blocked");
  blocked.value = "";
  const followUp = document.getElementById("wl-followup");
  followUp.value = "";
  followUp.min = now.slice(0, 10);
  const resolution = document.getElementById("wl-resolution");
  resolution.value = "";
  const syncDates = () => {
    dates.classList.toggle("hidden", statusSel.value !== "done");
    document.getElementById("wl-resolution-wrap").classList.toggle("hidden", statusSel.value !== "done");
    blockedWrap.classList.toggle("hidden", statusSel.value !== "blocked");
    followUp.disabled = statusSel.value !== "blocked"; // escondido e desabilitado: o navegador não valida
  };
  statusSel.onchange = syncDates;
  syncDates();
  ticket.value = "";
  after.checked = false;

  // "Já resolvi isso antes?": ao digitar o título de uma tarefa nova, mostra até 3
  // concluídas parecidas com o "como resolveu" delas (busca sem IA).
  const similarBox = document.getElementById("wl-similar");
  const titleInput = document.getElementById("wl-title");
  clear(similarBox);
  similarBox.classList.add("hidden");
  let simTimer = null, simSeq = 0;
  dlg.onclose = () => { clearTimeout(simTimer); simSeq++; }; // nada pendente entre aberturas
  titleInput.oninput = () => {
    clearTimeout(simTimer);
    simTimer = setTimeout(async () => {
      const q = titleInput.value.trim(), my = ++simSeq;
      if (q.length < 4) { similarBox.classList.add("hidden"); return; }
      let list = [];
      try { list = await api.get("/search/similar?title=" + encodeURIComponent(q)); } catch { /* sugestão: falha não atrapalha */ }
      if (my !== simSeq) return;
      clear(similarBox);
      similarBox.classList.toggle("hidden", !list.length);
      if (!list.length) return;
      similarBox.append(h("p", { class: "similar-head", text: "Já resolvido antes:" }),
        ...list.map((s) => h("div", { class: "similar-item" },
          h("button", { type: "button", class: "btn btn-text btn-sm", text: s.title, title: "Abrir a tarefa", onClick: () => openTask(s.id, onDone) }),
          h("p", { text: s.resolution.length > 160 ? s.resolution.slice(0, 159) + "…" : s.resolution }))));
    }, 400);
  };

  // Modelo: preenche o formulário; o checklist dele entra depois de criar.
  let checklist = [];
  const tplWrap = document.getElementById("wl-template-wrap");
  const tplSel = document.getElementById("wl-template");
  tplWrap.classList.add("hidden");
  api.get("/templates").then((list) => {
    if (!list.length) return;
    clear(tplSel);
    tplSel.append(h("option", { value: "", text: "Nenhum (tarefa em branco)" }),
      ...list.map((t) => h("option", { value: String(t.id), text: t.name + (t.checklist.length ? ` · ${t.checklist.length} itens` : "") })));
    tplSel.onchange = async () => {
      const t = list.find((x) => String(x.id) === tplSel.value);
      checklist = t ? t.checklist : [];
      if (!t) return;
      document.getElementById("wl-title").value = t.title;
      titleInput.oninput && titleInput.oninput(); // título do modelo também procura "já resolvido antes"
      document.getElementById("wl-desc").value = t.description || "";
      document.getElementById("wl-prio").value = String(t.priority);
      after.checked = t.after_hours;
      await projReady;
      if (t.project_id && [...projSel.options].some((o) => o.value === String(t.project_id))) projSel.value = String(t.project_id);
      extras.sync();
      syncObjectives();
    };
    tplWrap.classList.remove("hidden");
  }).catch(() => {});

  document.getElementById("wl-cancel").onclick = () => dlg.close();
  document.getElementById("wl-close").onclick = () => dlg.close();
  // Campos menos usados ficam em "Mais opções" (celular e computador).
  const more = document.getElementById("wl-more"), moreBtn = document.getElementById("wl-more-toggle");
  const setMore = (open) => { more.classList.toggle("open", open); moreBtn.setAttribute("aria-expanded", String(open)); moreBtn.textContent = open ? "Menos opções" : "Mais opções"; };
  setMore(false);
  moreBtn.onclick = () => setMore(!more.classList.contains("open"));
  document.getElementById("form-worklog").onsubmit = async (ev) => {
    ev.preventDefault();
    const payload = {
      title: document.getElementById("wl-title").value.trim(),
      description: document.getElementById("wl-desc").value.trim() || null,
      status: document.getElementById("wl-status").value,
      due_date: document.getElementById("wl-due").value || null,
      priority: Number(document.getElementById("wl-prio").value),
      project_id: pickedProject(),
      extra_project_ids: extras.ids(),
      objective_id: objSel.value ? Number(objSel.value) : null,
      ticket: ticket.value.trim() || null,
      after_hours: after.checked,
    };
    if (!payload.title) return;
    if (payload.status === "done" && doneAt.value) payload.completed_at = doneAt.value;
    if (createdAt.value) payload.created_at = createdAt.value;
    if (payload.status === "done" && resolution.value.trim()) payload.resolution = resolution.value.trim();
    if (payload.status === "blocked") {
      payload.blocked_reason = blocked.value.trim() || null;
      payload.follow_up_on = followUpDay(followUp.value || null);
    }
    const minutes = timeInput.value.trim() ? parseDuration(timeInput.value) : null;
    if (minutes === null && timeInput.value.trim()) {
      // Erro no próprio campo (balão nativo + aria-invalid), como o "Preencha este campo".
      timeInput.setCustomValidity("Tempo inválido. Ex.: 45, 1h30, 2:15."); timeInput.reportValidity(); return;
    }
    const btn = ev.submitter;
    if (btn) btn.disabled = true; // duplo clique criava a tarefa duas vezes
    try {
      const created = await api.post("/worklog", payload);
      if (created && created.queued) {
        // Sem sinal: o resto (checklist, tempo, anotação, fotos) vai junto quando a tarefa for criada.
        for (const label of checklist) await api.after(created.qid, "POST", "/worklog/{id}/checklist", { label });
        if (minutes) await api.after(created.qid, "POST", "/worklog/{id}/time", { minutes });
        if (opts.note) await api.after(created.qid, "POST", "/worklog/{id}/notes", { body: opts.note });
        for (const f of opts.files || []) await api.after(created.qid, "POST", "/worklog/{id}/photos", await prepare(f));
        dlg.close();
        toast("Sem conexão: tarefa guardada no aparelho. Vai sozinha quando a conexão voltar.");
        onDone && onDone();
        return;
      }
      // A tarefa já existe: se checklist ou tempo falharem, não reenviar (duplicaria).
      try {
        for (const label of checklist) await api.post(`/worklog/${created.id}/checklist`, { label });
        if (minutes) await api.post(`/worklog/${created.id}/time`, { minutes });
        // Texto compartilhado de outro app que não coube na descrição: vira anotação.
        if (opts.note) await api.post(`/worklog/${created.id}/notes`, { body: opts.note });
        if (opts.files && opts.files.length) await upload(`/worklog/${created.id}/photos`, opts.files);
      } catch (e) {
        toast(`Tarefa criada, mas ${minutes ? "o tempo ou " : ""}o checklist não foi salvo: ${e.message || "tente pelo detalhe"}.`, { error: true });
      }
      dlg.close();
      onDone && onDone();
    } catch (e) {
      errorToast(e, "Não foi possível salvar.");
    } finally {
      if (btn) btn.disabled = false;
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
  const requireNote = document.getElementById("rec-require-note");
  requireNote.checked = !!(item && item.require_note);
  const time = document.getElementById("rec-time");
  time.value = item && item.remind_at ? item.remind_at.slice(0, 5) : "";

  // Nova rotina: oferece os pacotes por área (projeto + rotinas num toque).
  document.getElementById("rec-pack").classList.toggle("hidden", !!item);
  document.getElementById("rec-pack-btn").onclick = () => { dlg.close(); openPacks(() => onDone && onDone()); };

  const pause = document.getElementById("rec-pause");
  pause.classList.toggle("hidden", !item);
  pause.textContent = item && item.paused_until ? `Pausada até ${shortDate(item.paused_until)}` : "Pausar";
  pause.onclick = item ? () => { dlg.close(); pauseRecurring(item, onDone); } : null;

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
          errorToast(e, "Não foi possível remover.");
        }
      }
    : null;

  document.getElementById("rec-cancel").onclick = () => dlg.close();
  document.getElementById("form-recurring").onsubmit = busy(async (ev) => {
    ev.preventDefault();
    const label = input.value.trim();
    if (!label) return;
    const agenda = sched.value();
    if (!agenda) return;
    try {
      const body = { label, ...agenda, require_note: requireNote.checked, remind_at: time.value || null };
      if (item) await api.patch(`/recurring/${item.id}`, body);
      else await api.post("/recurring", body);
      dlg.close();
      refreshReminders();
      onDone && onDone();
    } catch (e) {
      errorToast(e, "Não foi possível salvar.");
    }
  });
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
  const ivWrap = document.getElementById("rec-interval-wrap");
  const wraps = { weekly: wdBox, monthly: document.getElementById("rec-monthday-wrap") };

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
  const sync = () => {
    for (const [k, el] of Object.entries(wraps)) el.classList.toggle("hidden", freq.value !== k);
    // O mesmo campo de dias serve às duas: da criação ou da última vez que foi marcada.
    ivWrap.classList.toggle("hidden", freq.value !== "interval" && freq.value !== "after");
    document.getElementById("rec-interval-label").textContent = freq.value === "after"
      ? "Quantos dias depois da última vez que foi marcada" : "A cada quantos dias (contando de quando foi criada)";
  };
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
      if (f === "interval" || f === "after") {
        const n = Number(iv.value);
        if (!(n >= 2 && n <= 365)) { toast("Intervalo entre 2 e 365 dias.", { error: true }); return null; }
        return { freq: f, interval_days: n };
      }
      return { freq: "daily" };
    },
  };
}

export function askResolution(t, onDone) {
  // Ao fechar, o "Desfazer" da conclusão volta (o aviso some quando se clica numa ação).
  const undoAgain = () => toast(`Concluída: ${t.title}`, { action: "Desfazer", onAction: () => undoLatest("worklog", t.id, onDone) });
  const area = h("textarea", { rows: "4", maxlength: "1000", placeholder: "ex.: disjuntor trocado e circuito testado", "aria-label": "Como resolveu" });
  const err = h("p", { class: "error-text", role: "alert" });
  area.addEventListener("input", () => markInvalid([area], err, false));
  const form = h("form", {}, h("h2", { text: "Como resolveu?" }),
    h("p", { class: "dialog-note", text: `${t.title}: em poucas linhas. A busca encontra isso da próxima vez que o problema voltar.` }),
    area, err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Agora não", onClick: () => { dlg.close(); undoAgain(); } }),
      h("button", { type: "submit", class: "btn btn-primary", text: "Salvar" })));
  form.addEventListener("submit", busy(async () => {
    if (!area.value.trim()) { dlg.close(); undoAgain(); return; }
    try {
      await api.patch(`/worklog/${t.id}`, { resolution: area.value.trim() });
      dlg.close();
      // Desfaz as duas coisas: a anotação (última ação) e a conclusão.
      toast("Anotado. A busca vai encontrar.", { action: "Desfazer a conclusão", onAction: async () => {
        await undoLatest("worklog", t.id, null);
        await undoLatest("worklog", t.id, onDone);
      } });
      onDone && onDone();
    } catch (e) { err.textContent = e.message || "Não foi possível salvar."; markInvalid([area], err); area.focus(); }
  }));
  const dlg = modal(form);
  area.focus();
}

export async function finishTask(t, onDone, { fromEdit = false } = {}) {
  if (!fromEdit && editingTaskId() === t.id) { toast("Termine a edição da tarefa (Pronto) antes de concluir."); return; }
  const refocus = focusAfterRemoval(); // o foco vai para a tarefa que ficar no lugar
  try {
    const r = await api.post(`/worklog/${t.id}/finish`);
    Promise.resolve(onDone && onDone()).then(refocus);
    if (r && r.queued) { toast(`Concluída sem conexão: ${t.title}. Vai quando a conexão voltar.`); return; }
    // A base de conhecimento só cresce se for perguntada na hora de concluir.
    toast(`Concluída: ${t.title}`, { actions: [
      ["Como resolveu?", () => askResolution(t, onDone)],
      ["Desfazer", () => undoLatest("worklog", t.id, onDone)],
    ] });
  } catch (e) {
    errorToast(e, "Não foi possível concluir.");
  }
}

// "Reabrir" uma concluída (concluiu por engano, ou o problema voltou): volta para
// "a fazer". Como uma edição da situação: o Desfazer devolve a conclusão como era.
export async function reopenTask(t, onDone) {
  try {
    await api.patch(`/worklog/${t.id}`, { status: "todo" });
    Promise.resolve(onDone && onDone());
    toast(`Reaberta: ${t.title}`, { action: "Desfazer", onAction: () => undoLatest("worklog", t.id, onDone) });
  } catch (e) {
    errorToast(e, "Não foi possível reabrir.");
  }
}

// ---------------------------------------------------------------- quadro --

// root: onde montar. opts.readOnly (visão do admin), opts.boardUrl.
export async function mount(root, opts = {}) {
  const readOnly = !!opts.readOnly;
  const boardUrl = opts.boardUrl || "/board";
  // As concluídas do próprio quadro paginam no servidor; a visão da Equipe
  // (rota do viewer) recebe as 200 mais recentes e pagina aqui.
  const serverDone = !readOnly && boardUrl === "/board";
  // Páginas no endereço (#/tarefas?p=2&pc=3), só no quadro da própria pessoa.
  let openPage = readOnly ? 1 : hashPage("p"), donePage = readOnly ? 1 : hashPage("pc");
  let project = readOnly ? "" : sessionStorage.getItem("nexus.board.project") || "";

  // Quadro e projetos (do filtro) vêm juntos: uma ida ao servidor a menos.
  // Busca antes de limpar: na volta à tela, a visita anterior fica até chegar.
  const fetchBoard = () => {
    const qs = [];
    if (project !== "") qs.push(`project=${project}`);
    if (serverDone) qs.push(`done_limit=${DONE_PAGE}`, `done_offset=${(donePage - 1) * DONE_PAGE}`);
    const sep = boardUrl.includes("?") ? "&" : "?";
    return api.get(qs.length ? `${boardUrl}${sep}${qs.join("&")}` : boardUrl);
  };
  let [list, data] = await Promise.all([readOnly ? null : listProjects(true).catch(() => null), fetchBoard()]);

  clear(root);
  // Tarefas (as rotinas ficam na tela Hoje).
  const wip = column("Em aberto");
  const done = column("Concluídas", { collapsible: true, className: "column-done" });
  root.append(h("div", { class: "columns" }, wip.section, done.section));

  // Filtro por projeto (só no quadro do próprio usuário).
  const filter = h("select", { class: "select-sm", "aria-label": "Filtrar por projeto" });
  if (list) {
    filter.append(h("option", { value: "", text: "Todos os projetos" }), h("option", { value: "0", text: "Sem projeto" }),
      ...list.map((p) => h("option", { value: String(p.id), text: p.name })));
    if (![...filter.options].some((o) => o.value === project)) {
      project = ""; // o projeto guardado sumiu: o quadro veio filtrado por ele
      data = await fetchBoard();
    }
    filter.value = project;
    filter.addEventListener("change", () => {
      project = filter.value;
      sessionStorage.setItem("nexus.board.project", project);
      openPage = donePage = 1; // outro filtro: as duas listas voltam à página 1
      refresh();
    });
  }

  // Filtro ativo (Material 3, filter chip): destacado e com um X para limpar.
  const clearFilter = h("button", { type: "button", class: "icon filter-clear", title: "Limpar o filtro", "aria-label": "Limpar o filtro de projeto",
    onClick: () => { filter.value = ""; filter.dispatchEvent(new Event("change")); } }, icon("close"));
  const markFilter = () => {
    filter.classList.toggle("filter-on", project !== "");
    clearFilter.classList.toggle("hidden", project === "");
  };
  filter.addEventListener("change", markFilter);
  markFilter();
  if (opts.setActions && !readOnly) {
    opts.setActions(
      filter.options.length > 2 ? h("div", { class: "filter-wrap" }, filter, clearFilter) : null,
      h("button", { type: "button", class: "btn btn-primary", "data-fab": "", onClick: () => openWorklog(refresh, newTaskOpts()) }, icon("add"), "Tarefa")
    );
  }

  // Quadro filtrado: a tarefa nova já vem com o projeto do filtro (como na tela do projeto).
  function newTaskOpts() {
    if (project === "") return {};
    return { project_id: project === "0" ? null : Number(project) };
  }

  function render(data) {
    if (!readOnly && project === "") lateBadge(data.in_progress, data.today);
    // A linha do assistente, acima do título (só no quadro do próprio usuário).
    if (!readOnly && opts.setAssist) opts.setAssist(boardLine(data.in_progress, data.today, opts.me));
    renderCards(wip, data.in_progress, false, data.today);
    renderCards(done, data.done, true, data.today, data);
  }

  async function refresh() {
    let d = await fetchBoard();
    // A página guardada passou do fim (concluídas que voltaram, outro filtro): a última.
    if (serverDone && d.done_total !== undefined && donePage > 1 && !d.done.length) {
      donePage = Math.max(1, Math.ceil(d.done_total / DONE_PAGE));
      d = await fetchBoard();
    }
    render(d);
  }

  function renderCards(col, items, isDone, today, data = {}) {
    clear(col.body);
    clear(col.foot);
    // Concluídas: o total real (o servidor manda uma página; a Equipe, as 200 mais recentes).
    const total = isDone ? (serverDone ? Math.max(data.done_total ?? 0, items.length) : items.length) : items.length;
    col.count.textContent = String(isDone && data.done_total !== undefined ? Math.max(data.done_total, items.length) : total);
    if (!items.length && !(isDone && serverDone && total)) {
      col.body.append(h("p", { class: "empty", text: isDone ? "Nada concluído ainda." : "Nada em aberto." }));
      if (!readOnly) setHashPage(isDone ? "pc" : "p", 1, "tarefas");
      return;
    }
    const size = isDone ? DONE_PAGE : OPEN_PAGE;
    let list, page;
    if (isDone && serverDone) { list = items; page = donePage; }
    else ({ rows: list, page } = pageSlice(items, isDone ? donePage : openPage, size));
    if (isDone) donePage = page; else openPage = page;
    if (!readOnly) setHashPage(isDone ? "pc" : "p", page, "tarefas");
    for (const it of list) {
      const canCheck = !readOnly && !isDone;  // concluir à esquerda, como no Hoje
      const card = h("article", { class: "card" + (isOverdue(it, today) ? " overdue" : "") + (it.priority === 1 && !isDone ? " high" : "") + (isDone ? " is-done" : "") + (canCheck ? " has-check" : ""), "data-id": it.id },
        h("h3", {}, readOnly ? it.title : h("button", { type: "button", class: "card-open", text: it.title, onClick: () => openTask(it.id, refresh) })));
      if (it.description) card.append(h("p", { text: it.description }));
      card.append(h("div", { class: "card-meta" }, ...taskChips(it, today)));
      if (!readOnly) {
        const actions = h("div", { class: "card-actions" });
        if (canCheck) card.prepend(h("button", { type: "button", class: "icon card-check", title: "Concluir", "aria-label": "Concluir " + it.title, onClick: () => finishTask(it, refresh) }, icon("check")));
        if (!isDone) actions.append(desk(timerButton(it, refresh)), moreButton(it, refresh));
        if (actions.firstChild) card.append(actions);
        withMenu(card, it, refresh);
      }
      col.body.append(card);
    }
    // Equipe: o servidor manda as 200 mais recentes; na última página, diz onde estão as outras.
    if (isDone && !serverDone && data.done_total > items.length && page === Math.ceil(items.length / size))
      col.body.append(h("p", { class: "muted small", text: `Mostrando as ${items.length} mais recentes de ${data.done_total}; as anteriores estão nos relatórios.` }));
    col.foot.append(pager({
      page, total, size, label: isDone ? "concluídas" : "tarefas em aberto",
      onPage: async (n) => {
        if (isDone) donePage = n; else openPage = n;
        if (isDone && serverDone) await refresh();
        else renderCards(col, items, isDone, today, data);
        col.body.scrollTop = 0;
      },
      focus: () => col.title,
    }) || "");
  }

  if (serverDone && donePage > 1 && !data.done.length && data.done_total !== undefined) { // ?pc= além do fim
    donePage = Math.max(1, Math.ceil(data.done_total / DONE_PAGE));
    data = await fetchBoard();
  }
  render(data);
}

function column(title, opts = {}) {
  const count = h("span", { class: "count-badge" });
  const titleEl = h("h2", { text: title });
  const head = h("div", { class: "column-head" }, titleEl, count);
  const body = h("div", { class: "column-body" });
  const foot = h("div", { class: "column-foot" }); // as páginas: fora da rolagem da coluna
  const section = h("section", { class: "column" + (opts.className ? " " + opts.className : "") }, head, body, foot);
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
  return { section, body, foot, count, title: titleEl };
}
