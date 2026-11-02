// Atribuir tarefas (papel "Manda tarefas"), dentro da tela Equipe, sem tela
// própria: o botão "Atribuir tarefa" do cabeçalho abre um diálogo por cima da
// tela (como o de nova tarefa/projeto) e, logo abaixo do painel, "Tarefas que
// atribuí", com filtro simples e páginas. A tarefa nasce na conta de quem recebe
// (que vira o dono) e ela recebe um e-mail. Quem aceita receber aparece no
// próprio diálogo (a lista "Para" e a linha embaixo dela).
//
// Quem recebeu pode devolver a tarefa com o motivo (devolver.js): aqui ela fica
// "devolvida" até você atribuir de novo (o mesmo diálogo, já preenchido, para a
// mesma pessoa ou outra) ou encerrar.
import { api } from "./api.js";
import { h, icon, clear, field, shortDate, localDay, dateTime } from "./dom.js";
import { busy, confirmDialog, errorToast, hashPage, modal, pager, pageSlice, setHashPage, toast } from "./ui.js";
import { STATUS_LABELS } from "./board.js";
import { session } from "./session.js";

const SENT_PAGE = 15;   // linha média (título, para quem, etiquetas, ações)
const VIEW = "equipe";  // a tela dona do endereço (?p=)

const FILTERS = [
  ["all", "Todas", () => true],
  ["open", "Em aberto", (r) => r.status !== "done" && r.status !== "removed"],
  ["returned", "Devolvidas", (r) => r.ended && r.ended.kind === "returned"],
  ["done", "Concluídas", (r) => r.status === "done"],
];

const openReturn = (r) => r.ended && r.ended.kind === "returned" && !r.ended.resolved;

// ------------------------------------------------------------ o diálogo --
// Um diálogo só para atribuir, atribuir de novo (devolvida: `fromReturn`, já
// preenchido) e alterar (`edit`: a linha da lista; a pessoa não muda e o
// servidor só aceita título, descrição, prazo e prioridade).
export async function assignDialog({ fromReturn = null, edit = null, onDone } = {}) {
  let people = [];
  if (!edit) {
    try { people = await api.get("/assign/people"); } catch (e) { errorToast(e); return; }
  }
  const accepting = people.filter((p) => p.accepts && p.id !== session.me.id);
  const others = people.filter((p) => !p.accepts && p.id !== session.me.id).length;
  // "Todos recebem de quem atribui" (Admin › Para empresas): ninguém precisa aceitar.
  const everyone = people.some((p) => p.everyone);
  const close = h("button", { type: "button", class: "btn btn-text", text: "Voltar", onClick: () => dlg.close() });
  const heading = h("h2", { text: edit ? "Alterar tarefa atribuída" : fromReturn ? "Atribuir de novo" : "Atribuir tarefa" });

  if (!edit && !accepting.length) {
    const dlg = modal(heading,
      h("p", { text: everyone ? "Ainda não há ninguém com o papel Usuário (e acesso liberado) para receber tarefas."
        : "Ninguém aceitou receber tarefas ainda. Cada pessoa liga isso em Configurações > Conta, em “Permitir que me atribuam tarefas”." }),
      h("div", { class: "dialog-actions" }, h("div", { class: "spacer" }), h("button", { type: "button", class: "btn btn-primary", text: "Entendi", onClick: () => dlg.close() })));
    return;
  }

  const pre = edit || (fromReturn && fromReturn.ended.prefill) || {};
  let who = null;
  if (!edit) {
    // Uma pessoa só: já vem marcada. Mais de uma: escolhe (nada de mandar para a primeira da lista sem querer).
    who = h("select", { required: "required" },
      accepting.length > 1 ? h("option", { value: "", text: "Escolha quem recebe" }) : null,
      ...accepting.map((p) => h("option", { value: p.id, text: p.display_name ? `${p.display_name} · ${p.email}` : p.email })));
  }
  const title = h("input", { type: "text", maxlength: "200", required: "required", value: pre.title || "" });
  const desc = h("textarea", { rows: "3", maxlength: "300", placeholder: "O que fazer, onde, o que levar…" });
  desc.value = pre.description || "";
  const today = localDay(Date.now());
  // Prazo que já passou (a devolvida voltou tarde) não vem preenchido: escolha de novo.
  const due = h("input", { type: "date", value: pre.due_date && (edit || pre.due_date >= today) ? pre.due_date : "" });
  const prio = h("select", {}, h("option", { value: "1", text: "Alta" }), h("option", { value: "2", text: "Normal" }), h("option", { value: "3", text: "Baixa" }));
  prio.value = String(pre.priority || 2);
  const ticket = h("input", { type: "text", maxlength: "41", placeholder: "ex.: 4821", autocomplete: "off", value: pre.ticket || "" });
  const after = h("input", { type: "checkbox" });
  after.checked = !!pre.after_hours;
  const err = h("p", { class: "error-text", role: "alert" });

  const quemAceita = everyone
    ? "Nesta instância, todos recebem tarefas de quem atribui (definido pela administração)."
    : accepting.length === 1 ? "Aparece só quem aceita receber tarefas (1 pessoa)." : `Aparecem as ${accepting.length} pessoas que aceitam receber tarefas.`;
  const outras = !others ? "" : everyone
    ? (others === 1 ? " Fica de fora 1 conta com acesso bloqueado ou convite ainda não aceito." : ` Ficam de fora ${others} contas com acesso bloqueado ou convite ainda não aceito.`)
    : (others === 1 ? " A outra pessoa ainda não aceita" : ` As outras ${others} ainda não aceitam`) + " (cada uma liga em Configurações > Conta).";
  const form = h("form", {},
    fromReturn ? h("p", { class: "eq-returned-note" }, icon("undo"),
      h("span", { text: `${fromReturn.to_name} devolveu: «${fromReturn.ended.reason || "sem motivo"}». Ajuste o que precisar e escolha quem recebe (a mesma pessoa ou outra).` })) : null,
    edit ? h("p", { class: "dialog-note", text: `Para ${edit.to_name}` }) : field("Para", who),
    who ? h("p", { class: "help assign-who-help", text: quemAceita + outras }) : null,
    field("Título", title),
    field("Descrição (opcional, até 300 caracteres)", desc),
    h("div", { class: "field-row" }, field("Prazo (opcional)", due), field("Prioridade", prio)),
    edit ? null : h("div", { class: "field-row" }, field("Chamado (opcional)", ticket),
      h("div", { class: "field field-check" }, h("label", { class: "check-line" }, after, h("span", { text: "Plantão / fora do horário" })))),
    h("p", { class: "dialog-note", text: edit
      ? `${edit.to_name} recebe um e-mail com a mudança. Depois que a tarefa for começada, só quem recebeu pode mudá-la.`
      : "A pessoa recebe um e-mail e a tarefa passa a ser dela. Enquanto estiver a fazer, você ainda corrige ou cancela; depois que ela começar, você só acompanha." }),
    err,
    h("div", { class: "dialog-actions" }, close,
      h("button", { type: "submit", class: "btn btn-primary" }, icon(edit ? "check" : "send"), edit ? "Salvar" : "Atribuir")));

  form.addEventListener("submit", busy(async () => {
    err.textContent = "";
    try {
      if (edit) {
        // Só o que mudou: um campo que a pessoa já mexeu não é regravado por cima.
        const body = {};
        if (title.value.trim() !== edit.title) body.title = title.value.trim();
        if (desc.value.trim() !== (edit.description || "")) body.description = desc.value.trim() || null;
        if ((due.value || null) !== (edit.due_date || null)) body.due_date = due.value || null;
        if (Number(prio.value) !== edit.priority) body.priority = Number(prio.value);
        if (!Object.keys(body).length) { dlg.close(); return; }
        await api.patch(`/assign/${edit.id}`, body);
        dlg.close();
        toast("Tarefa alterada.");
      } else {
        if (!who.value) { err.textContent = "Escolha quem recebe."; who.focus(); return; }
        const res = await api.post("/assign", {
          user_id: Number(who.value), title: title.value.trim(), description: desc.value.trim() || null,
          due_date: due.value || null, priority: Number(prio.value), ticket: ticket.value.trim() || null, after_hours: after.checked,
          ...(fromReturn ? { from_return: fromReturn.id } : {}),
        });
        dlg.close();
        toast(`Atribuída a ${res.to}.${res.emailed ? " E-mail enviado." : ""}`);
      }
      if (onDone) onDone();
    } catch (e) { err.textContent = e.message || (edit ? "Não foi possível alterar." : "Não foi possível atribuir."); }
  }));
  const dlg = modal(heading, form);
  (who && !who.value ? who : title).focus();
}

// ------------------------------------------------ Tarefas que atribuí --
// { el, load(ready?), focusReturned(id) }: a seção e como recarregar.
// onChange: depois de alterar, cancelar, encerrar ou atribuir de novo (o painel
// da Equipe se atualiza: "Precisa de atenção" mostra as devolvidas).
export function sentPanel({ onChange = null } = {}) {
  const sec = h("section", { class: "panel eq-sent", "aria-label": "Tarefas que atribuí" });
  let rows = null, page = hashPage("p"), filter = "all", focusId = null;

  async function load(ready) {
    try {
      rows = ready === undefined ? await api.get("/assign/sent") : ready;
      if (rows instanceof Error) throw rows;
    } catch (e) { errorToast(e); rows = null; }
    paint();
  }
  const reload = () => { load(); if (onChange) onChange(); };

  function paint() {
    clear(sec);
    const n = rows ? rows.filter(openReturn).length : 0;
    sec.append(h("div", { class: "panel-head" }, h("h2", { text: "Tarefas que atribuí" }),
      rows && rows.length ? h("span", { class: "count", text: String(rows.length) }) : null));
    if (!rows) return;
    if (!rows.length) {
      sec.append(h("p", { class: "empty", text: "Você ainda não atribuiu tarefas. Use “Atribuir tarefa”, no alto da tela." }));
      return;
    }
    // Filtro simples (não é aba): botões que marcam, com quantas há em cada um.
    sec.append(h("div", { class: "seg seg-sm eq-sent-filter", role: "group", "aria-label": "Mostrar" },
      ...FILTERS.map(([key, label, test]) => {
        const c = key === "all" ? rows.length : rows.filter(test).length;
        return h("button", { type: "button", class: "chip-btn", "aria-pressed": String(filter === key),
          text: c && key !== "all" ? `${label} · ${c}` : label,
          onClick: () => { if (filter === key) return; filter = key; page = 1; paint(); sec.querySelector(`[aria-pressed="true"]`).focus(); } });
      })));
    if (n) sec.append(h("p", { class: "help", text: n === 1 ? "1 devolvida espera você: atribua de novo ou encerre." : `${n} devolvidas esperam você: atribua de novo ou encerre.` }));
    const test = FILTERS.find((f) => f[0] === filter)[2];
    // O que pede atenção primeiro: devolvidas sem decisão, atrasadas, as abertas,
    // as concluídas e as que saíram (cada grupo na ordem do servidor).
    const rank = (r) => (openReturn(r) ? -1 : r.status === "removed" ? 3 : r.status === "done" ? 2 : r.late ? 0 : 1);
    const ordered = rows.filter(test).map((r, i) => [r, i]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map(([r]) => r);
    if (focusId) {
      const at = ordered.findIndex((r) => r.id === focusId);
      if (at >= 0) page = Math.floor(at / SENT_PAGE) + 1;
    }
    const slice = pageSlice(ordered, page, SENT_PAGE);
    page = slice.page;
    setHashPage("p", page, VIEW);
    if (!ordered.length) sec.append(h("p", { class: "empty", text: "Nenhuma tarefa neste filtro." }));
    for (const r of slice.rows) sec.append(row(r, reload));
    const nav = pager({ page, total: ordered.length, size: SENT_PAGE, label: "tarefas que atribuí",
      onPage: (p) => { page = p; paint(); }, focus: () => sec.querySelector(".panel-head h2") });
    if (nav) sec.append(nav);
    if (focusId) {
      const el = sec.querySelector(`.list-row[data-id="${focusId}"]`);
      focusId = null;
      if (el) {
        el.classList.add("eq-focus");
        el.tabIndex = -1;
        requestAnimationFrame(() => { el.scrollIntoView({ block: "center" }); el.focus({ preventScroll: true }); });
      }
    }
  }

  // Veio de "Precisa de atenção": a devolvida em destaque na lista.
  function focusReturned(id) {
    filter = "returned";
    focusId = id;
    paint();
  }

  return { el: sec, load, focusReturned };
}

function row(r, reload) {
  const chips = [];
  let reason = null;
  let acts = null;
  if (r.status === "removed") {
    // Saiu da conta de quem recebeu: fica aqui com o que houve (60 dias).
    const quando = r.ended.at ? " em " + shortDate(localDay(r.ended.at)) : "";
    if (r.ended.kind === "returned") {
      chips.push(h("span", { class: "chip returned", text: `devolvida por ${r.to_name}${quando}` }));
      if (r.ended.reason) reason = h("p", { class: "sent-reason", text: `«${r.ended.reason}»` });
      const res = r.ended.resolved;
      if (res) chips.push(h("span", { class: "chip", text: res.kind === "closed" ? "encerrada" : `atribuída de novo a ${res.to}` }));
      else acts = h("div", { class: "request-actions" },
        h("button", { type: "button", class: "btn btn-tonal btn-sm", onClick: () => assignDialog({ fromReturn: r, onDone: reload }) }, icon("send"), "Atribuir de novo"),
        h("button", { type: "button", class: "btn btn-text btn-sm", text: "Encerrar", onClick: () => closeReturn(r, reload) }));
    } else {
      // Fato neutro (decisão de quem recebeu, ou sua): chip comum, sem o vermelho do atraso.
      chips.push(h("span", { class: "chip", text: r.ended.kind === "canceled" ? "cancelada por você" + quando : `excluída por ${r.to_name}${quando}` }));
    }
  } else {
    chips.push(h("span", { class: "chip " + r.status, text: r.status === "done" && r.completed_at
      ? "concluída em " + shortDate(localDay(r.completed_at)) : STATUS_LABELS[r.status] }));
    if (r.late) chips.push(h("span", { class: "chip late", text: "atrasada · " + shortDate(r.due_date) }));
    else if (r.due_date && r.status !== "done") chips.push(h("span", { class: "chip", text: "prazo " + shortDate(r.due_date) }));
    if (r.priority === 1 && r.status !== "done") chips.push(h("span", { class: "chip prio-1", text: "alta" }));
    if (r.status === "blocked" && r.blocked_reason) chips.push(h("span", { class: "chip blocked-reason", title: "Aguardando: " + r.blocked_reason, text: r.blocked_reason }));
    // Enquanto está "a fazer" e sem nada registrado, quem atribuiu ainda corrige ou cancela.
    if (r.editable) acts = h("div", { class: "request-actions" },
      h("button", { type: "button", class: "btn btn-text btn-sm", text: "Alterar", onClick: () => assignDialog({ edit: r, onDone: reload }) }),
      r.cancelable
        ? h("button", { type: "button", class: "btn btn-text btn-sm", text: "Cancelar", onClick: () => cancelSent(r, reload) })
        : h("small", { class: "muted", text: `${r.to_name} já mexeu nela: cancelar, só ela` }));
  }
  const dim = r.status === "removed" && !openReturn(r);
  return h("div", { class: "list-row" + (dim ? " is-removed" : ""), "data-id": r.id },
    h("div", { class: "t" }, h("span", { text: r.title }),
      h("small", { text: `para ${r.to_name} · ${r.assigned_at ? dateTime(r.assigned_at) : ""}` }),
      h("div", { class: "card-meta" }, ...chips), reason),
    acts);
}

async function cancelSent(r, done) {
  if (!(await confirmDialog({ title: "Cancelar esta tarefa?", text: `“${r.title}” sai das tarefas de ${r.to_name}, que recebe um e-mail avisando. A tarefa continua nesta lista, marcada como cancelada.`, confirm: "Cancelar tarefa", danger: true, dismiss: "Voltar" }))) return;
  try { await api.post(`/assign/${r.id}/cancel`); toast("Tarefa cancelada."); }
  catch (e) { errorToast(e, "Não foi possível cancelar."); }
  done();
}

async function closeReturn(r, done) {
  if (!(await confirmDialog({ title: "Encerrar a devolvida?", text: `“${r.title}” não vai para ninguém e sai de “Precisa de atenção”. Continua nesta lista, marcada como encerrada.`, confirm: "Encerrar", dismiss: "Voltar" }))) return;
  try { await api.post(`/assign/${r.id}/close`); toast("Encerrada."); }
  catch (e) { errorToast(e, "Não foi possível encerrar."); }
  done();
}
