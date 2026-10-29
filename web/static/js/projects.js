// Projetos/clientes: lista em cache, seletor, etiqueta colorida e a aba de
// gestão em Configurações. A cor vem da API e entra via CSSOM (CSP ok).
import { api } from "./api.js";
import { h, icon, clear, field } from "./dom.js";
import { errorToast, toast } from "./ui.js";

export const PALETA = ["#5294E2", "#81C995", "#FDD663", "#C58AF9", "#F28B82", "#78D9EC", "#F6AE6B", "#A1A1A8"];

let cache = null;

export async function listProjects(force = false) {
  if (!cache || force) cache = await api.get("/projects");
  return cache;
}

export function invalidateProjects() {
  cache = null;
}

// Etiqueta "● Nome" de uma tarefa (nada se ela não tem projeto).
export function projectChip(t) {
  if (!t.project_name) return null;
  const dot = h("span", { class: "dot" });
  dot.style.background = t.project_color || "var(--dim)";
  return h("span", { class: "chip project" }, dot, t.project_name);
}

// Etiquetas de todos os projetos da tarefa: o principal e os extras.
export function projectChips(t) {
  const extras = (t.extra_projects || []).map((p) => projectChip({ project_name: p.name, project_color: p.color }));
  return [projectChip(t), ...extras].filter(Boolean);
}

// Outros projetos da tarefa (além do principal): etiquetas com × e um seletor
// "+ outro projeto". getPrincipal() diz o principal atual (ele não aparece na
// lista; sem principal, não há extras). onChange(ids) a cada mudança.
// Devolve { el, ids(), sync() } — sync() depois de trocar o principal.
export function extraProjectsField(initial, getPrincipal, onChange) {
  let ids = [...(initial || [])];
  const el = h("div", { class: "extra-projects" });
  async function paint() {
    const list = await listProjects().catch(() => []);
    const principal = getPrincipal();
    ids = ids.filter((id) => id !== principal);
    clear(el);
    if (!principal) {
      el.append(h("span", { class: "hint", text: "Escolha o projeto principal antes." }));
      return;
    }
    for (const id of ids) {
      const p = list.find((x) => x.id === id) || { id, name: "(projeto arquivado)", color: null };
      const chip = projectChip({ project_name: p.name, project_color: p.color });
      chip.append(h("button", { type: "button", class: "chip-x", title: "Tirar " + p.name, "aria-label": "Tirar o projeto " + p.name,
        onClick: () => { ids = ids.filter((x) => x !== id); paint(); onChange(ids); } }, icon("close")));
      el.append(chip);
    }
    const rest = list.filter((p) => p.id !== principal && !ids.includes(p.id));
    if (!rest.length || ids.length >= 10) return;
    const add = h("select", { class: "select-sm", "aria-label": "Adicionar outro projeto" },
      h("option", { value: "", text: ids.length ? "+ mais um" : "+ outro projeto" }),
      ...rest.map((p) => h("option", { value: String(p.id), text: p.name })));
    add.addEventListener("change", () => {
      if (!add.value) return;
      ids = [...ids, Number(add.value)];
      paint();
      onChange(ids);
    });
    el.append(add);
  }
  paint();
  return { el, ids: () => ids, sync: paint };
}

// Projeto padrão (Configurações > Conta): vai para a tarefa criada sem projeto.
export function defaultProjectPanel(me, onSaved) {
  const sel = h("select", { "aria-label": "Projeto padrão" });
  const fill = async () => {
    const list = await listProjects();
    clear(sel);
    sel.append(h("option", { value: "", text: "Nenhum (a tarefa fica sem projeto)" }),
      ...list.map((p) => h("option", { value: String(p.id), text: p.name })));
    sel.value = list.some((p) => p.id === me.default_project_id) ? String(me.default_project_id) : "";
  };
  fill().catch(() => {});
  sel.addEventListener("change", async () => {
    try {
      const r = await api.put("/me/default-project", { project_id: sel.value ? Number(sel.value) : null });
      if (onSaved) onSaved(r);
      toast(r.default_project_id ? "Projeto padrão salvo." : "Sem projeto padrão.");
    } catch (e) { errorToast(e); fill().catch(() => {}); }
  });
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Projeto padrão" })),
    h("p", { class: "help", text: "Quando você cria uma tarefa sem escolher projeto, ela entra neste. Vale também para o registro rápido, os modelos sem projeto, a IA e as tarefas que você recebe por atribuição." }),
    field("Projeto padrão", sel));
}

// Preenche um <select> com "Sem projeto", os projetos e "+ Novo projeto…".
// O novo projeto é criado na hora e fica selecionado.
// onPick(valor): chamado quando o usuário escolhe um projeto (ou cria um novo).
export async function fillProjectSelect(select, selectedId, onPick) {
  const list = await listProjects();
  clear(select);
  select.append(h("option", { value: "", text: "Sem projeto" }));
  for (const p of list) select.append(h("option", { value: String(p.id), text: p.name }));
  // Tarefa ligada a um projeto arquivado: mantém a opção para não perder o vínculo.
  if (selectedId && !list.some((p) => p.id === selectedId)) {
    select.append(h("option", { value: String(selectedId), text: "(projeto arquivado)" }));
  }
  select.append(h("option", { value: "__new", text: "+ Novo projeto…" }));
  select.value = selectedId ? String(selectedId) : "";
  let previous = select.value;
  select.onchange = async () => {
    if (select.value !== "__new") { previous = select.value; if (onPick) onPick(select.value); return; }
    const name = await askName();
    if (!name) { select.value = previous; return; }
    try {
      const p = await api.post("/projects", { name });
      invalidateProjects();
      await fillProjectSelect(select, p.id, onPick);
      if (onPick) onPick(String(p.id));
      toast(`Projeto “${p.name}” criado.`);
    } catch (e) {
      errorToast(e, "Erro ao criar projeto.");
      select.value = previous;
    }
  };
}

// O seletor de objetivo (nova tarefa e detalhe): os do projeto, na ordem.
export async function fillObjectiveSelect(select, projectId, selectedId) {
  // Chamadas seguidas (o projeto carregou, depois trocou): só a última preenche,
  // e as opções só são trocadas depois que a lista chega (nada duplicado).
  const my = (select._seq = (select._seq || 0) + 1);
  const list = projectId ? await api.get(`/projects/${projectId}/objectives`).catch(() => []) : [];
  if (my !== select._seq) return list;
  clear(select);
  select.append(h("option", { value: "", text: projectId ? "Sem objetivo" : "Escolha um projeto antes" }));
  select.disabled = !projectId;
  list.forEach((ob, i) => select.append(h("option", { value: String(ob.id), text: `${i + 1}. ${ob.title}` })));
  select.value = selectedId && list.some((x) => x.id === selectedId) ? String(selectedId) : "";
  return list;
}

// Pergunta o nome num diálogo próprio (sem prompt() do navegador).
export function askName() {
  return new Promise((resolve) => {
    let value = null;
    const input = h("input", { type: "text", maxlength: "60", required: "required", placeholder: "Ex.: Loja Vila Velha" });
    const form = h("form", {},
      field("Nome do projeto ou cliente", input),
      h("div", { class: "dialog-actions" },
        h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
        h("button", { type: "submit", class: "btn btn-primary", text: "Criar" })));
    const dlg = h("dialog", {}, h("h2", { text: "Novo projeto" }), form);
    form.addEventListener("submit", (ev) => { ev.preventDefault(); value = input.value.trim() || null; dlg.close(); });
    dlg.addEventListener("close", () => { dlg.remove(); resolve(value); });
    document.body.append(dlg);
    dlg.showModal();
    input.focus();
  });
}
