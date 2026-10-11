// Extração de relatório em PDF por período. O admin passa opts.exportBase
// apontando para o usuário alvo.
import { api } from "./api.js";
import { h, icon, clear } from "./dom.js";
import { errorToast } from "./ui.js";

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function ranges() {
  const t = new Date();
  const dow = t.getDay(); // domingo = 0 (a semana do app começa no domingo)
  const ws = new Date(t); ws.setDate(t.getDate() - dow);
  const pws = new Date(ws); pws.setDate(ws.getDate() - 7);
  const pwe = new Date(ws); pwe.setDate(ws.getDate() - 1);
  const ms = new Date(t.getFullYear(), t.getMonth(), 1);
  const pms = new Date(t.getFullYear(), t.getMonth() - 1, 1);
  const pme = new Date(t.getFullYear(), t.getMonth(), 0);
  return [
    ["Esta semana", ws, t], ["Semana passada", pws, pwe],
    ["Este mês", ms, t], ["Mês passado", pms, pme],
  ];
}

export async function mount(root, opts = {}) {
  const base = opts.exportBase || "/reports/export";
  clear(root);

  const t = new Date();
  const weekAgo = new Date(); weekAgo.setDate(t.getDate() - 6);
  const startInput = h("input", { type: "date", value: iso(weekAgo) });
  const endInput = h("input", { type: "date", value: iso(t) });
  const err = h("p", { class: "error-text" });
  // Projeto: só no relatório do próprio usuário (o admin vê o geral).
  const projSel = h("select", {}, h("option", { value: "", text: "Todos (relatório completo)" }));
  if (!opts.exportBase) {
    try {
      for (const p of await api.get("/projects?include_archived=true"))
        projSel.append(h("option", { value: String(p.id), text: p.name + (p.archived ? " (arquivado)" : "") }));
    } catch { /* sem projetos */ }
  }
  const btn = h("button", { type: "button", class: "btn btn-primary", onClick: run }, icon("reports"), "Exportar PDF");

  const quick = h("div", { class: "quick" }, ...ranges().map(([label, a, b]) =>
    h("button", { type: "button", class: "btn btn-ghost btn-sm", text: label, onClick: () => { startInput.value = iso(a); endInput.value = iso(b); } })));

  // Com projeto escolhido: "projeto completo" (padrão, sem datas) ou um período.
  let whole = true;
  const scope = h("div", { class: "seg seg-sm hidden", role: "tablist", "aria-label": "Abrangência" });
  for (const [val, label] of [[true, "Projeto completo"], [false, "Escolher período"]]) {
    scope.append(h("button", {
      type: "button", class: "chip-btn", role: "tab", text: label, "aria-selected": String(val === whole),
      onClick: () => { whole = val; sync(); },
    }));
  }
  const dates = h("div", { class: "report-dates" },
    h("div", { class: "field" }, h("label", { text: "Início" }), startInput),
    h("div", { class: "field" }, h("label", { text: "Fim" }), endInput));
  const wholeNote = h("p", { class: "help hidden", text: "Do primeiro registro do projeto até hoje: tudo o que foi entregue, o tempo gasto e o que ainda está aberto." });
  function sync() {
    const proj = !!projSel.value;
    scope.classList.toggle("hidden", !proj);
    [...scope.children].forEach((b, i) => b.setAttribute("aria-selected", String((i === 0) === whole)));
    const useDates = !proj || !whole;
    dates.classList.toggle("hidden", !useDates);
    quick.classList.toggle("hidden", !useDates);
    wholeNote.classList.toggle("hidden", useDates);
  }
  projSel.addEventListener("change", sync);
  if (opts.projectId) projSel.value = String(opts.projectId);

  root.append(h("div", { class: "report-section" },
    h("h3", { text: "Relatório em PDF" }),
    h("p", { class: "sub", text: "Indicadores, ritmo, rotinas, entregas, o que está em aberto e o diário com o tempo apontado. Escolhendo um projeto, sai só o que é dele — do período que você quiser ou do projeto inteiro." }),
    projSel.options.length > 1 ? h("div", { class: "field report-project" }, h("label", { text: "Projeto" }), projSel) : null,
    scope, wholeNote, quick,
    h("div", { class: "report-controls" }, dates, btn),
    err));
  sync();

  // Exportação dos dados (só no próprio usuário; o admin exporta PDF).
  if (!opts.exportBase) {
    const dl = (path, label, help) => {
      const b = h("button", { type: "button", class: "btn btn-ghost", onClick: async () => {
        b.disabled = true;
        try { await api.download(path); } catch (e) { errorToast(e, "Falha ao exportar."); } finally { b.disabled = false; }
      } }, icon("download"), label);
      return h("div", { class: "export-row" }, b, h("span", { class: "help", text: help }));
    };
    root.append(h("div", { class: "report-section" },
      h("h3", { text: "Exportar dados" }),
      h("p", { class: "sub", text: "Seus dados em formato aberto, para planilha, faturamento ou backup." }),
      dl("/export/apontamentos.csv", "Apontamentos (CSV)", "um registro por apontamento de tempo: dia, horas, tarefa, projeto e observação"),
      dl("/export/tarefas.csv", "Tarefas (CSV)", "todas as tarefas com status, prioridade, projeto, prazo, checklist e horas"),
      dl("/export/tudo.json", "Tudo (JSON)", "tarefas com anotações, checklist e tempo, recorrentes com os dias feitos e projetos")));
  }

  async function run() {
    err.textContent = "";
    const proj = projSel.value ? `project=${projSel.value}` : "";
    const useDates = !proj || !whole;
    const start = startInput.value, end = endInput.value;
    if (useDates && (!start || !end)) { err.textContent = "Preencha início e fim."; return; }
    if (useDates && start > end) { err.textContent = "O início não pode ser depois do fim."; return; }
    btn.disabled = true;
    try {
      const q = [useDates ? `start=${start}&end=${end}` : "", proj].filter(Boolean).join("&");
      await api.download(`${base}?${q}`);
    } catch (e) {
      err.textContent = e.message || "Falha ao exportar.";
    } finally {
      btn.disabled = false;
    }
  }
}
