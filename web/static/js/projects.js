// Projetos/clientes: lista em cache, seletor, etiqueta colorida e a aba de
// gestão em Configurações. A cor vem da API e entra via CSSOM (CSP ok).
import { api } from "./api.js";
import { h, icon, clear, field } from "./dom.js";
import { busy, errorToast, modal, toast } from "./ui.js";

export const PALETA = ["#5294E2", "#81C995", "#FDD663", "#C58AF9", "#F28B82", "#78D9EC", "#F6AE6B", "#A1A1A8"];

// A cor gravada no banco é um hex da PALETA; na tela ela vira o token do tema
// (--proj-1..8 em tokens.css: pastéis no escuro, versões AA no claro). Hex
// desconhecido passa como está; sem cor, o cinza apagado.
export function corProjeto(hex) {
  if (!hex) return "var(--dim)";
  const i = PALETA.findIndex((c) => c.toLowerCase() === String(hex).toLowerCase());
  return i < 0 ? hex : `var(--proj-${i + 1})`;
}

// Ícones de projeto: biblioteca fixa (sprite #icon-proj-<nome> em index.html;
// a mesma lista do backend, schemas.PROJECT_ICONS). Sem escolha = pasta.
export const ICONES = [
  ["pasta", "Pasta"], ["predio", "Prédio"], ["loja", "Loja"], ["clinica", "Clínica"], ["fabrica", "Fábrica"],
  ["escola", "Escola"], ["casa", "Casa"], ["escritorio", "Escritório"], ["servidor", "Servidor"], ["rede", "Rede"],
  ["wifi", "Wi-Fi"], ["seguranca", "Segurança"], ["manutencao", "Manutenção"], ["eletrica", "Elétrica"],
  ["hidraulica", "Hidráulica"], ["veiculo", "Veículo"], ["pessoa", "Pessoa"], ["maleta", "Maleta"],
  ["computador", "Computador"], ["celular", "Celular"], ["camera", "Câmera"], ["carrinho", "Carrinho"],
  ["calendario", "Calendário"], ["estrela", "Estrela"],
];
const NOMES_ICONE = new Set(ICONES.map(([n]) => n));

export function iconeProjeto(nome) {
  const el = icon("proj-" + (NOMES_ICONE.has(nome) ? nome : "pasta"));
  el.classList.add("proj-ico");
  return el;
}

// O ícone num quadradinho sólido na cor do projeto (cartão, cabeçalho, prévia).
export function projTile(p, extra = "") {
  const el = h("span", { class: "proj-tile" + (extra ? " " + extra : ""), "aria-hidden": "true" }, iconeProjeto(p.icon));
  el.style.background = corProjeto(p.color);
  return el;
}

let cache = null;

export async function listProjects(force = false) {
  if (!cache || force) cache = await api.get("/projects");
  return cache;
}

export function invalidateProjects() {
  cache = null;
}

// Etiqueta "[ícone] Nome" de uma tarefa (nada se ela não tem projeto): o ícone
// do projeto na cor dele, no lugar da bolinha.
export function projectChip(t) {
  if (!t.project_name) return null;
  const ic = iconeProjeto(t.project_icon);
  ic.style.color = corProjeto(t.project_color);
  return h("span", { class: "chip project" }, ic, t.project_name);
}

// Etiquetas de todos os projetos da tarefa: o principal e os extras.
export function projectChips(t) {
  const extras = (t.extra_projects || []).map((p) => projectChip({ project_name: p.name, project_color: p.color, project_icon: p.icon }));
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
      const chip = projectChip({ project_name: p.name, project_color: p.color, project_icon: p.icon });
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
      errorToast(e, "Não foi possível criar o projeto.");
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

// Grupo de opções (cor, ícone) com setas do teclado: só a marcada entra no Tab.
function radioGroup(label, cls, items, current, onPick) {
  const box = h("div", { class: cls, role: "radiogroup", "aria-label": label });
  const mark = (b) => {
    for (const x of box.children) {
      x.setAttribute("aria-checked", String(x === b));
      x.tabIndex = x === b ? 0 : -1;
    }
  };
  for (const [value, name, paint] of items) {
    const b = h("button", { type: "button", role: "radio", title: name, "aria-label": name, "data-value": value });
    paint(b);
    b.addEventListener("click", () => { mark(b); onPick(value); });
    box.append(b);
  }
  box.addEventListener("keydown", (ev) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[ev.key];
    if (!step) return;
    ev.preventDefault();
    const all = [...box.children];
    const next = all[(all.indexOf(document.activeElement) + step + all.length) % all.length];
    next.focus();
    next.click();
  });
  mark([...box.children].find((b) => b.dataset.value === current) || box.firstChild);
  return box;
}

// Criar ou editar o projeto: prévia do cartão, nome, descrição, cor e o ícone
// (grade de toque logo abaixo da cor). Resolve com o projeto salvo (ou null).
// `preset` (só ao criar): {name, color, icon} já sugeridos.
export function projectDialog(p = null, preset = {}) {
  return new Promise((resolve) => {
    let saved = null;
    const cur = p || preset;
    let color = cur.color || PALETA[0];
    let iconName = cur.icon || "pasta";
    const name = h("input", { type: "text", maxlength: "60", required: "required", value: cur.name || "", placeholder: "Ex.: Loja Vila Velha" });
    const desc = h("textarea", { rows: "2", maxlength: "500", placeholder: "Do que se trata (opcional)" });
    desc.value = cur.description || "";
    const prevTile = projTile({ color, icon: iconName }, "proj-tile-md");
    const prevName = h("strong", { class: "proj-preview-name" });
    const paintPreview = () => {
      prevTile.style.background = corProjeto(color);
      prevTile.replaceChildren(iconeProjeto(iconName));
      prevName.textContent = name.value.trim() || "Nome do projeto";
    };
    name.addEventListener("input", paintPreview);
    const swatches = radioGroup("Cor", "swatches swatches-lg", PALETA.map((c, i) => [c, `Cor ${i + 1}`, (b) => {
      b.className = "swatch-btn";
      const dot = h("span", { class: "swatch-dot" });
      dot.style.background = corProjeto(c);
      b.append(dot);
    }]), PALETA.find((c) => c.toLowerCase() === String(color).toLowerCase()) || "", (c) => { color = c; paintPreview(); });
    const grade = radioGroup("Ícone", "icon-grid", ICONES.map(([n, nome]) => [n, nome, (b) => {
      b.className = "icon-pick";
      b.append(iconeProjeto(n));
    }]), iconName, (n) => { iconName = n; paintPreview(); });
    paintPreview();
    const err = h("p", { class: "error-text" });
    const form = h("form", { class: "proj-form" }, h("h2", { text: p ? "Editar projeto" : "Novo projeto" }),
      h("div", { class: "proj-preview", "aria-hidden": "true" }, prevTile, prevName),
      field("Nome do projeto ou cliente", name), field("Descrição", desc),
      h("div", { class: "field" }, h("span", { class: "field-label", text: "Cor" }), swatches),
      h("div", { class: "field" }, h("span", { class: "field-label", text: "Ícone" }), grade), err,
      h("div", { class: "dialog-actions" },
        h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
        h("button", { type: "submit", class: "btn btn-primary", text: p ? "Salvar" : "Criar projeto" })));
    form.addEventListener("submit", busy(async () => {
      const body = { name: name.value.trim(), description: desc.value.trim() || null, color, icon: iconName };
      try {
        saved = p ? await api.patch(`/projects/${p.id}`, body) : await api.post("/projects", body);
        invalidateProjects();
        dlg.close();
      } catch (e) { err.textContent = e.message || "Não foi possível salvar."; }
    }));
    const dlg = modal(form);
    dlg.classList.add("proj-dialog");
    dlg.addEventListener("close", () => resolve(saved));
    name.focus();
  });
}
