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

// Texto de apresentação: no celular, recolhido em duas linhas com "Como funciona".
function intro(text) {
  const p = h("p", { class: "sub intro" }, text);
  const btn = h("button", { type: "button", class: "btn btn-text btn-sm intro-more", "aria-expanded": "false", text: "Como funciona",
    onClick: () => { const open = p.classList.toggle("open"); btn.setAttribute("aria-expanded", String(open)); btn.textContent = open ? "Recolher" : "Como funciona"; } });
  return [p, btn];
}

export async function mount(root, opts = {}) {
  const base = opts.exportBase || "/reports/export";
  // Projetos antes de limpar: na volta à tela, a visita anterior fica até chegar.
  const projects = await api.get(opts.projectsUrl || "/projects?include_archived=true").catch(() => []);
  clear(root);

  const today = localDay(Date.now());
  const startInput = h("input", { type: "date", value: addDays(today, -6), max: today });
  const endInput = h("input", { type: "date", value: today, max: today });
  const err = h("p", { class: "error-text" });
  // Projeto: os do próprio usuário, ou (admin) os do usuário escolhido.
  const projSel = h("select", {}, h("option", { value: "", text: "Todos (relatório completo)" }));
  for (const p of projects)
    projSel.append(h("option", { value: String(p.id), text: p.name + (p.archived ? " (arquivado)" : "") }));
  const btn = h("button", { type: "button", class: "btn btn-primary", onClick: run }, icon("reports"), "Exportar PDF");

  // Períodos prontos como botão segmentado: o que bate com as datas fica marcado.
  const periods = ranges(today);
  const quick = h("div", { class: "seg seg-sm quick", role: "group", "aria-label": "Período" }, ...periods.map(([label, a, b]) =>
    h("button", { type: "button", class: "chip-btn", text: label, "aria-pressed": "false",
      onClick: () => { startInput.value = a; endInput.value = b; markPeriod(); refreshPreview(); } })));
  function markPeriod() {
    [...quick.children].forEach((b, i) => {
      const on = periods[i][1] === startInput.value && periods[i][2] === endInput.value;
      b.setAttribute("aria-pressed", String(on));
      b.setAttribute("aria-selected", String(on)); // mesmo visual do .seg
    });
  }
  for (const el of [startInput, endInput]) el.addEventListener("change", markPeriod);

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
    intro("Indicadores, ritmo, rotinas, tarefas concluídas, o que está em aberto e o diário com o tempo apontado. Escolhendo um projeto, sai só o que é dele — do período que você quiser ou do projeto inteiro."),
    projSel.options.length > 1 ? field("Projeto", projSel, "report-project") : null,
    scope, wholeNote, quick,
    h("div", { class: "report-controls" }, dates, btn),
    preview, err));
  sync();
  markPeriod();
  refreshPreview();

  // Exportação dos dados (só no próprio usuário; o admin exporta PDF).
  if (!opts.exportBase) {
    // Cada exportação é um item de lista (Material 3): ícone, título, descrição
    // e o download no fim; a linha toda é o botão.
    const dl = (path, label, help) => {
      const b = h("button", { type: "button", class: "export-item", onClick: async () => {
        b.disabled = true;
        try { await api.download(typeof path === "function" ? path() : path); } catch (e) { errorToast(e, "Falha ao exportar."); } finally { b.disabled = false; }
      } }, h("span", { class: "export-ico" }, icon(label.includes("JSON") ? "folder" : label.includes("ZIP") ? "image" : "list")),
        h("span", { class: "export-text" }, h("span", { class: "export-title", text: label }), h("span", { class: "export-help", text: help })),
        icon("download"));
      return b;
    };
    root.append(h("div", { class: "report-section" },
      h("h3", { text: "Exportar dados" }),
      h("p", { class: "sub", text: "Seus dados em formato aberto, para planilha, faturamento ou backup." }),
      dl("/export/apontamentos.csv", "Apontamentos (CSV)", "um registro por apontamento de tempo: dia, horas, tarefa, projeto e observação"),
      dl("/export/tarefas.csv", "Tarefas (CSV)", "todas as tarefas com status, prioridade, projeto, prazo, checklist e horas"),
      dl(() => "/export/plantao.csv?" + new URLSearchParams(Object.entries({ start: startInput.value, end: endInput.value }).filter(([, v]) => v)),
        "Plantão do período (CSV)", "os apontamentos das tarefas marcadas como plantão, de todos os projetos, com as horas e o total — pra fechar sobreaviso ou banco de horas (usa o período escolhido acima)"),
      dl(() => "/export/rotinas.csv?" + new URLSearchParams(Object.entries({ start: startInput.value, end: endInput.value }).filter(([, v]) => v)),
        "Rotinas e evidências (CSV)", "trilha de auditoria: cada rotina em cada dia, se foi feita e o que foi conferido (usa o período escolhido acima)"),
      dl("/export/tudo.json", "Tudo (JSON)", "tarefas com anotações, checklist, tempo e como foram resolvidas; rotinas com dias feitos e evidências; vencimentos; projetos"),
      dl("/export/fotos.zip", "Fotos (ZIP)", "todas as fotos das tarefas e das evidências das rotinas, numa pasta por tarefa e por rotina")));
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
