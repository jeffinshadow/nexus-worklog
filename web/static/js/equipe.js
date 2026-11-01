// Equipe (Visualizador de tarefas): o registro de cada pessoa que aceitou
// (Configurações > Conta), somente leitura: quadro, o mês (a mesma tela de Meu
// mês, com o PDF) e as horas dessas pessoas em CSV.
import { api } from "./api.js";
import { h, icon, clear, field, localDay, addDays } from "./dom.js";
import { errorToast, actionMenu } from "./ui.js";
import * as board from "./board.js";
import * as mes from "./mes.js";

// Nomes diferentes dos itens do menu: aqui é o registro de outra pessoa.
const SUBVIEWS = [
  { key: "board", label: "Quadro" },
  { key: "mes", label: "Mês e PDF" },
];
const monthState = { month: null, months: null }; // o mês escolhido vale para todas as pessoas

export async function mount(root) {
  const users = await api.get("/viewer/users");
  clear(root); // só depois da resposta: na volta à tela, a visita anterior fica até chegar
  if (!users.length) {
    root.append(h("p", { class: "empty", text: "Ninguém liberou o registro ainda. Cada pessoa decide em Configurações > Conta." }));
    return;
  }
  const select = h("select", {},
    ...users.map((u) => h("option", { value: u.id }, `${u.display_name ? u.display_name + " · " : ""}${u.email}`)));

  let active = "board";
  const subtabs = h("div", { class: "seg seg-sm", role: "tablist", "aria-label": "Equipe" },
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
      // Só o mês pedido (este ou o passado), não tudo desde sempre.
      h("button", { type: "button", class: "btn btn-ghost", title: "Horas de quem liberou o registro, com pessoa e projeto (some por cliente na planilha)",
        "aria-haspopup": "menu", onClick: (ev) => {
          const b = ev.currentTarget;
          const today = localDay(Date.now()), first = today.slice(0, 8) + "01";
          const prevFirst = addDays(first, -1).slice(0, 8) + "01";
          const get = (start, end) => async () => {
            b.disabled = true;
            try { await api.download(`/viewer/export/apontamentos.csv?start=${start}&end=${end}`); }
            catch (e) { errorToast(e, "Não foi possível exportar."); } finally { b.disabled = false; }
          };
          actionMenu(b, "Horas da equipe (CSV)", [
            ["Este mês", "calendar", get(first, today)],
            ["Mês passado", "calendar", get(prevFirst, addDays(first, -1))],
          ]);
        } }, icon("download"), "Horas da equipe (CSV)")),
    h("p", { class: "dialog-note equipe-note", text: "Aparecem aqui só as pessoas que liberaram o registro para quem vê a equipe (cada uma decide em Configurações > Conta)." }),
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
      else await mes.view(box, { state: monthState, who: select.selectedOptions[0]?.textContent.split(" · ")[0] || "a pessoa",
        dashUrl: `/viewer/users/${uid}/dashboard`, exportBase: `/viewer/users/${uid}/reports/export`, projectsUrl: `/viewer/users/${uid}/projects` });
    } catch (e) {
      clear(box);
      if (e && e.status === 404 && my === seq) {
        // A pessoa desligou o aceite com a tela aberta: tentar de novo não adianta.
        const opt = select.selectedOptions[0];
        const who = opt ? opt.textContent.split(" · ")[0] : "Essa pessoa";
        if (opt) opt.remove();
        box.append(h("p", { class: "empty", text: `${who} não libera mais o registro para quem vê a equipe.` }));
      } else box.append(h("p", { class: "empty", text: e && e.status === 0 ? e.message : "Não foi possível carregar. Tente de novo." }));
    }
    if (my !== seq) return;
    clear(content);
    content.append(box);
  }
  select.addEventListener("change", renderCurrent);
  renderCurrent();
}
