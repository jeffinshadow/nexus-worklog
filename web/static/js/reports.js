// Extração de relatório em PDF por período. O admin passa opts.exportBase
// apontando para o usuário alvo.
import { api } from "./api.js";
import { h, icon, clear, field, addDays, localDay } from "./dom.js";
import { errorToast } from "./ui.js";
import { enabled, previewText } from "./assistant.js";

// Períodos a partir do "hoje" no fuso da app (não do relógio do navegador).
// A semana começa no domingo, como no resto do app.
function ranges(today) {
  const [y, m] = today.split("-").map(Number);
  const dow = new Date(today + "T00:00:00Z").getUTCDay();
  const ws = addDays(today, -dow);
  const ms = `${y}-${String(m).padStart(2, "0")}-01`;
  const pms = new Date(Date.UTC(y, m - 2, 1)).toISOString().slice(0, 10);
  return [
    ["Esta semana", ws, today], ["Semana passada", addDays(ws, -7), addDays(ws, -1)],
    ["Este mês", ms, today], ["Mês passado", pms, addDays(ms, -1)],
  ];
}

export async function mount(root, opts = {}) {
  const base = opts.exportBase || "/reports/export";
  clear(root);

  const today = localDay(Date.now());
  const startInput = h("input", { type: "date", value: addDays(today, -6), max: today });
  const endInput = h("input", { type: "date", value: today, max: today });
  const err = h("p", { class: "error-text" });
  // Projeto: os do próprio usuário, ou (admin) os do usuário escolhido.
  const projSel = h("select", {}, h("option", { value: "", text: "Todos (relatório completo)" }));
  try {
    for (const p of await api.get(opts.projectsUrl || "/projects?include_archived=true"))
      projSel.append(h("option", { value: String(p.id), text: p.name + (p.archived ? " (arquivado)" : "") }));
  } catch { /* sem projetos */ }
  const btn = h("button", { type: "button", class: "btn btn-primary", onClick: run }, icon("reports"), "Exportar PDF");

  const quick = h("div", { class: "quick" }, ...ranges(today).map(([label, a, b]) =>
    h("button", { type: "button", class: "btn btn-ghost btn-sm", text: label, onClick: () => { startInput.value = a; endInput.value = b; refreshPreview(); } })));

  // Com projeto escolhido: "projeto completo" (padrão, sem datas) ou um período.
  let whole = true;
  const scope = h("div", { class: "seg seg-sm hidden", role: "tablist", "aria-label": "Abrangência" });
  for (const [val, label] of [[true, "Projeto completo"], [false, "Escolher período"]]) {
    scope.append(h("button", {
      type: "button", class: "chip-btn", role: "tab", text: label, "aria-selected": String(val === whole),
      onClick: () => { whole = val; sync(); refreshPreview(); },
    }));
  }
  const dates = h("div", { class: "report-dates" },
    field("Início", startInput),
    field("Fim", endInput));
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

  // Prévia do assistente: o que o PDF vai trazer (só no próprio relatório).
  const preview = h("p", { class: "assist-note hidden", "aria-live": "polite" });
  let previewSeq = 0;
  async function refreshPreview() {
    if (opts.exportBase || !enabled(opts.me)) return;
    const proj = projSel.value;
    const useDates = !proj || !whole;
    const start = startInput.value, end = endInput.value;
    if (useDates && (!start || !end || start > end)) { preview.classList.add("hidden"); return; }
    const qs = [useDates ? `start=${start}&end=${end}` : "", proj ? `project=${proj}` : ""].filter(Boolean).join("&");
    const seq = ++previewSeq;
    try {
      const r = await api.get(`/reports/preview?${qs}`);
      if (seq !== previewSeq) return; // chegou uma resposta mais nova
      clear(preview);
      preview.append(icon("spark"), h("span", { text: previewText(r) }));
      preview.classList.remove("hidden");
    } catch { preview.classList.add("hidden"); }
  }
  for (const el of [projSel, startInput, endInput]) el.addEventListener("change", refreshPreview);

  root.append(h("div", { class: "report-section" },
    h("h3", { text: "Relatório em PDF" }),
    h("p", { class: "sub", text: "Indicadores, ritmo, rotinas, tarefas concluídas, o que está em aberto e o diário com o tempo apontado. Escolhendo um projeto, sai só o que é dele — do período que você quiser ou do projeto inteiro." }),
    projSel.options.length > 1 ? field("Projeto", projSel, "report-project") : null,
    scope, wholeNote, quick,
    h("div", { class: "report-controls" }, dates, btn),
    preview, err));
  sync();
  refreshPreview();

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
      dl("/export/tudo.json", "Tudo (JSON)", "tarefas com anotações, checklist e tempo, rotinas com os dias feitos e projetos")));
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
