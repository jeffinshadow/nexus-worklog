// Passos da rotina (a ronda com itens: casa de máquinas, bombas, gerador...).
// Marcar uma rotina com passos abre a lista, todos marcados; desmarcar um vira
// "feita, exceto: bombas" na evidência. A rotina conta UMA vez (nada muda nos
// números, no PDF nem na matriz); a evidência já vai para o PDF e o CSV.
import { api } from "./api.js";
import { h, icon, localDay } from "./dom.js";
import { busy, modal, toast } from "./ui.js";
import { photoGrid } from "./fotos.js";

const NOTE_MAX = 200;

// A evidência: o que não foi feito (ou "todos os N passos") e o texto da pessoa.
function stepsNote(steps, done, text = "") {
  const missing = steps.filter((_, i) => !done[i]);
  const extra = text.trim();
  let head = missing.length ? `feita, exceto: ${missing.join(", ")}` : `todos os ${steps.length} passos`;
  const room = NOTE_MAX - (extra ? extra.length + 3 : 0);
  if (head.length > room) head = head.slice(0, Math.max(20, room - 1)).trimEnd() + "…";
  return (extra ? `${head} · ${extra}` : head).slice(0, NOTE_MAX);
}

// r: a rotina ({id, label, steps, require_note}); day: o dia da tela (null = hoje).
// onDone(): recarrega quem abriu.
export function markWithSteps(r, day, onDone) {
  const boxes = r.steps.map(() => h("input", { type: "checkbox", checked: "checked" }));
  const list = h("ul", { class: "steps-list" }, ...r.steps.map((s, i) =>
    h("li", {}, h("label", { class: "check-line" }, boxes[i], h("span", { text: s })))));
  const text = h("input", { type: "text", maxlength: "120", placeholder: "ex.: bomba 2 com ruído; portão B sem trava" });
  const err = h("p", { class: "error-text", role: "alert" });
  const go = h("button", { type: "submit", class: "btn btn-primary" }, icon("check"), "Marcar feita");
  const sync = () => {
    const n = boxes.filter((b) => b.checked).length;
    go.disabled = !n;
    err.textContent = n ? "" : "Marque pelo menos um passo (ou cancele).";
  };
  list.addEventListener("change", sync);
  // A foto da evidência aqui mesmo (no campo é o comum): entra na hora, como no diálogo da evidência.
  const photoDay = day || localDay(Date.now());
  const photoBox = h("div", { class: "field" }, h("span", { class: "field-label", text: "Fotos (opcional)" }));
  const loadPhotos = async () => {
    let got = [];
    try { got = await api.get(`/recurring/${r.id}/photos?day=${photoDay}`); } catch { /* sem rede: só o botão */ }
    photoBox.querySelector(".photo-grid")?.remove();
    photoBox.append(photoGrid(got, { path: `/recurring/${r.id}/photos?day=${photoDay}`, onChange: loadPhotos }));
  };
  loadPhotos();
  // Foto ainda subindo: o "Marcar feita" espera (fechar antes cortaria o envio).
  photoBox.addEventListener("photo-busy", (ev) => { go.disabled = ev.detail || !boxes.some((b) => b.checked); });
  const form = h("form", {},
    h("h2", { text: r.label }),
    h("p", { class: "dialog-note", text: "Desmarque o que ficou sem fazer: isso fica anotado no PDF. A rotina conta como feita uma vez." }),
    list,
    h("label", { class: "field" }, r.require_note ? "Observação (esta rotina exige evidência)" : "Observação (opcional)", text),
    photoBox,
    err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }), go));
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    const done = boxes.map((b) => b.checked);
    // Exige evidência: com tudo feito, a observação é a evidência; faltando passo, a lista já é.
    if (r.require_note && done.every(Boolean) && !text.value.trim()) {
      err.textContent = "Esta rotina exige evidência: escreva o que foi conferido.";
      text.focus();
      return;
    }
    const note = stepsNote(r.steps, done, text.value);
    try {
      await api.post(`/recurring/${r.id}/toggle`, day ? { done: true, day, note } : { done: true, note });
      dlg.close();
      toast(done.every(Boolean) ? `Rotina marcada: ${r.label}` : `Rotina marcada, com ${done.filter((d) => !d).length} passo(s) de fora na evidência.`);
      const { refreshReminders } = await import("./lembretes.js");
      refreshReminders();
      if (onDone) onDone();
    } catch (e) { err.textContent = e.message || "Não foi possível salvar."; }
  }));
  const dlg = modal(form);
  dlg.classList.add("steps-dialog");
  sync();
  go.focus();
}
