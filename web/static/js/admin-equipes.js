// Admin › Equipes (sql/043): o admin master (quem é, os papéis dele num toque e
// a transferência com senha + código por e-mail) e o cadastro das equipes
// (lista; criar e editar num diálogo por cima da tela, com os membros em lote).
// Sem sub-abas. Uma pessoa pode estar em várias equipes; todo mundo começa sem
// equipe. Com equipes, "Vê a equipe" e "Manda tarefas" valem só entre quem
// compartilha uma equipe, e "Para empresas" só para quem está em alguma.
// Também daqui: Equipes… de uma conta (⋮ em Contas) e as caixas do convite.
import { api } from "./api.js";
import { h, icon, clear, field, markInvalid } from "./dom.js";
import { busy, confirmDialog, errorToast, modal, popupMenu, sheet, toast, warnBox, refocusBy } from "./ui.js";

const phone = () => matchMedia("(max-width: 860px)").matches;
function rowMenu(btn, title, items) {
  if (phone()) { sheet(title, items); return; }
  const r = btn.getBoundingClientRect();
  popupMenu(r.left, r.bottom + 4, items, r.top);
}
const label = (u) => (u.display_name ? `${u.display_name} · ${u.email}` : u.email);
const nameOf = (u) => u.display_name || u.name || u.email;
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
// Equipes ativas, por nome (para as caixas do convite e de Equipes…).
export const activeTeams = (teams) => teams.filter((t) => !t.archived_at);

// Menu: cada item aparece só para quem tem o papel (o master ligou ou desligou os dele).
function syncMenu(me) {
  for (const el of document.querySelectorAll("[data-need]")) {
    el.classList.toggle("hidden", !el.dataset.need.split(" ").some((r) => (me.roles || []).includes(r)));
  }
  window.dispatchEvent(new Event("nexus:me"));
}

export async function mountTeams(root, me) {
  clear(root);
  const [teams, master, users] = await Promise.all([api.get("/admin/teams"), api.get("/admin/master"), api.get("/admin/users")]);
  const reload = () => mountTeams(root, me);
  const newBtn = h("button", { type: "button", class: "btn btn-primary",
    onClick: () => teamDialog(null, users, !activeTeams(teams).length, reload) }, icon("add"), "Nova equipe");
  const title = h("h2", { text: "Equipes" });
  const list = h("div", { class: "admin-users-list" });
  if (!teams.length) {
    list.append(h("p", { class: "empty", text: "Nenhuma equipe ainda. Sem equipes, o Nexus funciona como organizador pessoal: quem tem “Vê a equipe” ou “Manda tarefas” alcança quem aceitar, em toda a instância." }));
  }
  for (const t of teams) list.append(teamRow(t));

  function teamRow(t) {
    const names = t.members.map(nameOf);
    const preview = names.length ? `${plural(names.length, "pessoa", "pessoas")}: ${names.slice(0, 4).join(", ")}${names.length > 4 ? "…" : ""}` : "ninguém ainda";
    const edit = () => teamDialog(t, users, false, reload);
    const items = [
      ["Editar…", "edit", edit],
      t.archived_at ? ["Desarquivar", "undo", () => setArchived(t, false)] : ["Arquivar", "folder", () => setArchived(t, true)],
      ["Excluir equipe", "trash", () => onDelete(t)],
    ];
    const more = h("button", { type: "button", class: "icon", title: "Mais ações", "aria-label": `Mais ações para a equipe ${t.name}`, "aria-haspopup": "menu",
      onClick: (ev) => rowMenu(ev.currentTarget, t.name, items) }, icon("more-v"));
    return h("div", { class: "list-row team-row" + (t.archived_at ? " is-archived" : "") },
      h("span", { class: "team-ico", "aria-hidden": "true" }, icon("team")),
      h("div", { class: "t" }, h("span", { text: t.name }),
        h("small", {}, preview, t.archived_at ? h("span", { class: "chip pending-chip", text: "arquivada" }) : null)),
      h("button", { type: "button", class: "btn btn-text btn-sm only-desk", text: "Editar", "aria-label": `Editar a equipe ${t.name}`, onClick: edit }),
      more);
  }

  async function setArchived(t, archived) {
    if (archived && !(await confirmDialog({ title: `Arquivar a equipe ${t.name}?`,
      text: "Ela deixa de contar: quem só se via (ou mandava tarefas) por ela perde o acesso na hora. Os membros ficam guardados; desarquivar devolve tudo.",
      confirm: "Arquivar" }))) return;
    try { await api.patch(`/admin/teams/${t.id}`, { archived }); toast(archived ? `Equipe ${t.name} arquivada.` : `Equipe ${t.name} de volta.`); await reload(); }
    catch (e) { errorToast(e); }
  }
  async function onDelete(t) {
    if (!(await confirmDialog({ title: `Excluir a equipe ${t.name}?`,
      text: `${t.members.length ? `${plural(t.members.length, "pessoa sai", "pessoas saem")} dela; nada dos registros é apagado.` : "Ela não tem ninguém."} Quem só se via (ou mandava tarefas) por ela perde o acesso na hora. Não dá para desfazer.`,
      confirm: "Excluir", danger: true }))) return;
    try { await api.del(`/admin/teams/${t.id}`); toast(`Equipe ${t.name} excluída.`); await reload(); }
    catch (e) { errorToast(e); }
  }

  root.append(h("div", { class: "settings-grid" },
    masterPanel(master, users, me, reload),
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, title, h("div", { class: "spacer" }), newBtn),
      h("p", { class: "help", text: "Com equipes, “Vê a equipe” e “Manda tarefas” valem só entre quem está na mesma equipe (somado ao aceite de cada pessoa ou às opções de Para empresas). Quem fica sem equipe não é visto nem recebe tarefas de ninguém, exceto do admin master. As opções de Para empresas valem só para quem está em alguma equipe; o pedido de convite e a política de privacidade valem para todos." }),
      list)));
}

// ------------------------------------------------- o diálogo da equipe --
// Nome e membros em lote (todas as contas, com busca). Criar a primeira equipe
// avisa o que muda (o escopo passa a valer).
function teamDialog(team, users, first, onSaved) {
  const name = h("input", { type: "text", maxlength: "60", required: "required", autocomplete: "off", value: team ? team.name : "", placeholder: "Ex.: Manutenção" });
  const err = h("p", { class: "error-text", role: "alert" });
  name.addEventListener("input", () => markInvalid([name], err, false));
  const chosen = new Set(team ? team.members.map((m) => m.id) : []);
  const search = h("input", { type: "search", placeholder: "Buscar por nome ou e-mail", "aria-label": "Buscar pessoa", autocomplete: "off" });
  const count = h("p", { class: "dialog-note", "aria-live": "polite" });
  const pick = h("div", { class: "team-pick", role: "group", "aria-label": "Quem está na equipe" });
  // Quem já está na equipe vem primeiro (o resto, em ordem de nome).
  const sorted = [...users].sort((a, b) => (chosen.has(b.id) - chosen.has(a.id)) || nameOf(a).localeCompare(nameOf(b), "pt-BR"));
  const paintCount = () => { count.textContent = chosen.size ? `${plural(chosen.size, "pessoa marcada", "pessoas marcadas")}.` : "Ninguém marcado ainda."; };
  const boxes = sorted.map((u) => {
    const cb = h("input", { type: "checkbox", value: String(u.id) });
    cb.checked = chosen.has(u.id);
    cb.addEventListener("change", () => { if (cb.checked) chosen.add(u.id); else chosen.delete(u.id); paintCount(); });
    const line = h("label", { class: "check-line team-pick-line" }, cb, h("span", {}, h("strong", { text: u.display_name || u.email }),
      u.display_name ? h("small", { text: u.email }) : null));
    return [u, line];
  });
  pick.append(...boxes.map(([, l]) => l));
  search.addEventListener("input", () => {
    const q = search.value.trim().toLowerCase();
    for (const [u, l] of boxes) l.hidden = !!q && !label(u).toLowerCase().includes(q);
  });
  paintCount();
  const submit = h("button", { type: "submit", class: "btn btn-primary", text: team ? "Salvar" : "Criar equipe" });
  const form = h("form", {},
    field("Nome da equipe", name),
    first ? warnBox("Esta é a primeira equipe. A partir dela, “Vê a equipe” e “Manda tarefas” valem só entre quem está na mesma equipe, e as opções de Para empresas só para quem está em alguma. Quem ficar sem equipe sai da tela Equipe dos outros (o admin master continua vendo, se ligar os papéis dele).") : null,
    h("fieldset", { class: "team-members" }, h("legend", { text: "Quem está na equipe" }),
      users.length > 8 ? h("div", { class: "field" }, search) : null, pick, count),
    err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }), submit));
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    const body = { name: name.value.trim(), member_ids: [...chosen] };
    if (!body.name) { err.textContent = "Dê um nome para a equipe."; markInvalid([name], err); name.focus(); return; }
    try {
      if (team) await api.patch(`/admin/teams/${team.id}`, body); else await api.post("/admin/teams", body);
      dlg.close();
      toast(team ? `Equipe ${body.name} salva.` : `Equipe ${body.name} criada${chosen.size ? ` com ${plural(chosen.size, "pessoa", "pessoas")}` : ""}.`);
      await onSaved();
      refocusBy(document.getElementById("main"), `Mais ações para a equipe ${body.name}`);
    } catch (e) {
      err.textContent = e.status === 409 ? "Já existe uma equipe com esse nome." : e.message || "Não foi possível salvar.";
      markInvalid([name], err);
      name.focus();
    }
  }));
  const dlg = modal(h("h2", { text: team ? `Equipe ${team.name}` : "Nova equipe" }), form);
  name.focus();
}

// ------------------------------------------------------- admin master --

function masterPanel(m, users, me, reload) {
  const head = h("div", { class: "panel-head" }, h("h2", { text: "Admin master" }));
  if (!m.me) {
    return h("section", { class: "panel" }, head,
      h("p", { class: "help" }, "O admin master é ", h("strong", { text: m.master ? m.master.name : "—" }),
        ". Só ele vê e manda tarefas para todos, com ou sem equipe (quando liga os próprios papéis), e só ele passa esse papel para outro admin."));
  }
  const toggle = (key, title, desc) => {
    const cb = h("input", { type: "checkbox" });
    cb.checked = !!m[key];
    cb.addEventListener("change", async () => {
      cb.setAttribute("aria-disabled", "true");
      try {
        const res = await api.put("/admin/master/roles", { [key]: cb.checked });
        m.viewer = res.viewer; m.assigner = res.assigner;
        me.roles = [...new Set([...(me.roles || []).filter((r) => r !== "viewer" && r !== "assigner"),
          ...(res.viewer ? ["viewer"] : []), ...(res.assigner ? ["assigner"] : [])])].sort();
        syncMenu(me);
        toast(cb.checked ? `Pronto: “${title}” ligado para você.` : `Pronto: “${title}” desligado para você.`);
      } catch (e) { cb.checked = !cb.checked; errorToast(e); }
      finally { cb.removeAttribute("aria-disabled"); }
    });
    return h("label", { class: "check-line role-line" }, cb, h("span", {}, h("strong", { text: title }), h("small", { text: desc })));
  };
  const admins = users.filter((u) => u.id !== me.id && u.roles.includes("admin") && !u.blocked_at && !u.invite_pending);
  const transfer = h("button", { type: "button", class: "btn btn-ghost", onClick: () => transferDialog(m, admins, reload) }, icon("key"), "Transferir o papel de master…");
  return h("section", { class: "panel" }, head,
    h("p", { class: "help", text: "Você é o admin master desta instância: o único que vê e manda tarefas para todos, com ou sem equipe. Ligue ou desligue quando quiser; desligados, a tela Equipe e o Atribuir somem para você." }),
    h("div", { class: "role-lines" },
      toggle("viewer", "Vê a equipe", "Ver, sem editar, o registro de quem aceitou (ou, em equipe, pelas opções de Para empresas), de todas as equipes e de quem está sem equipe."),
      toggle("assigner", "Manda tarefas", "Mandar tarefas para quem aceita receber (ou, em equipe, pelas opções de Para empresas), de todas as equipes e de quem está sem equipe.")),
    h("p", { class: "dialog-note", text: "O que você abrir do registro de outras pessoas fica no log de admin (o seu Histórico)." }),
    h("div", { class: "row-actions" }, transfer));
}

// Transferir: escolhe o admin e confirma com a senha; o código de 6 dígitos vai
// para o seu e-mail e é digitado no mesmo diálogo (vale 10 minutos, 5 tentativas).
function transferDialog(m, admins, reload) {
  if (!m.mail_configured) {
    const dlg = modal(h("h2", { text: "Transferir o papel de master" }),
      h("p", { text: "A confirmação vai por um código mandado ao seu e-mail, e o e-mail não está configurado no servidor. Configure o e-mail (SMTP) e volte aqui." }),
      h("div", { class: "dialog-actions" }, h("div", { class: "spacer" }), h("button", { type: "button", class: "btn btn-primary", text: "Entendi", onClick: () => dlg.close() })));
    return;
  }
  if (!admins.length) {
    const dlg = modal(h("h2", { text: "Transferir o papel de master" }),
      h("p", { text: "O papel só passa para outro admin que já entrou no Nexus e está com o acesso liberado. Dê o papel Admin a alguém em Contas (⋮ › Papéis…) e volte aqui." }),
      h("div", { class: "dialog-actions" }, h("div", { class: "spacer" }), h("button", { type: "button", class: "btn btn-primary", text: "Entendi", onClick: () => dlg.close() })));
    return;
  }
  const who = h("select", { required: "required" },
    admins.length > 1 ? h("option", { value: "", text: "Escolha o admin" }) : null,
    ...admins.map((u) => h("option", { value: String(u.id), text: label(u) })));
  const pw = h("input", { type: "password", autocomplete: "current-password", required: "required", maxlength: "128" });
  const code = h("input", { type: "text", inputmode: "numeric", autocomplete: "one-time-code", pattern: "[0-9]{6}", maxlength: "6", placeholder: "000000" });
  const err = h("p", { class: "error-text", role: "alert" });
  for (const el of [who, pw, code]) el.addEventListener("input", () => markInvalid([el], err, false));
  const step1 = h("div", {},
    h("p", { class: "help", text: "Quem recebe passa a ser o único que vê e manda tarefas para todos (quando ligar os papéis dele) e o único que pode passar o papel adiante. Você continua admin." }),
    field("Para quem (outro admin)", who), field("Sua senha", pw));
  const sentTo = h("p", { class: "help" });
  const step2 = h("div", { hidden: true }, sentTo, field("Código de 6 dígitos", code),
    h("p", { class: "dialog-note", text: "Vale por 10 minutos e funciona uma vez só; 5 erros e ele deixa de valer. Não chegou? Confira o spam ou volte e peça outro." }));
  const back = h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => {
    if (step2.hidden) { dlg.close(); return; }
    step2.hidden = true; step1.hidden = false; submit.textContent = "Mandar o código"; back.textContent = "Cancelar"; err.textContent = ""; pw.value = ""; pw.focus();
  } });
  const submit = h("button", { type: "submit", class: "btn btn-primary", text: "Mandar o código" });
  // Os dois passos validam aqui (a senha do 1º passo fica vazia e escondida no 2º: a validação nativa travaria o envio).
  const form = h("form", { novalidate: "novalidate" }, step1, step2, err, h("div", { class: "dialog-actions" }, back, submit));
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    if (!step2.hidden) {
      const c = code.value.trim();
      if (!/^\d{6}$/.test(c)) { err.textContent = "Digite os 6 números do código."; markInvalid([code], err); code.focus(); return; }
      try {
        const res = await api.post("/admin/master/transfer/confirm", { code: c });
        dlg.close();
        toast(`Pronto: ${res.master.name} agora é o admin master e foi avisado.`);
        await reload();
      } catch (e) {
        err.textContent = e.message || "Não foi possível confirmar.";
        markInvalid([code], err);
        code.select(); code.focus();
      }
      return;
    }
    if (!who.value) { err.textContent = "Escolha quem recebe o papel."; markInvalid([who], err); who.focus(); return; }
    if (!pw.value) { err.textContent = "Digite a sua senha."; markInvalid([pw], err); pw.focus(); return; }
    try {
      const res = await api.post("/admin/master/transfer", { to_user_id: Number(who.value), password: pw.value });
      pw.value = "";
      sentTo.textContent = `Mandamos um código para o seu e-mail. Digite-o para passar o papel para ${res.to}.`;
      step1.hidden = true; step2.hidden = false; submit.textContent = "Confirmar a transferência"; back.textContent = "Voltar";
      code.value = "";
      code.focus();
    } catch (e) {
      err.textContent = e.message || "Não foi possível mandar o código.";
      const bad = /senha/i.test(err.textContent) ? pw : who;
      markInvalid([bad], err);
      bad.focus();
    }
  }));
  const dlg = modal(h("h2", { text: "Transferir o papel de master" }), form);
  (admins.length > 1 ? who : pw).focus();
}

// --------------------------------------------- Equipes… de uma conta --
// Marcou ou desmarcou, já vale (como Papéis…). Só equipes ativas.
export async function editUserTeams(u, onChanged) {
  let teams;
  try { teams = activeTeams(await api.get("/admin/teams")); } catch (e) { errorToast(e); return; }
  const who = u.display_name || u.email;
  let changed = false, saving = false;
  const boxes = teams.map((t) => {
    const cb = h("input", { type: "checkbox", value: String(t.id) });
    cb.checked = (u.teams || []).some((x) => x.id === t.id);
    cb.addEventListener("change", () => { if (saving) { cb.checked = !cb.checked; return; } save(cb); });
    return [cb, h("label", { class: "check-line role-line" }, cb, h("span", {}, h("strong", { text: t.name }),
      h("small", { text: plural(t.members.length, "pessoa", "pessoas") })))];
  });
  async function save(cb) {
    saving = true;
    for (const [b] of boxes) b.setAttribute("aria-disabled", "true");
    try {
      const res = await api.put(`/admin/users/${u.id}/teams`, { team_ids: boxes.filter(([b]) => b.checked).map(([b]) => Number(b.value)) });
      u.teams = res.teams;
      changed = true;
      toast(res.teams.length ? `Equipes de ${who}: ${res.teams.map((t) => t.name).join(", ")}.` : `${who} ficou sem equipe.`);
    } catch (e) { cb.checked = !cb.checked; errorToast(e); }
    finally { saving = false; for (const [b] of boxes) b.removeAttribute("aria-disabled"); }
  }
  const dlg = modal(h("h2", { text: `Equipes de ${who}` }),
    teams.length
      ? h("p", { class: "dialog-note", text: "Pode estar em várias. Marcou ou desmarcou, já vale: quem vê a equipe ou manda tarefas alcança esta pessoa só por uma equipe em comum." })
      : h("p", { text: "Nenhuma equipe cadastrada ainda. Crie em Admin › Equipes." }),
    h("div", { class: "role-lines" }, ...boxes.map(([, l]) => l)),
    h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-text", text: "Fechar", onClick: () => dlg.close() })));
  dlg.addEventListener("close", async () => {
    if (!changed) return;
    await onChanged();
    refocusBy(document.getElementById("main"), "Mais ações para " + u.email);
  });
}

// Caixas de equipes para o convite: [fieldset, () => ids]. Sem equipes: nada.
export function inviteTeamsField(teams) {
  const act = activeTeams(teams);
  if (!act.length) return [null, () => []];
  const boxes = act.map((t) => {
    const cb = h("input", { type: "checkbox", value: String(t.id) });
    return [cb, h("label", { class: "check-line role-line" }, cb, h("span", {}, h("strong", { text: t.name }),
      h("small", { text: plural(t.members.length, "pessoa", "pessoas") })))];
  });
  const el = h("fieldset", { class: "invite-roles" }, h("legend", { text: "Equipes (opcional; dá para mudar depois em Equipes…)" }), ...boxes.map(([, l]) => l));
  return [el, () => boxes.filter(([b]) => b.checked).map(([b]) => Number(b.value))];
}
