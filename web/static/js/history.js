// Histórico: o que mudou na conta, por quem (app, chave de API, IA, admin),
// com "desfazer" na ação mais recente de cada item.
import { api } from "./api.js";
import { h, icon, clear, dateTime } from "./dom.js";
import { confirmDialog, errorToast, hashPage, pager, setHashPage, toast } from "./ui.js";

const SIZE = 30; // linhas de uma linha (hora + frase): cabem em ~2 telas no computador

const WHO = {
  web: (r) => ["web", null, "app"],
  api: (r) => ["api", "key", r.token_name || "chave"],
  mcp: (r) => ["mcp", "spark", `IA · ${r.token_name || "chave"}`],
  admin: (r) => ["admin", "admin", "admin"],
};

export async function mount(root) {
  let page = hashPage();

  async function render() {
    let { rows, total } = await api.page(`/history?limit=${SIZE}&offset=${(page - 1) * SIZE}`);
    const last = Math.max(1, Math.ceil(total / SIZE));
    if (page > last) { // a página guardada sumiu (o histórico encolheu): a última
      page = last;
      ({ rows, total } = await api.page(`/history?limit=${SIZE}&offset=${(page - 1) * SIZE}`));
    }
    setHashPage("p", page, "historico");
    clear(root);
    const panel = h("section", { class: "panel" },
      h("p", { class: "help muted", text: "Toda alteração fica registrada por 180 dias. A origem aparece quando não foi pelo app (chave de API, IA, admin). Dá para desfazer a mais recente de cada tarefa, rotina ou configuração." }));
    if (!rows.length) panel.append(h("p", { class: "empty", text: "Nada registrado ainda." }));
    const list = h("div", { class: "hist" });
    for (const r of rows) {
      const [cls, ic, label] = (WHO[r.actor] || WHO.web)(r);
      // Pelo próprio app é o normal: a origem só aparece quando é outra (chave, IA, admin).
      const badge = cls === "web" ? null : h("span", { class: "who-badge " + cls }, ic ? icon(ic) : null, label);
      const actions = h("div");
      if (r.can_undo) {
        actions.append(h("button", {
          type: "button", class: "btn btn-ghost btn-sm", onClick: async () => {
            if (!(await confirmDialog({ title: "Desfazer esta ação?", text: r.summary, confirm: "Desfazer" }))) return;
            try {
              await api.post(`/history/${r.id}/undo`);
              toast("Desfeito.");
              render();
            } catch (e) {
              errorToast(e, "Não foi possível desfazer.");
            }
          },
        }, icon("undo"), "Desfazer"));
      } else if (r.undone) {
        actions.append(h("span", { class: "chip", text: "desfeita" }));
      }
      list.append(h("div", { class: "hist-row" + (r.undone ? " undone" : "") },
        h("span", { class: "hist-when", text: dateTime(r.created_at) }),
        h("div", { class: "hist-what" }, badge, r.summary),
        actions));
    }
    panel.append(list, pager({ page, total, size: SIZE, label: "Histórico",
      onPage: async (n) => { page = n; await render(); }, focus: () => document.getElementById("page-title") }));
    root.append(panel);
  }

  await render();
}
