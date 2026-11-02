// Devolver uma tarefa atribuída (quem recebeu), com o motivo. Ela sai das
// tarefas da pessoa (como uma exclusão, desfazível) e quem atribuiu vê
// "devolvida" com o motivo em Equipe > Tarefas que atribuí, até atribuir de
// novo ou encerrar. Fica fora de task.js: o detalhe só chama.
import { api } from "./api.js";
import { h, icon, field, markInvalid } from "./dom.js";
import { busy, focusAfterRemoval, modal, toast, undoLatest } from "./ui.js";

// t: a tarefa (com assigned_by_name). onDone: depois de devolver ou desfazer.
// Promessa: true quando devolveu (o detalhe fecha).
export function returnTask(t, onDone) {
  return new Promise((resolve) => {
    let ok = false;
    const quem = t.assigned_by_name || "quem atribuiu";
    const reason = h("input", { type: "text", maxlength: "120", required: "required", autocomplete: "off",
      placeholder: "ex.: não é da minha área; estou de férias até dia 10" });
    const err = h("p", { class: "error-text", role: "alert" });
    const form = h("form", {},
      h("p", { class: "return-intro", text: `“${t.title}” volta para ${quem}, com o motivo, e sai das suas tarefas. Dá para desfazer pelo Histórico enquanto ${quem} não decidir o que fazer com ela.` }),
      field("Por quê? (até 120 caracteres)", reason),
      err,
      h("div", { class: "dialog-actions" },
        h("button", { type: "button", class: "btn btn-text", text: "Voltar", onClick: () => dlg.close() }),
        h("button", { type: "submit", class: "btn btn-primary" }, icon("undo"), "Devolver")));
    form.addEventListener("submit", busy(async () => {
      err.textContent = ""; markInvalid([reason], err, false);
      const why = reason.value.trim();
      if (why.length < 3) { err.textContent = "Diga em poucas palavras por que está devolvendo."; markInvalid([reason], err); reason.focus(); return; }
      const refocus = focusAfterRemoval();
      try {
        const res = await api.post(`/worklog/${t.id}/return`, { reason: why });
        ok = true;
        dlg.close();
        Promise.resolve(onDone && onDone()).then(refocus);
        toast(`Devolvida a ${res.to}.`, { action: "Desfazer", onAction: () => undoLatest("worklog", t.id, onDone) });
      } catch (e) { err.textContent = e.message || "Não foi possível devolver."; markInvalid([reason], err); }
    }));
    const dlg = modal(h("h2", { text: "Devolver a tarefa" }), form);
    dlg.addEventListener("close", () => resolve(ok));
    reason.focus();
  });
}
