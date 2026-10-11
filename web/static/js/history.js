// Histórico: o que mudou na conta, por quem (app, chave de API, IA, admin),
// com "desfazer" na ação mais recente de cada item.
import { api } from "./api.js";
import { h, icon, clear, dateTime } from "./dom.js";
import { confirmDialog, errorToast, toast } from "./ui.js";

const WHO = {
  web: (r) => ["web", null, "app"],
  api: (r) => ["api", "key", r.token_name || "chave"],
  mcp: (r) => ["mcp", "spark", `IA · ${r.token_name || "chave"}`],
  admin: (r) => ["admin", "admin", "admin"],
};

export async function mount(root) {
  let limit = 50;

  async function render() {
    const rows = await api.get(`/history?limit=${limit}`);
    clear(root);
    const panel = h("section", { class: "panel" },
      h("p", { class: "help muted", text: "Toda alteração fica registrada com a origem. Dá para desfazer a mais recente de cada tarefa, recorrente ou configuração." }));
    if (!rows.length) panel.append(h("p", { class: "empty", text: "Nada registrado ainda." }));
    const list = h("div", { class: "hist" });
    for (const r of rows) {
      const [cls, ic, label] = (WHO[r.actor] || WHO.web)(r);
      const badge = h("span", { class: "who-badge " + cls }, ic ? icon(ic) : null, label);
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
    panel.append(list);
    if (rows.length === limit && limit < 200) {
      panel.append(h("button", { type: "button", class: "btn btn-text show-more", text: "carregar mais", onClick: () => { limit = Math.min(200, limit + 50); render(); } }));
    }
    root.append(panel);
  }

  await render();
}
