// Extração de relatório em PDF por período. O admin passa opts.exportBase
// apontando para o usuário alvo.
import { api } from "./api.js";
import { h, icon, clear } from "./dom.js";

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

  root.append(h("div", { class: "report-section" },
    h("h3", { text: "Relatório do período" }),
    h("p", { class: "sub", text: "Um PDF com as atividades dia a dia: recorrentes devidas (feitas e não feitas), extras fora da agenda, pontuais concluídas e o tempo apontado. Escolhendo um projeto, sai só o que é dele." }),
    quick,
    h("div", { class: "report-controls" },
      h("div", { class: "field" }, h("label", { text: "Início" }), startInput),
      h("div", { class: "field" }, h("label", { text: "Fim" }), endInput),
      projSel.options.length > 1 ? h("div", { class: "field" }, h("label", { text: "Projeto" }), projSel) : null,
      btn),
    err));

  async function run() {
    err.textContent = "";
    const start = startInput.value, end = endInput.value;
    if (!start || !end) { err.textContent = "Preencha início e fim."; return; }
    if (start > end) { err.textContent = "O início não pode ser depois do fim."; return; }
    btn.disabled = true;
    try {
      const proj = projSel.value ? `&project=${projSel.value}` : "";
      await api.download(`${base}?start=${start}&end=${end}${proj}`);
    } catch (e) {
      err.textContent = e.message || "Falha ao exportar.";
    } finally {
      btn.disabled = false;
    }
  }
}
