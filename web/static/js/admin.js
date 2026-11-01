import { api } from "./api.js";
import { h, icon, clear, field, markInvalid } from "./dom.js";
import { codeBox, confirmDialog, errorToast, modal, navBadge, toast, busy, warnBox, popupMenu, sheet, refocusBy } from "./ui.js";
import { applyBranding } from "./branding.js";
import { avatar } from "./profile.js";

const ROLES = [
  ["user", "Usuário", "tem o próprio registro (Hoje, Tarefas, Rotinas) e pode receber tarefas"],
  ["admin", "Admin", "convites, contas, papéis e configurações gerais"],
  ["assigner", "Manda tarefas", "libera a tela Atribuir: manda tarefas para quem aceitou receber"],
  ["viewer", "Vê a equipe", "libera a tela Equipe: vê, sem editar, o registro (quadro, números, PDF, horas e fotos) de quem permitir (cada pessoa libera em Configurações > Conta)"],
];

const phone = () => matchMedia("(max-width: 860px)").matches;

// Menu "mais ações" de uma linha: no computador ao lado do botão; no celular, de baixo.
function rowMenu(btn, title, items) {
  if (phone()) { sheet(title, items); return; }
  const r = btn.getBoundingClientRect();
  popupMenu(r.left, r.bottom + 4, items);
}

// Busca por nome ou e-mail nas listas de contas (só aparece com lista longa).
function searchBox(rows) {
  const input = h("input", { type: "search", placeholder: "Buscar por nome ou e-mail", "aria-label": "Buscar conta por nome ou e-mail", autocomplete: "off" });
  const none = h("p", { class: "empty hidden", text: "Nenhuma conta com esse nome ou e-mail." });
  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    let shown = 0;
    for (const [el, text] of rows) { const ok = !q || text.includes(q); el.classList.toggle("hidden", !ok); shown += ok; }
    none.classList.toggle("hidden", shown > 0);
  });
  return rows.length > 6 ? [h("div", { class: "field admin-search" }, input), none] : [];
}
const userText = (u) => `${u.display_name || ""} ${u.email}`.toLowerCase();

const dateShort = (iso) => new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });

// Número de pedidos de convite abertos no item Admin do menu (também ao abrir o app).
export function setRequestsBadge(n) {
  navBadge("admin", n, n === 1 ? "1 pedido de convite" : `${n} pedidos de convite`);
}

// Admin: contas (convite, senha, bloquear, papéis no ⋮ de cada uma), configurações
// gerais e identidade visual. Ver registros e relatórios é do Visualizador (Equipe).
export async function mount(root, ctx) {
  clear(root);
  const seg = h("div", { class: "seg", role: "tablist", "aria-label": "Admin" });
  const body = h("div");
  const abas = [
    ["usuarios", "Contas", (el) => mountUsers(el, ctx.me)],
    ["geral", "Geral", (el) => mountGeneral(el, ctx.me)],
    ["identidade", "Identidade visual", (el) => mountBranding(el)],
  ];
  for (const [key, label, fn] of abas) {
    seg.append(h("button", {
      type: "button", class: "chip-btn", role: "tab", "aria-selected": key === "usuarios" ? "true" : "false", text: label,
      onClick: () => {
        for (const b of seg.children) b.setAttribute("aria-selected", b.textContent === label ? "true" : "false");
        fn(body);
      },
    }));
  }
  root.append(seg, body);
  await mountUsers(body, ctx.me);
}

const roleNames = (roles) => ROLES.filter(([k]) => roles.includes(k)).map(([, n]) => n).join(" · ") || "sem papel";

async function mountUsers(root, me) {
  clear(root);
  const users = await api.get("/admin/users");
  const emailById = new Map(users.map((u) => [String(u.id), u.email]));
  const inviteBtn = h("button", { type: "button", class: "btn btn-primary", onClick: onInvite }, icon("add"), "Convidar pessoa");
  const rows = users.map((u) => [userRow(u), userText(u)]);
  const list = h("section", { class: "panel admin-users" },
    h("div", { class: "panel-head" }, h("h2", { text: "Contas" }), h("div", { class: "spacer" }), inviteBtn),
    // Os papéis de cada conta mudam no ⋮ dela ("Papéis…"); aqui, o que cada um pode.
    h("details", { class: "roles-help" }, h("summary", { text: "O que cada papel pode" }),
      h("dl", { class: "roles-legend" }, ...ROLES.flatMap(([, n, d]) => [h("dt", { text: n }), h("dd", { text: d })]))),
    ...searchBox(rows), ...rows.map(([el]) => el));

  function userRow(u) {
    const self = u.id === me.id;
    const chips = [];
    if (u.invite_pending) chips.push(h("span", { class: "chip pending-chip " + (u.invite_expired ? "late" : "today"), text: u.invite_expired ? "convite vencido" : "convite pendente",
      title: u.invite_expired ? "O link de 7 dias venceu: reenvie o convite" : "Aguardando a pessoa criar a senha" }));
    if (u.blocked_at) chips.push(h("span", { class: "chip pending-chip late", text: "acesso bloqueado", title: "Para liberar, use Liberar acesso" }));
    if (self) chips.push(h("span", { class: "chip pending-chip", text: "você" }));
    // Quem ainda não aceitou o convite recebe outro link; os demais, senha temporária
    // (que também libera uma conta bloqueada). O resto fica no menu da linha.
    // No celular, a ação da linha vai para o ⋮ (o e-mail fica inteiro na linha).
    const [mainText, mainFn] = self ? [] : u.invite_pending ? ["Reenviar convite", () => onResend(u)]
      : [u.blocked_at ? "Liberar acesso" : "Redefinir senha", () => onReset(String(u.id), !!u.blocked_at)];
    const main = self ? null : h("button", { type: "button", class: "btn btn-text btn-sm only-desk", text: mainText,
      "aria-label": `${mainText} de ${u.email}`, onClick: mainFn });
    const items = [
      self ? null : u.invite_pending ? ["Cancelar convite", "close", () => onCancelInvite(u)] : u.blocked_at ? null : ["Bloquear acesso", "alert", () => onBlock(u)],
      ["Papéis…", "person", () => editRoles(u, me, () => mountUsers(root, me))],
      self || u.invite_pending ? null : ["Excluir conta", "trash", () => onDelete(u)],
    ];
    const more = h("button", { type: "button", class: "icon", title: "Mais ações", "aria-label": "Mais ações para " + u.email, "aria-haspopup": "menu",
      onClick: (ev) => rowMenu(ev.currentTarget, u.display_name || u.email, phone() && main ? [[mainText, "key", mainFn], ...items] : items) }, icon("more-v"));
    return h("div", { class: "list-row" }, avatar(u, "sm"),
      h("div", { class: "t" }, h("span", { text: u.display_name ? `${u.display_name} · ${u.email}` : u.email }),
        h("small", {}, roleNames(u.roles), ...chips)),
      main, more);
  }

  // Pedidos de convite que chegaram pela tela de login (só com e-mail configurado).
  // Os abertos primeiro; os já respondidos ficam recolhidos (saem sozinhos em 30 dias).
  const pedidos = await api.get("/admin/invite-requests").catch(() => []);
  const ORIGEM = { colega: "indicação de colega", site: "site da ShadowTec", github: "GitHub", outro: "outro" };
  const abertos = pedidos.filter((r) => r.status === "pending");
  const decididos = pedidos.filter((r) => r.status !== "pending");
  setRequestsBadge(abertos.length);
  const requestRow = (r) => h("div", { class: "request-row" + (r.status === "pending" ? "" : " decided") },
    h("div", { class: "t" },
      h("span", { class: "request-who" }, h("strong", { text: r.name }), " · ", r.email),
      h("small", { text: `${ORIGEM[r.source]}${r.source_note ? ` (${r.source_note})` : ""} · ${dateShort(r.created_at)}` }),
      h("p", { class: "request-reason", text: r.reason })),
    r.status === "pending"
      ? h("div", { class: "request-actions" },
          r.has_account ? h("span", { class: "chip", text: "já tem conta" }) : null,
          h("button", { type: "button", class: "btn btn-primary btn-sm", disabled: r.has_account ? "disabled" : null, onClick: busy(async () => {
            try { const res = await api.post(`/admin/invite-requests/${r.id}/invite`); await mountUsers(root, me); showInvite(res); }
            catch (e) { errorToast(e, "Não foi possível convidar."); }
          }) }, icon("send"), "Convidar"),
          h("button", { type: "button", class: "btn btn-text btn-sm", text: "Recusar", onClick: async () => {
            if (!(await confirmDialog({ title: `Recusar o pedido de ${r.name}?`, text: "Nenhum e-mail é enviado para quem pediu. O pedido fica na lista por 30 dias.", confirm: "Recusar" }))) return;
            try { await api.post(`/admin/invite-requests/${r.id}/decline`); await mountUsers(root, me); } catch (e) { errorToast(e); }
          } }))
      : h("span", { class: "chip " + (r.status === "invited" ? "done" : ""), text: r.status === "invited" ? "convidado" : "recusado" }));
  const requests = pedidos.length ? h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Pedidos de convite" }),
      abertos.length ? h("span", { class: "count", text: String(abertos.length) }) : null),
    ...(abertos.length ? abertos.map(requestRow) : [h("p", { class: "empty", text: "Nenhum pedido esperando resposta." })]),
    decididos.length ? h("details", { class: "requests-decided" },
      h("summary", { text: `Já respondidos (${decididos.length})` }), ...decididos.map(requestRow)) : null) : null;
  root.append(h("div", { class: "settings-grid" }, requests, list));

  // ---- Cancelar convite (ninguém entrou ainda: a conta não tem dados) ----
  async function onCancelInvite(u) {
    if (!(await confirmDialog({ title: "Cancelar o convite?", text: `O link mandado para ${u.email} deixa de valer e a conta sai da lista. Se precisar, convide de novo depois.`, confirm: "Cancelar convite", danger: true, dismiss: "Voltar" }))) return;
    try { await api.post(`/admin/users/${u.id}/cancel-invite`); toast(`Convite de ${u.email} cancelado.`); mountUsers(root, me); }
    catch (e) { errorToast(e, "Não foi possível cancelar o convite."); }
  }

  // ---- Bloquear acesso: corta agora, sem apagar nada; "Liberar acesso" (senha temporária) volta ----
  async function onBlock(u) {
    const ok = await confirmDialog({
      title: "Bloquear o acesso?",
      text: `${u.email} sai de todos os aparelhos agora e não entra mais: a senha vira uma que ninguém sabe, e as chaves de API, o link do calendário e a entrada com digital ou rosto (passkeys) param de funcionar. Tarefas, rotinas e histórico ficam guardados. Para liberar, use “Liberar acesso”: gera uma senha temporária para você repassar.`,
      confirm: "Bloquear", danger: true,
    });
    if (!ok) return;
    try { await api.post(`/admin/users/${u.id}/block`); toast(`Acesso de ${u.email} bloqueado. Os dados ficam.`); mountUsers(root, me); }
    catch (e) { errorToast(e, "Não foi possível bloquear."); }
  }

  // ---- Excluir conta (LGPD): apaga a conta e todos os dados dela; confirma com o e-mail ----
  function onDelete(u) {
    const input = h("input", { type: "email", autocomplete: "off", required: "required" });
    const err = h("p", { class: "error-text", role: "alert" });
    input.addEventListener("input", () => markInvalid([input], err, false));
    const form = h("form", {},
      h("p", { class: "help", text: `Exclui a conta ${u.email} e tudo o que está nela: tarefas, rotinas, tempo, anotações, chaves de API e histórico. Não dá para desfazer. Tarefas que essa pessoa atribuiu a outras continuam com quem recebeu. O e-mail e as contagens ficam registrados no seu histórico (180 dias).` }),
      h("p", { class: "help", text: "Só quer cortar o acesso agora (férias, celular perdido)? Use “Bloquear acesso” no menu da conta: a pessoa sai de todos os aparelhos e os dados ficam." }),
      field("Digite o e-mail da conta para confirmar", input), err,
      h("div", { class: "dialog-actions" },
        h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
        h("button", { type: "submit", class: "btn btn-danger", text: "Excluir para sempre" })));
    form.addEventListener("submit", busy(async (ev) => {
      ev.preventDefault();
      err.textContent = "";
      try {
        const res = await api.post(`/admin/users/${u.id}/delete`, { confirm_email: input.value.trim() });
        dlg.close();
        toast(`Conta ${res.email} excluída (${res.tasks} tarefas, ${res.routines} rotinas).`);
        mountUsers(root, me);
      } catch (e) { err.textContent = e.message || "Não foi possível excluir."; markInvalid([input], err); input.focus(); }
    }));
    const dlg = modal(h("h2", { text: "Excluir conta?" }), form);
    input.focus();
  }

  // ---- Redefinir senha (senha temporária, troca forçada no próximo login) ----
  // Numa conta bloqueada, é o "Liberar acesso".
  async function onReset(uid, blocked = false) {
    const email = emailById.get(uid) || "";
    const ok = await confirmDialog(blocked ? {
      title: "Liberar o acesso?",
      text: `Gera uma senha temporária para ${email} entrar de novo. Repasse à pessoa; no primeiro login, ela cria uma senha nova.`,
      confirm: "Liberar",
    } : {
      title: "Redefinir senha?",
      text: `Gera uma senha temporária para ${email}. As sessões, as chaves de API e o link de calendário da conta são revogados; no próximo login, a pessoa define uma senha nova.`,
      confirm: "Redefinir", danger: true,
    });
    if (!ok) return;
    try {
      const res = await api.post(`/admin/users/${uid}/reset-password`);
      showPassword(res.email, res.temp_password);
      if (blocked) mountUsers(root, me);
    } catch (e) {
      errorToast(e, "Não foi possível redefinir a senha.");
    }
  }

  async function onResend(u) {
    try { showInvite(await api.post(`/admin/users/${u.id}/invite`)); }
    catch (e) { errorToast(e, "Não foi possível reenviar."); }
  }

  // ---- Convidar pessoa (convite). Com e-mail no servidor: link por e-mail (a
  // pessoa cria a senha); sem: senha temporária, trocada no 1º login ----
  async function onInvite() {
    const byLink = await api.get("/auth/options").then((o) => o.email).catch(() => false);
    const input = h("input", { type: "email", required: "required", autocomplete: "off" });
    const err = h("p", { class: "error-text", role: "alert" });
    input.addEventListener("input", () => markInvalid([input], err, false));
    const submit = h("button", { type: "submit", class: "btn btn-primary", text: byLink ? "Enviar convite" : "Criar conta" });
    const form = h(
      "form",
      {},
      h("label", { class: "field" }, "E-mail do convidado", input),
      h("p", {
        class: "dialog-note",
        text: byLink
          ? "O convidado recebe por e-mail um link para criar a própria senha (vale 7 dias, uso único). Você também vê o link, para mandar por outro canal se precisar."
          : "A conta nasce com uma senha temporária, que o convidado troca no primeiro acesso. (Com e-mail configurado no servidor, o convite vai por link.)",
      }),
      err,
      h(
        "div",
        { class: "dialog-actions" },
        h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
        submit
      )
    );
    form.addEventListener("submit", busy(async (ev) => {
      ev.preventDefault();
      err.textContent = "";
      submit.disabled = true;
      try {
        const res = await api.post("/admin/users", { email: input.value.trim() });
        dlg.close();
        if (res.invite_url) showInvite(res); else showPassword(res.email, res.temp_password);
        mountUsers(root, me); // recarrega a lista com o novo usuário
      } catch (e) {
        err.textContent =
          e.status === 409 ? "Esse e-mail já tem conta." :
          e.status === 422 ? "E-mail inválido." :
          e.message || "Não foi possível criar a conta.";
        if (e.status === 409 || e.status === 422) markInvalid([input], err);
        submit.disabled = false;
        input.focus();
      }
    }));
    const dlg = modal(h("h2", { text: "Convidar pessoa" }), form);
    input.focus();
  }

  function showInvite(res) {
    const dlg = modal(
      h("h2", { text: res.emailed ? "Convite enviado" : "Convite criado" }),
      res.emailed
        ? h("p", {}, "Mandamos o convite para ", h("strong", { text: res.email }), ". Se não chegar, mande este link por outro canal:")
        : warnBox(`O e-mail para ${res.email} não saiu. Mande este link por outro canal (WhatsApp, chat):`),
      codeBox(res.invite_url),
      h("p", { class: "dialog-note", text: "Vale por 7 dias e funciona uma vez só. Reenviar gera um link novo e o anterior deixa de valer." }),
      h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-primary", text: "Pronto", onClick: () => dlg.close() })));
  }

  function showPassword(email, pw) {
    const dlg = modal(
      h("h2", { text: "Senha temporária" }),
      h("p", {}, "Usuário: ", h("strong", { text: email })),
      codeBox(pw),
      h("p", { class: "dialog-note", text: "Repasse agora — não será exibida novamente. A pessoa deverá trocá-la no próximo login." }),
      h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-primary", text: "Pronto", onClick: () => dlg.close() })));
  }
}


// ---- Papéis de uma conta (acumuláveis), pelo ⋮ da linha em Contas ----
// Marcou ou desmarcou, já vale; dar Admin e tirar Usuário pedem confirmação.
function editRoles(u, me, onChanged) {
  const who = u.display_name || u.email;
  let changed = false, saving = false;
  const boxes = ROLES.map(([k, n, d]) => {
    const cb = h("input", { type: "checkbox", value: k });
    cb.checked = u.roles.includes(k);
    if (k === "admin" && u.id === me.id) { cb.disabled = true; cb.title = "Você não pode tirar o seu próprio admin"; }
    cb.addEventListener("change", () => { if (saving) { cb.checked = !cb.checked; return; } save(cb); });
    return [cb, h("label", { class: "check-line role-line" }, cb, h("span", {}, h("strong", { text: n }), h("small", { text: d })))];
  });
  async function save(cb) {
    const roles = boxes.filter(([b]) => b.checked).map(([b]) => b.value);
    if (!roles.length) { cb.checked = true; toast("A conta precisa de pelo menos um papel.", { error: true }); return; }
    if (cb.value === "user" && !cb.checked && !(await confirmDialog({
      title: `Tirar o papel Usuário de ${who}?`,
      text: `${who} deixa de ver o próprio registro (Hoje, Tarefas, Rotinas) e de receber tarefas. Os dados ficam guardados e voltam se você marcar de novo.`,
      confirm: "Tirar", danger: true }))) { cb.checked = true; return; }
    if (cb.value === "admin" && cb.checked && !(await confirmDialog({
      title: `Dar Admin a ${who}?`,
      text: `${who} passa a convidar, bloquear e excluir contas, mudar papéis e as configurações gerais.`,
      confirm: "Dar Admin" }))) { cb.checked = false; return; }
    // Enquanto salva, as caixas não mudam, mas a marcada segue focada (desabilitar jogaria o foco no <body>).
    saving = true;
    for (const [b] of boxes) b.setAttribute("aria-disabled", "true");
    try {
      await api.put(`/admin/users/${u.id}/roles`, { roles });
      u.roles = roles;
      changed = true;
      paintConsent();
      toast(`Papéis de ${who} salvos.`);
    } catch (e) { cb.checked = !cb.checked; errorToast(e); }
    finally {
      saving = false;
      for (const [b] of boxes) b.removeAttribute("aria-disabled");
      if (!dlg.contains(document.activeElement)) cb.focus();  // voltou de uma confirmação
    }
  }
  // Visualizador só vê quem liberou: mostra aqui, para o admin não procurar a pessoa na Equipe.
  const consent = h("p", { class: "dialog-note" });
  const paintConsent = () => {
    consent.textContent = !u.roles.includes("user") ? "" : u.viewers_allowed
      ? "O registro desta conta está liberado a quem vê a equipe (cada pessoa decide em Configurações > Conta)."
      : "O registro desta conta não está liberado a quem vê a equipe (cada pessoa decide em Configurações > Conta).";
  };
  paintConsent();
  const dlg = modal(h("h2", { text: `Papéis de ${who}` }),
    h("p", { class: "dialog-note", text: "Qualquer combinação. Marcou ou desmarcou, já vale." }),
    h("div", { class: "role-lines" }, ...boxes.map(([, l]) => l)), consent,
    h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-text", text: "Fechar", onClick: () => dlg.close() })));
  // A linha da conta mostra os papéis novos; o foco volta ao ⋮ dela (a lista foi redesenhada).
  dlg.addEventListener("close", async () => {
    if (!changed) return;
    await onChanged();
    refocusBy(document.getElementById("main"), "Mais ações para " + u.email);
  });
}

// ---- Geral: limite de datas retroativas em tarefas ----
async function mountGeneral(root, me) {
  clear(root);
  const cfg = await api.get("/admin/settings");
  const days = h("input", { type: "number", min: "1", max: "366", value: String(cfg.retro_days), required: "required" });
  const contact = h("input", { type: "text", maxlength: "200", value: cfg.support_contact || "", placeholder: "ex.: suporte@empresa.com · ramal 2040" });
  const quota = h("input", { type: "number", min: "0", max: "100000", value: String(cfg.photo_quota_mb), required: "required" });
  const err = h("p", { class: "error-text", role: "alert" });
  for (const el of [days, contact, quota]) el.addEventListener("input", () => markInvalid([days, contact, quota], err, false));
  const form = h("form", {},
    field("Datas passadas em tarefas (dias)", days),
    h("p", { class: "dialog-note field-note", text: "Vale para criar ou concluir tarefas com data passada, pelo app, pela API e pela IA. As rotinas seguem com 7 dias." }),
    field("Contato de suporte (aparece em Ajuda)", contact),
    field("Espaço de fotos por pessoa (MB)", quota),
    h("p", { class: "dialog-note field-note", text: "Fotos das tarefas e das rotinas, já reduzidas no aparelho (em geral 200 a 400 KB cada). 0 = ninguém envia fotos novas." }),
    err, h("button", { type: "submit", class: "btn btn-primary", text: "Salvar" }));
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    try {
      const res = await api.put("/admin/settings", { retro_days: Number(days.value), support_contact: contact.value.trim() || null, photo_quota_mb: Number(quota.value) });
      me.retro_days = res.retro_days;
      me.support_contact = res.support_contact;
      toast("Configurações salvas.");
    } catch (e) {
      err.textContent = e.message || "Não foi possível salvar.";
      // O campo do erro, pelo que o servidor disse (senão, os dois números).
      const m = err.textContent.toLowerCase();
      const bad = /contato|suporte/.test(m) ? [contact] : /foto|mb|espaço/.test(m) ? [quota] : /dia|retro/.test(m) ? [days] : [days, quota];
      markInvalid(bad, err);
      bad[0].focus();
    }
  }));
  root.append(h("div", { class: "settings-grid" }, h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Geral" })), form)));
}


// ---- Identidade visual: logo + duas linhas do lockup (menu e login) ----
async function mountBranding(root) {
  clear(root);
  let brand = await api.get("/branding");

  const preview = h("div", { class: "lockup lockup--preview" },
    h("img", { class: "lockup-mark", alt: "", src: brand.logo || "/img/dragon-mark.svg" }),
    h("span", { class: "lockup-type" }, h("span", { text: brand.line1 }), h("span", { text: brand.line2 })));
  const l1 = h("input", { type: "text", maxlength: "24", value: brand.line1 });
  const l2 = h("input", { type: "text", maxlength: "24", value: brand.line2 });
  const sync = () => {
    preview.querySelectorAll(".lockup-type span")[0].textContent = l1.value || "—";
    preview.querySelectorAll(".lockup-type span")[1].textContent = l2.value;
  };
  l1.addEventListener("input", sync);
  l2.addEventListener("input", sync);

  const file = h("input", { type: "file", accept: "image/svg+xml,image/png,image/webp", "aria-label": "Logo da equipe (SVG, PNG ou WebP)" });
  const err = h("p", { class: "error-text", role: "alert" });

  const apply = (b) => {
    brand = b;
    preview.querySelector(".lockup-mark").src = b.logo || "/img/dragon-mark.svg";
    applyBranding(b); // atualiza o menu na hora
  };

  const saveText = h("button", { type: "button", class: "btn btn-primary", text: "Salvar textos", onClick: async () => {
    err.textContent = "";
    try {
      apply(await api.put("/admin/branding", { line1: l1.value.trim(), line2: l2.value.trim() }));
      toast("Textos salvos.");
    } catch (e) { err.textContent = e.message || "Não foi possível salvar."; }
  } });

  const upload = h("button", { type: "button", class: "btn btn-ghost", onClick: async () => {
    err.textContent = "";
    const f = file.files && file.files[0];
    if (!f) { err.textContent = "Escolha um arquivo SVG, PNG ou WebP."; return; }
    if (f.size > 256 * 1024) { err.textContent = "O arquivo passa de 256 KB."; return; }
    try {
      apply(await api.upload("/admin/branding/logo", f));
      file.value = "";
      toast("Logo atualizado.");
    } catch (e) { err.textContent = e.message || "Não foi possível enviar."; }
  } }, icon("add"), "Enviar logo");

  const reset = h("button", { type: "button", class: "btn btn-text", text: "Restaurar dragão padrão", onClick: async () => {
    try { apply(await api.del("/admin/branding/logo")); toast("Logo padrão restaurado."); }
    catch (e) { errorToast(e); }
  } });

  root.append(
    h("div", { class: "settings-grid" },
      h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", { text: "Prévia" })),
        h("div", { class: "brand-preview" }, preview),
        h("p", { class: "help", text: "Aparece no menu lateral, no login e na troca de senha. O logo fica com a altura das duas linhas de texto." })),
      h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", { text: "Textos" })),
        h("div", { class: "field-row" },
          field("Linha 1 (destaque)", l1),
          field("Linha 2 (opcional)", l2)),
        saveText),
      h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", { text: "Logo" })),
        h("p", { class: "help", text: "SVG, PNG ou WebP, até 256 KB. Prefira SVG ou PNG com fundo transparente. SVG com script, eventos ou links externos é recusado." }),
        h("div", { class: "field" }, file),
        err,
        h("div", { class: "dialog-actions" }, reset, h("div", { class: "spacer" }), upload))));
}
