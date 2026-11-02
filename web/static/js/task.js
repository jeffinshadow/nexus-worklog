// Detalhe de uma tarefa: é também onde se edita. O lápis ao lado do título
// troca a leitura (etiquetas) pelos campos: título, descrição e os detalhes
// (status, prazo, projeto...), que salvam sozinhos ao sair do campo.
// Abaixo, checklist, tempo apontado e anotações.
// Abre por cima do quadro/Hoje; ao fechar, quem abriu recarrega (onChange).
import { api } from "./api.js";
import { h, icon, clear, addDays, shortDate, dateTime, field, localDateTime, localDay, sendRow } from "./dom.js";
import { overlay } from "./fila.js";
import { errorToast, modal, toast, undoLatest, busy, sheet, syncRail, growFrom, refocusBy, actionMenu, pager, pageSlice } from "./ui.js";

const ENTRY_PAGE = 10; // anotações e apontamentos: os 10 mais recentes, depois páginas
import { finishTask, reopenTask, deleteTask, duplicateTask, followUpDay, isOverdue, ticketUrl, taskChips, blockTask, canBlock } from "./board.js";
import { extraProjectsField, fillObjectiveSelect, fillProjectSelect } from "./projects.js";
import { session } from "./session.js";
import { timerButton, timerState, startTimer, stopTimer } from "./timer.js";
import { pastedImages, photosSection, upload } from "./fotos.js";
import { returnTask } from "./devolver.js";

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

// Tarefa aberta no painel lateral (computador): o quadro marca o cartão dela.
let sideTaskId = null, sideOwner = null;
export const openTaskId = () => sideTaskId;
// Tarefa em edição no detalhe: concluir (aqui, no cartão, na linha, no menu)
// espera o "Pronto" — a conclusão não sai com um campo pela metade.
let editingId = null;
export const editingTaskId = () => editingId;
const EDIT_HINT = "Termine a edição (Pronto) para concluir";
function markEditing(id) {
  editingId = id;
  for (const el of document.querySelectorAll("[data-task-id], .obj-task[data-task]"))
    el.classList.toggle("editing", id !== null && Number(el.dataset.taskId || el.dataset.task) === id);
}
function markSelected() {
  for (const el of document.querySelectorAll("[data-task-id]"))
    el.classList.toggle("selected", Number(el.dataset.taskId) === sideTaskId);
}
// Fecha o painel lateral (ex.: ao trocar de tela).
export function closeSidePanel() {
  for (const d of document.querySelectorAll("dialog.task-dialog.side[open]")) d.close();
}

// Sem sinal, uma tarefa que nunca foi aberta com sinal não está no cache do
// aparelho: o que houver dela nas listas guardadas (Hoje, Tarefas, busca...)
// serve para mostrar o título e deixar anotar, pôr foto e concluir pela fila.
async function cachedTask(id) {
  if (!("caches" in window)) return null;
  const find = (o, depth) => {
    if (!o || typeof o !== "object" || depth > 5) return null;
    if (Array.isArray(o)) { for (const x of o) { const r = find(x, depth + 1); if (r) return r; } return null; }
    if (o.id === id && typeof o.title === "string" && "status" in o) return o;
    for (const v of Object.values(o)) { const r = find(v, depth + 1); if (r) return r; }
    return null;
  };
  try {
    const cache = await caches.open("nexus-dados");  // o mesmo nome de sw.js
    for (const req of await cache.keys()) {
      if (!new URL(req.url).pathname.startsWith("/api/") || /\/photos/.test(req.url)) continue;
      const hit = find(await (await cache.match(req)).json().catch(() => null), 0);
      if (hit) return hit;
    }
  } catch { /* sem cache */ }
  return null;
}

// opts.editTitle: abre já editando o título, selecionado (a cópia do Duplicar).
export async function openTask(taskId, onChange, opts = {}) {
  // Computador: painel lateral (lista + detalhe, Material 3); o quadro segue
  // visível e clicável ao lado. Celular: tela inteira.
  const side = matchMedia("(min-width: 861px)").matches;
  closeSidePanel(); // um detalhe por vez: abrir outro cartão troca o painel
  let changed = false;
  const entryPages = { notes: 1, time: 1 }; // continuam na mesma página quando a tarefa se redesenha
  const body = h("div", { class: "task-body" });
  const dlg = h("dialog", { class: "task-dialog" + (side ? " side" : ""), "aria-label": "Detalhe da tarefa" }, body);
  document.body.append(dlg);
  // Print colado (Ctrl+V) com o detalhe aberto: vira foto da tarefa.
  dlg.addEventListener("paste", async (ev) => {
    const files = pastedImages(ev);
    if (!files.length) return;
    ev.preventDefault();
    toast("Enviando o print…");
    if (await upload(`/worklog/${taskId}/photos`, files)) { toast("Print adicionado às fotos."); touch(); }
  });
  // Visão expandida (pedido dos clientes, para ler com folga): o painel vira
  // uma janela larga no meio da tela; Esc ou o mesmo botão voltam ao painel.
  let expanded = false;
  const expand = (on) => { expanded = on; dlg.classList.toggle("expanded", on); paint(); };
  const onKey = (ev) => {
    if (ev.key !== "Escape" || document.querySelector("dialog:modal")) return;
    if (expanded) expand(false); else dlg.close();
  };
  // Aberta sem sinal só com o que havia nas listas: a conexão voltou, busca os detalhes.
  const onOnline = () => { if (dlg.open && cur && cur.offline) render(); };
  addEventListener("online", onOnline);
  dlg.addEventListener("close", () => {
    removeEventListener("online", onOnline);
    dlg.remove();
    if (editing && editingId === taskId) markEditing(null);
    if (side) {
      document.removeEventListener("keydown", onKey);
      // O "close" chega depois; se outro painel já abriu, ele é o dono agora.
      if (sideOwner === dlg) { sideOwner = null; sideTaskId = null; document.body.classList.remove("has-side"); syncRail(); markSelected(); }
      // O foco estava no painel (Esc, Fechar): volta ao cartão desta tarefa, não ao topo da página.
      const a = document.activeElement;
      if (!sideOwner && (!a || a === document.body || !a.isConnected)) {
        const card = document.querySelector(`#main [data-task-id="${taskId}"]`);
        if (card) (card.querySelector(".card-open, button") || card).focus();
      }
    }
    if (changed) onChange && onChange();
  });
  // No painel lateral o quadro ao lado se atualiza na hora; na janela, ao fechar.
  // (Um campo salvo ao sair dele pode terminar com a janela já fechada.)
  const notify = () => { if (side || !dlg.open) { if (onChange) onChange(); } else changed = true; };
  const touch = () => { notify(); return render(); };
  // Desfazer pelo aviso pode chegar com o detalhe já fechado: aí recarrega quem abriu.
  const after = () => (dlg.open ? touch() : onChange && onChange());

  // false: não deu para mostrar (o detalhe não abre, ou fecha).
  let offlineBase = null;
  async function render() {
    let t;
    try {
      t = await api.get(`/worklog/${taskId}`);
    } catch (e) {
      if (e.status === 0 && (offlineBase || !cur)) {
        // Sem sinal e sem nada desta tarefa no cache: abre com o que houver das listas.
        if (!offlineBase) {
          const hit = await cachedTask(taskId);
          offlineBase = { title: "Tarefa", status: "todo", ...(hit || {}), id: taskId, offline: true,
            checklist: [], time: [], notes: [], photos: [], minutes: 0, today: localDay() };
        }
        cur = await overlay(`/worklog/${taskId}`, structuredClone(offlineBase));
        paint();
        return true;
      }
      if (e.status === 0 && cur) { errorToast(e); return true; }  // fica com o que já está na tela
      errorToast(e, "Tarefa não encontrada.");
      if (dlg.open) dlg.close();
      return false;
    }
    cur = t;
    offlineBase = null;
    paint();
    return true;
  }

  // Desenha com o que já está em memória (entrar no modo edição não vai ao servidor).
  function paint() {
    const t = cur, today = t.today;
    clear(body);

    // ---- cabeçalho: leitura (título, descrição, etiquetas) ou edição no lugar
    let title = null, titleBlock;
    if (editing) {
      title = h("textarea", { class: "inline-edit inline-title", rows: "1", maxlength: "200", "aria-label": "Título" });
      title.value = t.title;
      // Textarea: a descrição pode ter linhas (atribuída, colada); um <input> as juntaria ao salvar.
      const desc = h("textarea", { class: "inline-edit inline-desc", rows: "1", maxlength: "300", placeholder: "Adicionar descrição", "aria-label": "Descrição" });
      desc.value = t.description || "";
      inline(title, () => cur.title, (v) => (v ? { title: v } : null));
      inline(desc, () => cur.description || "", (v) => ({ description: v || null }));
      title.addEventListener("input", () => grow(title));
      desc.addEventListener("input", () => grow(desc));
      titleBlock = [title, desc];
    } else {
      titleBlock = [h("h2", { text: t.title }),
        t.description ? h("p", { class: "task-desc", text: t.description }) : null,
        t.resolution && t.status === "done" ? h("p", { class: "resolution" }, h("strong", { text: "Como resolveu: " }), t.resolution) : null,
        h("div", { class: "card-meta" }, ...taskChips(t, today))];
    }
    // Lápis ao lado do título: entra na edição; "Pronto" volta (e busca do
    // servidor o que mudou, para as etiquetas saírem certas).
    const off = !!t.offline;  // aberta sem sinal: só o que vai pela fila
    const toggle = off ? null : editing
      ? h("button", { type: "button", class: "btn btn-ghost btn-sm edit-toggle", onClick: async () => { await pending; editing = false; markEditing(null); render(); } }, icon("check"), "Pronto")
      : h("button", { type: "button", class: "icon edit-toggle", title: "Editar a tarefa", "aria-label": "Editar a tarefa",
          onClick: () => { editing = true; markEditing(t.id); refocus = "Título"; paint(); } }, icon("edit"));

    const remove = async () => { if (await deleteTask(t, onChange)) dlg.close(); };
    // A cópia leva o que está salvo: espera o último campo e abre no lugar desta.
    const dup = async () => { await pending; dlg.close(); duplicateTask(cur, onChange); };
    // Atribuída por outra pessoa e ainda aberta: devolver com o motivo (sai das tarefas dela).
    const giveBack = t.assigned_by_name && t.status !== "done" && !off
      ? async () => { await pending; if (await returnTask(cur, onChange)) dlg.close(); } : null;
    const head = h("div", { class: "task-head" },
      h("div", { class: "task-title" }, h("div", { class: "title-row" }, h("div", { class: "title-main" }, ...titleBlock), toggle),
        t.assigned_by_name ? h("p", { class: "assigned-note" }, icon("send"), "Atribuída por " + t.assigned_by_name,
          giveBack ? h("button", { type: "button", class: "btn btn-text btn-sm", onClick: giveBack }, "Devolver…") : null) : null),
      h("div", { class: "task-tools" },
        timerButton(t, after),
        t.status !== "done"
          ? h("button", { type: "button", class: "icon", title: editing ? EDIT_HINT : "Concluir", "aria-label": "Concluir", disabled: editing ? "disabled" : null,
              onClick: () => finishTask(t, after) }, icon("check"))
          : off ? null : h("button", { type: "button", class: "icon", title: "Reabrir", "aria-label": "Reabrir", onClick: async () => { await pending; reopenTask(cur, after); } }, icon("undo")),
        // Aguardando à vista (decisão do dono, 02/11): o mesmo diálogo do menu do cartão.
        !off && canBlock(t) ? h("button", { type: "button", class: "icon", title: "Marcar como aguardando", "aria-label": "Marcar como aguardando",
          onClick: async () => { await pending; blockTask(cur, after); } }, icon("clock")) : null,
        ...(off ? [] : [
          h("button", { type: "button", class: "icon", title: "Copiar resumo (para o chamado ou o cliente)", "aria-label": "Copiar resumo", onClick: async () => { await pending; copySummary(cur); } }, icon("copy")),
          h("button", { type: "button", class: "icon", title: "Duplicar tarefa", "aria-label": "Duplicar tarefa", onClick: dup }, icon("add")),
          h("button", { type: "button", class: "icon", title: "Excluir", "aria-label": "Excluir", onClick: remove }, icon("trash"))]),
        h("button", { type: "button", class: "icon", title: "Fechar", "aria-label": "Fechar", onClick: () => dlg.close() }, icon("close"))));

    // Celular e painel lateral: barra no topo (fechar e o resto no ⋮) e as
    // duas ações principais como botões grandes abaixo do título.
    const appbar = h("div", { class: "task-appbar" },
      h("button", { type: "button", class: "icon", title: "Fechar", "aria-label": "Fechar", onClick: () => dlg.close() }, icon("close")),
      h("span", { class: "task-appbar-title", text: "Tarefa" }),
      saved,
      side ? h("button", { type: "button", class: "icon", title: expanded ? "Voltar ao painel" : "Expandir para ler",
        "aria-label": expanded ? "Voltar ao painel" : "Expandir para ler", "aria-pressed": String(expanded),
        onClick: () => expand(!expanded) }, icon(expanded ? "shrink" : "expand")) : null,
      off ? null : h("button", { type: "button", class: "icon", title: "Mais ações", "aria-label": "Mais ações", onClick: (ev) => {
        const items = [
          t.status === "done" ? ["Reabrir", "undo", async () => { await pending; reopenTask(cur, after); }] : null,
          ["Copiar resumo (para o chamado ou o cliente)", "copy", async () => { await pending; copySummary(cur); }],
          ["Duplicar tarefa", "add", dup],
          giveBack ? ["Devolver a quem atribuiu…", "undo", giveBack] : null,
          ["Excluir tarefa", "trash", remove],
        ];
        // Computador (painel ao lado): menu junto do botão, como o clique direito; celular: folha de baixo.
        if (!side) sheet(t.title, items); else actionMenu(ev.currentTarget, t.title, items);
      } }, icon("more-v")));
    const running = (timerState() || {}).task_id === t.id;
    // Concluída: o botão grande é o "Reabrir" (o mesmo do menu).
    const mainActs = t.status === "done" ? (off ? null : h("div", { class: "task-main-actions" },
      h("button", { type: "button", class: "btn btn-ghost", onClick: async () => { await pending; reopenTask(cur, after); } }, icon("undo"), "Reabrir")))
      : h("div", { class: "task-main-actions" },
      h("button", { type: "button", class: "btn btn-ghost" + (running ? " timer-on" : ""), onClick: () => (running ? stopTimer(after) : startTimer(t, after)) },
        icon(running ? "stop" : "play"), running ? "Parar cronômetro" : "Cronômetro"),
      !off && canBlock(t) ? h("button", { type: "button", class: "btn btn-ghost", onClick: async () => { await pending; blockTask(cur, after); } },
        icon("clock"), "Aguardando") : null,
      h("button", { type: "button", class: "btn btn-primary", title: editing ? EDIT_HINT : null, disabled: editing ? "disabled" : null,
        onClick: () => finishTask(t, after) }, icon("check"), "Concluir"));
    if (mainActs && mainActs.children.length === 3) mainActs.classList.add("three");

    const offNote = off ? h("p", { class: "offline-note", role: "status" }, icon("alert"),
      h("span", { text: "Sem conexão: os detalhes desta tarefa aparecem quando a conexão voltar. Anotação, foto, concluir e cronômetro ficam guardados e vão sozinhos." })) : null;
    body.append(...(off ? [appbar, head, offNote, mainActs, photosSection(t, touch), notesPanel(t)]
      : [appbar, head, mainActs, editing ? details(t, today) : null, checklist(t), photosSection(t, touch), timePanel(t, today), notesPanel(t)]).filter(Boolean));
    if (title) requestAnimationFrame(() => { grow(title); grow(body.querySelector(".inline-desc")); }); // a altura só existe com o campo na tela (e o painel aberto)
    // Redesenhou com o foco num campo (ex.: trocou o status): volta para ele.
    if (refocus) { const el = body.querySelector(`[aria-label="${refocus}"]`); if (el) el.focus(); refocus = null; }
  }

  // ---- edição no lugar
  // Salva só o que mudou; na falha, avisa e redesenha com o que está no servidor.
  let cur = null, refocus = null, savedTimer = null, editing = false;
  let rowEdit = null; // "time:<id>" ou "note:<id>": a linha que está sendo corrigida
  let pending = Promise.resolve(); // o último salvamento (o "Pronto" espera ele)
  const saved = h("span", { class: "saved-mark", "aria-live": "polite" });
  function save(patch, redraw = false) {
    pending = doSave(patch, redraw);
    return pending;
  }
  async function doSave(patch, redraw) {
    try { await api.patch(`/worklog/${taskId}`, patch); }
    catch (e) { errorToast(e, "Não foi possível salvar."); await render(); return; }
    Object.assign(cur, patch);
    notify();
    saved.textContent = "Salvo";
    clearTimeout(savedTimer);
    savedTimer = setTimeout(() => { saved.textContent = ""; }, 1800);
    if (redraw) { refocus = document.activeElement && document.activeElement.getAttribute("aria-label"); await render(); }
  }
  // Campo de texto: Enter salva, Esc desfaz (os dois mantêm o foco no campo;
  // Esc sem nada a desfazer fecha, como fora dele); salva também ao sair.
  // toPatch(valor) devolve o que mandar, ou null para voltar ao valor anterior.
  function inline(el, original, toPatch) {
    const multi = el.tagName === "TEXTAREA" && !el.classList.contains("inline-title");
    const commit = () => {
      const v = el.value.trim();
      if (v === original()) return;
      const patch = toPatch(v);
      if (!patch) { el.value = original(); grow(el); return; }
      save(patch);
    };
    el.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && el.value.trim() !== original()) { ev.preventDefault(); ev.stopPropagation(); el.value = original(); grow(el); }
      else if (ev.key === "Enter" && (!multi || ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); commit(); }
    });
    el.addEventListener("blur", commit);
  }
  function grow(el) {
    if (!el || !el.classList.contains("inline-title") && !el.classList.contains("inline-desc")) return;
    el.style.height = "auto";
    el.style.height = el.scrollHeight + "px";
  }

  // ---- detalhes (o que antes ficava na janela "Editar")
  function details(t, today) {
    const sec = h("section", { class: "task-sec task-props" },
      h("div", { class: "task-sec-head" }, icon("edit"), h("h3", { text: "Detalhes" })));
    const grid = h("div", { class: "props" });

    const status = h("select", { "aria-label": "Situação" },
      ...[["todo", "A fazer"], ["in_progress", "Em andamento"], ["blocked", "Aguardando"], ["done", "Concluída"]]
        .map(([v, l]) => h("option", { value: v, text: l })));
    status.value = t.status;
    status.addEventListener("change", () => {
      // Concluir pelo status = o mesmo concluir dos botões (com "Como resolveu?").
      if (status.value === "done") { refocus = "Situação"; finishTask(t, after, { fromEdit: true }); }
      else save({ status: status.value }, true);
    });

    const due = h("input", { type: "date", "aria-label": "Prazo", class: isOverdue(t, today) ? "late" : "" });
    due.value = t.due_date || "";
    due.addEventListener("change", () => {
      due.classList.toggle("late", !!due.value && due.value < today && t.status !== "done");
      save({ due_date: due.value || null });
    });

    // Lembrar em: data e hora do aviso (na tela e no aparelho). Vazio tira.
    const remind = h("input", { type: "datetime-local", "aria-label": "Lembrete com hora" });
    const nowLocal = localDateTime(Date.now());
    remind.value = t.remind_at ? localDateTime(t.remind_at) : "";
    remind.min = remind.value && remind.value < nowLocal ? remind.value : nowLocal;  // um lembrete já passado fica como está
    remind.addEventListener("change", () => save({ remind_at: remind.value || null }).then(() => import("./lembretes.js").then((m) => m.refreshReminders())));

    const proj = h("select", { "aria-label": "Projeto" });
    // Demanda que atende mais de uma frente: outros projetos além do principal.
    const extras = extraProjectsField((t.extra_projects || []).map((p) => p.id), () => cur.project_id || null,
      (ids) => save({ extra_project_ids: ids }));
    // Objetivo: só os do projeto principal (trocar o projeto tira do objetivo).
    const obj = h("select", { "aria-label": "Objetivo" });
    const objField = field("Objetivo", obj, "wide");
    // Só aparece quando o projeto tem objetivos (sem projeto ou sem objetivos, não há o que escolher).
    const syncObj = (pid, sel) => fillObjectiveSelect(obj, pid, sel)
      .then((list) => objField.classList.toggle("hidden", !(list || []).length)).catch(() => {});
    objField.classList.add("hidden");
    syncObj(t.project_id, t.objective_id);
    obj.addEventListener("change", () => save({ objective_id: obj.value ? Number(obj.value) : null }));
    fillProjectSelect(proj, t.project_id, (v) => {
      const id = v ? Number(v) : null;
      if (id !== (cur.project_id || null)) save({ project_id: id }).then(() => {
        extras.sync();
        cur.objective_id = null;
        syncObj(id, null);
      });
    }).catch(() => {});

    const prio = h("select", { "aria-label": "Prioridade" },
      h("option", { value: "1", text: "Alta" }), h("option", { value: "2", text: "Normal" }), h("option", { value: "3", text: "Baixa" }));
    prio.value = String(t.priority || 2);
    prio.addEventListener("change", () => save({ priority: Number(prio.value) }));

    const ticket = h("input", { type: "text", maxlength: "41", placeholder: "ex.: 4821", autocomplete: "off", "aria-label": "Nº do chamado ou OS" });
    ticket.value = t.ticket || "";
    inline(ticket, () => cur.ticket || "", (v) => ({ ticket: v || null }));
    ticket.id = "f-ticket-" + t.id;
    const url = t.ticket ? ticketUrl(t.ticket) : null;

    const afterHours = h("input", { type: "checkbox", "aria-label": "Plantão / fora do horário" });
    afterHours.checked = !!t.after_hours;
    afterHours.addEventListener("change", () => save({ after_hours: afterHours.checked }));

    grid.append(field("Situação", status), field("Prazo", due),
      ...(t.status !== "done" ? [field("Lembrete com hora", remind)] : []), field("Prioridade", prio), field("Projeto", proj, t.status !== "done" ? "wide" : ""),
      objField,
      h("div", { class: "field wide" }, h("span", { class: "field-label", text: "Outros projetos" }), extras.el),
      h("div", { class: "field" }, h("label", { for: ticket.id, text: "Nº do chamado ou OS" }),
        url ? h("div", { class: "with-link" }, ticket, h("a", { class: "icon", href: url, target: "_blank", rel: "noopener noreferrer", title: "Abrir o chamado", "aria-label": "Abrir o chamado" }, icon("right"))) : ticket,
        // Sem endereço (nem da administração nem da pessoa): o número fica só texto; uma dica discreta.
        t.ticket && !url ? h("small", { class: "ticket-hint" },
          h("a", { href: "#/config?aba=conta", text: "Configure o endereço do sistema de chamados" }), " em Configurações › Conta.") : null),
      h("div", { class: "field field-check" }, h("label", { class: "check-line" }, afterHours, h("span", { text: "Plantão / fora do horário" }))));

    if (t.status === "blocked") {
      const reason = h("input", { type: "text", maxlength: "120", placeholder: "ex.: retorno do fornecedor", "aria-label": "Aguardando o quê?" });
      reason.value = t.blocked_reason || "";
      inline(reason, () => cur.blocked_reason || "", (v) => ({ blocked_reason: v || null }));
      const follow = h("input", { type: "date", "aria-label": "Dia para cobrar" });
      follow.value = t.follow_up_on || "";
      // Hoje ou depois — mas uma cobrança já atrasada pode ficar como está.
      follow.min = t.follow_up_on && t.follow_up_on < today ? t.follow_up_on : today;
      follow.addEventListener("change", () => {
        const day = followUpDay(follow.value || null);
        follow.value = day || "";
        save({ follow_up_on: day });
      });
      grid.append(field("Aguardando o quê?", reason), field("Dia para cobrar", follow));
    }
    if (t.status === "done") {
      const now = localDateTime(Date.now());
      const doneAt = h("input", { type: "datetime-local", "aria-label": "Concluída em", max: now,
        min: addDays(now.slice(0, 10), -((session.me && session.me.retro_days) || 60)) + "T00:00" });
      doneAt.value = t.completed_at ? localDateTime(t.completed_at) : "";
      doneAt.addEventListener("change", () => { if (doneAt.value) save({ completed_at: doneAt.value }); });
      const resolution = h("textarea", { rows: "2", maxlength: "1000", placeholder: "ex.: disjuntor trocado e circuito testado", "aria-label": "Como resolveu?" });
      resolution.value = t.resolution || "";
      inline(resolution, () => cur.resolution || "", (v) => ({ resolution: v || null }));
      grid.append(field("Concluída em", doneAt), field("Como resolveu? (entra na busca)", resolution, "wide"));
    }
    sec.append(grid);
    return sec;
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
      if (rowEdit === "check:" + c.id) { sec.append(checkEditForm(c)); continue; }
      const cb = h("input", { type: "checkbox", "aria-label": c.label });
      cb.checked = c.done;
      cb.addEventListener("change", async () => {
        try { await api.patch(`/checklist/${c.id}`, { done: cb.checked }); await touch(); refocusBy(body, c.label); }
        catch (e) { cb.checked = !cb.checked; errorToast(e); }
      });
      sec.append(h("label", { class: "check-row" + (c.done ? " done" : "") }, cb, h("span", { class: "label", text: c.label }),
        t.offline ? null : h("button", { type: "button", class: "icon", title: "Corrigir o texto do item", "aria-label": "Corrigir " + c.label,
          onClick: (ev) => { ev.preventDefault(); editRow("check:" + c.id, "Texto do item"); } }, icon("edit")),
        h("button", { type: "button", class: "icon", title: "Excluir item", "aria-label": "Excluir " + c.label, onClick: async (ev) => {
          ev.preventDefault();
          try {
            await api.del(`/checklist/${c.id}`);
            touch();
            toast("Item excluído.", { action: "Desfazer", onAction: () => undoLatest("checklist", c.id, after) });
          } catch (e) { errorToast(e); }
        } }, icon("trash"))));
    }
    const input = h("input", { type: "text", maxlength: "200", placeholder: "Adicionar item", "aria-label": "Novo item do checklist" });
    sec.append(sendRow(input, async () => {
      input.disabled = true;
      try { await api.post(`/worklog/${t.id}/checklist`, { label: input.value.trim() }); await touch(); focusLast(".task-sec input[type=text]"); }
      catch (e) { input.disabled = false; errorToast(e); }
    }, "Adicionar item", "task-add"));
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
    dur.addEventListener("input", () => dur.setCustomValidity("")); // erro some ao corrigir
    const day = h("input", { type: "date", value: today, max: today, min: addDays(today, -366), "aria-label": "Dia" });
    const note = h("input", { type: "text", maxlength: "200", placeholder: "o que foi feito (opcional)", "aria-label": "Observação" });
    const form = h("form", { class: "time-form" }, dur, day, note,
      h("button", { type: "submit", class: "btn btn-ghost btn-sm" }, icon("add"), "Apontar"));
    form.addEventListener("submit", busy(async (ev) => {
      ev.preventDefault();
      const minutes = parseDuration(dur.value);
      if (!minutes || minutes > 1440) { dur.setCustomValidity("Duração inválida. Ex.: 45, 1h30, 2:15."); dur.reportValidity(); return; }
      try {
        await api.post(`/worklog/${t.id}/time`, { minutes, day: day.value || today, note: note.value.trim() || null });
        toast(`Apontado ${duration(minutes)}.`);
        entryPages.time = 1; // o novo aparece em cima, na página 1
        touch();
      } catch (e) { errorToast(e); }
    }));
    sec.append(form);
    const box = h("div");
    sec.append(box);
    const row = (e) => {
      if (rowEdit === "time:" + e.id) { box.append(timeEditForm(e, today)); return; }
      const what = `${duration(e.minutes)} em ${shortDate(e.day)}`;
      box.append(h("div", { class: "mini-row" },
        h("span", { class: "mono when", text: shortDate(e.day) }),
        h("span", { class: "mono amount", text: duration(e.minutes) }),
        h("span", { class: "what" }, e.note || "", actorBadge(e)),
        h("button", { type: "button", class: "icon", title: "Corrigir apontamento", "aria-label": "Corrigir apontamento de " + what,
          onClick: () => editRow("time:" + e.id, "Duração do apontamento") }, icon("edit")),
        h("button", { type: "button", class: "icon", title: "Excluir apontamento", "aria-label": "Excluir apontamento de " + what, onClick: async () => {
          try {
            await api.del(`/time/${e.id}`);
            touch();
            toast("Apontamento excluído.", { action: "Desfazer", onAction: () => undoLatest("time", e.id, after) });
          } catch (err) { errorToast(err); }
        } }, icon("trash"))));
    };
    pagedEntries(box, t.time, "time", row, "apontamentos de tempo", sec.querySelector("h3"));
    return sec;
  }

  // Corrigir um apontamento ou uma anotação no lugar da linha: Salvar (ou Enter) e
  // Cancelar (ou Esc). O aviso traz o Desfazer, como nas exclusões.
  function editRow(key, focusLabel) {
    rowEdit = key;
    refocus = focusLabel;
    paint();
  }
  function closeRow(backLabel) {
    rowEdit = null;
    paint();
    if (backLabel) refocusBy(body, backLabel);
  }
  function timeEditForm(e, today) {
    const back = "Corrigir apontamento de " + `${duration(e.minutes)} em ${shortDate(e.day)}`;
    const dur = h("input", { type: "text", class: "dur", value: duration(e.minutes).replace(" min", ""), "aria-label": "Duração do apontamento" });
    dur.addEventListener("input", () => dur.setCustomValidity(""));
    const day = h("input", { type: "date", value: e.day, max: today, min: addDays(today, -366), "aria-label": "Dia do apontamento" });
    const note = h("input", { type: "text", maxlength: "200", value: e.note || "", placeholder: "o que foi feito (opcional)", "aria-label": "Observação do apontamento" });
    const form = h("form", { class: "time-form row-edit" }, dur, day, note,
      h("div", { class: "row-edit-actions" },
        h("button", { type: "button", class: "btn btn-text btn-sm", text: "Cancelar", onClick: () => closeRow(back) }),
        h("button", { type: "submit", class: "btn btn-primary btn-sm", text: "Salvar" })));
    form.addEventListener("keydown", (ev) => { if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); closeRow(back); } });
    form.addEventListener("submit", busy(async (ev) => {
      ev.preventDefault();
      const minutes = parseDuration(dur.value);
      if (!minutes || minutes > 1440) { dur.setCustomValidity("Duração inválida. Ex.: 45, 1h30, 2:15."); dur.reportValidity(); return; }
      try {
        await api.patch(`/time/${e.id}`, { minutes, day: day.value || e.day, note: note.value.trim() || null });
        rowEdit = null;
        await touch();
        refocusBy(body, "Corrigir apontamento de " + `${duration(minutes)} em ${shortDate(day.value || e.day)}`);
        toast(`Apontamento corrigido: ${duration(minutes)}.`, { action: "Desfazer", onAction: () => undoLatest("time", e.id, after) });
      } catch (err) { errorToast(err, "Não foi possível corrigir."); }
    }));
    return form;
  }
  // Corrigir o texto de um item do checklist (fica no mesmo lugar da lista).
  function checkEditForm(c) {
    const input = h("input", { type: "text", maxlength: "200", value: c.label, "aria-label": "Texto do item" });
    const save = busy(async () => {
      const v = input.value.trim();
      if (!v || v === c.label) { closeRow("Corrigir " + c.label); return; }
      try {
        await api.patch(`/checklist/${c.id}`, { label: v });
        rowEdit = null;
        await touch();
        refocusBy(body, "Corrigir " + v);
        toast("Item corrigido.", { action: "Desfazer", onAction: () => undoLatest("checklist", c.id, after) });
      } catch (e) { errorToast(e, "Não foi possível corrigir."); }
    });
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); closeRow("Corrigir " + c.label); }
      else if (ev.key === "Enter") { ev.preventDefault(); save(); }
    });
    return h("div", { class: "check-row row-edit" }, input,
      h("div", { class: "row-edit-actions" },
        h("button", { type: "button", class: "btn btn-text btn-sm", text: "Cancelar", onClick: () => closeRow("Corrigir " + c.label) }),
        h("button", { type: "button", class: "btn btn-primary btn-sm", text: "Salvar", onClick: save })));
  }
  function noteEditForm(n) {
    const text = h("textarea", { rows: "3", maxlength: "2000", "aria-label": "Texto da anotação" });
    text.value = n.body;
    const back = "Editar anotação de " + dateTime(n.created_at);
    const save = busy(async () => {
      const v = text.value.trim();
      if (!v) { text.setCustomValidity("Escreva a anotação, ou cancele."); text.reportValidity(); return; }
      if (v === n.body) { closeRow(back); return; }
      try {
        await api.patch(`/notes/${n.id}`, { body: v });
        rowEdit = null;
        await touch();
        refocusBy(body, back);
        toast("Anotação corrigida.", { action: "Desfazer", onAction: () => undoLatest("note", n.id, after) });
      } catch (e) { errorToast(e, "Não foi possível corrigir."); }
    });
    text.addEventListener("input", () => text.setCustomValidity(""));
    text.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); closeRow(back); }
      else if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); save(); }
    });
    return h("div", { class: "note row-edit" },
      h("div", { class: "note-meta" }, h("span", { class: "mono", text: dateTime(n.created_at) })),
      text,
      h("div", { class: "row-edit-actions" },
        h("button", { type: "button", class: "btn btn-text btn-sm", text: "Cancelar", onClick: () => closeRow(back) }),
        h("button", { type: "button", class: "btn btn-primary btn-sm", text: "Salvar", onClick: save })));
  }
  // Uma página de anotações ou apontamentos (os mais recentes primeiro).
  function pagedEntries(box, items, key, row, label, heading) {
    const paint = () => {
      clear(box);
      const { rows, page } = pageSlice(items, entryPages[key], ENTRY_PAGE);
      entryPages[key] = page;
      rows.forEach(row);
      const nav = pager({ page, total: items.length, size: ENTRY_PAGE, label, compact: true,
        onPage: (n) => { entryPages[key] = n; paint(); }, focus: heading });
      if (nav) box.append(nav);
    };
    paint();
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
      try { await api.post(`/worklog/${t.id}/notes`, { body: v }); entryPages.notes = 1; touch(); }
      catch (e) { errorToast(e); }
    };
    text.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); send(); } });
    sec.append(h("div", { class: "note-form" }, text,
      h("button", { type: "button", class: "btn btn-ghost btn-sm", onClick: send }, "Anotar")));
    const box = h("div");
    sec.append(box);
    const row = (n) => {
      if (rowEdit === "note:" + n.id) { box.append(noteEditForm(n)); return; }
      const when = dateTime(n.created_at);
      box.append(h("div", { class: "note" },
        h("div", { class: "note-meta" }, h("span", { class: "mono", text: when }), actorBadge(n),
          n.pending || t.offline ? null : h("button", { type: "button", class: "icon", title: "Editar anotação", "aria-label": "Editar anotação de " + when,
            onClick: () => editRow("note:" + n.id, "Texto da anotação") }, icon("edit")),
          n.pending ? h("span", { class: "chip today", text: "esperando conexão" }) : h("button", { type: "button", class: "icon", title: "Excluir anotação", "aria-label": "Excluir anotação de " + when, onClick: async () => {
            try {
              await api.del(`/notes/${n.id}`);
              touch();
              toast("Anotação excluída.", { action: "Desfazer", onAction: () => undoLatest("note", n.id, after) });
            } catch (e) { errorToast(e); }
          } }, icon("trash"))),
        h("p", { text: n.body })));
    };
    pagedEntries(box, t.notes, "notes", row, "anotações", sec.querySelector("h3"));
    if (!t.notes.length) sec.append(h("p", { class: "empty", text: "Nada anotado ainda." }));
    return sec;
  }

  if (opts.editTitle) { editing = true; markEditing(taskId); }
  if (!(await render())) { removeEventListener("online", onOnline); dlg.remove(); return; }
  const pickTitle = () => { const el = body.querySelector(".inline-title"); if (el) { el.focus(); el.select(); } };
  if (!side) { dlg.showModal(); growFrom(dlg); if (opts.editTitle) pickTitle(); return; }
  dlg.show();
  sideOwner = dlg;
  sideTaskId = taskId;
  document.body.classList.add("has-side");
  syncRail();
  markSelected();
  document.addEventListener("keydown", onKey);
  const first = dlg.querySelector(".task-appbar button");
  if (opts.editTitle) pickTitle();
  else if (first) first.focus();
}

// Resumo para colar no chamado (GLPI, Jira...) ou no e-mail do cliente: o que
// foi feito, como resolveu e o tempo, montado do que já está registrado.
export function summaryText(t) {
  const linhas = [t.title + (t.ticket ? ` (chamado ${t.ticket})` : "")];
  if (t.description) linhas.push(t.description);
  const feitos = t.checklist.filter((c) => c.done).map((c) => `- ${c.label}`);
  if (feitos.length) linhas.push("", "Feito:", ...feitos);
  if (t.resolution) linhas.push("", "Como foi resolvido:", t.resolution);
  if (t.minutes) linhas.push("", `Tempo: ${duration(t.minutes)}`);
  if (t.status === "done" && t.completed_at) linhas.push(`Concluído em ${dateTime(t.completed_at)}.`);
  return linhas.join("\n");
}

async function copySummary(t) {
  const text = summaryText(t);
  try { await navigator.clipboard.writeText(text); toast("Resumo copiado. Cole no chamado ou no e-mail."); }
  catch {
    const area = h("textarea", { rows: "10", readonly: "readonly", class: "handoff-text", "aria-label": "Resumo da tarefa" });
    area.value = text;
    const dlg = modal(h("h2", { text: "Resumo da tarefa" }), area,
      h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-text", text: "Fechar", onClick: () => dlg.close() })));
    area.select();
  }
}
