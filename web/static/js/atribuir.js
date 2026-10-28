// Atribuir tarefas (Atribuidor): mandar uma tarefa para quem aceitou receber,
// acompanhar o status das que mandou e ver quem aceita. A tarefa nasce na conta
// de quem recebe (que vira o dono) e ele recebe um e-mail.
import { api } from "./api.js";
import { h, icon, clear, field, shortDate, localDay, dateTime } from "./dom.js";
import { errorToast, toast } from "./ui.js";
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
    h("div", { class: "panel-head" }, icon("send"), h("h2", { text: "Nova tarefa" })));
  if (!accepting.length) {
    sec.append(h("p", { class: "empty", text: "Ninguém aceitou receber tarefas ainda. Cada pessoa liga isso em Configurações > Conta." }));
    return sec;
  }
  const who = h("select", { required: "required" },
    ...accepting.map((p) => h("option", { value: p.id, text: `${p.name} · ${p.email}` })));
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
      h("div", { class: "field field-check" }, h("label", { class: "weekday-option" }, after, h("span", { text: "Plantão / fora do horário" })))),
    h("p", { class: "dialog-note", text: "A pessoa recebe um e-mail e a tarefa passa a ser dela. Depois de enviada, você acompanha o status, mas não edita." }),
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
  sec.append(h("div", { class: "panel-head" }, icon("list"), h("h2", { text: "Tarefas que atribuí" })));
  if (!rows) return;
  if (!rows.length) {
    sec.append(h("p", { class: "empty", text: "Você ainda não atribuiu tarefas." }));
    return;
  }
  for (const r of rows) {
    const chips = [h("span", { class: "chip " + r.status, text: STATUS_LABELS[r.status] })];
    if (r.status === "done" && r.completed_at) chips.push(h("span", { class: "chip done", text: "fim " + shortDate(localDay(r.completed_at)) }));
    else if (r.late) chips.push(h("span", { class: "chip late", text: "atrasada · " + shortDate(r.due_date) }));
    else if (r.due_date) chips.push(h("span", { class: "chip", text: "prazo " + shortDate(r.due_date) }));
    if (r.priority === 1 && r.status !== "done") chips.push(h("span", { class: "chip prio-1", text: "alta" }));
    if (r.status === "blocked" && r.blocked_reason) chips.push(h("span", { class: "chip blocked-reason", text: "aguardando " + r.blocked_reason }));
    sec.append(h("div", { class: "list-row" },
      h("div", { class: "t" }, h("span", { text: r.title }),
        h("small", { text: `para ${r.to_name} · ${r.assigned_at ? dateTime(r.assigned_at) : ""}` })),
      h("div", { class: "card-meta" }, ...chips)));
  }
}

// Quem aceita receber tarefas (também na tela de Admin).
export function consentsPanel(people) {
  const sec = h("section", { class: "panel" },
    h("div", { class: "panel-head" }, icon("team"), h("h2", { text: "Quem aceita receber tarefas" })),
    h("p", { class: "help", text: "Cada pessoa decide em Configurações > Conta. Sem o aceite, não dá para atribuir." }));
  if (!people.length) sec.append(h("p", { class: "empty", text: "Nenhuma pessoa com registro." }));
  for (const p of people) {
    sec.append(h("div", { class: "list-row" }, avatar(p, "sm"),
      h("div", { class: "t" }, h("span", { text: p.name }), h("small", { text: p.email })),
      p.accepts
        ? h("span", { class: "chip done", title: "Aceitou em " + dateTime(p.accepts_assignments_at), text: "aceita · desde " + shortDate(localDay(p.accepts_assignments_at)) })
        : h("span", { class: "chip", text: "não aceita" })));
  }
  return sec;
}
