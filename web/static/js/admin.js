import { api } from "./api.js";
import { h, icon, clear, field, markInvalid, localDay, dateTime, addDays } from "./dom.js";
import { codeBox, confirmDialog, errorToast, modal, navBadge, toast, busy, warnBox, popupMenu, sheet, refocusBy,
  pager, pageSlice, hashPage, setHashPage } from "./ui.js";
import { applyBranding } from "./branding.js";
import { avatar } from "./profile.js";
import { healthPanel } from "./saude.js";

const ROLES = [
  ["user", "Usuário", "tem o próprio registro (Hoje, Tarefas, Rotinas) e pode receber tarefas"],
  ["admin", "Admin", "convites, contas, papéis e configurações gerais"],
  ["assigner", "Manda tarefas", "libera Atribuir na tela Equipe: manda tarefas para quem aceitou receber"],
  ["viewer", "Vê a equipe", "libera a tela Equipe: vê, sem editar, o registro (quadro, números, PDF, horas e fotos) de quem permitir (cada pessoa libera em Configurações > Conta)"],
];

// "Vê a equipe" com a instância em "Visível para quem gerencia": vê todos (sem aceite).
// "Manda tarefas" com "Todos recebem de quem atribui": manda para todos (sem aceite).
const roleDesc = (k, d, me) => k === "viewer" && me && me.org && me.org.team_visibility === "managers"
  ? "libera a tela Equipe: vê, sem editar, o registro (quadro, números, PDF, horas e fotos) de todos — nesta instância, visível para quem gerencia (Admin › Para empresas)"
  : k === "assigner" && me && me.org && me.org.assign_receive === "all"
  ? "libera Atribuir na tela Equipe: manda tarefas para todos com o papel Usuário — nesta instância, todos recebem de quem atribui (Admin › Para empresas)"
  : d;

const phone = () => matchMedia("(max-width: 860px)").matches;

// Menu "mais ações" de uma linha: no computador ao lado do botão; no celular, de baixo.
function rowMenu(btn, title, items) {
  if (phone()) { sheet(title, items); return; }
  const r = btn.getBoundingClientRect();
  popupMenu(r.left, r.bottom + 4, items, r.top);
}

const userText = (u) => `${u.display_name || ""} ${u.email}`.toLowerCase();

const dateShort = (iso) => new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
const dmy = (ts) => { const [y, m, d] = localDay(ts).split("-"); return `${d}/${m}/${y}`; };
// "hoje, 14:20", "ontem, 09:05" ou a data (no fuso da app).
function seenText(ts) {
  const day = localDay(ts), today = localDay(Date.now());
  const hm = dateTime(ts).split(" ").pop();
  return day === today ? `hoje, ${hm}` : day === addDays(today, -1) ? `ontem, ${hm}` : dmy(ts);
}
// Criação e último acesso de uma conta (convite pendente: a data do convite).
const accessLine = (u) => u.invite_pending ? `Convidada em ${dmy(u.created_at)}`
  : `Criada em ${dmy(u.created_at)} · ` + (u.last_seen_at ? `último acesso ${seenText(u.last_seen_at)}` : "nunca entrou");

// Situação das contas (os chips acima da lista; o número já é o resumo).
const STATUS = [
  ["all", "Todas as situações", () => true],
  ["active", "Ativas", (u) => !u.invite_pending && !u.blocked_at],
  ["pending", "Convite pendente", (u) => u.invite_pending],
  ["blocked", "Bloqueadas", (u) => !!u.blocked_at],
];
const PAGE = 20;
// Filtros da lista de contas: ficam enquanto o app está aberto (redesenhar depois de uma ação não os perde).
const usersFilter = { q: "", role: "", status: "all" };

// Origem dos pedidos de convite ("site" e "github" só nos pedidos antigos).
const ORIGEM = { colega: "indicação de colega", empresa: "pela empresa ou equipe", internet: "internet ou redes sociais",
  outro: "outro", site: "site", github: "GitHub" };

// Bloquear ou excluir quem tem tarefas abertas: passar para outra pessoa
// (papel Usuário, acesso liberado e que já entrou: a regra do servidor) ou deixar. value(): id, null (deixar) ou
// undefined (escolheu passar, mas sem pessoa).
function transferPicker(u, users, keep) {
  if (!u.open_tasks) return null;
  const n = u.open_tasks;
  const others = users.filter((x) => x.id !== u.id && x.roles.includes("user") && !x.blocked_at && !x.invite_pending);
  const pass = h("input", { type: "radio", name: "transfer", value: "pass" });
  const stay = h("input", { type: "radio", name: "transfer", value: "keep" });
  const sel = h("select", { "aria-label": "Quem recebe as tarefas" }, h("option", { value: "", text: "Escolha a pessoa…" }),
    ...others.map((x) => h("option", { value: String(x.id), text: x.display_name ? `${x.display_name} · ${x.email}` : x.email })));
  pass.checked = others.length > 0;
  stay.checked = !pass.checked;
  if (!others.length) { pass.disabled = true; sel.disabled = true; }
  sel.addEventListener("change", () => { if (sel.value) { pass.checked = true; markInvalid([sel], null, false); } });
  stay.addEventListener("change", () => markInvalid([sel], null, false));
  const el = h("fieldset", { class: "transfer-tasks" },
    h("legend", { text: n === 1 ? "1 tarefa aberta" : `${n} tarefas abertas` }),
    h("label", { class: "check-line role-line" }, pass, h("span", {}, h("strong", { text: "Passar para outra pessoa" }),
      h("small", { text: "Vão com as anotações, o checklist e as fotos; quem recebe é avisado e fica no histórico. O tempo já registrado continua nesta conta." }))),
    h("div", { class: "field transfer-who" }, sel),
    h("label", { class: "check-line role-line" }, stay, h("span", {}, h("strong", { text: keep[0] }), h("small", { text: keep[1] }))),
    others.length ? null : h("p", { class: "dialog-note", text: "Nenhuma outra conta com o papel Usuário, acesso liberado e que já entrou no Nexus pode receber." }));
  return { el, sel, value: () => stay.checked ? null : sel.value ? Number(sel.value) : undefined };
}

const movedText = (t) => t && t.count ? ` ${t.count === 1 ? "1 tarefa passou" : `${t.count} tarefas passaram`} para ${t.to}.` : "";

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
    ["empresas", "Para empresas", (el) => mountOrg(el, ctx.me)],
    ["identidade", "Identidade visual", (el) => mountBranding(el)],
  ];
  // #/admin?aba=empresas abre direto na aba (link da Conta e do detalhe da tarefa).
  const pedida = (location.hash.match(/[?&]aba=(\w+)/) || [])[1];
  const first = abas.find(([k]) => k === pedida) || abas[0];
  for (const [key, label, fn] of abas) {
    seg.append(h("button", {
      type: "button", class: "chip-btn", role: "tab", "aria-selected": key === first[0] ? "true" : "false", text: label,
      onClick: () => {
        for (const b of seg.children) b.setAttribute("aria-selected", b.textContent === label ? "true" : "false");
        fn(body);
      },
    }));
  }
  root.append(seg, body);
  await first[2](body);
}

const roleNames = (roles) => ROLES.filter(([k]) => roles.includes(k)).map(([, n]) => n).join(" · ") || "sem papel";

async function mountUsers(root, me) {
  clear(root);
  const [users, pedidos] = await Promise.all([api.get("/admin/users"), api.get("/admin/invite-requests").catch(() => [])]);
  const emailById = new Map(users.map((u) => [String(u.id), u.email]));
  const inviteBtn = h("button", { type: "button", class: "btn btn-primary", onClick: onInvite }, icon("add"), "Convidar pessoa");
  const st = usersFilter;
  let page = hashPage("pc");
  const title = h("h2", { text: "Contas" });
  const box = h("div", { class: "admin-users-list" });
  // Busca, papel e situação: só com lista longa (com poucas contas, é ruído).
  const many = users.length > 6;
  const search = h("input", { type: "search", placeholder: "Buscar por nome ou e-mail", "aria-label": "Buscar conta por nome ou e-mail", autocomplete: "off", value: st.q });
  search.addEventListener("input", () => { st.q = search.value.trim().toLowerCase(); page = 1; paint(); });
  const roleSel = h("select", { "aria-label": "Filtrar por papel" }, h("option", { value: "", text: "Todos os papéis" }),
    ...ROLES.map(([k, n]) => h("option", { value: k, text: n })));
  roleSel.value = st.role;
  roleSel.addEventListener("change", () => { st.role = roleSel.value; page = 1; paint(); });
  if (!STATUS.some(([k, , test]) => k === st.status && (k === "all" || users.some(test)))) st.status = "all";
  // Situação num seletor, ao lado do papel: a faixa de filtros fica numa linha só.
  const statusSel = h("select", { "aria-label": "Filtrar por situação" },
    ...STATUS.filter(([k, , test]) => k === "all" || users.some(test)).map(([k, label, test]) =>
      h("option", { value: k, text: `${label} (${users.filter(test).length})` })));
  statusSel.value = st.status;
  statusSel.addEventListener("change", () => { st.status = statusSel.value; page = 1; paint(); });
  const list = h("section", { class: "panel admin-users" },
    h("div", { class: "panel-head" }, title, h("div", { class: "spacer" }), inviteBtn),
    // Os papéis de cada conta mudam no ⋮ dela ("Papéis…"); aqui, o que cada um pode.
    h("details", { class: "roles-help" }, h("summary", { text: "O que cada papel pode" }),
      h("dl", { class: "roles-legend" }, ...ROLES.flatMap(([k, n, d]) => [h("dt", { text: n }), h("dd", { text: roleDesc(k, d, me) })]))),
    many ? h("div", { class: "admin-filters" }, h("div", { class: "field admin-search" }, search),
      h("div", { class: "field admin-role" }, roleSel), h("div", { class: "field admin-role" }, statusSel)) : null,
    box);

  function paint() {
    clear(box);
    const test = STATUS.find(([k]) => k === st.status)[2];
    const f = many ? st : { q: "", role: "" };
    const shown = users.filter((u) => (!many || test(u)) && (!f.role || u.roles.includes(f.role)) && (!f.q || userText(u).includes(f.q)));
    if (!shown.length) box.append(h("p", { class: "empty", text: "Nenhuma conta com esses filtros." }));
    const sl = pageSlice(shown, page, PAGE);
    page = sl.page;
    setHashPage("pc", page, "admin");
    for (const u of sl.rows) box.append(userRow(u));
    const nav = pager({ page, total: shown.length, size: PAGE, label: "contas", onPage: (n) => { page = n; paint(); }, focus: () => title });
    if (nav) box.append(nav);
  }

  function userRow(u) {
    const self = u.id === me.id;
    const chips = [];
    if (u.invite_pending) chips.push(h("span", { class: "chip pending-chip " + (u.invite_expired ? "late" : "today"), text: u.invite_expired ? "convite vencido" : "convite pendente",
      title: u.invite_expired ? "O link de 7 dias venceu: reenvie o convite" : "Aguardando a pessoa criar a senha" }));
    if (u.blocked_at) chips.push(h("span", { class: "chip pending-chip late", text: "acesso bloqueado", title: `Bloqueada em ${dmy(u.blocked_at)}. Para liberar, use Liberar acesso` }));
    if (self) chips.push(h("span", { class: "chip pending-chip", text: "você" }));
    // Quem ainda não aceitou o convite recebe outro link; os demais, nova senha
    // (que também libera uma conta bloqueada). O resto fica no menu da linha.
    // No celular, a ação da linha vai para o ⋮ (o e-mail fica inteiro na linha).
    const [mainText, mainFn] = self ? [] : u.invite_pending ? ["Reenviar convite", () => onResend(u)]
      : [u.blocked_at ? "Liberar acesso" : "Redefinir senha", () => onReset(String(u.id), !!u.blocked_at)];
    const main = self ? null : h("button", { type: "button", class: "btn btn-text btn-sm only-desk", text: mainText,
      "aria-label": `${mainText} de ${u.email}`, onClick: mainFn });
    const items = [
      self ? null : u.invite_pending ? ["Cancelar convite", "close", () => onCancelInvite(u)] : u.blocked_at ? null : ["Bloquear acesso", "alert", () => onBlock(u)],
      ["Papéis…", "person", () => editRoles(u, me, () => mountUsers(root, me))],
      ["Editar nome e e-mail", "edit", () => editProfile(u, me, () => mountUsers(root, me))],
      self || u.invite_pending ? null : ["Excluir conta", "trash", () => onDelete(u)],
    ];
    const more = h("button", { type: "button", class: "icon", title: "Mais ações", "aria-label": "Mais ações para " + u.email, "aria-haspopup": "menu",
      onClick: (ev) => rowMenu(ev.currentTarget, u.display_name || u.email, phone() && main ? [[mainText, "key", mainFn], ...items] : items) }, icon("more-v"));
    return h("div", { class: "list-row" }, avatar(u, "sm"),
      h("div", { class: "t" }, u.display_name ? h("span", { class: "dot-list" }, h("span", { text: u.display_name }), h("span", { text: u.email })) : h("span", { text: u.email }),
        h("small", {}, roleNames(u.roles), ...chips),
        h("small", { class: "account-seen", text: accessLine(u) })),
      main, more);
  }

  // Pedidos de convite que chegaram pela tela de login (só com e-mail configurado).
  // Os abertos primeiro, em páginas; os já respondidos ficam recolhidos (saem sozinhos em 30 dias).
  const abertos = pedidos.filter((r) => r.status === "pending");
  const decididos = pedidos.filter((r) => r.status !== "pending");
  setRequestsBadge(abertos.length);
  const requestRow = (r) => h("div", { class: "request-row" + (r.status === "pending" ? "" : " decided") },
    h("div", { class: "t" },
      h("span", { class: "request-who" }, h("strong", { text: r.name }), " · ", r.email),
      h("small", { text: `${ORIGEM[r.source] || r.source}${r.source_note ? ` (${r.source_note})` : ""} · ${dateShort(r.created_at)}` }),
      h("p", { class: "request-reason", text: r.reason })),
    r.status === "pending"
      ? h("div", { class: "request-actions" },
          r.has_account ? h("span", { class: "chip", text: "já tem conta" }) : null,
          h("button", { type: "button", class: "btn btn-primary btn-sm", disabled: r.has_account ? "disabled" : null,
            "aria-label": `Convidar ${r.name}`, onClick: () => onInvite(r) }, icon("send"), "Convidar"),
          h("button", { type: "button", class: "btn btn-text btn-sm", text: "Recusar", "aria-label": `Recusar o pedido de ${r.name}`, onClick: async () => {
            if (!(await confirmDialog({ title: `Recusar o pedido de ${r.name}?`, text: "Nenhum e-mail é enviado para quem pediu. O pedido fica na lista por 30 dias.", confirm: "Recusar" }))) return;
            try { await api.post(`/admin/invite-requests/${r.id}/decline`); await mountUsers(root, me); } catch (e) { errorToast(e); }
          } }))
      : h("span", { class: "chip " + (r.status === "invited" ? "done" : ""), text: r.status === "invited" ? "convidado" : "recusado" }));
  // Uma lista em páginas (20 por página) dentro de `box`; foco no título ao trocar.
  const pagedList = (rows, box, key, label, head, compact) => {
    let pg = key ? hashPage(key) : 1;
    const draw = () => {
      clear(box);
      const sl = pageSlice(rows, pg, PAGE);
      pg = sl.page;
      if (key) setHashPage(key, pg, "admin");
      for (const r of sl.rows) box.append(requestRow(r));
      const nav = pager({ page: pg, total: rows.length, size: PAGE, label, compact, onPage: (n) => { pg = n; draw(); }, focus: head });
      if (nav) box.append(nav);
    };
    draw();
    return box;
  };
  const reqTitle = h("h2", { text: "Pedidos de convite" });
  const decSummary = h("summary", { text: `Já respondidos (${decididos.length})` });
  const requests = pedidos.length ? h("section", { class: "panel" },
    h("div", { class: "panel-head" }, reqTitle,
      abertos.length ? h("span", { class: "count", text: String(abertos.length) }) : null),
    abertos.length ? pagedList(abertos, h("div"), "pp", "pedidos de convite", () => reqTitle, false)
      : h("p", { class: "empty", text: "Nenhum pedido esperando resposta." }),
    decididos.length ? h("details", { class: "requests-decided" }, decSummary,
      pagedList(decididos, h("div"), null, "pedidos já respondidos", () => decSummary, true)) : null) : null;
  root.append(h("div", { class: "settings-grid" }, requests, list));
  paint();

  // ---- Cancelar convite (ninguém entrou ainda: a conta não tem dados) ----
  async function onCancelInvite(u) {
    if (!(await confirmDialog({ title: "Cancelar o convite?", text: `O link mandado para ${u.email} deixa de valer e a conta sai da lista. Se precisar, convide de novo depois.`, confirm: "Cancelar convite", danger: true, dismiss: "Voltar" }))) return;
    try { await api.post(`/admin/users/${u.id}/cancel-invite`); toast(`Convite de ${u.email} cancelado.`); mountUsers(root, me); }
    catch (e) { errorToast(e, "Não foi possível cancelar o convite."); }
  }

  // ---- Bloquear acesso: corta agora, sem apagar nada; "Liberar acesso" volta.
  // Com tarefas abertas, oferece passá-las para outra pessoa. ----
  function onBlock(u) {
    const tp = transferPicker(u, users, ["Deixar nesta conta", "Ficam guardadas e voltam se você liberar o acesso."]);
    const err = h("p", { class: "error-text", role: "alert" });
    const form = h("form", {},
      h("p", { text: `${u.email} sai de todos os aparelhos agora e não entra mais: a senha vira uma que ninguém sabe, e as chaves de API, o link do calendário e a entrada com digital ou rosto (passkeys) param de funcionar. Tarefas, rotinas e histórico ficam guardados. Para liberar, use “Liberar acesso”.` }),
      tp ? tp.el : null, err,
      h("div", { class: "dialog-actions" },
        h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
        h("button", { type: "submit", class: "btn btn-danger", text: "Bloquear" })));
    form.addEventListener("submit", busy(async (ev) => {
      ev.preventDefault();
      err.textContent = "";
      const to = tp ? tp.value() : null;
      if (to === undefined) { err.textContent = "Escolha quem recebe as tarefas (ou deixe nesta conta)."; markInvalid([tp.sel], err); tp.sel.focus(); return; }
      try {
        const res = await api.post(`/admin/users/${u.id}/block`, to ? { transfer_to: to } : {});
        dlg.close();
        toast(`Acesso de ${u.email} bloqueado.${movedText(res.transferred) || " Os dados ficam."}`);
        mountUsers(root, me);
      } catch (e) { err.textContent = e.message || "Não foi possível bloquear."; }
    }));
    const dlg = modal(h("h2", { text: "Bloquear o acesso?" }), form);
    (tp ? tp.sel : form.querySelector(".btn-text")).focus();
  }

  // ---- Excluir conta (LGPD): apaga a conta e todos os dados dela; confirma com o e-mail ----
  function onDelete(u) {
    const tp = transferPicker(u, users, ["Excluir junto com a conta", "As tarefas abertas saem com o resto dos dados."]);
    const input = h("input", { type: "email", autocomplete: "off", required: "required" });
    const err = h("p", { class: "error-text", role: "alert" });
    input.addEventListener("input", () => markInvalid([input], err, false));
    const form = h("form", {},
      h("p", { class: "help", text: `Exclui a conta ${u.email} e tudo o que está nela: tarefas, rotinas, tempo, anotações, chaves de API e histórico. Não dá para desfazer. Tarefas que essa pessoa atribuiu a outras continuam com quem recebeu. O e-mail e as contagens ficam registrados no seu histórico (180 dias).` }),
      h("p", { class: "help", text: "Só quer cortar o acesso agora (férias, celular perdido)? Use “Bloquear acesso” no menu da conta: a pessoa sai de todos os aparelhos e os dados ficam." }),
      tp ? tp.el : null,
      field("Digite o e-mail da conta para confirmar", input), err,
      h("div", { class: "dialog-actions" },
        h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
        h("button", { type: "submit", class: "btn btn-danger", text: "Excluir para sempre" })));
    form.addEventListener("submit", busy(async (ev) => {
      ev.preventDefault();
      err.textContent = "";
      const to = tp ? tp.value() : null;
      if (to === undefined) { err.textContent = "Escolha quem recebe as tarefas (ou exclua junto)."; markInvalid([tp.sel], err); tp.sel.focus(); return; }
      try {
        const res = await api.post(`/admin/users/${u.id}/delete`, { confirm_email: input.value.trim(), ...(to ? { transfer_to: to } : {}) });
        dlg.close();
        toast(`Conta ${res.email} excluída (${res.tasks} tarefas, ${res.routines} rotinas).${movedText(res.transferred)}`);
        mountUsers(root, me);
      } catch (e) { err.textContent = e.message || "Não foi possível excluir."; markInvalid([input], err); input.focus(); }
    }));
    const dlg = modal(h("h2", { text: "Excluir conta?" }), form);
    (tp ? tp.sel : input).focus();
  }

  // ---- Redefinir senha / Liberar acesso. Com e-mail no servidor, o padrão é
  // mandar o link de nova senha (ninguém repassa senha); a senha temporária
  // continua como alternativa. Sem e-mail, só a senha temporária. ----
  async function onReset(uid, blocked = false) {
    const email = emailById.get(uid) || "";
    const byMail = await api.get("/auth/options").then((o) => o.email).catch(() => false);
    const method = byMail ? await chooseReset(email, blocked) : (await confirmDialog(blocked ? {
      title: "Liberar o acesso?",
      text: `Gera uma senha temporária para ${email} entrar de novo. Repasse à pessoa; no primeiro login, ela cria uma senha nova.`,
      confirm: "Liberar",
    } : {
      title: "Redefinir senha?",
      text: `Gera uma senha temporária para ${email}. As sessões, as chaves de API e o link de calendário da conta são revogados; no próximo login, a pessoa define uma senha nova.`,
      confirm: "Redefinir", danger: true,
    })) && "temp";
    if (!method) return;
    try {
      const res = await api.post(`/admin/users/${uid}/reset-password`, { method });
      if (res.reset_url) showResetLink(res); else showPassword(res.email, res.temp_password);
      if (blocked) mountUsers(root, me);
    } catch (e) {
      errorToast(e, "Não foi possível redefinir a senha.");
    }
  }

  function chooseReset(email, blocked) {
    return new Promise((resolve) => {
      let pick = null;
      const link = h("button", { type: "button", class: "btn btn-primary", onClick: () => { pick = "link"; dlg.close(); } }, icon("send"), "Mandar link por e-mail");
      const dlg = modal(
        h("h2", { text: blocked ? "Liberar o acesso?" : "Redefinir senha?" }),
        h("p", { text: blocked
          ? `${email} volta a entrar criando uma senha nova.`
          : `A senha atual de ${email} deixa de valer agora, e as sessões, as chaves de API e o link de calendário da conta são revogados.` }),
        h("dl", { class: "reset-ways" },
          h("dt", { text: "Link por e-mail (recomendado)" }),
          h("dd", { text: "A pessoa recebe um link para criar a senha. Vale 24 horas e funciona uma vez só; ninguém precisa repassar senha." }),
          h("dt", { text: "Senha temporária" }),
          h("dd", { text: "Você vê uma senha e repassa; a pessoa troca no primeiro login." })),
        h("div", { class: "dialog-actions reset-actions" },
          h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
          h("button", { type: "button", class: "btn btn-ghost", text: "Gerar senha temporária", onClick: () => { pick = "temp"; dlg.close(); } }),
          link));
      dlg.addEventListener("close", () => resolve(pick));
      link.focus();
    });
  }

  function showResetLink(res) {
    const dlg = modal(
      h("h2", { text: res.emailed ? "Link enviado" : "Link criado" }),
      res.emailed
        ? h("p", {}, "Mandamos o link de nova senha para ", h("strong", { text: res.email }), ". Se não chegar, mande este link por outro canal:")
        : warnBox(`O e-mail para ${res.email} não saiu. Mande este link por outro canal (WhatsApp, chat):`),
      codeBox(res.reset_url),
      h("p", { class: "dialog-note", text: "Vale por 24 horas e funciona uma vez só. Pedir de novo gera um link novo e o anterior deixa de valer." }),
      h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-primary", text: "Pronto", onClick: () => dlg.close() })));
  }

  async function onResend(u) {
    try { showInvite(await api.post(`/admin/users/${u.id}/invite`)); }
    catch (e) { errorToast(e, "Não foi possível reenviar."); }
  }

  // ---- Convidar pessoa (convite). Com e-mail no servidor: link por e-mail (a
  // pessoa cria a senha); sem: senha temporária, trocada no 1º login ----
  // O admin já informa o nome (vale até o primeiro acesso; no tour a pessoa
  // confere) e escolhe os papéis ali (mudam depois em Papéis…). Vindo de um
  // pedido de convite (req), o e-mail é o do pedido e o nome vem preenchido.
  async function onInvite(req = null) {
    if (req instanceof Event) req = null;
    const byLink = req ? true : await api.get("/auth/options").then((o) => o.email).catch(() => false);
    const input = h("input", { type: "email", required: "required", autocomplete: "off", value: req ? req.email : "" });
    if (req) { input.readOnly = true; input.setAttribute("aria-readonly", "true"); }
    const name = h("input", { type: "text", maxlength: "60", autocomplete: "off", value: req ? req.name || "" : "", placeholder: "Ex.: Maria Souza" });
    const err = h("p", { class: "error-text", role: "alert" });
    input.addEventListener("input", () => markInvalid([input], err, false));
    const boxes = ROLES.map(([k, n, d]) => {
      const cb = h("input", { type: "checkbox", value: k });
      cb.checked = k === "user";
      cb.addEventListener("change", () => markInvalid(boxes.map(([b]) => b), err, false));
      return [cb, h("label", { class: "check-line role-line" }, cb, h("span", {}, h("strong", { text: n }), h("small", { text: roleDesc(k, d, me) })))];
    });
    const locked = me.org && me.org.identity_managed;
    const submit = h("button", { type: "submit", class: "btn btn-primary", text: byLink ? "Enviar convite" : "Criar conta" });
    const form = h(
      "form",
      {},
      field("E-mail do convidado", input),
      field("Nome da pessoa (opcional)", name),
      h("p", { class: "dialog-note field-note", text: locked
        ? "Fica como o nome da conta. Nome e e-mail são definidos pela administração: depois, mude em Editar nome e e-mail."
        : "Fica como o nome da conta até o primeiro acesso; no tour, a pessoa confere e ajusta." }),
      h("fieldset", { class: "invite-roles" }, h("legend", { text: "Papéis (dá para mudar depois em Papéis…)" }), ...boxes.map(([, l]) => l)),
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
      const roles = boxes.filter(([b]) => b.checked).map(([b]) => b.value);
      if (!roles.length) {
        err.textContent = "Escolha pelo menos um papel.";
        markInvalid(boxes.map(([b]) => b), err);
        boxes[0][0].focus();
        return;
      }
      if (roles.includes("admin") && !(await confirmDialog({
        title: "Convidar já como Admin?",
        text: "A pessoa vai poder convidar, bloquear e excluir contas, mudar papéis e as configurações gerais.",
        confirm: "Convidar como Admin" }))) return;
      submit.disabled = true;
      const body = { display_name: name.value.trim() || null, roles };
      try {
        const res = req ? await api.post(`/admin/invite-requests/${req.id}/invite`, body)
          : await api.post("/admin/users", { email: input.value.trim(), ...body });
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
    const dlg = modal(h("h2", { text: req ? `Convidar ${req.name}` : "Convidar pessoa" }), form);
    (req ? name : input).focus();
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
    return [cb, h("label", { class: "check-line role-line" }, cb, h("span", {}, h("strong", { text: n }), h("small", { text: roleDesc(k, d, me) })))];
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
      const res = await api.put(`/admin/users/${u.id}/roles`, { roles });
      u.roles = roles;
      changed = true;
      paintConsent();
      toast(res.notified ? `Papéis de ${who} salvos. A pessoa é avisada do que mudou.` : `Papéis de ${who} salvos.`);
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
    consent.textContent = !u.roles.includes("user") ? "" : me.org && me.org.team_visibility === "managers"
      ? "Nesta instância, quem vê a equipe vê o registro de todos (Admin › Para empresas). A escolha da pessoa fica guardada para quando voltar a “Cada pessoa escolhe”."
      : u.viewers_allowed
      ? "O registro desta conta está liberado a quem vê a equipe (cada pessoa decide em Configurações > Conta)."
      : "O registro desta conta não está liberado a quem vê a equipe (cada pessoa decide em Configurações > Conta).";
  };
  paintConsent();
  const dlg = modal(h("h2", { text: `Papéis de ${who}` }),
    h("p", { class: "dialog-note", text: u.invite_pending || u.id === me.id ? "Qualquer combinação. Marcou ou desmarcou, já vale."
      : "Qualquer combinação. Marcou ou desmarcou, já vale; a pessoa vê um aviso do que mudou no próximo acesso (e por e-mail, se configurado)." }),
    h("div", { class: "role-lines" }, ...boxes.map(([, l]) => l)), consent,
    h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-text", text: "Fechar", onClick: () => dlg.close() })));
  // A linha da conta mostra os papéis novos; o foco volta ao ⋮ dela (a lista foi redesenhada).
  dlg.addEventListener("close", async () => {
    if (!changed) return;
    await onChanged();
    refocusBy(document.getElementById("main"), "Mais ações para " + u.email);
  });
}

// ---- Editar nome e e-mail de uma conta (o caminho quando a administração os
// define; também corrige um convite). Trocar o e-mail avisa o antigo e o novo. ----
function editProfile(u, me, onChanged) {
  const name = h("input", { type: "text", maxlength: "60", value: u.display_name || "", placeholder: u.name || "", autocomplete: "off" });
  const email = h("input", { type: "email", maxlength: "254", value: u.email, required: "required", autocomplete: "off" });
  const err = h("p", { class: "error-text", role: "alert" });
  for (const el of [name, email]) el.addEventListener("input", () => markInvalid([name, email], err, false));
  const submit = h("button", { type: "submit", class: "btn btn-primary", text: "Salvar" });
  const form = h("form", {},
    field("Nome", name),
    h("p", { class: "dialog-note field-note", text: "Em branco, o Nexus usa o nome tirado do e-mail." }),
    field("E-mail (é o login)", email),
    h("p", { class: "dialog-note field-note", text: u.invite_pending
      ? "O convite ainda não foi aceito: depois de trocar o e-mail, use Reenviar convite."
      : "Trocar o e-mail muda o login na hora. Mandamos um aviso para o endereço antigo e para o novo." }),
    err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }), submit));
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    const body = { display_name: name.value.trim() || null };
    if (email.value.trim().toLowerCase() !== u.email) body.email = email.value.trim();
    try {
      await api.put(`/admin/users/${u.id}/profile`, body);
      dlg.close();
      toast("Nome e e-mail salvos.");
      await onChanged();
      refocusBy(document.getElementById("main"), "Mais ações para " + (body.email || u.email).toLowerCase());
    } catch (e) {
      err.textContent = e.status === 409 ? "Esse e-mail já é de outra conta." : e.status === 422 ? "E-mail inválido." : e.message || "Não foi possível salvar.";
      markInvalid(e.status === 409 || e.status === 422 ? [email] : [name, email], err);
      (e.status === 409 || e.status === 422 ? email : name).focus();
    }
  }));
  const dlg = modal(h("h2", { text: `Nome e e-mail de ${u.display_name || u.email}` }), form);
  name.focus();
}

// ---- Para empresas e instituições: opções globais, todas desligadas por
// padrão (o padrão é o organizador pessoal). Cada mudança vale na hora e fica
// no histórico de quem mudou. ----
async function mountOrg(root, me) {
  clear(root);
  let cfg = await api.get("/admin/org");
  const save = async (patch, msg) => {
    cfg = await api.put("/admin/org", patch);
    me.org = { team_visibility: cfg.team_visibility, assign_receive: cfg.assign_receive, identity_managed: cfg.identity_managed };
    toast(msg);
  };

  // Duas opções em rádio; trocar pede confirmação com o efeito (visibilidade e receber tarefas).
  const choice = (key, opts, confirmOf, msgOf) => {
    const radios = opts.map(([v, n, d]) => {
      const r = h("input", { type: "radio", name: "org-" + key, value: v });
      r.checked = cfg[key] === v;
      r.addEventListener("change", async () => {
        if (!r.checked) return;
        const reset = () => { for (const x of radios) x[0].checked = x[0].value === cfg[key]; };
        // Cancelou: o foco volta ao rádio que continua marcado (não ao recusado, que repetiria a pergunta na próxima seta).
        if (!(await confirmDialog(confirmOf(v)))) { reset(); (radios.find((x) => x[0].checked) || [r])[0].focus(); return; }
        try { await save({ [key]: v }, msgOf(v)); }
        catch (e) { errorToast(e); reset(); }
      });
      return [r, h("label", { class: "check-line role-line" }, r, h("span", {}, h("strong", { text: n }), h("small", { text: d })))];
    });
    return radios.map(([, l]) => l);
  };
  const receive = choice("assign_receive", [
    ["self", "Cada pessoa escolhe", "Padrão. Quem tem o papel “Manda tarefas” só manda para quem aceitar receber, em Configurações > Conta."],
    ["all", "Todos recebem de quem atribui", "Todos com o papel Usuário recebem tarefas de quem tem o papel “Manda tarefas”, sem que a pessoa possa desligar. A escolha de cada um fica guardada."],
  ], (v) => v === "all" ? {
    title: "Todos passam a receber tarefas de quem atribui?",
    text: "Quem tem o papel “Manda tarefas” passa a mandar tarefas para todas as pessoas com o papel Usuário, mesmo quem não aceitou. Na Conta de cada um, a chave fica bloqueada com o motivo, e quem já usa o Nexus vê um aviso no próximo acesso. As escolhas de cada pessoa ficam guardadas.",
    confirm: "Todos recebem",
  } : {
    title: "Voltar para “Cada pessoa escolhe”?",
    text: "Cada pessoa volta ao que tinha escolhido em Configurações > Conta. Quem não tinha aceitado deixa de receber tarefas novas; as que já recebeu continuam com ela.",
    confirm: "Voltar ao padrão",
  }, (v) => v === "all" ? "Pronto: todos recebem tarefas de quem atribui." : "Pronto: cada pessoa escolhe de novo se recebe tarefas.");

  // Visibilidade da equipe: duas opções; trocar pede confirmação com o efeito.
  const VIS = [
    ["self", "Cada pessoa escolhe", "Padrão. Quem tem o papel “Vê a equipe” vê só o registro de quem permitir, em Configurações > Conta."],
    ["managers", "Visível para quem gerencia", "Quem tem o papel “Vê a equipe” vê o registro de todos (quadro, números, PDF, horas e fotos), sem que a pessoa possa desligar. A escolha de cada um fica guardada."],
  ];
  const radios = VIS.map(([v, n, d]) => {
    const r = h("input", { type: "radio", name: "org-vis", value: v });
    r.checked = cfg.team_visibility === v;
    r.addEventListener("change", async () => {
      if (!r.checked) return;
      const toManagers = v === "managers";
      const ok = await confirmDialog(toManagers ? {
        title: "Deixar o registro de todos visível para quem gerencia?",
        text: "Quem tem o papel “Vê a equipe” passa a ver o registro de todas as pessoas, mesmo de quem não permitiu. Na Conta de cada um, a chave fica bloqueada com o motivo, e quem já usa o Nexus vê um aviso no próximo acesso. As escolhas de cada pessoa ficam guardadas.",
        confirm: "Deixar visível",
      } : {
        title: "Voltar para “Cada pessoa escolhe”?",
        text: "Cada pessoa volta ao que tinha escolhido em Configurações > Conta. Quem não tinha permitido some da tela Equipe na hora.",
        confirm: "Voltar ao padrão",
      });
      if (!ok) { for (const x of radios) x[0].checked = x[0].value === cfg.team_visibility; (radios.find((x) => x[0].checked) || [r])[0].focus(); return; }
      try { await save({ team_visibility: v }, toManagers ? "Pronto: quem gerencia a equipe vê o registro de todos." : "Pronto: cada pessoa escolhe de novo."); }
      catch (e) { errorToast(e); for (const x of radios) x[0].checked = x[0].value === cfg.team_visibility; }
    });
    return [r, h("label", { class: "check-line role-line" }, r, h("span", {}, h("strong", { text: n }), h("small", { text: d })))];
  });

  // Chaves simples (ligou ou desligou, já vale).
  const toggle = (key, label, desc, onMsg, offMsg) => {
    const cb = h("input", { type: "checkbox" });
    cb.checked = !!cfg[key];
    cb.addEventListener("change", async () => {
      cb.setAttribute("aria-disabled", "true");
      try { await save({ [key]: cb.checked }, cb.checked ? onMsg : offMsg); }
      catch (e) { cb.checked = !cb.checked; errorToast(e); }
      finally { cb.removeAttribute("aria-disabled"); }
    });
    return h("label", { class: "check-line role-line" }, cb, h("span", {}, h("strong", { text: label }), h("small", { text: desc })));
  };

  root.append(h("div", { class: "settings-grid" }, h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Para empresas e instituições" })),
    h("p", { class: "help", text: "O Nexus nasce como organizador pessoal: cada pessoa decide o que mostra. Quando ele é de uma empresa ou instituição, estas opções ajudam. Todas começam desligadas; cada mudança vale na hora e fica no seu histórico." }),
    h("fieldset", { class: "org-option" }, h("legend", { text: "Visibilidade da equipe" }), ...radios.map(([, l]) => l)),
    h("fieldset", { class: "org-option" }, h("legend", { text: "Receber tarefas atribuídas" }), ...receive),
    h("fieldset", { class: "org-option" }, h("legend", { text: "Nome e e-mail" }),
      toggle("identity_managed", "Nome e e-mail definidos pela administração",
        "Ligado, só o admin muda nome e e-mail (Contas › ⋮ › Editar nome e e-mail); na Conta de cada um, os campos ficam bloqueados com o motivo. Desligado, cada pessoa muda os seus (o e-mail novo é confirmado por link).",
        "Pronto: nome e e-mail agora são definidos pela administração.", "Pronto: cada pessoa volta a mudar o próprio nome e e-mail.")),
    h("fieldset", { class: "org-option" }, h("legend", { text: "Tela de login" }),
      toggle("invite_request_on", "Mostrar “Solicitar convite” na tela de login",
        "Ligado, quem não tem conta pede acesso pela tela de login e o pedido chega em Contas. Desligado (padrão), só entra quem você convidar."
          + (cfg.mail_configured ? "" : " Hoje o e-mail não está configurado no servidor, então o pedido não aparece mesmo ligado."),
        "Pronto: a tela de login oferece o pedido de convite.", "Pronto: a tela de login não oferece mais o pedido de convite.")),
    ticketField(),
    privacyField())));

  // Política de privacidade da instância: link na tela de login, na Conta e no convite.
  function privacyField() {
    const url = h("input", { type: "url", maxlength: "300", value: cfg.privacy_url || "", id: "org-privacy-url",
      placeholder: "https://empresa.com.br/privacidade" });
    const err = h("p", { class: "error-text", role: "alert" });
    url.addEventListener("input", () => markInvalid([url], err, false));
    const saveBtn = h("button", { type: "button", class: "btn btn-primary", text: "Salvar endereço", onClick: busy(async () => {
      err.textContent = "";
      const v = url.value.trim();
      try {
        await save({ privacy_url: v || null }, v ? "Pronto: o link da política aparece no login, na Conta e no convite." : "Pronto: sem link de política de privacidade.");
        me.privacy_url = cfg.privacy_url;
      } catch (e) {
        err.textContent = e.status === 422 ? "Use um endereço começando com https://." : e.message || "Não foi possível salvar.";
        markInvalid([url], err);
        url.focus();
      }
    }) });
    return h("fieldset", { class: "org-option org-ticket" }, h("legend", { text: "Política de privacidade" }),
      field("Endereço da política de privacidade", url),
      h("p", { class: "dialog-note field-note", text: "Preenchido, o link aparece na tela de login, em Configurações > Conta e no e-mail de convite. Vazio (padrão), nenhum link aparece." }),
      err, h("div", { class: "row-actions" }, saveBtn));
  }

  // Endereço do sistema de chamados da instância. Vazio = cada pessoa usa o seu (Conta).
  function ticketField() {
    const url = h("input", { type: "url", maxlength: "300", value: cfg.ticket_url || "", id: "org-ticket-url",
      placeholder: "https://glpi.empresa.com.br/front/ticket.form.php?id={id}" });
    const err = h("p", { class: "error-text", role: "alert" });
    url.addEventListener("input", () => markInvalid([url], err, false));
    const saveBtn = h("button", { type: "button", class: "btn btn-primary", text: "Salvar endereço", onClick: busy(async () => {
      err.textContent = "";
      const v = url.value.trim();
      try {
        await save({ ticket_url: v || null }, v ? "Pronto: o endereço vale para todos." : "Pronto: cada pessoa volta a usar o próprio endereço.");
        me.ticket_url_managed = !!cfg.ticket_url;
        if (cfg.ticket_url) me.ticket_url = cfg.ticket_url;
      } catch (e) {
        err.textContent = e.status === 422 ? "Use um endereço começando com http:// ou https://." : e.message || "Não foi possível salvar.";
        markInvalid([url], err);
        url.focus();
      }
    }) });
    return h("fieldset", { class: "org-option org-ticket" }, h("legend", { text: "Sistema de chamados" }),
      field("Endereço do chamado ou OS (para todos)", url),
      h("p", { class: "dialog-note field-note", text: "Troque o número por {id} (ex.: https://sistema.empresa/os/{id}); sem {id}, o número vai no fim. Preenchido, vale para todos e o campo fica travado na Conta de cada um. Vazio (padrão), cada pessoa configura o seu; os endereços de cada um ficam guardados." }),
      err, h("div", { class: "row-actions" }, saveBtn));
  }
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
    h("div", { class: "panel-head" }, h("h2", { text: "Geral" })), form), await healthPanel()));
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

  // Toque duplo não manda duas vezes (enquanto um envio corre, o segundo é ignorado).
  const once = (fn) => { let on = false; return async (ev) => { if (on) return; on = true; try { await fn(ev); } finally { on = false; } }; };
  const saveText = h("button", { type: "button", class: "btn btn-primary", text: "Salvar textos", onClick: once(async () => {
    err.textContent = "";
    try {
      apply(await api.put("/admin/branding", { line1: l1.value.trim(), line2: l2.value.trim() }));
      toast("Textos salvos.");
    } catch (e) { err.textContent = e.message || "Não foi possível salvar."; }
  }) });

  const upload = h("button", { type: "button", class: "btn btn-ghost", onClick: once(async () => {
    err.textContent = "";
    const f = file.files && file.files[0];
    if (!f) { err.textContent = "Escolha um arquivo SVG, PNG ou WebP."; return; }
    if (f.size > 256 * 1024) { err.textContent = "O arquivo passa de 256 KB."; return; }
    try {
      apply(await api.upload("/admin/branding/logo", f));
      file.value = "";
      toast("Logo atualizado.");
    } catch (e) { err.textContent = e.message || "Não foi possível enviar."; }
  }) }, icon("add"), "Enviar logo");

  const reset = h("button", { type: "button", class: "btn btn-text", text: "Restaurar dragão padrão", onClick: once(async () => {
    try { apply(await api.del("/admin/branding/logo")); toast("Logo padrão restaurado."); }
    catch (e) { errorToast(e); }
  }) });

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
