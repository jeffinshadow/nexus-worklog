// Busca: tarefas (título, descrição, anotações, checklist, apontamentos),
// rotinas e projetos. Rota #/busca?q=… ; o termo aparece destacado.
import { api } from "./api.js";
import { h, icon, clear, localDay } from "./dom.js";
import { errorToast, hashPage, pager, setHashPage, toast } from "./ui.js";
import { openRecurring, taskChips } from "./board.js";
import { corProjeto, iconeProjeto } from "./projects.js";
import { openTask } from "./task.js";
import { card, enabled } from "./assistant.js";

const TASKS = 20; // linha alta (título, etiquetas e até 3 trechos)
const SIDE = 10;  // rotinas e projetos: lista lateral curta

function queryFromHash() {
  const qs = location.hash.split("?")[1] || "";
  return new URLSearchParams(qs).get("q") || "";
}

const FOLD = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

// Texto com o termo destacado em <mark> (comparação sem acento).
export function highlight(text, q) {
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
  const input = h("input", { type: "search", value: q, maxlength: "100", placeholder: "Tarefas, anotações, projetos…", "aria-label": "Buscar" });
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
  ctx.setEyebrow(`“${q}”`);

  // Cada seção pagina sozinha; a página de cada uma fica no endereço (?p=, ?pr=, ?pp=).
  const pg = { tasks: hashPage("p"), rec: hashPage("pr"), proj: hashPage("pp") };
  const fetchPage = () => api.get(`/search?q=${encodeURIComponent(q)}&limit=${TASKS}&offset=${(pg.tasks - 1) * TASKS}`
    + `&side_limit=${SIDE}&rec_offset=${(pg.rec - 1) * SIDE}&proj_offset=${(pg.proj - 1) * SIDE}`);
  let r;
  try {
    r = await fetchPage();
    // Página guardada além do fim (algo foi excluído): a última de cada seção.
    const fix = (k, total, size) => { const last = Math.max(1, Math.ceil(total / size)); if (pg[k] > last) { pg[k] = last; return true; } return false; };
    if ([fix("tasks", r.total_tasks, TASKS), fix("rec", r.total_recurring, SIDE), fix("proj", r.total_projects, SIDE)].some(Boolean)) r = await fetchPage();
  } catch (e) {
    root.append(h("p", { class: "empty", text: e.message || "Não foi possível buscar." }));
    return;
  }
  setHashPage("p", pg.tasks, "busca"); setHashPage("pr", pg.rec, "busca"); setHashPage("pp", pg.proj, "busca");
  const today = localDay(Date.now()); // só para os chips (prazo, atrasada)
  const refresh = () => mount(root, ctx);

  if (!r.total_tasks && !r.total_recurring && !r.total_projects) {
    if (enabled(ctx.me))
      ctx.setAssist(card({ key: "busca", lines: [`Não encontrei nada com “${q}”. Tente uma palavra só ou um termo mais curto; acentos e maiúsculas não importam.`], compact: true }));
    else root.append(h("p", { class: "empty", text: "Nada encontrado. Tente outra palavra ou o número do chamado." }));
    return;
  }

  // Trocar de página redesenha só a seção; o foco vai para o título dela.
  const turn = (k, sel) => async (n) => {
    pg[k] = n;
    r = await fetchPage();
    setHashPage({ tasks: "p", rec: "pr", proj: "pp" }[k], n, "busca");
    paint();
    return sel;
  };
  const count = (total) => h("span", { class: "count", text: String(total) });
  const tasksBox = h("div", { class: "search-box" }), sideBox = h("div", { class: "search-box" });
  root.append(tasksBox, sideBox);

  function paint() {
    clear(tasksBox); clear(sideBox);
    if (r.total_tasks) {
      const panel = h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", { class: "search-h-tasks", text: "Tarefas" }), count(r.total_tasks)));
      for (const t of r.tasks) {
        const hits = t.hits.filter((x) => x.kind !== "título");
        panel.append(h("div", { class: "search-row" + (t.status === "done" ? " done" : "") },
          h("button", { type: "button", class: "card-open", onClick: () => openTask(t.id, refresh) }, ...highlight(t.title, q)),
          h("div", { class: "card-meta" }, ...taskChips(t, today)),
          ...hits.map((x) => h("p", { class: "hit" }, h("span", { class: "hit-kind mono", text: x.kind }), ...highlight(x.text, q)))));
      }
      panel.append(pager({ page: pg.tasks, total: r.total_tasks, size: TASKS, label: "tarefas encontradas",
        onPage: turn("tasks"), focus: () => tasksBox.querySelector(".search-h-tasks") }));
      tasksBox.append(panel);
    }

    if (r.total_recurring || r.total_projects) {
      const side = h("section", { class: "panel" });
      if (r.total_recurring) {
        side.append(h("div", { class: "panel-head" }, h("h2", { class: "search-h-rec", text: "Rotinas" }), count(r.total_recurring)));
        for (const x of r.recurring)
          side.append(h("div", { class: "list-row" }, h("div", { class: "t" }, ...highlight(x.label, q),
            x.active ? null : h("small", { text: "removida" })),
            x.active ? h("button", { type: "button", class: "btn btn-ghost btn-sm", text: "Editar rotina", "aria-label": "Editar a rotina " + x.label,
              onClick: () => editRoutine(x.id, refresh) }) : null));
        side.append(pager({ page: pg.rec, total: r.total_recurring, size: SIDE, label: "rotinas encontradas", compact: true,
          onPage: turn("rec"), focus: () => sideBox.querySelector(".search-h-rec") }));
      }
      if (r.total_projects) {
        side.append(h("div", { class: "panel-head" }, h("h2", { class: "search-h-proj", text: "Projetos" }), count(r.total_projects)));
        for (const p of r.projects) {
          const dot = iconeProjeto(p.icon);
          dot.style.color = corProjeto(p.color);
          side.append(h("div", { class: "list-row" }, dot, h("div", { class: "t" }, ...highlight(p.name, q),
            p.archived ? h("small", { text: "arquivado" }) : null),
            h("a", { class: "btn btn-ghost btn-sm", href: "#/projetos?id=" + p.id, text: "Abrir projeto", "aria-label": "Abrir o projeto " + p.name })));
        }
        side.append(pager({ page: pg.proj, total: r.total_projects, size: SIDE, label: "projetos encontrados", compact: true,
          onPage: turn("proj"), focus: () => sideBox.querySelector(".search-h-proj") }));
      }
      sideBox.append(side);
    }
  }
  paint();
}

// Rotina achada na busca: abre o mesmo editor do Hoje, com a agenda atual dela.
async function editRoutine(id, onDone) {
  try {
    const b = await api.get("/board");
    const item = b.recurring.find((x) => x.id === id);
    if (!item) { toast("Essa rotina não está mais ativa.", { error: true }); onDone(); return; }
    openRecurring(item, onDone);
  } catch (e) { errorToast(e, "Não foi possível abrir a rotina."); }
}
