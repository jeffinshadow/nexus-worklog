// Projetos: a lista (progresso de cada um) e o projeto aberto, com os
// objetivos na ordem de execução e as tarefas de cada um (também em ordem).
// Ordem: arrastar pela alça no computador; no celular e no teclado, pelo ⋮
// (subir, descer, mover para outro objetivo). Progresso e status vêm do servidor.
import { api } from "./api.js";
import { h, icon, clear, field, shortDate, localDay } from "./dom.js";
import { busy, confirmDialog, errorToast, modal, popupMenu, sheet, toast, undoLatest } from "./ui.js";
import { finishTask, openWorklog, taskChips } from "./board.js";
import { openTask } from "./task.js";
import { PALETA, askName, invalidateProjects } from "./projects.js";

const STATUS = { todo: "não iniciado", in_progress: "em andamento", done: "concluído" };
const phone = () => matchMedia("(max-width: 860px)").matches;

export async function mount(root, ctx) {
  const id = Number(new URLSearchParams(location.hash.split("?")[1] || "").get("id")) || null;
  if (id) return mountProject(root, ctx, id);
  return mountList(root, ctx);
}

// Menu de ações: no computador ao lado do botão; no celular, de baixo.
function actionsMenu(btn, title, items) {
  if (phone()) { sheet(title, items); return; }
  const r = btn.getBoundingClientRect();
  popupMenu(r.left, r.bottom + 4, items);
}

function progress(done, total, label = true) {
  const bar = h("span");
  bar.style.width = total ? `${Math.round((100 * done) / total)}%` : "0";
  return h("div", { class: "obj-progress" },
    h("div", { class: "progress thin", role: "img", "aria-label": `${done} de ${total} concluídas` }, bar),
    label ? h("span", { class: "obj-progress-l mono", text: total ? `${done} de ${total}` : "sem tarefas" }) : null);
}

// ------------------------------------------------------------------ lista --

async function mountList(root, ctx) {
  const list = await api.get("/projects?include_archived=true");
  ctx.setEyebrow("objetivos · tarefas · ordem de execução");
  const novo = async () => {
    const name = await askName();
    if (!name) return;
    try {
      const p = await api.post("/projects", { name });
      invalidateProjects();
      location.hash = `#/projetos?id=${p.id}`;
    } catch (e) { errorToast(e, "Erro ao criar projeto."); }
  };
  ctx.setActions(h("button", { type: "button", class: "btn btn-primary", "data-fab": "", onClick: novo }, icon("add"), "Projeto"));
  clear(root);
  const ativos = list.filter((p) => !p.archived), arquivados = list.filter((p) => p.archived);
  if (!list.length) {
    root.append(h("section", { class: "panel" }, h("p", { class: "empty",
      text: "Nenhum projeto ainda. Projetos agrupam as tarefas de um cliente ou de uma frente; dentro deles, objetivos em ordem de execução." })));
    return;
  }
  const card = (p) => {
    const dot = h("span", { class: "dot big" });
    dot.style.background = p.color || "var(--dim)";
    return h("a", { class: "proj-card" + (p.archived ? " archived" : ""), href: `#/projetos?id=${p.id}` },
      h("div", { class: "proj-card-head" }, dot, h("h2", { text: p.name }), p.archived ? h("span", { class: "chip", text: "arquivado" }) : null),
      progress(p.done_tasks, p.total_tasks),
      h("p", { class: "proj-card-meta", text: [
        p.objectives ? `${p.objectives} objetivo${p.objectives > 1 ? "s" : ""}` : "sem objetivos",
        p.open_tasks ? `${p.open_tasks} em aberto` : "nada em aberto"].join(" · ") }));
  };
  root.append(h("div", { class: "proj-grid" }, ...ativos.map(card)));
  if (arquivados.length) {
    const box = h("div", { class: "proj-grid hidden" }, ...arquivados.map(card));
    const toggle = h("button", { type: "button", class: "btn btn-text btn-sm", text: `Arquivados (${arquivados.length})`,
      "aria-expanded": "false", onClick: () => { const open = box.classList.toggle("hidden"); toggle.setAttribute("aria-expanded", String(!open)); } });
    root.append(h("div", { class: "proj-archived" }, toggle, box));
  }
}

// ---------------------------------------------------------------- projeto --

async function mountProject(root, ctx, pid) {
  let o;
  try { o = await api.get(`/projects/${pid}/overview`); }
  catch (e) {
    if (e.status === 404) { location.hash = "#/projetos"; return; }
    throw e;
  }
  const refresh = () => mountProject(root, ctx, pid);
  const today = localDay(new Date().toISOString());
  const p = o.project;
  ctx.setEyebrow("projeto");
  ctx.setActions(
    h("button", { type: "button", class: "btn btn-ghost", onClick: () => openWorklog(refresh, { project_id: pid }) }, icon("add"), "Tarefa"),
    h("button", { type: "button", class: "btn btn-primary", "data-fab": "", onClick: () => editObjective(pid, null, refresh) }, icon("add"), "Objetivo"));

  clear(root);
  const dot = h("span", { class: "dot big" });
  dot.style.background = p.color || "var(--dim)";
  const projMenu = h("button", { type: "button", class: "icon", title: "Ações do projeto", "aria-label": "Ações do projeto" }, icon("more-v"));
  projMenu.addEventListener("click", () => actionsMenu(projMenu, p.name, [
    ["Renomear e cor", "edit", () => editProject(p, refresh)],
    [p.archived ? "Reativar" : "Arquivar", "folder", () => saveProject(p, { archived: !p.archived },
      p.archived ? "Projeto reativado." : "Arquivado: some dos seletores, as tarefas continuam.", refresh)],
    ["Excluir projeto", "trash", () => deleteProject(p)],
  ]));
  root.append(h("div", { class: "proj-head" },
    h("a", { class: "btn btn-text btn-sm proj-back", href: "#/projetos" }, icon("left"), "Projetos"),
    h("div", { class: "proj-title" }, dot, h("h2", { text: p.name }), p.archived ? h("span", { class: "chip", text: "arquivado" }) : null, projMenu),
    progress(o.totals.done, o.totals.total),
    h("p", { class: "proj-card-meta", text: o.objectives.length
      ? `${o.objectives.length} objetivo${o.objectives.length > 1 ? "s" : ""} · ${o.totals.objectives_open} em aberto · na ordem de execução`
      : "Crie objetivos (as demandas principais) e ponha as tarefas na ordem em que vão ser feitas." })));

  const blocks = h("div", { class: "obj-list" });
  o.objectives.forEach((ob, i) => blocks.append(objectiveBlock(ob, i, o, pid, today, refresh)));
  root.append(blocks, objectiveBlock(null, -1, o, pid, today, refresh));
  if (!phone()) dragObjectives(blocks, pid, refresh);
}

function objectiveBlock(ob, index, o, pid, today, refresh) {
  const data = ob || o.unassigned;
  const oid = ob ? ob.id : null;
  const list = h("div", { class: "obj-tasks", "data-objective": oid === null ? "" : String(oid) });
  data.tasks.forEach((t, i) => list.append(taskRow(t, i, data.tasks, oid, o, pid, today, refresh)));
  if (!data.tasks.length) list.append(h("p", { class: "empty obj-empty", text: ob ? "Nenhuma tarefa aberta neste objetivo." : "Nada solto: todas as tarefas abertas têm objetivo." }));
  if (!phone()) dragTasks(list, pid, refresh);

  // + Tarefa: título e Enter, já neste objetivo (no fim da fila).
  const add = h("input", { type: "text", maxlength: "200", class: "obj-add", placeholder: "+ Tarefa e Enter",
    "aria-label": ob ? `Nova tarefa em ${ob.title}` : "Nova tarefa sem objetivo" });
  add.addEventListener("keydown", async (ev) => {
    if (ev.key !== "Enter" || !add.value.trim()) return;
    ev.preventDefault();
    add.disabled = true;
    try {
      await api.post("/worklog", oid ? { title: add.value.trim(), objective_id: oid } : { title: add.value.trim(), project_id: pid });
      await refresh(); // e o cursor volta ao campo do mesmo bloco (lote de tarefas seguidas)
      document.querySelector(`.obj-block[data-objective-block="${oid ?? ""}"] .obj-add`)?.focus();
    } catch (e) { add.disabled = false; errorToast(e, "Erro ao criar a tarefa."); }
  });

  const doneList = h("div", { class: "obj-done hidden" }, ...data.done_tasks.map((t) =>
    h("div", { class: "obj-task done" },
      h("span", { class: "obj-check-done", "aria-hidden": "true" }, icon("check")),
      h("button", { type: "button", class: "card-open", text: t.title, onClick: () => openTask(t.id, refresh) }))));
  const doneToggle = data.done ? h("button", { type: "button", class: "btn btn-text btn-sm obj-done-toggle", "aria-expanded": "false",
    text: `${data.done} concluída${data.done > 1 ? "s" : ""}`,
    onClick: () => { const hide = doneList.classList.toggle("hidden"); doneToggle.setAttribute("aria-expanded", String(!hide)); } }) : null;

  const head = [];
  if (ob) {
    const grip = h("button", { type: "button", class: "icon grip only-desk", title: "Arrastar para mudar a ordem", "aria-label": `Arrastar ${ob.title}`, tabindex: "-1" }, icon("grip"));
    const menuBtn = h("button", { type: "button", class: "icon", title: "Ações do objetivo", "aria-label": `Ações de ${ob.title}` }, icon("more-v"));
    const ids = o.objectives.map((x) => x.id);
    const move = (d) => { const j = index + d; if (j < 0 || j >= ids.length) return; [ids[index], ids[j]] = [ids[j], ids[index]]; orderObjectives(pid, ids, refresh); };
    menuBtn.addEventListener("click", () => actionsMenu(menuBtn, ob.title, [
      ["Editar", "edit", () => editObjective(pid, ob, refresh)],
      index > 0 ? ["Subir na ordem", "left", () => move(-1)] : null,
      index < ids.length - 1 ? ["Descer na ordem", "right", () => move(1)] : null,
      ["Excluir objetivo", "trash", () => deleteObjective(ob, refresh)],
    ]));
    const late = ob.due_date && ob.status !== "done" && ob.due_date < today;
    head.push(h("div", { class: "obj-head" }, grip,
      h("span", { class: "obj-n mono", text: String(index + 1) }),
      h("h3", { text: ob.title }),
      h("span", { class: "chip obj-status " + ob.status, text: STATUS[ob.status] }),
      ob.due_date ? h("span", { class: "chip " + (late ? "late" : ""), text: (late ? "atrasado · " : "prazo ") + shortDate(ob.due_date) }) : null,
      menuBtn));
    if (ob.description) head.push(h("p", { class: "obj-desc", text: ob.description }));
    head.push(progress(ob.done, ob.total));
  } else {
    head.push(h("div", { class: "obj-head" }, h("h3", { text: "Sem objetivo" }),
      h("span", { class: "obj-sub", text: "tarefas do projeto que ainda não entraram num objetivo" })));
  }
  const sec = h("section", { class: "panel obj-block" + (ob ? "" : " unassigned"), "data-objective-block": oid === null ? "" : String(oid) },
    ...head, list, add, doneToggle, doneList);
  if (ob) sec.dataset.id = String(ob.id);
  return sec;
}

function taskRow(t, i, tasks, oid, o, pid, today, refresh) {
  // Na tela do projeto, projeto e objetivo já estão no contexto: sem essas etiquetas.
  const chips = taskChips({ ...t, project_name: null, extra_projects: [], objective_title: null }, today);
  const grip = h("button", { type: "button", class: "icon grip only-desk", title: "Arrastar para mudar a ordem", "aria-label": `Arrastar ${t.title}`, tabindex: "-1" }, icon("grip"));
  const menuBtn = h("button", { type: "button", class: "icon", title: "Ordem e objetivo", "aria-label": `Ordem e objetivo de ${t.title}` }, icon("more-v"));
  const ids = tasks.map((x) => x.id);
  const move = (d) => { const j = i + d; if (j < 0 || j >= ids.length) return; [ids[i], ids[j]] = [ids[j], ids[i]]; orderTasks(pid, oid, ids, refresh); };
  menuBtn.addEventListener("click", () => actionsMenu(menuBtn, t.title, [
    ["Abrir", "right", () => openTask(t.id, refresh)],
    i > 0 ? ["Subir na ordem", "left", () => move(-1)] : null,
    i < ids.length - 1 ? ["Descer na ordem", "right", () => move(1)] : null,
    ["Mover para outro objetivo…", "folder", () => moveTo(t, oid, o, pid, refresh)],
  ]));
  const row = h("div", { class: "obj-task", "data-task": String(t.id) }, grip,
    h("button", { type: "button", class: "icon", title: "Concluir", "aria-label": "Concluir " + t.title, onClick: () => finishTask(t, refresh) }, icon("check")),
    h("div", { class: "t" },
      h("button", { type: "button", class: "card-open", text: t.title, onClick: () => openTask(t.id, refresh) }),
      chips.length ? h("small", {}, h("span", { class: "card-meta" }, ...chips)) : null),
    menuBtn);
  return row;
}

function moveTo(t, oid, o, pid, refresh) {
  const destinos = [...o.objectives.map((x) => [x.title, x.id]), ["Sem objetivo", null]].filter(([, id]) => id !== oid);
  if (!destinos.length) { toast("Crie outro objetivo antes."); return; }
  sheet(`Mover “${t.title}” para`, destinos.map(([nome, id]) => [nome, id === null ? "folder" : "check", () => {
    const alvo = id === null ? o.unassigned : o.objectives.find((x) => x.id === id);
    orderTasks(pid, id, [...alvo.tasks.map((x) => x.id), t.id], refresh, `Movida para ${nome}.`);
  }]));
}

// ----------------------------------------------------------- ordenação --

async function orderObjectives(pid, ids, refresh) {
  try { await api.post(`/projects/${pid}/objectives/order`, { ids }); }
  catch (e) { errorToast(e, "Não foi possível reordenar."); }
  refresh();
}

async function orderTasks(pid, oid, ids, refresh, msg) {
  try {
    await api.post(`/projects/${pid}/tasks/order`, { objective_id: oid, task_ids: ids });
    if (msg) toast(msg);
  } catch (e) { errorToast(e, "Não foi possível reordenar."); }
  refresh();
}

// Arrastar (computador): a linha anda na tela enquanto arrasta e, ao soltar,
// o bloco de destino manda a ordem nova (de outro bloco = muda de objetivo).
let dragging = null;

function afterEl(container, y, selector) {
  let best = null, bestOff = -Infinity;
  for (const el of container.querySelectorAll(selector)) {
    if (el === dragging?.el) continue;
    const r = el.getBoundingClientRect();
    const off = y - r.top - r.height / 2;
    if (off < 0 && off > bestOff) { bestOff = off; best = el; }
  }
  return best;
}

function dragTasks(list, pid, refresh) {
  list.addEventListener("dragstart", (ev) => {
    const row = ev.target.closest && ev.target.closest(".obj-task[data-task]");
    if (!row || dragging) return;
    dragging = { kind: "task", el: row };
    row.classList.add("dragging");
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", row.dataset.task);
  });
  list.addEventListener("dragover", (ev) => {
    if (dragging?.kind !== "task") return;
    ev.preventDefault();
    list.querySelector(".obj-empty")?.remove();
    const after = afterEl(list, ev.clientY, ".obj-task[data-task]");
    if (after) list.insertBefore(dragging.el, after); else list.append(dragging.el);
  });
  list.addEventListener("drop", (ev) => {
    if (dragging?.kind !== "task") return;
    ev.preventDefault();
    const ids = [...list.querySelectorAll(".obj-task[data-task]")].map((r) => Number(r.dataset.task));
    const oid = list.dataset.objective === "" ? null : Number(list.dataset.objective);
    dragging.dropped = true;
    orderTasks(pid, oid, ids, refresh);
  });
  list.addEventListener("dragend", () => {
    if (dragging?.kind !== "task") return;
    const dropped = dragging.dropped;
    dragging.el.classList.remove("dragging");
    dragging = null;
    if (!dropped) refresh(); // soltou fora: volta como estava
  });
  // Só a alça inicia o arrasto (o resto da linha continua clicável e selecionável).
  for (const row of list.querySelectorAll(".obj-task[data-task]")) {
    const grip = row.querySelector(".grip");
    grip.addEventListener("pointerdown", () => { row.draggable = true; });
    row.addEventListener("dragend", () => { row.draggable = false; });
  }
}

function dragObjectives(blocks, pid, refresh) {
  blocks.addEventListener("dragstart", (ev) => {
    const sec = ev.target.closest && ev.target.closest(".obj-block[data-id]");
    if (!sec || ev.target !== sec || dragging) return;
    dragging = { kind: "objective", el: sec };
    sec.classList.add("dragging");
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", sec.dataset.id);
  });
  blocks.addEventListener("dragover", (ev) => {
    if (dragging?.kind !== "objective") return;
    ev.preventDefault();
    const after = afterEl(blocks, ev.clientY, ".obj-block[data-id]");
    if (after) blocks.insertBefore(dragging.el, after); else blocks.append(dragging.el);
  });
  blocks.addEventListener("drop", (ev) => {
    if (dragging?.kind !== "objective") return;
    ev.preventDefault();
    dragging.dropped = true;
    orderObjectives(pid, [...blocks.querySelectorAll(".obj-block[data-id]")].map((s) => Number(s.dataset.id)), refresh);
  });
  blocks.addEventListener("dragend", () => {
    if (dragging?.kind !== "objective") return;
    const dropped = dragging.dropped;
    dragging.el.classList.remove("dragging");
    dragging = null;
    if (!dropped) refresh();
  });
  for (const sec of blocks.querySelectorAll(".obj-block[data-id]")) {
    const grip = sec.querySelector(".obj-head .grip");
    grip.addEventListener("pointerdown", () => { sec.draggable = true; });
    sec.addEventListener("dragend", () => { sec.draggable = false; });
  }
}

// ------------------------------------------------------------- diálogos --

function editObjective(pid, ob, refresh) {
  const title = h("input", { type: "text", maxlength: "120", required: "required", value: ob ? ob.title : "", placeholder: "Ex.: Módulo de pagamentos" });
  const desc = h("textarea", { rows: "3", maxlength: "500", placeholder: "O que precisa estar pronto (opcional)" });
  desc.value = ob?.description || "";
  const due = h("input", { type: "date" });
  due.value = ob?.due_date || "";
  const err = h("p", { class: "error-text" });
  const form = h("form", {}, h("h2", { text: ob ? "Editar objetivo" : "Novo objetivo" }),
    !ob ? h("p", { class: "dialog-note", text: "Uma demanda principal do projeto. Entra no fim da ordem de execução; depois é só arrastar." }) : null,
    field("Objetivo", title), field("Descrição", desc), field("Prazo (opcional)", due), err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
      h("button", { type: "submit", class: "btn btn-primary", text: ob ? "Salvar" : "Criar objetivo" })));
  form.addEventListener("submit", busy(async () => {
    const body = { title: title.value.trim(), description: desc.value.trim() || null, due_date: due.value || null };
    try {
      if (ob) await api.patch(`/objectives/${ob.id}`, body); else await api.post(`/projects/${pid}/objectives`, body);
      dlg.close();
      refresh();
    } catch (e) { err.textContent = e.message || "Não foi possível salvar."; }
  }));
  const dlg = modal(form);
  title.focus();
}

async function deleteObjective(ob, refresh) {
  if (!(await confirmDialog({ title: `Excluir “${ob.title}”?`, text: "As tarefas continuam no projeto, em “Sem objetivo”. Dá para desfazer pelo histórico.", confirm: "Excluir", danger: true }))) return;
  try {
    await api.del(`/objectives/${ob.id}`);
    refresh();
    toast("Objetivo excluído.", { action: "Desfazer", onAction: () => undoLatest("objective", ob.id, refresh) });
  } catch (e) { errorToast(e); }
}

async function saveProject(p, patch, msg, refresh) {
  try {
    await api.patch(`/projects/${p.id}`, patch);
    invalidateProjects();
    if (msg) toast(msg);
    refresh();
  } catch (e) { errorToast(e, "Falha ao salvar."); }
}

function editProject(p, refresh) {
  const name = h("input", { type: "text", maxlength: "60", required: "required", value: p.name });
  let color = p.color;
  const swatches = h("div", { class: "swatches", role: "radiogroup", "aria-label": "Cor" }, ...PALETA.map((c) => {
    const b = h("button", { type: "button", class: "swatch", role: "radio", title: c, "aria-label": c,
      "aria-checked": String(c.toLowerCase() === (color || "").toLowerCase()) });
    b.style.background = c;
    b.addEventListener("click", () => {
      color = c;
      for (const x of swatches.children) x.setAttribute("aria-checked", String(x === b));
    });
    return b;
  }));
  const err = h("p", { class: "error-text" });
  const form = h("form", {}, h("h2", { text: "Projeto" }), field("Nome do projeto ou cliente", name),
    h("div", { class: "field" }, h("span", { class: "field-label", text: "Cor" }), swatches), err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
      h("button", { type: "submit", class: "btn btn-primary", text: "Salvar" })));
  form.addEventListener("submit", busy(async () => {
    try {
      await api.patch(`/projects/${p.id}`, { name: name.value.trim(), color });
      invalidateProjects();
      dlg.close();
      refresh();
    } catch (e) { err.textContent = e.message || "Não foi possível salvar."; }
  }));
  const dlg = modal(form);
  name.focus();
}

async function deleteProject(p) {
  if (!(await confirmDialog({ title: `Excluir “${p.name}”?`, text: "Os objetivos saem junto; as tarefas continuam, sem projeto (ou no outro projeto que tiverem). Dá para desfazer pelo histórico.", confirm: "Excluir", danger: true }))) return;
  try {
    await api.del(`/projects/${p.id}`);
    invalidateProjects();
    location.hash = "#/projetos";
    toast("Projeto excluído.", { action: "Desfazer", onAction: () => undoLatest("project", p.id, () => { invalidateProjects(); location.hash = `#/projetos?id=${p.id}`; }) });
  } catch (e) { errorToast(e); }
}
