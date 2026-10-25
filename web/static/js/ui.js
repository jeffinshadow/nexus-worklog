// Peças de interface reutilizáveis: diálogos, avisos (toasts) e cópia.
// Substituem alert()/confirm() do navegador. Tudo criado via DOM (CSP).
import { api } from "./api.js";
import { h, icon } from "./dom.js";

// Diálogo modal criado na hora; some do DOM ao fechar.
export function modal(...children) {
  const dlg = h("dialog", {}, ...children);
  document.body.appendChild(dlg);
  dlg.addEventListener("close", () => dlg.remove());
  dlg.showModal();
  return dlg;
}

// Confirmação com botões próprios. Resolve true/false.
export function confirmDialog({ title, text, confirm = "Confirmar", danger = false }) {
  return new Promise((resolve) => {
    let ok = false;
    const dlg = modal(
      h("h2", { text: title }),
      text ? h("p", { text }) : null,
      h("div", { class: "dialog-actions" },
        h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
        h("button", {
          type: "button", class: "btn " + (danger ? "btn-danger" : "btn-primary"), text: confirm,
          onClick: () => { ok = true; dlg.close(); },
        }))
    );
    dlg.addEventListener("close", () => resolve(ok));
  });
}

// Aviso curto no rodapé. opts: { error, action: "Desfazer", onAction }
export function toast(message, opts = {}) {
  const box = document.getElementById("toasts");
  if (!box) return;
  const el = h("div", { class: "toast" + (opts.error ? " error" : ""), role: "status" }, h("span", { text: message }));
  if (opts.action) {
    el.append(h("button", {
      type: "button", class: "btn btn-ghost btn-sm", text: opts.action,
      onClick: async () => { el.remove(); await opts.onAction?.(); },
    }));
  }
  box.append(el);
  setTimeout(() => el.remove(), opts.action ? 7000 : 3500);
}

// Formulário: o botão de envio fica desabilitado até o handler terminar
// (duplo clique não manda duas vezes). Uso: addEventListener("submit", busy(async (ev) => {...})).
export function busy(fn) {
  return async (ev) => {
    if (ev) ev.preventDefault(); // nunca o envio nativo do formulário
    const form = ev && ev.target;
    if (form && form.dataset) {
      if (form.dataset.busy) return;
      form.dataset.busy = "1";
    }
    const btns = form && form.querySelectorAll ? [...form.querySelectorAll("[type=submit]")] : [];
    btns.forEach((b) => { b.disabled = true; });
    try { return await fn(ev); } finally {
      if (form && form.dataset) delete form.dataset.busy;
      btns.forEach((b) => { b.disabled = false; });
    }
  };
}

// Só mensagens da API (que têm status) vão para a tela; erro de JavaScript
// (em inglês, técnico) vira a mensagem genérica.
export function errorToast(e, fallback = "Algo deu errado.") {
  toast((e && "status" in e && e.message) || fallback, { error: true });
}

// Desfaz a ação mais recente de um item (usa o histórico do backend).
export async function undoLatest(entity, entityId, onDone) {
  try {
    const rows = await api.get(`/history?limit=1&entity=${entity}&entity_id=${entityId}`);
    if (!rows.length || !rows[0].can_undo) throw new Error("Nada para desfazer.");
    await api.post(`/history/${rows[0].id}/undo`);
    toast("Desfeito.");
    onDone && onDone();
  } catch (e) {
    errorToast(e, "Não foi possível desfazer.");
  }
}

// Bloco de código/valor com botão de copiar.
export function codeBox(text) {
  const btn = h("button", { type: "button", class: "icon-btn copy", title: "Copiar", "aria-label": "Copiar" }, icon("copy"));
  btn.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(text); toast("Copiado."); }
    catch { toast("Selecione e copie manualmente.", { error: true }); }
  });
  return h("div", { class: "codebox" }, text, btn);
}

export function warnBox(text) {
  return h("div", { class: "warnbox" }, icon("alert"), h("span", { text }));
}
