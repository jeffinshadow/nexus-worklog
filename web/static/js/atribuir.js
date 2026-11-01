// Atribuir tarefas (Atribuidor): mandar uma tarefa para quem aceitou receber,
// acompanhar o status das que mandou e ver quem aceita. A tarefa nasce na conta
// de quem recebe (que vira o dono) e ele recebe um e-mail.
import { api } from "./api.js";
import { h, icon, clear, field, shortDate, localDay, dateTime } from "./dom.js";
import { busy, confirmDialog, errorToast, modal, toast } from "./ui.js";
import { avatar } from "./profile.js";
import { STATUS_LABELS } from "./board.js";
import { session } from "./session.js";

export async function mount(root) {
  // As duas listas vêm juntas (uma ida ao servidor a menos) e antes de limpar:
  // na volta à tela, a visita anterior fica até chegar.
  const [people, sent] = await Promise.all([api.get("/assign/people"), api.get("/assign/sent").catch((e) => e)]);
  clear(root);
  const grid = h("div", { class: "settings-grid" });
  root.append(grid);
  const sentBox = h("section", { class: "panel" });
  grid.append(assignForm(people, () => loadSent(sentBox)), sentBox, consentsPanel(people));
  await loadSent(sentBox, sent);
}

function assignForm(people, onSent) {
  const accepting = people.filter((p) => p.accepts && p.id !== session.me.id);
  const sec = h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Nova tarefa" })));
  if (!accepting.length) {
    sec.append(h("p", { class: "empty", text: "Ninguém aceitou receber tarefas ainda. Cada pessoa liga isso em Configurações > Conta." }));
    return sec;
  }
  const who = h("select", { required: "required" },
    ...accepting.map((p) => h("option", { value: p.id, text: p.display_name ? `${p.display_name} · ${p.email}` : p.email })));
  const title = h("input", { type: "text", maxlength: "200", required: "required" });
  const desc = h("input", { type: "text", maxlength: "300" });
  const due = h("input", { type: "date" });
  const prio = h("select", {}, h("option", { value: "1", text: "Alta" }), h("option", { value: "2", text: "Normal", selected: "selected" }), h("option", { value: "3", text: "Baixa" }));
  const ticket = h("input", { type: "text", maxlength: "41", placeholder: "ex.: 4821", autocomplete: "off" });
  const after = h("input", { type: "checkbox" });
  const err = h("p", { class: "error-text" });
  const submit = h("button", { type: "submit", class: "btn btn-primary" }, icon("send"), "Atribuir");
  const form = h("form", {},
    field("Para", who),
    field("Título", title),
    field("Descrição (uma linha, opcional)", desc),
    h("div", { class: "field-row" }, field("Prazo (opcional)", due), field("Prioridade", prio)),
    h("div", { class: "field-row" }, field("Chamado (opcional)", ticket),
      h("div", { class: "field field-check" }, h("label", { class: "check-line" }, after, h("span", { text: "Plantão / fora do horário" })))),
    h("p", { class: "dialog-note", text: "A pessoa recebe um e-mail e a tarefa passa a ser dela. Enquanto estiver a fazer, você ainda corrige ou cancela; depois que ela começar, você só acompanha." }),
    err, h("div", { class: "dialog-actions" }, h("div", { class: "spacer" }), submit));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    submit.disabled = true;
    try {
      const res = await api.post("/assign", {
        user_id: Number(who.value), title: title.value.trim(), description: desc.value.trim() || null,
        due_date: due.value || null, priority: Number(prio.value), ticket: ticket.value.trim() || null, after_hours: after.checked,
      });
      toast(`Atribuída a ${res.to}.${res.emailed ? " E-mail enviado." : ""}`);
      title.value = desc.value = due.value = ticket.value = "";
      prio.value = "2";
      after.checked = false;
      onSent();
    } catch (e) {
      err.textContent = e.message || "Não foi possível atribuir.";
    } finally { submit.disabled = false; }
  });
  sec.append(form);
  return sec;
}

// `ready`: a lista já buscada (ou o erro dela) na abertura da tela.
async function loadSent(sec, ready) {
  let rows;
  try {
    rows = ready === undefined ? await api.get("/assign/sent") : ready;
    if (rows instanceof Error) throw rows;
  } catch (e) { errorToast(e); rows = null; }
  clear(sec);
  sec.append(h("div", { class: "panel-head" }, h("h2", { text: "Tarefas que atribuí" })));
  if (!rows) return;
  if (!rows.length) {
    sec.append(h("p", { class: "empty", text: "Você ainda não atribuiu tarefas." }));
    return;
  }
  const reload = () => loadSent(sec);
  for (const r of rows) {
    const chips = [];
    if (r.status === "removed") {
      // Saiu da conta de quem recebeu: fica aqui com o que houve (60 dias).
      const quando = r.ended.at ? " em " + shortDate(localDay(r.ended.at)) : "";
      chips.push(h("span", { class: "chip late", text:
        r.ended.kind === "canceled" ? "cancelada por você" + quando
        : `excluída por ${r.to_name}${quando}` }));  // um termo só (com ou sem data)
    } else {
      chips.push(h("span", { class: "chip " + r.status, text: r.status === "done" && r.completed_at
        ? "concluída em " + shortDate(localDay(r.completed_at)) : STATUS_LABELS[r.status] }));
      if (r.late) chips.push(h("span", { class: "chip late", text: "atrasada · " + shortDate(r.due_date) }));
      else if (r.due_date && r.status !== "done") chips.push(h("span", { class: "chip", text: "prazo " + shortDate(r.due_date) }));
      if (r.priority === 1 && r.status !== "done") chips.push(h("span", { class: "chip prio-1", text: "alta" }));
      if (r.status === "blocked" && r.blocked_reason) chips.push(h("span", { class: "chip blocked-reason", title: "Aguardando: " + r.blocked_reason, text: r.blocked_reason }));
    }
    // Enquanto está "a fazer" e sem nada registrado, quem atribuiu ainda corrige ou cancela.
    const acts = r.editable ? h("div", { class: "request-actions" },
      h("button", { type: "button", class: "btn btn-text btn-sm", text: "Alterar", onClick: () => editSent(r, reload) }),
      r.cancelable
        ? h("button", { type: "button", class: "btn btn-text btn-sm", text: "Cancelar", onClick: () => cancelSent(r, reload) })
        : h("small", { class: "muted", text: `${r.to_name} já mexeu nela: cancelar, só ela` })) : null;
    sec.append(h("div", { class: "list-row" + (r.status === "removed" ? " is-removed" : "") },
      h("div", { class: "t" }, h("span", { text: r.title }),
        h("small", { text: `para ${r.to_name} · ${r.assigned_at ? dateTime(r.assigned_at) : ""}` }),
        h("div", { class: "card-meta" }, ...chips)),
      acts));
  }
}

function editSent(r, done) {
  const title = h("input", { type: "text", maxlength: "200", required: "required", value: r.title });
  const due = h("input", { type: "date", value: r.due_date || "" });
  const prio = h("select", {}, h("option", { value: "1", text: "Alta" }), h("option", { value: "2", text: "Normal" }), h("option", { value: "3", text: "Baixa" }));
  prio.value = String(r.priority);
  const err = h("p", { class: "error-text" });
  const form = h("form", {},
    field("Título", title),
    h("div", { class: "field-row" }, field("Prazo (opcional)", due), field("Prioridade", prio)),
    h("p", { class: "dialog-note", text: `${r.to_name} recebe um e-mail com a mudança. Depois que a tarefa for começada, só quem recebeu pode mudá-la.` }),
    err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Voltar", onClick: () => dlg.close() }),
      h("button", { type: "submit", class: "btn btn-primary", text: "Salvar" })));
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    try {
      await api.patch(`/assign/${r.id}`, { title: title.value.trim(), due_date: due.value || null, priority: Number(prio.value) });
      dlg.close();
      toast("Tarefa alterada.");
      done();
    } catch (e) { err.textContent = e.message || "Não foi possível alterar."; }
  }));
  const dlg = modal(h("h2", { text: "Alterar tarefa atribuída" }), form);
  title.focus();
}

async function cancelSent(r, done) {
  if (!(await confirmDialog({ title: "Cancelar esta tarefa?", text: `“${r.title}” sai das tarefas de ${r.to_name}, que recebe um e-mail avisando. A tarefa continua nesta lista, marcada como cancelada.`, confirm: "Cancelar tarefa", danger: true, dismiss: "Voltar" }))) return;
  try { await api.post(`/assign/${r.id}/cancel`); toast("Tarefa cancelada."); }
  catch (e) { errorToast(e, "Não foi possível cancelar."); }
  done();
}

// Quem aceita receber tarefas. Sem nome escolhido pela pessoa, só o e-mail (como no Admin).
function consentsPanel(people) {
  const sec = h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Quem aceita receber tarefas" })),
    h("p", { class: "help", text: "Cada pessoa decide em Configurações > Conta. Sem o aceite, não dá para atribuir." }));
  if (!people.length) sec.append(h("p", { class: "empty", text: "Nenhuma pessoa com registro." }));
  // Só quem aceita, com o número dos outros embaixo (a lista não vira um diretório de quem recusou).
  const others = people.filter((p) => !p.accepts).length;
  if (people.length && others === people.length) sec.append(h("p", { class: "empty", text: "Ninguém aceita receber tarefas ainda." }));
  for (const p of people.filter((x) => x.accepts)) {
    sec.append(h("div", { class: "list-row" }, avatar(p, "sm"),
      h("div", { class: "t" }, h("span", { text: p.display_name || p.email }), p.display_name ? h("small", { text: p.email }) : null),
      p.accepts
        ? h("span", { class: "chip done", title: "Aceitou em " + dateTime(p.accepts_assignments_at), text: "aceita · desde " + shortDate(localDay(p.accepts_assignments_at)) })
        : h("span", { class: "chip", text: "não aceita" })));
  }
  if (others && others < people.length) sec.append(h("p", { class: "dialog-note", text: others === 1 ? "A outra pessoa não aceita receber tarefas." : `As outras ${others} pessoas não aceitam receber tarefas.` }));
  return sec;
}
