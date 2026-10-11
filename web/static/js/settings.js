import { api } from "./api.js";
import { h } from "./dom.js";

// Dias úteis como máscara de bits, domingo = bit 0 (igual ao backend).
const DAYS = [
  { bit: 1, label: "Seg" }, { bit: 2, label: "Ter" }, { bit: 3, label: "Qua" },
  { bit: 4, label: "Qui" }, { bit: 5, label: "Sex" }, { bit: 6, label: "Sáb" },
  { bit: 0, label: "Dom" },
];

// Diálogo de preferências. onSaved(novoValor) é chamado depois de gravar.
export function openSettings(me, onSaved) {
  const boxes = DAYS.map((d) => {
    const cb = h("input", { type: "checkbox", value: String(d.bit) });
    cb.checked = ((me.work_days >> d.bit) & 1) === 1;
    return { d, cb };
  });
  const err = h("p", { class: "error-text" });
  const save = h("button", { type: "submit", text: "Salvar" });

  const form = h(
    "form",
    {},
    h("fieldset", { class: "weekday-picker" },
      h("legend", { text: "Meus dias úteis" }),
      ...boxes.map(({ d, cb }) => h("label", { class: "weekday-option" }, cb, h("span", { text: d.label })))
    ),
    h("p", {
      class: "dialog-note",
      text: "Recorrentes só contam como devidas nesses dias. O que você marcar fora deles fica salvo como extra.",
    }),
    err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "text", text: "Cancelar", onClick: () => dlg.close() }),
      save)
  );

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const mask = boxes.reduce((m, { d, cb }) => (cb.checked ? m | (1 << d.bit) : m), 0);
    if (!mask) {
      err.textContent = "Escolha pelo menos um dia.";
      return;
    }
    save.disabled = true;
    try {
      const res = await api.post("/auth/settings", { work_days: mask });
      me.work_days = res.work_days;
      dlg.close();
      onSaved && onSaved(res.work_days);
    } catch (e) {
      err.textContent = e.message || "Falha ao salvar.";
      save.disabled = false;
    }
  });

  const dlg = h("dialog", {}, h("h2", { text: "Configurações" }), form);
  document.body.appendChild(dlg);
  dlg.addEventListener("close", () => dlg.remove());
  dlg.showModal();
}
