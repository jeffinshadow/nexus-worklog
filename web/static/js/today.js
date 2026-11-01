// Tela inicial "Hoje": o dia em um olhar e as ações mais comuns sem trocar de
// tela. É o único lugar das rotinas (marcar até 7 dias atrás, editar, achado).
import { api } from "./api.js";
import { h, icon, clear, weekdayDate, localDay, addDays, shortDate } from "./dom.js";
import { errorToast, modal, toast, busy, refocusBy, actionMenu, calmMotion, undoLatest } from "./ui.js";
import { reminderState, refreshReminders } from "./lembretes.js";
import { photoGrid } from "./fotos.js";
import { openRecurring, pauseRecurring, openWorklog, finishTask, askResolution, taskChips, isOverdue, scheduleLabel, dayLabel, moreButton, desk, lateBadge, withMenu } from "./board.js";
import { openTask } from "./task.js";
import { fillProjectSelect } from "./projects.js";
import { summaryPanel } from "./summary.js";
import { quickRegister, lastDone } from "./quick.js";
import { todayCard } from "./assistant.js";
import { timerButton } from "./timer.js";
import { todayRenewals } from "./renewals.js";
import { packButton } from "./pacotes.js";

const LAST_PROJECT = "nexus.quick.project";
const OPEN_FILTER = "nexus.today.filter";
// Filtro das abertas: todas, as que vencem até hoje (atrasadas inclusas) ou só as de prioridade alta.
const FILTERS = [
  ["all", "Todas", () => true, "Nada em aberto."],
  ["due", "Vence hoje", (t, today) => !!t.due_date && t.due_date <= today, "Nada vencendo hoje nem atrasado."],
  ["prio", "Prioritárias", (t) => t.priority === 1, "Nenhuma tarefa de prioridade alta em aberto."],
];

// opts.day: dia das rotinas (padrão hoje); opts.focusQuick: volta o cursor ao
// registro rápido (lote de itens seguidos); opts.summary: reaproveita o resumo.
// Busca pendente do "já resolvido antes" da montagem anterior (refresh/navegação).
let pendingHint = null;

export async function mount(root, ctx, opts = {}) {
  if (pendingHint) pendingHint();
  const day = opts.day || null;
  const refresh = () => mount(root, ctx, { day });
  const vencP = todayRenewals(() => mount(root, ctx, { day })); // em paralelo com o quadro
  const [b, sum] = await Promise.all([
    api.get(day ? `/board?day=${day}` : "/board"),
    opts.summary ? Promise.resolve(opts.summary) : api.get("/summary").catch(() => null),
  ]);
  const today = b.today;
  ctx.setEyebrow(weekdayDate(today) + (b.work_day ? "" : " · não útil"));
  ctx.setActions(
    h("button", { type: "button", class: "btn btn-ghost", title: "Texto pronto com o que fica aberto, o que está aguardando e o que foi concluído nas últimas 12 h", onClick: showHandoff }, icon("copy"), "Passagem de turno"),
    h("button", { type: "button", class: "btn btn-primary", "data-fab": "", onClick: () => openWorklog(refresh) }, icon("add"), "Tarefa")
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
  if (!day) lateBadge(open, today);

  clear(root);

  // ---- rotinas (do dia escolhido)
  const go = (d) => mount(root, ctx, { day: d === today ? null : d, summary: sum });
  const prev = h("button", { type: "button", class: "icon", title: "Dia anterior", "aria-label": "Dia anterior", onClick: () => go(addDays(b.day, -1)) }, icon("left"));
  const next = h("button", { type: "button", class: "icon", title: "Próximo dia", "aria-label": "Próximo dia", onClick: () => go(addDays(b.day, 1)) }, icon("right"));
  prev.disabled = b.day <= b.min_day;
  next.disabled = b.day >= today;
  const recPanel = h("section", { class: "panel t-rec" },
    h("div", { class: "panel-head" }, h("h2", { text: "Rotinas" }), h("span", { class: "count", text: `${recDone}/${due.length}${extraTxt}` }),
      b.recurring.length > 1 ? h("button", { type: "button", class: "icon", title: "Mudar a ordem das rotinas", "aria-label": "Mudar a ordem das rotinas",
        onClick: () => reorderRoutines(ctx.me.id, refresh) }, icon("grip")) : null,
      h("button", { type: "button", class: "icon accent", title: "Nova rotina", "aria-label": "Nova rotina", onClick: () => openRecurring(null, refresh) }, icon("add"))),
    h("div", { class: "day-nav" }, prev, h("span", { class: "day-nav-label", text: dayLabel(b.day, today) }), next));
  if (due.length) {
    const bar = h("span");
    bar.style.width = `${Math.round((recDone / due.length) * 100)}%`;
    recPanel.append(h("div", { class: "progress", role: "img", "aria-label": `${recDone} de ${due.length} feitas` }, bar));
  }
  if (!b.recurring.length)
    recPanel.append(h("p", { class: "empty", text: "Nenhuma rotina ainda. Crie o que você confere sempre (rondas, equipamentos, fila de pedidos, e-mail…) ou comece com um pacote da sua área." }),
      packButton(refresh));
  else if (!due.length)
    recPanel.append(h("p", { class: "empty", text: "Nada previsto para este dia. Marcar mesmo assim conta como extra." }));
  for (const r of [...due, ...off]) {
    const cb = h("input", { type: "checkbox", "aria-label": r.label });
    cb.checked = r.done_today;
    cb.addEventListener("change", async () => {
      // Tela aberta desde ontem (ou servida do cache): "Hoje" já é outro dia.
      if (b.day === today && today !== localDay(Date.now())) {
        cb.checked = !cb.checked;
        toast("Virou o dia: a tela foi atualizada. Marque de novo, se for o caso.");
        refresh();
        return;
      }
      // Rotina que exige evidência: marcar abre o campo antes de salvar.
      if (cb.checked && r.require_note && !r.note) {
        cb.checked = false;
        editEvidence(r, b.day, refresh);
        return;
      }
      try {
        await api.post(`/recurring/${r.id}/toggle`, { done: cb.checked, day: b.day }); // o dia da tela, não o do relógio
        refreshReminders();
        await refresh();
        refocusBy(root, r.label); // a lista foi redesenhada: o foco volta para a mesma rotina
      } catch (e) {
        cb.checked = !cb.checked;
        errorToast(e, "Não foi possível salvar.");
      }
    });
    // Esmaecida: a própria linha diz por quê (e o leitor de tela também, pela descrição da caixa).
    const hint = [r.paused_until ? `pausada até ${shortDate(r.paused_until)}` : "", scheduleLabel(r, b.day),
      r.due === false && !r.paused_until ? "fora da agenda deste dia (se marcar, é extra)" : "",
      r.require_note && !r.done_today ? "exige evidência" : "",
      r.photos ? `${r.photos} foto${r.photos > 1 ? "s" : ""}` : ""].filter(Boolean).join(" · ");
    // Horário: perto dele (ou passado, sem marcar) a etiqueta acende, como o aviso.
    const at = r.remind_at ? r.remind_at.slice(0, 5) : null;
    const state = at && b.day === today && r.due !== false ? reminderState({ ...r, remind_at: at }) : null;
    const time = at ? h("span", { class: "chip rem-at" + (state ? " " + state : ""), id: `rec-at-${r.id}`, text: state === "due" ? `${at} · na hora` : at }) : null;
    // O aria-label da caixa troca o texto do <label>: horário, estado e evidência vão pela descrição.
    cb.setAttribute("aria-describedby", [at && `rec-at-${r.id}`, hint && `rec-hint-${r.id}`, r.note && `rec-ev-${r.id}`].filter(Boolean).join(" "));
    if (!cb.getAttribute("aria-describedby")) cb.removeAttribute("aria-describedby");
    recPanel.append(h("label", { class: "check-row" + (r.done_today ? " done" : "") + (r.due === false ? " off" : "") }, cb,
      h("span", { class: "label" }, h("span", { class: "rec-title" }, r.label, time), hint ? h("small", { id: `rec-hint-${r.id}`, text: hint }) : null,
        r.note ? h("small", { class: "evidence", id: `rec-ev-${r.id}`, text: "evidência: " + r.note }) : null),
      // Marcada: anota o que foi conferido (vai para o relatório, para comprovar depois).
      r.done_today ? h("button", { type: "button", class: "icon", title: r.note ? "Editar a evidência" : "Anotar a evidência (o que foi conferido)",
        "aria-label": "Evidência de " + r.label, onClick: (ev) => { ev.preventDefault(); editEvidence(r, b.day, refresh); } }, icon("note")) : null,
      // O resto num menu ⋮ (folha de baixo no celular, menu junto do botão no computador):
      // achou algo na verificação? vira tarefa (com anotações e tempo).
      h("button", { type: "button", class: "icon", title: "Mais ações", "aria-label": "Mais ações de " + r.label,
        onClick: (ev) => { ev.preventDefault(); actionMenu(ev.currentTarget, r.label, [
          r.done_today ? [r.note ? "Editar a evidência" : "Anotar a evidência", "note", () => editEvidence(r, b.day, refresh)] : null,
          ["Registrar um achado como tarefa", "alert", () => openWorklog(refresh, { title: `Achado: ${r.label}` })],
          ["Editar rotina", "edit", () => openRecurring(r, refresh)],
          [r.paused_until ? "Retomar ou mudar a pausa" : "Pausar até…", "bell-off", () => pauseRecurring(r, refresh)],
        ]); } }, icon("more-v"))));
  }

  // ---- abertas + registro rápido (com projeto; com "— 15min" já sai concluída)
  const proj = h("select", { class: "select-sm", "aria-label": "Projeto do registro rápido" });
  // Último escolhido nesta aba; senão o projeto padrão (Configurações > Conta).
  const lastProj = sessionStorage.getItem(LAST_PROJECT);
  fillProjectSelect(proj, lastProj !== null ? Number(lastProj) || null : ctx.me.default_project_id || null)
    .then(() => proj.addEventListener("change", () => sessionStorage.setItem(LAST_PROJECT, proj.value)))
    .catch(() => {});
  const quick = h("input", { type: "text", maxlength: "200", "aria-label": "Registrar tarefa rápida",
    placeholder: "O que você fez? — 15min" });
  // "Já resolvido antes" também aqui (por onde entra a maioria das tarefas):
  // o título sem os marcadores, depois de uma pausa na digitação.
  const hint = h("div", { class: "similar hidden", "aria-live": "polite" });
  let hintTimer = null, hintSeq = 0;
  pendingHint = () => { clearTimeout(hintTimer); hintSeq++; };
  quick.addEventListener("input", () => {
    clearTimeout(hintTimer);
    hintTimer = setTimeout(async () => {
      if (!quick.isConnected) return; // trocou de tela
      const q = quick.value.split(/\s[@#!^]|\s[-–—]\s/)[0].trim(), my = ++hintSeq;
      if (q.length < 6) { hint.classList.add("hidden"); return; }
      let list = [];
      try { list = await api.get("/search/similar?title=" + encodeURIComponent(q)); } catch { /* sugestão */ }
      if (my !== hintSeq) return;
      clear(hint);
      hint.classList.toggle("hidden", !list.length);
      if (list.length) hint.append(h("p", { class: "similar-head", text: "Já resolvido antes:" }),
        ...list.map((s) => h("div", { class: "similar-item" },
          h("button", { type: "button", class: "btn btn-text btn-sm", text: s.title, onClick: () => openTask(s.id, refresh) }),
          h("p", { text: s.resolution.length > 140 ? s.resolution.slice(0, 139) + "…" : s.resolution }))));
    }, 500);
  });
  quick.addEventListener("keydown", async (ev) => {
    if (ev.key !== "Enter" || !quick.value.trim()) return;
    ev.preventDefault();
    clearTimeout(hintTimer); hintSeq++; // a sugestão pendente não serve mais
    const project_id = proj.value && proj.value !== "__new" ? Number(proj.value) : null;
    quick.disabled = true;
    try {
      // "Ver": a linha nova fica abaixo da dobra no celular (concluídas ou abertas).
      const msg = await quickRegister(quick.value, project_id);
      const done = lastDone; // registrada já concluída ("— 30min"): pergunta como resolveu, como o Concluir
      toast(msg, { actions: [
        ["Ver", () => document.querySelector(/conclu/i.test(msg) ? ".t-done" : ".t-open")?.scrollIntoView({ behavior: calmMotion() ? "auto" : "smooth", block: "start" })],
        done ? ["Como resolveu?", () => askResolution(done, refresh)] : null,
      ].filter(Boolean) });
    } catch (e) {
      quick.disabled = false;
      errorToast(e, "Não foi possível registrar.");
      return;
    }
    mount(root, ctx, { day, focusQuick: true, summary: sum });
  });
  const openPanel = h("section", { class: "panel t-open" },
    h("div", { class: "panel-head" }, h("h2", { text: "Em aberto" }),
      h("span", { class: "count" + (late.length || blocked.length ? " warn" : ""), text: [String(open.length),
        late.length ? `${late.length} atrasada${late.length > 1 ? "s" : ""}` : "",
        blocked.length ? `${blocked.length} aguardando` : ""].filter(Boolean).join(" · ") })),
    h("div", { class: "quick-row" }, quick, proj),
    h("p", { class: "quick-hint" }, "Enter registra. Projeto, chamado e prazo no próprio texto: ",
      h("button", { type: "button", class: "link-btn", text: "ver marcadores", onClick: () => window.dispatchEvent(new CustomEvent("nexus:help", { detail: "marcadores" })) })), hint);
  // Filtro (fica na aba): o número de cada opção ajuda a decidir antes de clicar.
  let filter = sessionStorage.getItem(OPEN_FILTER) || "all";
  if (!FILTERS.some(([k]) => k === filter)) filter = "all";
  const list = h("div", { class: "open-list" });
  const seg = h("div", { class: "seg seg-sm open-filter", role: "group", "aria-label": "Filtrar as tarefas em aberto" },
    ...FILTERS.map(([key, label, test]) => {
      const n = open.filter((t) => test(t, today)).length;
      return h("button", { type: "button", class: "chip-btn", "data-filter": key, "aria-pressed": String(key === filter),
        "aria-selected": String(key === filter), text: key === "all" ? label : `${label} · ${n}`,
        onClick: () => { filter = key; sessionStorage.setItem(OPEN_FILTER, key); paintOpen(); } });
    }));
  if (open.length) openPanel.append(seg);
  openPanel.append(list);
  function paintOpen() {
    const [, , test, empty] = FILTERS.find(([k]) => k === filter);
    for (const b of seg.children) {
      const on = b.dataset.filter === filter;
      b.setAttribute("aria-pressed", String(on));
      b.setAttribute("aria-selected", String(on)); // mesmo visual do .seg
    }
    clear(list);
    const shown = open.filter((t) => test(t, today));
    if (!shown.length) list.append(h("p", { class: "empty", text: open.length ? empty : "Nada em aberto." }));
    for (const t of shown) openRow(t);
  }
  // Feita sem sinal: ainda não tem id no servidor; aparece marcada, sem ações.
  const pendingRow = (t) => h("div", { class: "list-row" }, h("div", { class: "t" }, h("span", { text: t.title }),
    h("small", {}, h("span", { class: "card-meta" }, h("span", { class: "chip today", text: "esperando conexão" })))));
  function openRow(t) {
    if (t.pending) { list.append(pendingRow(t)); return; }
    list.append(withMenu(h("div", { class: "list-row" },
      h("button", { type: "button", class: "icon", title: "Concluir", "aria-label": "Concluir " + t.title, onClick: () => finishTask(t, refresh) }, icon("check")),
      h("div", { class: "t" },
        h("button", { type: "button", class: "card-open", text: t.title, onClick: () => openTask(t.id, refresh) }),
        h("small", {}, h("span", { class: "card-meta" }, ...taskChips(t, today)))),
      desk(timerButton(t, refresh)),
      moreButton(t, refresh)), t, refresh));
  }
  paintOpen();

  // ---- concluídas hoje (com projeto e tempo, para conferir no fim do dia)
  const donePanel = h("section", { class: "panel t-done" },
    h("div", { class: "panel-head" }, h("h2", { text: "Concluídas hoje" }), h("span", { class: "count", text: String(doneToday.length) })));
  if (!doneToday.length) donePanel.append(h("p", { class: "empty", text: "Ainda nada hoje." }));
  for (const t of doneToday) {
    if (t.pending) { donePanel.append(pendingRow(t)); continue; }
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
  const venc = await vencP; // só aparece com algo no aviso
  root.append(h("div", { class: "today-grid" }, venc, recPanel, openPanel, donePanel, sum ? summaryPanel(sum, refresh) : null));
}


// Evidência da rotina: uma linha curta do que foi conferido ("backup OK, 2,1 TB").
function editEvidence(r, day, refresh) {
  // Fotos da evidência (print, foto do painel): entram na hora, mesmo sem salvar o texto.
  const photoBox = h("div", { class: "field" }, h("span", { class: "field-label", text: "Fotos (opcional)" }));
  const loadPhotos = async () => {
    let list = [];
    try { list = await api.get(`/recurring/${r.id}/photos?day=${day}`); } catch { /* sem rede: só o botão */ }
    photoBox.querySelector(".photo-grid")?.remove();
    photoBox.append(photoGrid(list, { path: `/recurring/${r.id}/photos?day=${day}`, onChange: () => { loadPhotos(); refresh(); } }));
  };
  loadPhotos();
  const input = h("input", { type: "text", maxlength: "200", value: r.note || "", placeholder: "ex.: tudo certo; quadro 3 sem aquecimento; backup OK",
    required: r.require_note ? "required" : null });
  const err = h("p", { class: "error-text" });
  // Foto ainda subindo: o "Salvar" espera (fechar antes cortaria o envio).
  photoBox.addEventListener("photo-busy", (ev) => {
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = ev.detail;
    btn.textContent = ev.detail ? "Enviando a foto…" : "Salvar";
  });
  const form = h("form", {}, h("h2", { text: "Evidência" }),
    h("p", { class: "dialog-note", text: `${r.label}: o que foi conferido. Aparece no relatório em PDF e na exportação.${r.require_note ? " Esta rotina só é marcada com a evidência." : ""}` }),
    h("label", { class: "field" }, "Evidência", input), photoBox, err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
      h("button", { type: "submit", class: "btn btn-primary", text: "Salvar" })));
  form.addEventListener("submit", busy(async () => {
    try {
      await api.post(`/recurring/${r.id}/toggle`, { done: true, day, note: input.value.trim() || null });
      refreshReminders();
      dlg.close();
      refresh();
    } catch (e) { err.textContent = e.message || "Não foi possível salvar."; }
  }));
  const dlg = modal(form);
  input.focus();
}

// Passagem de turno/plantão: texto pronto (calculado no servidor) para colar no chat.
async function showHandoff() {
  let text;
  try { text = (await api.get("/summary/handoff")).text; } catch (e) { errorToast(e); return; }
  const area = h("textarea", { rows: "14", readonly: "readonly", class: "handoff-text", "aria-label": "Texto da passagem de turno" });
  area.value = text;
  const dlg = modal(h("h2", { text: "Passagem de turno" }),
    h("p", { class: "dialog-note", text: "O que fica aberto, o que está aguardando e por quê, o que foi concluído nas últimas 12 h. Cole no chat da equipe." }),
    area,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Fechar", onClick: () => dlg.close() }),
      h("button", { type: "button", class: "btn btn-primary", onClick: async () => {
        try { await navigator.clipboard.writeText(text); toast("Copiado."); dlg.close(); }
        catch { area.select(); toast("Selecione e copie (Ctrl+C).", { error: true }); }
      } }, icon("copy"), "Copiar")));
  area.focus();
}

// Ordem das rotinas (a sequência do dia: abrir a loja → ar → câmeras). Arrastar
// pela alça no computador; setas Subir/Descer em qualquer aparelho e no teclado.
// Salva de uma vez, com Desfazer.
async function reorderRoutines(uid, onDone) {
  let list;
  try { list = (await api.get("/board")).recurring.slice().sort((a, b) => (a.position ?? 0) - (b.position ?? 0) || a.id - b.id); }
  catch (e) { errorToast(e, "Não foi possível abrir as rotinas."); return; }
  const ol = h("ol", { class: "reorder-list" });
  const live = h("p", { class: "sr-only", "aria-live": "polite" });
  const paint = (focus) => {
    clear(ol);
    list.forEach((r, i) => {
      const up = h("button", { type: "button", class: "icon", title: "Subir", "aria-label": "Subir " + r.label, onClick: () => move(i, -1, "up") }, icon("chevron"));
      const down = h("button", { type: "button", class: "icon", title: "Descer", "aria-label": "Descer " + r.label, onClick: () => move(i, 1, "down") }, icon("chevron"));
      up.classList.add("up");
      up.disabled = i === 0;
      down.disabled = i === list.length - 1;
      const grip = h("span", { class: "grip only-desk", title: "Arrastar para mudar a ordem", "aria-hidden": "true" }, icon("grip"));
      const li = h("li", { class: "reorder-row", "data-id": String(r.id) }, grip,
        h("span", { class: "reorder-n mono", text: String(i + 1) }), h("span", { class: "reorder-label", text: r.label }), up, down);
      grip.addEventListener("pointerdown", () => { li.draggable = true; });
      li.addEventListener("dragend", () => { li.draggable = false; });
      ol.append(li);
      if (focus && focus.id === r.id) (focus.dir === "up" && !up.disabled ? up : !down.disabled ? down : up).focus();
    });
  };
  const move = (i, d, dir) => {
    const j = i + d;
    if (j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    paint({ id: list[j].id, dir });
    live.textContent = `${list[j].label}: posição ${j + 1} de ${list.length}`;
  };
  // Arrastar (computador): a linha vai para onde o ponteiro está; ao soltar, a lista segue o que se vê.
  let dragging = null;
  ol.addEventListener("dragstart", (ev) => {
    dragging = ev.target.closest && ev.target.closest(".reorder-row");
    if (!dragging) return;
    dragging.classList.add("dragging");
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", dragging.dataset.id);
  });
  ol.addEventListener("dragover", (ev) => {
    if (!dragging) return;
    ev.preventDefault();
    const rows = [...ol.querySelectorAll(".reorder-row")].filter((el) => el !== dragging);
    const after = rows.find((el) => { const r = el.getBoundingClientRect(); return ev.clientY < r.top + r.height / 2; });
    if (after) ol.insertBefore(dragging, after); else ol.append(dragging);
  });
  const endDrag = (ev) => {
    if (!dragging) return;
    if (ev) ev.preventDefault();
    const order = [...ol.querySelectorAll(".reorder-row")].map((el) => Number(el.dataset.id));
    list = order.map((id) => list.find((r) => r.id === id));
    dragging = null;
    paint();
  };
  ol.addEventListener("drop", endDrag);
  ol.addEventListener("dragend", () => endDrag());
  const form = h("form", {},
    h("h2", { text: "Ordem das rotinas" }),
    h("p", { class: "dialog-note", text: "A ordem em que elas aparecem no Hoje. Use as setas, ou arraste pela alça no computador." }),
    ol, live,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
      h("button", { type: "submit", class: "btn btn-primary", text: "Salvar a ordem" })));
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    try {
      await api.post("/recurring/order", { ids: list.map((r) => r.id) });
      dlg.close();
      refreshReminders();
      await onDone();
      toast("Ordem das rotinas salva.", { action: "Desfazer", onAction: () => undoLatest("recurring_order", uid, onDone) });
    } catch (e) { errorToast(e, "Não foi possível salvar a ordem."); }
  }));
  const dlg = modal(form);
  dlg.classList.add("reorder-dialog");
  paint();
  const first = ol.querySelector("button:not([disabled])");
  if (first) first.focus();
}
