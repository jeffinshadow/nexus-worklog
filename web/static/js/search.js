// Busca: tarefas (título, descrição, anotações, checklist, apontamentos),
// rotinas e projetos. Rota #/busca?q=… ; o termo aparece destacado.
import { api } from "./api.js";
import { h, icon, clear, localDay } from "./dom.js";
import { taskChips } from "./board.js";
import { openTask } from "./task.js";
import { card, enabled } from "./assistant.js";

function queryFromHash() {
  const qs = location.hash.split("?")[1] || "";
  return new URLSearchParams(qs).get("q") || "";
}

const FOLD = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

// Texto com o termo destacado em <mark> (comparação sem acento).
function highlight(text, q) {
  const f = FOLD(text), fq = FOLD(q);
  const out = [];
  let i = 0;
  if (fq.length >= 2 && f.length === text.length) {
    let j;
    while ((j = f.indexOf(fq, i)) !== -1) {
      if (j > i) out.push(text.slice(i, j));
      out.push(h("mark", { text: text.slice(j, j + fq.length) }));
      i = j + fq.length;
    }
  }
  out.push(text.slice(i));
  return out;
}

export async function mount(root, ctx) {
  const q = queryFromHash();
  clear(root);
  const input = h("input", { type: "search", value: q, maxlength: "100", placeholder: "Buscar em tarefas, anotações, checklist, projetos…", "aria-label": "Buscar" });
  const form = h("form", { class: "search-big", role: "search" }, icon("search"), input,
    h("button", { type: "submit", class: "btn btn-primary btn-sm", text: "Buscar" }));
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const v = input.value.trim();
    if (v) location.hash = "#/busca?q=" + encodeURIComponent(v);
  });
  root.append(form);
  setTimeout(() => input.focus(), 0);
  if (q.trim().length < 2) {
    root.append(h("p", { class: "empty", text: "Digite pelo menos 2 letras. A busca ignora acentos e maiúsculas." }));
    return;
  }
  ctx.setEyebrow(`resultados para “${q}”`);

  let r;
  try {
    r = await api.get("/search?q=" + encodeURIComponent(q));
  } catch (e) {
    root.append(h("p", { class: "empty", text: e.message || "Erro na busca." }));
    return;
  }
  const today = localDay(Date.now()); // só para os chips (prazo, atrasada)
  const refresh = () => mount(root, ctx);

  if (!r.tasks.length && !r.recurring.length && !r.projects.length) {
    if (enabled(ctx.me))
      ctx.setAssist(card({ lines: [`Não encontrei nada com “${q}”. Tente uma palavra só ou um termo mais curto; acentos e maiúsculas não importam.`], compact: true }));
    else root.append(h("p", { class: "empty", text: "Nada encontrado." }));
    return;
  }

  if (r.tasks.length) {
    const panel = h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "Tarefas" }),
        h("span", { class: "count", text: r.total_tasks > r.tasks.length ? `${r.tasks.length} de ${r.total_tasks}` : String(r.tasks.length) })));
    for (const t of r.tasks) {
      const hits = t.hits.filter((x) => x.kind !== "título");
      panel.append(h("div", { class: "search-row" + (t.status === "done" ? " done" : "") },
        h("button", { type: "button", class: "card-open", onClick: () => openTask(t.id, refresh) }, ...highlight(t.title, q)),
        h("div", { class: "card-meta" }, ...taskChips(t, today)),
        ...hits.map((x) => h("p", { class: "hit" }, h("span", { class: "hit-kind mono", text: x.kind }), ...highlight(x.text, q)))));
    }
    root.append(panel);
  }

  if (r.recurring.length || r.projects.length) {
    const side = h("section", { class: "panel" });
    if (r.recurring.length) {
      side.append(h("div", { class: "panel-head" }, h("h2", { text: "Rotinas" })));
      for (const x of r.recurring)
        side.append(h("div", { class: "list-row" }, h("div", { class: "t" }, ...highlight(x.label, q),
          x.active ? null : h("small", { text: "removida" }))));
    }
    if (r.projects.length) {
      side.append(h("div", { class: "panel-head" }, h("h2", { text: "Projetos" })));
      for (const p of r.projects) {
        const dot = h("span", { class: "dot" });
        dot.style.background = p.color;
        side.append(h("div", { class: "list-row" }, dot, h("div", { class: "t" }, ...highlight(p.name, q),
          p.archived ? h("small", { text: "arquivado" }) : null),
          h("a", { class: "btn btn-ghost btn-sm", href: "#/tarefas", text: "Ver no quadro",
            onClick: () => sessionStorage.setItem("nexus.board.project", String(p.id)) })));
      }
    }
    root.append(side);
  }
}
