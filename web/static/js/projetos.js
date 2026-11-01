// Projetos: a lista (progresso de cada um) e o projeto aberto, com os
// objetivos na ordem de execução e as tarefas de cada um (também em ordem).
// Ordem: arrastar pela alça no computador; no celular e no teclado, pelo ⋮
// (subir, descer, mover para outro objetivo). Progresso e status vêm do servidor.
import { api } from "./api.js";
import { h, icon, clear, field, shortDate, localDay, daysBetween } from "./dom.js";
import { busy, confirmDialog, errorToast, modal, popupMenu, sheet, toast, undoLatest } from "./ui.js";
import { finishTask, openWorklog, taskChips } from "./board.js";
import { duration, editingTaskId, openTask } from "./task.js";
import { PALETA, invalidateProjects, listProjects, projTile, projectDialog } from "./projects.js";

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

// "hoje", "ontem", "há 5 dias": informação para ver o que está parado (sem alerta).
function quando(ts, today) {
  if (!ts) return "";
  const d = daysBetween(localDay(ts), today);
  return d <= 0 ? "hoje" : d === 1 ? "ontem" : `há ${d} dias`;
}

// Os números do projeto: em aberto · aguardando · horas no mês.
function numeros(p, cls = "proj-nums") {
  const n = (v, l) => h("span", { class: "proj-num" }, h("strong", { class: "mono", text: v }), h("span", { text: l }));
  return h("div", { class: cls },
    n(String(p.open_tasks), "em aberto"), n(String(p.waiting_tasks), "aguardando"),
    n(p.minutes_month ? duration(p.minutes_month) : "0h", "no mês"));
}

// Lista: aba, ordem e busca valem enquanto o app está aberto (a ordem fica no aparelho).
const lista = { tab: "ativos", q: "", sort: (() => { try { return localStorage.getItem("nexus.projetos.ordem") || "atividade"; } catch { return "atividade"; } })() };

// Estado vazio: exemplos por área, com ícone; um toque cria o projeto.
const EXEMPLOS = [
  ["TI e redes", [["Servidores", "servidor"], ["Rede da matriz", "rede"], ["Help desk", "computador"]]],
  ["Manutenção predial", [["Prédio Centro", "predio"], ["Elétrica", "eletrica"], ["Hidráulica", "hidraulica"]]],
  ["Atendimento e campo", [["Loja Vila Velha", "loja"], ["Clínica Sul", "clinica"], ["Frota", "veiculo"]]],
];

async function mountList(root, ctx) {
  const list = await api.get("/projects?include_archived=true");
  ctx.setEyebrow("objetivos e tarefas");
  const today = localDay(new Date().toISOString());
  const proxCor = () => PALETA[list.length % PALETA.length];  // a mesma escolha do servidor
  const abrir = (p) => { if (p) location.hash = `#/projetos?id=${p.id}`; };
  const novo = async (preset = {}) => abrir(await projectDialog(null, { color: proxCor(), ...preset }));
  ctx.setActions(h("button", { type: "button", class: "btn btn-primary", "data-fab": "", onClick: () => novo() }, icon("add"), "Projeto"));
  clear(root);
  if (!list.length) {
    const rapido = async (name, iconName) => {
      try {
        const p = await api.post("/projects", { name, icon: iconName, color: proxCor() });
        invalidateProjects();
        abrir(p);
      } catch (e) { errorToast(e, "Não foi possível criar o projeto."); }
    };
    root.append(h("section", { class: "panel proj-empty" },
      h("h2", { text: "Comece pelo primeiro projeto" }),
      h("p", { class: "help", text: "Projetos agrupam as tarefas de um cliente, de um local ou de uma frente; dentro deles, objetivos em ordem de execução. Toque num exemplo para criar (dá para renomear depois) ou crie com outro nome." }),
      ...EXEMPLOS.map(([area, itens]) => h("div", { class: "proj-ex" }, h("h3", { text: area }),
        h("div", { class: "proj-ex-row" }, ...itens.map(([nome, ic]) =>
          h("button", { type: "button", class: "proj-ex-btn", onClick: () => rapido(nome, ic) }, projTile({ icon: ic, color: PALETA[0] }, "proj-tile-sm"), nome))))),
      h("button", { type: "button", class: "btn btn-ghost", onClick: () => novo() }, icon("add"), "Outro nome…")));
    return;
  }

  const ativos = list.filter((p) => !p.archived), arquivados = list.filter((p) => p.archived);
  if (!arquivados.length) lista.tab = "ativos";
  const grid = h("div", { class: "proj-grid" });
  const card = (p) => {
    const temObj = p.objectives > 0;
    return h("a", { class: "proj-card", href: `#/projetos?id=${p.id}` },
      h("div", { class: "proj-card-head" }, projTile(p),
        h("div", { class: "proj-card-title" }, h("h2", { text: p.name }),
          h("small", { class: "proj-last", text: "última atividade " + quando(p.last_activity, today) }))),
      temObj ? progress(p.objectives_done, p.objectives, false) : progress(p.done_tasks, p.total_tasks, false),
      h("p", { class: "proj-card-meta", text: temObj
        ? `${p.objectives_done} de ${p.objectives} objetivo${p.objectives > 1 ? "s" : ""} concluído${p.objectives_done === 1 ? "" : "s"}`
        : p.total_tasks ? `${p.done_tasks} de ${p.total_tasks} tarefas concluídas` : "nenhuma tarefa ainda" }),
      numeros(p));
  };
  const busca = h("input", { type: "search", class: "proj-search", placeholder: "Buscar projeto", "aria-label": "Buscar projeto", value: lista.q });
  const fold = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const paint = () => {
    const base = lista.tab === "arquivados" ? arquivados : ativos;
    const q = fold(lista.q.trim());
    const rows = base.filter((p) => !q || fold(p.name).includes(q));
    rows.sort(lista.sort === "nome" ? (a, b) => a.name.localeCompare(b.name, "pt-BR")
      : (a, b) => (b.last_activity || "").localeCompare(a.last_activity || "") || a.name.localeCompare(b.name, "pt-BR"));
    clear(grid);
    grid.append(...rows.map(card));
    if (!rows.length) grid.append(h("p", { class: "empty", text: q ? "Nenhum projeto com esse nome." : "Nenhum projeto ativo: reative um dos arquivados ou crie um novo." }));
  };
  busca.addEventListener("input", () => { lista.q = busca.value; paint(); });
  const tabs = h("div", { class: "seg seg-sm proj-tabs", role: "tablist", "aria-label": "Projetos" },
    ...[["ativos", `Ativos (${ativos.length})`], ["arquivados", `Arquivados (${arquivados.length})`]].map(([k, t]) =>
      h("button", { type: "button", class: "chip-btn", role: "tab", "aria-selected": String(lista.tab === k), text: t,
        disabled: k === "arquivados" && !arquivados.length ? "disabled" : null,
        onClick: (ev) => {
          lista.tab = k;
          for (const b of tabs.children) b.setAttribute("aria-selected", String(b === ev.currentTarget));
          paint();
        } })));
  const ordem = h("select", { class: "select-sm proj-sort", "aria-label": "Ordenar projetos" },
    h("option", { value: "atividade", text: "Atividade recente" }), h("option", { value: "nome", text: "Nome" }));
  ordem.value = lista.sort;
  ordem.addEventListener("change", () => {
    lista.sort = ordem.value;
    try { localStorage.setItem("nexus.projetos.ordem", ordem.value); } catch { /* sem armazenamento: vale só agora */ }
    paint();
  });
  root.append(h("div", { class: "proj-toolbar" }, tabs, list.length > 8 ? busca : null, ordem), grid);
  paint();
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
  // O título da página é o projeto aberto (como o detalhe de qualquer item), com o
  // ícone grande na cor dele; a lista volta pelo link. O próximo título troca o texto todo.
  const titulo = document.getElementById("page-title");
  titulo.replaceChildren(projTile(p, "proj-tile-lg"), h("span", { text: p.name }));
  ctx.setEyebrow(p.archived ? "projeto arquivado" : "projeto");
  document.title = `${p.name} · Nexus Worklog`;
  ctx.setActions(
    h("button", { type: "button", class: "btn btn-ghost", onClick: () => openWorklog(refresh, { project_id: pid }) }, icon("add"), "Tarefa"),
    h("button", { type: "button", class: "btn btn-primary", "data-fab": "", onClick: () => editObjective(pid, null, refresh) }, icon("add"), "Objetivo"));

  clear(root);
  const projMenu = h("button", { type: "button", class: "icon", title: "Ações do projeto", "aria-label": "Ações do projeto" }, icon("more-v"));
  projMenu.addEventListener("click", () => actionsMenu(projMenu, p.name, [
    ["Editar projeto", "edit", async () => { if (await projectDialog(p)) refresh(); }],
    p.archived ? ["Reativar", "folder", () => saveProject(p, { archived: false }, "Projeto reativado.", refresh)]
      : ["Arquivar…", "folder", () => archiveProject(p, o.totals.total - o.totals.done, refresh)],
    ["Excluir projeto", "trash", () => deleteProject(p)],
  ]));
  const upcoming = o.upcoming.length ? h("div", { class: "proj-upcoming" },
    h("h3", { text: "Próximos prazos" }),
    h("ul", {}, ...o.upcoming.map((x) => {
      const late = x.due_date < today;
      const label = h("span", { class: "proj-up-t" }, x.kind === "objective" ? icon("target") : null, x.title);
      return h("li", {}, x.kind === "task"
        ? h("button", { type: "button", class: "card-open", onClick: () => openTask(x.id, refresh) }, label) : label,
        h("span", { class: "chip " + (late ? "late" : x.due_date === today ? "today" : ""),
          text: late ? "atrasado · " + shortDate(x.due_date) : x.due_date === today ? "hoje" : shortDate(x.due_date) }));
    }))) : null;
  root.append(h("div", { class: "proj-head" },
    h("div", { class: "proj-bar" }, h("a", { class: "btn btn-text btn-sm proj-back", href: "#/projetos" }, icon("left"), "Todos os projetos"),
      projMenu),
    p.description ? h("p", { class: "proj-desc", text: p.description }) : null,
    h("div", { class: "proj-summary" }, numeros(p, "proj-nums proj-nums-lg"),
      h("p", { class: "proj-last", text: "última atividade " + quando(p.last_activity, today) })),
    progress(o.totals.done, o.totals.total),
    h("p", { class: "proj-card-meta", text: o.objectives.length
      ? `${o.objectives.length} objetivo${o.objectives.length > 1 ? "s" : ""} · ${o.totals.objectives_open} em aberto · na ordem de execução`
      : "Crie objetivos (as demandas principais) e ponha as tarefas na ordem em que vão ser feitas." }),
    upcoming));

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
    } catch (e) { add.disabled = false; errorToast(e, "Não foi possível criar a tarefa."); }
  });

  const doneList = h("div", { class: "obj-done hidden" }, ...data.done_tasks.map((t) => doneRow(t, oid, o, pid, refresh)));
  if (!phone()) dragSource(doneList, refresh);
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

// Concluída: também muda de objetivo (arrastando para outro bloco ou pelo ⋮).
function doneRow(t, oid, o, pid, refresh) {
  const grip = h("button", { type: "button", class: "icon grip only-desk", title: "Arrastar para outro objetivo", "aria-label": `Arrastar ${t.title}`, tabindex: "-1" }, icon("grip"));
  const menuBtn = h("button", { type: "button", class: "icon", title: "Objetivo", "aria-label": `Objetivo de ${t.title}` }, icon("more-v"));
  menuBtn.addEventListener("click", () => actionsMenu(menuBtn, t.title, [
    ["Abrir", "right", () => openTask(t.id, refresh)],
    ["Mover para outro objetivo…", "folder", () => moveTo(t, oid, o, pid, refresh)],
  ]));
  return h("div", { class: "obj-task done", "data-task": String(t.id), "data-done": "" }, grip,
    h("span", { class: "obj-check-done", "aria-hidden": "true" }, icon("check")),
    h("div", { class: "t" }, h("button", { type: "button", class: "card-open", text: t.title, onClick: () => openTask(t.id, refresh) })),
    menuBtn);
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
  const row = h("div", { class: "obj-task" + (editingTaskId() === t.id ? " editing" : ""), "data-task": String(t.id) }, grip,
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
  sheet(`Mover “${t.title}” para`, destinos.map(([nome, id]) => [nome, id === null ? "folder" : "check", async () => {
    if (t.status === "done") { // concluída: só troca o objetivo (a fila das abertas fica como está)
      try { await api.patch(`/worklog/${t.id}`, { objective_id: id }); toast(`Movida para ${nome}.`); }
      catch (e) { errorToast(e, "Não foi possível mover."); }
      refresh();
      return;
    }
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

// Origem do arrasto: linhas abertas e concluídas (só a alça inicia; o resto da
// linha continua clicável e selecionável).
function dragSource(container, refresh) {
  container.addEventListener("dragstart", (ev) => {
    const row = ev.target.closest && ev.target.closest(".obj-task[data-task]");
    if (!row || dragging) return;
    dragging = { kind: "task", el: row, done: row.hasAttribute("data-done"), refresh };
    row.classList.add("dragging");
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", row.dataset.task);
  });
  for (const row of container.querySelectorAll(".obj-task[data-task]")) {
    const grip = row.querySelector(".grip");
    grip.addEventListener("pointerdown", () => { row.draggable = true; });
    row.addEventListener("dragend", () => { row.draggable = false; });
  }
}

function dragTasks(list, pid, refresh) {
  dragSource(list, refresh);
  list.addEventListener("dragover", (ev) => {
    if (dragging?.kind !== "task") return;
    ev.preventDefault();
    list.querySelector(".obj-empty")?.remove();
    const after = afterEl(list, ev.clientY, ".obj-task[data-task]");
    if (after) list.insertBefore(dragging.el, after); else list.append(dragging.el);
  });
  list.addEventListener("drop", async (ev) => {
    if (dragging?.kind !== "task") return;
    ev.preventDefault();
    const oid = list.dataset.objective === "" ? null : Number(list.dataset.objective);
    dragging.dropped = true;
    if (dragging.done) { // concluída: muda o objetivo e volta para as concluídas do bloco novo
      try { await api.patch(`/worklog/${dragging.el.dataset.task}`, { objective_id: oid }); }
      catch (e) { errorToast(e, "Não foi possível mover."); }
      refresh();
      return;
    }
    const ids = [...list.querySelectorAll(".obj-task[data-task]:not([data-done])")].map((r) => Number(r.dataset.task));
    orderTasks(pid, oid, ids, refresh);
  });
}

// Fim do arrasto de tarefa (de qualquer origem): soltou fora, volta como estava.
document.addEventListener("dragend", () => {
  if (dragging?.kind !== "task") return;
  const { dropped, refresh } = dragging;
  dragging.el.classList.remove("dragging");
  dragging = null;
  if (!dropped) refresh();
});

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
    !ob ? h("p", { class: "dialog-note intro", text: "Uma demanda principal do projeto. Entra no fim da ordem de execução; depois é só arrastar." }) : null,
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
  } catch (e) { errorToast(e, "Não foi possível salvar."); }
}

// Arquivar com segurança: diz quantas tarefas em aberto ainda têm este projeto
// como principal e deixa escolher: manter, concluir agora ou mover para outro.
async function archiveProject(p, abertas, refresh) {
  const outros = (await listProjects(true).catch(() => [])).filter((x) => x.id !== p.id);
  let escolha = "keep";
  const destino = h("select", { "aria-label": "Projeto que recebe as tarefas", disabled: "disabled" },
    ...outros.map((x) => h("option", { value: String(x.id), text: x.name })));
  const opcao = (valor, texto, extra = null) => {
    const r = h("input", { type: "radio", name: "arq-tarefas", value: valor });
    if (valor === escolha) r.checked = true;
    r.addEventListener("change", () => { escolha = valor; destino.disabled = valor !== "move"; });
    return h("div", { class: "arq-op" }, h("label", { class: "check-line" }, r, texto), extra);
  };
  const err = h("p", { class: "error-text" });
  const n = `${abertas} tarefa${abertas > 1 ? "s" : ""} em aberto`;
  const form = h("form", {}, h("h2", { text: `Arquivar “${p.name}”?` }),
    h("p", { class: "dialog-note", text: "O projeto sai dos seletores e da lista de ativos; nada é apagado e dá para reativar quando quiser." }),
    abertas ? h("fieldset", { class: "arq-fs" }, h("legend", { text: `Ainda há ${n} neste projeto. O que fazer com ${abertas > 1 ? "elas" : "ela"}?` }),
      opcao("keep", "Manter como estão (continuam no quadro)"),
      opcao("done", "Concluir agora"),
      outros.length ? opcao("move", "Mover para outro projeto", destino) : null) : null,
    err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
      h("button", { type: "submit", class: "btn btn-primary", text: "Arquivar" })));
  form.addEventListener("submit", busy(async () => {
    const body = { open_tasks: escolha };
    if (escolha === "move") body.move_to = Number(destino.value);
    try {
      const r = await api.post(`/projects/${p.id}/archive`, body);
      invalidateProjects();
      dlg.close();
      const alvo = escolha === "move" ? outros.find((x) => x.id === body.move_to)?.name : "";
      toast(r.moved ? `Arquivado; ${r.moved} tarefa${r.moved > 1 ? "s" : ""} foi para ${alvo}.`
        : r.done ? `Arquivado; ${r.done} tarefa${r.done > 1 ? "s" : ""} concluída${r.done > 1 ? "s" : ""}.`
          : "Arquivado: some dos seletores, as tarefas continuam.",
      r.moved || r.done ? {} : { action: "Desfazer", onAction: () => undoLatest("project", p.id, () => { invalidateProjects(); refresh(); }) });
      refresh();
    } catch (e) { err.textContent = e.message || "Não foi possível arquivar."; }
  }));
  const dlg = modal(form);
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
