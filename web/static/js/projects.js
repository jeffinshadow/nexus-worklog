// Projetos/clientes: lista em cache, seletor, etiqueta colorida e a aba de
// gestão em Configurações. A cor vem da API e entra via CSSOM (CSP ok).
import { api } from "./api.js";
import { h, icon, clear } from "./dom.js";
import { confirmDialog, errorToast, toast, undoLatest } from "./ui.js";

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

// Preenche um <select> com "Sem projeto", os projetos e "+ Novo projeto…".
// O novo projeto é criado na hora e fica selecionado.
export async function fillProjectSelect(select, selectedId) {
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
    if (select.value !== "__new") { previous = select.value; return; }
    const name = await askName();
    if (!name) { select.value = previous; return; }
    try {
      const p = await api.post("/projects", { name });
      invalidateProjects();
      await fillProjectSelect(select, p.id);
      toast(`Projeto “${p.name}” criado.`);
    } catch (e) {
      errorToast(e, "Erro ao criar projeto.");
      select.value = previous;
    }
  };
}

// Pergunta o nome num diálogo próprio (sem prompt() do navegador).
function askName() {
  return new Promise((resolve) => {
    let value = null;
    const input = h("input", { type: "text", maxlength: "60", required: "required", placeholder: "Ex.: Loja Vila Velha" });
    const form = h("form", {},
      h("div", { class: "field" }, h("label", { text: "Nome do projeto ou cliente" }), input),
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

// ------------------------------------------------- aba em Configurações --

export async function projectsPanel(rerender) {
  const list = await api.get("/projects?include_archived=true");
  const name = h("input", { type: "text", maxlength: "60", required: "required", placeholder: "Ex.: Loja Vila Velha" });
  const err = h("p", { class: "error-text" });
  const form = h("form", { class: "inline-form" },
    h("div", { class: "field" }, h("label", { text: "Novo projeto ou cliente" }), name),
    h("button", { type: "submit", class: "btn btn-primary" }, icon("add"), "Criar"));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    try {
      await api.post("/projects", { name: name.value.trim() });
      invalidateProjects();
      rerender();
    } catch (e) {
      err.textContent = e.message || "Falha ao criar.";
    }
  });

  const save = async (p, patch, msg) => {
    try {
      await api.patch(`/projects/${p.id}`, patch);
      invalidateProjects();
      if (msg) toast(msg);
      rerender();
    } catch (e) {
      errorToast(e, "Falha ao salvar.");
    }
  };

  const rows = list.map((p) => {
    const swatches = h("div", { class: "swatches", role: "radiogroup", "aria-label": "Cor de " + p.name },
      ...PALETA.map((c) => {
        const b = h("button", {
          type: "button", class: "swatch", role: "radio", title: c, "aria-label": c,
          "aria-checked": c.toLowerCase() === (p.color || "").toLowerCase() ? "true" : "false",
          onClick: () => save(p, { color: c }),
        });
        b.style.background = c;
        return b;
      }));
    const input = h("input", { type: "text", maxlength: "60", value: p.name, "aria-label": "Nome do projeto" });
    input.addEventListener("change", () => {
      const v = input.value.trim();
      if (v && v !== p.name) save(p, { name: v }, "Renomeado.");
      else input.value = p.name;
    });
    const dot = h("span", { class: "dot big" });
    dot.style.background = p.color;
    return h("div", { class: "project-row" + (p.archived ? " inactive" : "") },
      dot, input,
      h("span", { class: "token-meta", text: `${p.open_tasks} abertas · ${p.total_tasks} no total${p.archived ? " · arquivado" : ""}` }),
      swatches,
      h("div", { class: "actions" },
        h("button", { type: "button", class: "btn btn-ghost btn-sm", text: p.archived ? "Reativar" : "Arquivar",
          onClick: () => save(p, { archived: !p.archived }, p.archived ? "Projeto reativado." : "Arquivado: some dos seletores, as tarefas continuam.") }),
        h("button", { type: "button", class: "icon", title: "Excluir", "aria-label": "Excluir " + p.name, onClick: async () => {
          if (!(await confirmDialog({ title: `Excluir “${p.name}”?`, text: "As tarefas continuam, só ficam sem projeto. Dá para desfazer pelo histórico.", confirm: "Excluir", danger: true }))) return;
          try {
            await api.del(`/projects/${p.id}`);
            invalidateProjects();
            rerender();
            toast("Projeto excluído.", { action: "Desfazer", onAction: () => undoLatest("project", p.id, () => { invalidateProjects(); rerender(); }) });
          } catch (e) { errorToast(e); }
        } }, icon("trash"))));
  });

  return h("div", { class: "settings-grid" },
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, icon("folder"), h("h2", { text: "Projetos e clientes" })),
      h("p", { class: "help", text: "Agrupe as tarefas por cliente ou projeto: filtre o quadro, veja o tempo apontado e tire o relatório só daquele projeto." }),
      form, err),
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "Meus projetos" }), h("span", { class: "count", text: String(list.filter((p) => !p.archived).length) + " ativos" })),
      ...(list.length ? rows : [h("p", { class: "empty", text: "Nenhum projeto ainda." })])));
}
