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
  const btn = h("button", { type: "button", class: "btn btn-primary", onClick: run }, icon("reports"), "Exportar PDF");

  const quick = h("div", { class: "quick" }, ...ranges().map(([label, a, b]) =>
    h("button", { type: "button", class: "btn btn-ghost btn-sm", text: label, onClick: () => { startInput.value = iso(a); endInput.value = iso(b); } })));

  root.append(h("div", { class: "report-section" },
    h("h3", { text: "Relatório do período" }),
    h("p", { class: "sub", text: "Um PDF com as atividades dia a dia: recorrentes feitas e não feitas nos dias úteis, extras dos outros dias e as pontuais concluídas." }),
    quick,
    h("div", { class: "report-controls" },
      h("div", { class: "field" }, h("label", { text: "Início" }), startInput),
      h("div", { class: "field" }, h("label", { text: "Fim" }), endInput),
      btn),
    err));

  async function run() {
    err.textContent = "";
    const start = startInput.value, end = endInput.value;
    if (!start || !end) { err.textContent = "Preencha início e fim."; return; }
    if (start > end) { err.textContent = "O início não pode ser depois do fim."; return; }
    btn.disabled = true;
    try {
      await api.download(`${base}?start=${start}&end=${end}`);
    } catch (e) {
      err.textContent = e.message || "Falha ao exportar.";
    } finally {
      btn.disabled = false;
    }
  }
}
