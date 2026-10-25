// Vencimentos: certificados, licenças, domínios, garantias. Cadastro em
// Configurações > Vencimentos; no Hoje aparecem só os que estão no aviso.
import { api } from "./api.js";
import { h, icon, clear, field, shortDate, addDays } from "./dom.js";

// Mesma data N meses depois (31/01 + 1 mês = 28/02 ou 29/02).
function addMonths(iso, n) {
  const [y, m, d] = iso.split("-").map(Number);
  const last = new Date(Date.UTC(y, m - 1 + n + 1, 0)).getUTCDate();
  const t = new Date(Date.UTC(y, m - 1 + n, Math.min(d, last)));
  return t.toISOString().slice(0, 10);
}
import { busy, confirmDialog, errorToast, modal, toast, undoLatest } from "./ui.js";
import { fillProjectSelect } from "./projects.js";

function when(r) {
  if (r.days_left < 0) return { text: `venceu há ${-r.days_left} d`, cls: "late" };
  if (r.days_left === 0) return { text: "vence hoje", cls: "late" };
  return { text: `vence em ${r.days_left} d · ${shortDate(r.expires_on)}`, cls: r.warning ? "today" : "" };
}

function row(r, onChange, compact = false) {
  const w = when(r);
  return h("div", { class: "list-row" },
    h("div", { class: "t" }, h("span", { text: r.label }),
      !compact && (r.note || r.project_name) ? h("small", { text: [r.project_name, r.note].filter(Boolean).join(" · ") }) : null),
    h("span", { class: "chip " + w.cls, text: w.text }),
    h("button", { type: "button", class: "btn btn-ghost btn-sm", title: "Criar a tarefa de renovação (prazo = vencimento)", onClick: async () => {
      try {
        await api.post("/worklog", { title: `Renovar: ${r.label}`.slice(0, 200), due_date: r.expires_on, project_id: r.project_id || null });
        toast("Tarefa de renovação criada em Tarefas.");
      } catch (e) { errorToast(e); }
    } }, "Virar tarefa"),
    h("button", { type: "button", class: "btn btn-ghost btn-sm", title: "Informar a nova data de vencimento", onClick: () => openRenewal(r, onChange, true) }, "Renovei"),
    compact ? null : h("button", { type: "button", class: "icon", title: "Editar", "aria-label": "Editar " + r.label, onClick: () => openRenewal(r, onChange) }, icon("edit")),
    compact ? null : h("button", { type: "button", class: "icon", title: "Excluir", "aria-label": "Excluir " + r.label, onClick: async () => {
      if (!(await confirmDialog({ title: "Excluir vencimento?", text: `“${r.label}” sai da lista. Dá para desfazer pelo histórico.`, confirm: "Excluir", danger: true }))) return;
      try {
        await api.del(`/renewals/${r.id}`);
        onChange();
        toast("Vencimento excluído.", { action: "Desfazer", onAction: () => undoLatest("renewal", r.id, onChange) });
      } catch (e) { errorToast(e); }
    } }, icon("trash")));
}

// Cadastro e edição; renew = só a nova data ("Renovei").
export function openRenewal(r, onChange, renew = false) {
  const label = h("input", { type: "text", maxlength: "120", required: "required", value: r ? r.label : "", placeholder: "ex.: Certificado *.empresa.com.br" });
  const expires = h("input", { type: "date", required: "required", value: r && !renew ? r.expires_on : "" });
  if (renew) {
    expires.min = addDays(r.expires_on, 1); // renovar é empurrar a data pra frente (ano digitado errado é comum)
    if (r.renew_months) expires.value = addMonths(r.expires_on, r.renew_months); // periódico: já sugere a próxima
  }
  const months = h("input", { type: "number", min: "1", max: "120", value: r && r.renew_months ? String(r.renew_months) : "", placeholder: "ex.: 12" });
  const warn = h("input", { type: "number", min: "1", max: "365", value: String(r ? r.warn_days : 30) });
  const note = h("input", { type: "text", maxlength: "200", value: r && r.note ? r.note : "", placeholder: "onde renovar, contrato, fornecedor (opcional)" });
  const proj = h("select", {});
  fillProjectSelect(proj, r ? r.project_id : null).catch(() => {});
  const err = h("p", { class: "error-text" });
  const fields = renew
    ? [h("p", { class: "dialog-note", text: `${r.label}: qual a nova data de vencimento? A anterior era ${shortDate(r.expires_on)}.` }), field("Vence em", expires)]
    : [field("O que vence", label), h("div", { class: "field-row" }, field("Vence em", expires), field("Avisar com quantos dias", warn)),
      h("div", { class: "field-row" }, field("Projeto / cliente", proj), field("Repete a cada (meses, opcional)", months)),
      field("Observação", note)];
  const form = h("form", {}, h("h2", { text: renew ? "Renovado" : r ? "Editar vencimento" : "Novo vencimento" }), ...fields, err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
      h("button", { type: "submit", class: "btn btn-primary", text: "Salvar" })));
  form.addEventListener("submit", busy(async () => {
    err.textContent = "";
    if (renew && expires.value <= r.expires_on) { err.textContent = `A nova data deve ser depois de ${shortDate(r.expires_on)}.`; return; }
    const body = renew ? { expires_on: expires.value } : {
      label: label.value.trim(), expires_on: expires.value, warn_days: Number(warn.value) || 30,
      project_id: proj.value && proj.value !== "__new" ? Number(proj.value) : null, note: note.value.trim() || null,
      renew_months: Number(months.value) || null,
    };
    try {
      if (r) await api.patch(`/renewals/${r.id}`, body); else await api.post("/renewals", body);
      dlg.close();
      toast(renew ? "Nova data salva." : "Vencimento salvo.");
      onChange();
    } catch (e) { err.textContent = e.message || "Não foi possível salvar."; }
  }));
  const dlg = modal(form);
  (renew ? expires : label).focus();
}

// Configurações > Vencimentos: lista completa e cadastro.
export async function renewalsPanel(rerender) {
  const list = await api.get("/renewals");
  const sec = h("section", { class: "panel" },
    h("div", { class: "panel-head" }, icon("calendar"), h("h2", { text: "Vencimentos" }), h("div", { class: "spacer" }),
      h("button", { type: "button", class: "btn btn-primary btn-sm", onClick: () => openRenewal(null, rerender) }, icon("add"), "Novo")),
    h("p", { class: "help", text: "Certificados, licenças, domínios, garantias e contratos. Avisam no Hoje, no e-mail da manhã e no calendário a partir dos dias de antecedência de cada um. O Nexus não consulta nada de fora: vale a data informada aqui." }));
  if (!list.length) sec.append(h("p", { class: "empty", text: "Nenhum vencimento cadastrado ainda." }));
  for (const r of list) sec.append(row(r, rerender));
  return sec;
}

// Hoje: só os que já estão no aviso (ou vencidos). Nada no aviso = nada na tela.
export async function todayRenewals(refresh) {
  let list;
  try { list = (await api.get("/renewals")).filter((r) => r.warning); }
  catch {
    // Silêncio aqui pareceria "nada vencendo" — perigoso para certificado e domínio.
    return h("section", { class: "panel t-venc" }, h("p", { class: "empty" }, "Vencimentos: não foi possível carregar. ",
      h("button", { type: "button", class: "btn btn-text btn-sm", text: "Tentar de novo", onClick: refresh })));
  }
  if (!list.length) return null;
  const sec = h("section", { class: "panel t-venc" },
    h("div", { class: "panel-head" }, icon("calendar"), h("h2", { text: "Vencimentos" }),
      h("span", { class: "count warn", text: String(list.length) })));
  for (const r of list) sec.append(row(r, refresh, true));
  return sec;
}
