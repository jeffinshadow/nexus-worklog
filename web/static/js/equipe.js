// Equipe (Visualizador de tarefas): o registro de cada pessoa que aceitou
// (Configurações > Conta), somente leitura: quadro, retrospectiva, relatório
// em PDF e as horas dessas pessoas em CSV.
import { api } from "./api.js";
import { h, icon, clear, field } from "./dom.js";
import { errorToast } from "./ui.js";
import * as board from "./board.js";
import * as dashboard from "./dashboard.js";
import * as reports from "./reports.js";

// Nomes diferentes dos itens do menu: aqui é o registro de outra pessoa.
const SUBVIEWS = [
  { key: "board", label: "Quadro" },
  { key: "dashboard", label: "Números" },
  { key: "reports", label: "PDF" },
];

export async function mount(root) {
  const users = await api.get("/viewer/users");
  clear(root); // só depois da resposta: na volta à tela, a visita anterior fica até chegar
  if (!users.length) {
    root.append(h("p", { class: "empty", text: "Ninguém liberou o registro para visualizadores ainda. Cada pessoa decide em Configurações > Conta, em “Permitir que visualizadores vejam meu registro”." }));
    return;
  }
  const select = h("select", {},
    ...users.map((u) => h("option", { value: u.id }, `${u.display_name ? u.display_name + " · " : ""}${u.email}`)));

  let active = "board";
  const subtabs = h("div", { class: "seg seg-sm", role: "tablist" },
    ...SUBVIEWS.map((s) => h("button", {
      type: "button", class: "chip-btn", role: "tab", text: s.label,
      "aria-selected": s.key === active ? "true" : "false",
      onClick: () => {
        active = s.key;
        for (const b of subtabs.children) b.setAttribute("aria-selected", b.textContent === s.label ? "true" : "false");
        renderCurrent();
      },
    })));

  const content = h("div", {});
  const note = h("p", { class: "readonly-note" });
  const paintNote = () => { note.textContent = `somente leitura · registro de ${select.selectedOptions[0]?.textContent.split(" · ")[0] || ""}`; };
  root.append(
    h("div", { class: "admin-bar" },
      field("Pessoa", select),
      h("button", { type: "button", class: "btn btn-ghost", title: "Horas de quem liberou o registro, com pessoa e projeto (some por cliente na planilha)", onClick: async (ev) => {
        const b = ev.currentTarget;
        b.disabled = true;
        try { await api.download("/viewer/export/apontamentos.csv"); } catch (e) { errorToast(e, "Não foi possível exportar."); } finally { b.disabled = false; }
      } }, icon("download"), "Horas da equipe (CSV)")),
    subtabs,
    note,
    content);

  // Troca rápida de pessoa ou aba: monta fora da tela e só a última resposta entra.
  let seq = 0;
  async function renderCurrent() {
    const my = ++seq;
    const uid = select.value;
    paintNote();
    const box = h("div", {});
    try {
      if (active === "board") await board.mount(box, { readOnly: true, boardUrl: `/viewer/users/${uid}/board` });
      else if (active === "dashboard") await dashboard.mount(box, { dashUrl: `/viewer/users/${uid}/dashboard` });
      else await reports.mount(box, { exportBase: `/viewer/users/${uid}/reports/export`, projectsUrl: `/viewer/users/${uid}/projects` });
    } catch (e) {
      clear(box);
      box.append(h("p", { class: "empty", text: e && e.status === 0 ? e.message : "Não foi possível carregar. Tente de novo." }));
    }
    if (my !== seq) return;
    clear(content);
    content.append(box);
  }
  select.addEventListener("change", renderCurrent);
  renderCurrent();
}
