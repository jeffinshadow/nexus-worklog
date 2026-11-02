// Configurações: uma página só, com seções (Conta, Avisos, Calendário, IA e API) e atalhos no topo.
// Cada campo salva ao mudar (sem botão Salvar). Links antigos (#/config?aba=avisos) rolam até a seção.
import { api } from "./api.js";
import { h, icon, clear, dateTime, field, matchPasswords } from "./dom.js";
import { codeBox, confirmDialog, errorToast, modal, toast, warnBox, busy, singleKeysOn, setSingleKeys, calmMotion, hashPage, pager, pageSlice, setHashPage } from "./ui.js";
import { defaultProjectPanel } from "./projects.js";
import { avatar, squarePhoto } from "./profile.js";
import { pushPanel } from "./notificacoes.js";
import { cancelled, register as registerPasskey, supported as passkeySupported } from "./passkey.js";

const SECTIONS = [
  ["conta", "Conta"],
  ["avisos", "Avisos"],
  ["calendario", "Calendário"],
  ["ia", "IA e API"],
];
const OLD_TABS = { dias: "conta", chaves: "ia" }; // links antigos
// Os mesmos nomes do Admin (cada papel com o nome do que ele faz; a tela vem junto).
const ROLE_SHORT = { admin: "Admin", assigner: "Manda tarefas", viewer: "Vê a equipe" };
const ROLE_SCREEN = { admin: "tela Admin", assigner: "tela Equipe", viewer: "tela Equipe" };

// Dias úteis como máscara de bits, domingo = bit 0 (igual ao backend).
const DAYS = [
  [1, "Seg"], [2, "Ter"], [3, "Qua"], [4, "Qui"], [5, "Sex"], [6, "Sáb"], [0, "Dom"],
];

// Salvar ao mudar: as gravações saem uma de cada vez, na ordem (a última vale);
// com `delay`, mudanças seguidas (vários dias marcados) viram uma gravação só.
// Sair da tela antes do prazo grava na hora (no hashchange).
const pendingSaves = new Set();
function saver(run, delay = 0) {
  let timer = null, chain = Promise.resolve();
  const go = () => { timer = null; pendingSaves.delete(trigger); chain = chain.then(run).catch(() => {}); return chain; };
  const trigger = () => {
    clearTimeout(timer);
    if (!delay) return go();
    pendingSaves.add(trigger);
    timer = setTimeout(go, delay);
    return chain;
  };
  trigger.flush = () => (timer ? (clearTimeout(timer), go()) : chain);
  return trigger;
}
addEventListener("hashchange", () => { for (const s of [...pendingSaves]) s.flush(); });

// Erro de um campo: a frase embaixo dele (role=alert) e o campo marcado.
let errSeq = 0;
const errorLine = () => h("p", { class: "error-text", role: "alert", id: "cfg-err-" + ++errSeq });
function fieldError(err, inputs, text) {
  err.textContent = text || "";
  for (const el of [].concat(inputs || [])) {
    if (text) { el.setAttribute("aria-invalid", "true"); el.setAttribute("aria-errormessage", err.id); }
    else el.removeAttribute("aria-invalid");
  }
}

// Chave (checkbox) que grava no servidor: durante a gravação fica aria-disabled
// (e não disabled), para o foco não cair no <body>; cliques nesse meio são ignorados.
function lockWhileSaving(cb) {
  let saving = false;
  cb.addEventListener("click", (ev) => { if (saving) ev.preventDefault(); });
  return async (fn) => {
    saving = true;
    cb.setAttribute("aria-disabled", "true");
    try { await fn(); } finally { saving = false; cb.removeAttribute("aria-disabled"); }
  };
}

// Os títulos dos painéis viram h3 (o h2 é o da seção), com o mesmo desenho.
function demote(nodes) {
  for (const n of nodes) {
    if (!n || !n.querySelectorAll) continue;
    for (const t of n.querySelectorAll(".panel-head > h2")) {
      const h3 = h("h3", {});
      for (const a of t.attributes) h3.setAttribute(a.name, a.value);
      h3.append(...t.childNodes);
      t.replaceWith(h3);
    }
  }
  return nodes;
}

export async function mount(root, ctx) {
  // Vencimentos e Projetos viraram itens do menu: link antigo vai para a tela nova.
  if (/aba=vencimentos/.test(location.hash)) { location.hash = "#/vencimentos"; return; }
  if (/aba=projetos/.test(location.hash)) { location.hash = "#/projetos"; return; }
  // Conta sem registro próprio (só Admin/Visualizador/Atribuidor): só Conta e IA e API.
  const isUser = (ctx.me.roles || []).includes("user");
  const sections = isUser ? SECTIONS : SECTIONS.filter(([k]) => k === "ia" || k === "conta");
  let want = new URLSearchParams(location.hash.split("?")[1] || "").get("aba") || "";
  want = OLD_TABS[want] || want;
  if (!sections.some(([k]) => k === want)) want = "";

  // Cada seção se carrega e se redesenha sozinha; uma que falhar não derruba as outras.
  const builders = {
    // Quem é (nome, foto, tema), o que muda o dia (dias úteis, projeto padrão), quem vê e atribui tarefas, o resto.
    conta: async (again) => isUser
      ? [profilePanel(ctx.me, again), themePanel(ctx.me), workDays(ctx.me), defaultProjectPanel(ctx.me, (r) => meChanged(ctx.me, r)),
        privacyPanel(ctx.me), assistantPanel(ctx.me), ticketsPanel(ctx.me), shortcutsPanel(), account(ctx.me),
        await otherDevicesPanel(), await passkeysPanel(again)]
      : [profilePanel(ctx.me, again), themePanel(ctx.me), account(ctx.me), await otherDevicesPanel(), await passkeysPanel(again)],
    // Notificações dos aparelhos primeiro; e-mail depois.
    avisos: async (again) => [...(await notices(await pushPanel(again))).childNodes],
    calendario: async (again) => [...(await calendarFeed(again)).childNodes],
    ia: async (again) => [...(await tokens(again)).childNodes, ...aiHelp(), ...(await webhooksPanel(again)).childNodes],
  };

  clear(root);
  const index = h("nav", { class: "settings-index", "aria-label": "Seções de Configurações" });
  const groups = {};
  root.append(index);
  for (const [key, label] of sections) {
    const title = h("h2", { class: "settings-group-title", id: "cfg-" + key, tabindex: "-1", text: label });
    const body = h("div", { class: "settings-grid", "aria-busy": "true" });
    groups[key] = { title, body, seq: 0 };
    root.append(h("section", { class: "settings-group", "aria-labelledby": title.id }, title, body));
    index.append(h("a", { href: "#/config?aba=" + key, text: label, onClick: (ev) => {
      if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return; // nova aba: o link normal
      ev.preventDefault();
      window.history.replaceState(null, "", "#/config?aba=" + key); // recarregar volta à mesma seção
      goTo(key, true);
    } }));
  }
  // Excluir a conta: no fim da página, longe do resto.
  root.append(h("div", { class: "settings-grid settings-danger" }, deleteAccount(isUser)));

  const fill = async (key) => {
    const g = groups[key], my = ++g.seq;
    let nodes;
    try { nodes = demote(await builders[key](() => fill(key))); }
    catch (e) { nodes = [h("p", { class: "empty", text: e && e.status === 0 ? e.message : "Não foi possível carregar esta parte. Tente de novo." })]; }
    if (my !== g.seq) return; // um redesenho mais novo já entrou
    clear(g.body);
    g.body.append(...nodes.filter(Boolean));
    g.body.removeAttribute("aria-busy");
  };
  await Promise.all(sections.map(([k]) => fill(k)));

  // Rola até a seção (sem animação na abertura) e põe o foco no título dela.
  function goTo(key, smooth) {
    const t = groups[key] && groups[key].title;
    if (!t) return;
    t.scrollIntoView({ block: "start", behavior: smooth && !calmMotion() ? "smooth" : "auto" });
    t.focus({ preventScroll: true });
  }
  // A tela volta ao topo depois de montar e entra com uma animação de escala
  // (que muda as posições medidas): a seção pedida vem depois das duas.
  if (want && want !== sections[0][0]) setTimeout(async () => {
    await Promise.all(document.getAnimations().map((a) => a.finished.catch(() => {})));
    goTo(want, false);
  }, 0);
}

// ----------------------------------------------------------------- perfil --

// O app inteiro usa o mesmo objeto `me`: atualiza e avisa (menu, lembrete).
function meChanged(me, res) {
  Object.assign(me, res);
  window.dispatchEvent(new Event("nexus:me"));
}

// Nome e e-mail definidos pela administração (Admin › Para empresas): a Conta só mostra.
const IDENTITY_LOCKED = "Nesta instância do Nexus, nome e e-mail são definidos pela administração. Para mudar, fale com quem administra.";
const identityLocked = (me) => !!(me.org && me.org.identity_managed);

function profilePanel(me, rerender) {
  const locked = identityLocked(me);
  const name = h("input", { type: "text", maxlength: "60", value: me.display_name || "", placeholder: me.name });
  if (locked) { name.disabled = true; name.setAttribute("aria-describedby", "name-locked"); }
  const err = errorLine();
  const file = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp", class: "hidden" });
  const pick = h("button", { type: "button", class: "btn btn-ghost btn-sm", onClick: () => file.click() }, icon("edit"), me.avatar ? "Trocar foto" : "Enviar foto");
  const remove = me.avatar ? h("button", {
    type: "button", class: "btn btn-text btn-sm", text: "Remover", onClick: async () => {
      try { meChanged(me, await api.del("/me/avatar")); toast("Foto removida."); rerender(); }
      catch (e) { errorToast(e); }
    },
  }) : null;
  file.addEventListener("change", async () => {
    const f = file.files && file.files[0];
    if (!f) return;
    pick.disabled = true;
    try {
      const blob = await squarePhoto(f);
      meChanged(me, await api.upload("/me/avatar", blob));
      toast("Foto atualizada.");
      rerender();
    } catch (e) {
      errorToast(e, "Não foi possível usar esta foto.");
    } finally {
      pick.disabled = false;
      file.value = "";
    }
  });
  // Salva ao sair do campo (ou no Enter), sem botão.
  const form = h("form", {}, field("Nome de exibição", name), locked ? null : err,
    locked ? h("p", { class: "dialog-note lock-note", id: "name-locked" }, icon("lock"), IDENTITY_LOCKED) : null);
  let saved = me.display_name || "";
  const save = saver(async () => {
    const v = name.value.trim();
    if (v === saved) return;
    fieldError(err, name, "");
    try {
      meChanged(me, await api.put("/me/profile", { display_name: v || null }));
      const before = saved;
      saved = me.display_name || "";
      name.placeholder = me.name;
      toast(`Combinado: vou chamar você de ${me.name}.`, { action: "Desfazer", onAction: async () => {
        name.value = before; await save();
      } });
    } catch (e) {
      fieldError(err, name, e.message || "Não foi possível salvar o nome.");
    }
  });
  name.addEventListener("change", save);
  form.addEventListener("submit", (ev) => { ev.preventDefault(); save(); });
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Perfil" })),
    h("div", { class: "profile-row" }, avatar(me, "lg"),
      h("div", {}, h("div", { class: "row-actions" }, pick, remove), file,
        h("p", { class: "help", text: "PNG, JPEG ou WebP. A foto é recortada em quadrado e reduzida no seu navegador antes do envio; os dados de localização dela não saem daqui." }))),
    h("p", { class: "help", text: "Aparece no menu, nas saudações e no cabeçalho dos relatórios. " + (locked ? "" :
      (me.display_name ? "Em branco, volto a usar o nome tirado do seu e-mail." : `Em branco, uso “${me.name}”, tirado do seu e-mail.`)) }),
    form);
}

// ------------------------------------------------------------- assistente --

function assistantPanel(me) {
  // Um só interruptor; o resto (lembrete de inatividade, reabrir fala fechada) é fixo.
  const falas = h("input", { type: "checkbox" });
  falas.checked = me.assistant.enabled;
  const guard = lockWhileSaving(falas);
  falas.addEventListener("change", () => guard(async () => {
    try {
      meChanged(me, { assistant: await api.put("/me/assistant", { enabled: falas.checked }) });
      toast("Assistente salvo.");
    } catch (e) { falas.checked = !falas.checked; errorToast(e, "Não foi possível salvar o assistente."); }
  }));
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Assistente" })),
    h("div", { class: "notice-row" },
      h("label", { class: "notice-main" }, falas, h("span", {}, h("strong", { text: "Falas do assistente" }),
        h("small", { text: "A saudação e os avisos do Hoje, o lembrete quando passa um tempo sem registro, a prévia do PDF em Meu mês e as notas em Tarefas e Busca. Tudo calculado a partir dos seus próprios registros." })))));
}

const TOKENS_OFF_PAGE = 10; // chaves revogadas e vencidas, recolhidas

// --------------------------------------------------------------- chamados --

function ticketsPanel(me) {
  // Definido pela administração (Admin › Para empresas): o campo fica à vista, travado, com o motivo.
  if (me.ticket_url_managed) {
    const locked = h("input", { type: "url", value: me.ticket_url || "", disabled: "disabled", "aria-describedby": "tickets-locked" });
    return h("section", { class: "panel", id: "chamados" },
      h("div", { class: "panel-head" }, h("h2", { text: "Chamados e ordens de serviço" })),
      field("Endereço do chamado ou OS", locked),
      h("p", { class: "dialog-note field-note", id: "tickets-locked" }, "Definido pela administração e vale para todos: o “#4821” das tarefas abre o chamado.",
        (me.roles || []).includes("admin") ? h("a", { href: "#/admin?aba=empresas", text: " Mudar em Admin › Para empresas." }) : " Para mudar, fale com quem administra."));
  }
  const url = h("input", { type: "url", maxlength: "300", value: me.ticket_url || "",
    placeholder: "https://glpi.empresa.com.br/front/ticket.form.php?id={id}" });
  // Salva ao sair do campo (ou no Enter); um endereço inválido fica marcado, com a frase embaixo.
  const err = errorLine();
  const save = saver(async () => {
    const v = url.value.trim();
    if (v === (me.ticket_url || "")) { fieldError(err, url, ""); return; }
    try {
      const r = await api.put("/me/tickets", { ticket_url: v || null });
      fieldError(err, url, "");
      meChanged(me, r);
      toast(r.ticket_url ? "Endereço salvo: o número do chamado vira link." : "Endereço removido.");
    } catch (e) { fieldError(err, url, e && e.status === 0 ? e.message : "Use um endereço começando com http:// ou https://."); }
  });
  url.addEventListener("change", save);
  url.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); save(); } });
  return h("section", { class: "panel", id: "chamados" },
    h("div", { class: "panel-head" }, h("h2", { text: "Chamados e ordens de serviço" })),
    h("p", { class: "help", text: "Opcional. Se a sua equipe usa um sistema de chamados ou de ordens de serviço, cole o endereço de um deles, trocando o número por {id} (ex.: https://sistema.empresa/os/{id}). Sem {id}, o número vai no fim. Com o endereço, o “#4821” das tarefas abre o chamado." }),
    field("Endereço do chamado ou OS", url), err);
}

// ---------------------------------------------------------------- atalhos --

function shortcutsPanel() {
  const keys = [["n", "nova tarefa"], ["q", "registro rápido"], ["/", "buscar"], ["h", "Hoje"], ["t", "Tarefas"], ["r", "Meu mês"],
    ["l", "Meu mês (outro período ou formato)"], ["s", "parar o cronômetro"], ["?", "ver todos os atalhos"]];
  // Desligar: para quem usa controle por voz ou esbarra numa tecla sem querer.
  const on = h("input", { type: "checkbox" });
  on.checked = singleKeysOn();
  on.addEventListener("change", () => setSingleKeys(on.checked));
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Atalhos de teclado" })),
    h("div", { class: "notice-row" },
      h("label", { class: "notice-main" }, on, h("span", {}, h("strong", { text: "Atalhos de uma tecla" }),
        h("small", { text: "Vale para este aparelho. Desligados, as letras abaixo não fazem nada." })))),
    h("dl", { class: "shortcuts" }, ...keys.flatMap(([k, l]) => [h("dt", {}, h("kbd", { text: k })), h("dd", { text: l })])),
    h("p", { class: "help", text: "Funcionam fora dos campos de texto." }));
}

// ------------------------------------------------------------- dias úteis --

function workDays(me) {
  const boxes = DAYS.map(([bit, label]) => {
    const cb = h("input", { type: "checkbox" });
    cb.checked = ((me.work_days >> bit) & 1) === 1;
    return { bit, label, cb };
  });
  const err = errorLine();
  // Salva ao marcar (vários dias seguidos viram uma gravação só); nenhum dia não vale.
  const paint = (mask) => { for (const { bit, cb } of boxes) cb.checked = ((mask >> bit) & 1) === 1; };
  const save = saver(async () => {
    const mask = boxes.reduce((m, { bit, cb }) => (cb.checked ? m | (1 << bit) : m), 0);
    if (mask === me.work_days) { fieldError(err, cbs, ""); return; }
    if (!mask) { fieldError(err, cbs, "Escolha pelo menos um dia."); return; }
    fieldError(err, cbs, "");
    const before = me.work_days;
    try {
      const res = await api.post("/auth/settings", { work_days: mask });
      me.work_days = res.work_days;
      toast("Dias úteis salvos.", { action: "Desfazer", onAction: async () => { paint(before); await save(); } });
    } catch (e) {
      paint(me.work_days);
      errorToast(e, "Não foi possível salvar os dias úteis.");
    }
  }, 700);
  const cbs = boxes.map((b) => b.cb);
  for (const cb of cbs) cb.addEventListener("change", save);
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Meus dias úteis" })),
    h("p", { class: "help", text: "As rotinas que repetem “nos dias úteis” seguem estes dias. O que você marcar fora da agenda de uma rotina fica salvo como extra e não entra no percentual. Atenção: mudar os dias úteis recalcula também os números dos dias anteriores." }),
    h("fieldset", { class: "weekday-picker" }, h("legend", { class: "sr-only", text: "Meus dias úteis" }),
      ...boxes.map(({ label, cb }) => h("label", { class: "weekday-option" }, cb, h("span", { text: label })))),
    err);
}

// ------------------------------------------------------------------ avisos --

// push: o painel das notificações dos aparelhos (grava junto, a cada mudança).
async function notices(push) {
  const p = await api.get("/notifications");
  // Um só interruptor: Seu dia (manhã, dias úteis), Antes de encerrar (se faltar rotina) e o Resumo da semana (segunda).
  const mailOn = h("input", { type: "checkbox", "aria-label": "Receber avisos por e-mail" });
  mailOn.checked = p.email_on;
  const mailRow = h("div", { class: "notice-row" }, h("label", { class: "notice-main" }, mailOn, h("span", {},
    h("strong", { text: "Receber avisos por e-mail" }),
    h("small", { text: "De manhã (nos dias úteis): atrasadas, o que vence hoje, rotinas e prioridades. No fim do dia, se faltar alguma rotina. Às segundas, o resumo da semana. Só sai e-mail quando há algo a avisar." }))));
  // Semanal: o PDF anexado e uma cópia (quem acompanha o trabalho) — só valem com o resumo da semana ligado.
  const pdf = h("input", { type: "checkbox" });
  pdf.checked = !!p.weekly_pdf;
  const cc = h("input", { type: "email", maxlength: "254", value: p.weekly_cc || "", placeholder: "ex.: colega@empresa.com.br",
    autocomplete: "off", "aria-label": "Mandar cópia do resumo semanal para" });
  const weeklyExtra = h("div", { class: "notice-sub" },
    h("label", { class: "check-line" }, pdf, h("span", { text: "Anexar o relatório da semana em PDF (o mesmo de Meu mês, com os títulos das tarefas)" })),
    field("Mandar cópia para quem acompanha meu trabalho (opcional)", cc),
    h("p", { class: "dialog-note", text: "A cópia recebe o mesmo e-mail, com o PDF se estiver ligado. Use só com quem já acompanha o seu trabalho." }));
  const syncWeekly = () => { pdf.disabled = cc.disabled = !mailOn.checked; weeklyExtra.classList.toggle("off", !mailOn.checked); };
  mailOn.addEventListener("change", syncWeekly);
  syncWeekly();
  const titles = h("input", { type: "checkbox" });
  titles.checked = p.show_titles;
  // Salva a cada mudança (e-mail e notificações juntos).
  // O e-mail da cópia salva ao sair do campo; inválido, fica marcado com a frase embaixo.
  const ccErr = errorLine();
  weeklyExtra.children[1].after(ccErr);
  const save = saver(async () => {
    const body = { show_titles: titles.checked, weekly_pdf: pdf.checked, weekly_cc: cc.value.trim() || null };
    body.email_on = mailOn.checked;
    if (body.weekly_cc && !cc.checkValidity()) { fieldError(ccErr, cc, "O e-mail da cópia não parece válido."); body.weekly_cc = p.weekly_cc || null; }
    else fieldError(ccErr, cc, "");
    try {
      await api.put("/notifications", body);
      await api.put("/push/prefs", push.collect());
      p.weekly_cc = body.weekly_cc;
      toast("Avisos salvos.");
    }
    catch (e) { if (e.status === 422) fieldError(ccErr, cc, "O e-mail da cópia não parece válido."); else errorToast(e, "Não foi possível salvar os avisos."); }
  }, 400);
  // Os testes saem com o que está salvo: antes, termina a gravação que estiver pendente.
  const test = h("button", { type: "button", class: "btn btn-ghost" }, icon("mail"), "Mandar um teste");
  test.disabled = !p.mail_configured;
  test.addEventListener("click", async () => {
    test.disabled = true;
    try { await save.flush(); const r = await api.post("/notifications/test"); toast(`Teste enviado para ${r.to}.`); }
    catch (e) { errorToast(e, "Não foi possível enviar."); }
    finally { setTimeout(() => { test.disabled = false; }, 4000); }
  });
  // A semana passada como sairia na segunda (só para você; a cópia não recebe).
  const testWeek = h("button", { type: "button", class: "btn btn-ghost", title: "A semana passada como sairia na segunda, só para você" },
    icon("reports"), "Testar a semana");
  testWeek.disabled = !p.mail_configured;
  testWeek.addEventListener("click", async () => {
    testWeek.disabled = true;
    try { await save.flush(); const r = await api.post("/notifications/test?kind=weekly"); toast(`Semana enviada para ${r.to}.`); }
    catch (e) { errorToast(e, "Não foi possível enviar."); }
    finally { setTimeout(() => { testWeek.disabled = false; }, 4000); }
  });
  // Só um alerta, e só quando o último envio falhou (o detalhe está em Admin › Saúde do Nexus).
  const last = p.recent.find((r) => r.ok !== null || r.error !== "nada a avisar");
  const failedMail = last && last.ok === false
    ? warnBox(`O último e-mail não saiu (${dateTime(last.sent_at)}). Quem administra pode ver em Saúde do Nexus.`) : null;
  const mailPanel = h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "Avisos por e-mail" })),
      h("p", { class: "help" }, "Enviados para ", h("strong", { class: "mono", text: p.email }),
        ". Sem rastreamento de abertura ou de cliques; só sai e-mail quando há algo a avisar."),
      p.mail_configured ? null : warnBox("O envio de e-mail ainda não está configurado neste servidor. Você pode deixar tudo escolhido; os avisos começam quando ele for ligado."),
      failedMail, mailRow, weeklyExtra,
      h("label", { class: "check-line notice-titles" }, titles, h("span", { text: "Mostrar os títulos das tarefas no e-mail (desligado: só os números)" })),
      h("div", { class: "row-actions" }, test, testWeek));
  // Qualquer escolha dos dois painéis (a cópia, ao sair do campo) grava.
  for (const panel of [push, mailPanel]) panel.addEventListener("change", (e) => { if (e.target.matches("input, select")) save(); });
  return h("div", { class: "settings-grid" }, push, mailPanel);
}

// -------------------------------------------------------------- calendário --

async function calendarFeed(rerender) {
  const st = await api.get("/calendar");
  const rec = h("input", { type: "checkbox" });
  rec.checked = st.active ? st.include_recurring : true;
  const panel = h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Calendário" })),
    h("p", { class: "help", text: "Assine o Nexus no Google Agenda, Outlook ou no celular: os prazos das tarefas abertas aparecem como eventos de dia inteiro e as rotinas como eventos repetidos. A agenda atualiza sozinha (o Google pode levar algumas horas)." }),
    h("label", { class: "check-line" }, rec, h("span", { text: "Incluir as rotinas" })));

  if (!st.active) {
    panel.append(h("div", { class: "row-actions" }, h("button", { type: "button", class: "btn btn-primary", onClick: async () => {
      try { showFeed(await api.post("/calendar", { include_recurring: rec.checked })); rerender(); }
      catch (e) { errorToast(e); }
    } }, icon("calendar"), "Criar link do calendário")));
    return h("div", { class: "settings-grid" }, panel);
  }
  rec.addEventListener("change", async () => {
    try { await api.patch("/calendar", { include_recurring: rec.checked }); toast("Calendário atualizado."); }
    catch (e) { rec.checked = !rec.checked; errorToast(e); }
  });
  panel.append(
    h("div", { class: "token-row" },
      h("span", { class: "token-name", text: "Link ativo" }),
      h("div", { class: "actions" },
        h("button", { type: "button", class: "btn btn-ghost btn-sm", text: "Gerar novo link", onClick: async () => {
          if (!(await confirmDialog({ title: "Gerar um novo link?", text: "O link atual para de funcionar: as agendas que o assinam precisam do novo.", confirm: "Gerar novo" }))) return;
          try { showFeed(await api.post("/calendar", { include_recurring: rec.checked })); rerender(); } catch (e) { errorToast(e); }
        } }),
        h("button", { type: "button", class: "btn btn-danger btn-sm", text: "Revogar", onClick: async () => {
          if (!(await confirmDialog({ title: "Revogar o link do calendário?", text: "As agendas que o assinam deixam de receber atualizações.", confirm: "Revogar", danger: true }))) return;
          try { await api.del("/calendar"); toast("Link revogado."); rerender(); } catch (e) { errorToast(e); }
        } })),
      h("span", { class: "token-meta", text: `${st.prefix}… · criado ${dateTime(st.created_at)} · ${st.last_used_at ? "última leitura " + dateTime(st.last_used_at) : "ainda não lido por nenhuma agenda"}` })),
    h("p", { class: "dialog-note", text: "O link completo só aparece quando é criado. Perdeu? Gere um novo." }));
  return h("div", { class: "settings-grid" }, panel);
}

function showFeed(res) {
  const url = location.origin + res.path;
  const webcal = url.replace(/^https?:/, "webcal:");
  const dlg = modal(
    h("h2", { text: "Link do calendário" }),
    h("p", { text: "Copie agora: ele não aparece de novo. Quem tiver o link vê seus prazos e rotinas." }),
    codeBox(url),
    h("p", { class: "dialog-note", text: "Google Agenda: Outras agendas > + > Do URL > cole o link." }),
    h("p", { class: "dialog-note", text: "Outlook: Adicionar calendário > Assinar da Web." }),
    h("p", { class: "dialog-note" }, "iPhone/Mac: ", h("a", { href: webcal, text: "abrir no Calendário" }), "."),
    h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-primary", text: "Pronto", onClick: () => dlg.close() })));
}

// ----------------------------------------------------------- chaves de API --

// Escopo da chave: [opção no formulário, na lista, o que explica embaixo].
const SCOPES = {
  write: ["Ler e registrar (recomendado para IA)", "ler e registrar", "Faz tudo o que você faz nas suas tarefas, rotinas e projetos, inclusive editar e excluir (tudo fica no Histórico, com desfazer)."],
  append: ["Só registrar (não altera nem exclui)", "só registrar", "Cria tarefas, anota, adiciona item de checklist, aponta tempo, usa o cronômetro, marca rotinas e conclui. Não edita, não desmarca e não exclui nada: bom para uma IA que só anota o que você contar ou para um alerta automático."],
  read: ["Só leitura", "só leitura", "Só consulta (resumos, tarefas, histórico); não muda nada."],
};

const VALIDADES = [["30", "30 dias"], ["90", "90 dias"], ["180", "180 dias"], ["365", "1 ano"], ["", "sem validade"]];

async function tokens(rerender) {
  const list = await api.get("/tokens");
  const name = h("input", { type: "text", maxlength: "60", placeholder: "Ex.: Claude do notebook", required: "required" });
  const scope = h("select", {}, ...Object.entries(SCOPES).map(([v, [t]]) => h("option", { value: v, text: t })));
  const scopeNote = h("p", { class: "dialog-note field-note", "aria-live": "polite" });
  const syncScope = () => { scopeNote.textContent = SCOPES[scope.value][2]; };
  scope.addEventListener("change", syncScope);
  syncScope();
  const expires = h("select", {}, ...VALIDADES.map(([v, t]) => h("option", { value: v, text: t })));
  expires.value = "90";
  const err = h("p", { class: "error-text" });
  const create = h("button", { type: "submit", class: "btn btn-primary" }, icon("key"), "Criar chave");
  const form = h("form", {},
    field("Nome (para reconhecer no histórico)", name),
    h("div", { class: "field-row" },
      field("O que a chave pode fazer", scope),
      field("Validade", expires)),
    scopeNote, err, create);
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    create.disabled = true;
    try {
      const res = await api.post("/tokens", {
        name: name.value.trim(), scope: scope.value,
        expires_in_days: expires.value ? Number(expires.value) : null,
      });
      showNewToken(res);
      rerender();
    } catch (e) {
      err.textContent = e.message || "Não foi possível criar.";
      create.disabled = false;
    }
  }));

  const rowOf = (t) => {
    const meta = [
      `${t.prefix}…`, (SCOPES[t.scope] || SCOPES.read)[1],
      t.expires_at ? `vence ${dateTime(t.expires_at).slice(0, 5)}` : "sem validade",
      t.last_used_at ? `usada ${dateTime(t.last_used_at)}` : "nunca usada",
    ];
    if (t.revoked_at) meta.push("revogada");
    else if (!t.active) meta.push("vencida");
    const actions = h("div", { class: "actions" });
    if (t.active) {
      actions.append(h("button", {
        type: "button", class: "btn btn-danger btn-sm", text: "Revogar", onClick: async () => {
          if (!(await confirmDialog({ title: `Revogar “${t.name}”?`, text: "Quem estiver usando esta chave perde o acesso na hora. Não dá para desfazer.", confirm: "Revogar", danger: true }))) return;
          try { await api.del(`/tokens/${t.id}`); toast("Chave revogada."); rerender(); }
          catch (e) { errorToast(e); }
        },
      }));
    } else if (!t.revoked_at) {
      actions.append(h("button", { type: "button", class: "btn btn-ghost btn-sm", text: "Renovar", "aria-label": `Renovar a chave ${t.name}`,
        onClick: () => renewToken(t, rerender) }));
    }
    // "O que esta chave fez": o Histórico só com o que ela fez (desfazer continua item a item).
    const n = t.actions_7d || 0;
    actions.prepend(h("a", { class: "btn btn-ghost btn-sm", href: `#/historico?chave=${t.id}`, text: "O que fez",
      "aria-label": `O que a chave ${t.name} fez (${n} ${n === 1 ? "ação" : "ações"} nos últimos 7 dias)` }));
    if (n) meta.push(`${n} ${n === 1 ? "ação" : "ações"} em 7 dias`);
    return h("div", { class: "token-row" + (t.active ? "" : " inactive") },
      h("span", { class: "token-name", text: t.name }), actions, h("span", { class: "token-meta", text: meta.join(" · ") }));
  };
  // As ativas, todas; as revogadas e vencidas se acumulam: recolhidas, de 10 em 10.
  const ativas = list.filter((t) => t.active), inativas = list.filter((t) => !t.active);
  const rows = list.length ? ativas.map(rowOf) : [h("p", { class: "empty", text: "Nenhuma chave ainda." })];
  if (list.length && !ativas.length) rows.push(h("p", { class: "empty", text: "Nenhuma chave ativa." }));
  if (inativas.length) {
    const box = h("div");
    const summary = h("summary", {}, `Antigas (${inativas.length})`, h("small", { text: "vencidas e revogadas; uma vencida pode ser renovada" }));
    let page = hashPage("pi");
    const paint = () => {
      clear(box);
      const slice = pageSlice(inativas, page, TOKENS_OFF_PAGE);
      page = slice.page;
      setHashPage("pi", page, "config");
      box.append(...slice.rows.map(rowOf));
      const nav = pager({ page, total: inativas.length, size: TOKENS_OFF_PAGE, label: "chaves revogadas e vencidas", compact: true,
        onPage: (n) => { page = n; paint(); }, focus: summary });
      if (nav) box.append(nav);
    };
    paint();
    rows.push(h("details", { class: "requests-decided tokens-off", open: page > 1 ? "open" : null }, summary, box));
  }

  return h("div", { class: "settings-grid" },
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "Nova chave" })),
      h("p", { class: "help", text: "Em vez de registrar à mão, conte para a IA o que você fez e ela registra no Nexus. Uma chave deixa uma IA ou automação usar o Nexus em seu nome, sem a sua senha; tudo o que ela fizer aparece no Histórico com o nome que você der aqui. Ao criar, a janela já traz a configuração pronta para o Claude Code, o Claude Desktop, o Cursor e o Gemini CLI." }),
      form),
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "Minhas chaves" }), h("span", { class: "count", text: (() => { const n = list.filter((t) => t.active).length; return n + (n === 1 ? " ativa" : " ativas"); })() })),
      ...rows));
}

// Chave vencida: nova validade a partir de hoje, a mesma chave (a IA não precisa ser reconfigurada).
function renewToken(t, rerender) {
  const expires = h("select", {}, ...VALIDADES.map(([v, l]) => h("option", { value: v, text: l })));
  expires.value = "90";
  const err = h("p", { class: "error-text", role: "alert" });
  const form = h("form", {}, h("h2", { text: `Renovar “${t.name}”` }),
    h("p", { class: "dialog-note", text: "A mesma chave volta a funcionar, com a validade nova contada a partir de hoje: quem usa essa chave (a IA, a automação) não precisa ser configurado de novo." }),
    field("Nova validade", expires), err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
      h("button", { type: "submit", class: "btn btn-primary", text: "Renovar" })));
  const dlg = modal(form);
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    try {
      await api.post(`/tokens/${t.id}/renew`, { expires_in_days: expires.value ? Number(expires.value) : null });
      dlg.close();
      toast(`Chave “${t.name}” renovada.`);
      rerender();
    } catch (e) { err.textContent = e.message || "Não foi possível renovar."; }
  }));
  setTimeout(() => expires.focus(), 0);
}

// O bloco de configuração de cada IA, com a chave (ou nxs_SUA_CHAVE, na ajuda).
function aiConfigs(key) {
  const url = `${location.origin}/mcp`;
  const desktop = { command: "npx", args: ["-y", "mcp-remote", url, "--header", "Authorization:${NEXUS_AUTH}"], env: { NEXUS_AUTH: `Bearer ${key}` } };
  return {
    code: `claude mcp add --scope user --transport http nexus ${url} --header "Authorization: Bearer ${key}"`,
    desktop: JSON.stringify({ mcpServers: { nexus: desktop } }, null, 2),
    desktopMerge: JSON.stringify({ preferences: { "...": "o que já estava aqui" }, mcpServers: { "outro-servidor": { "...": "o que já estava aqui" }, nexus: desktop } }, null, 2),
    cursor: JSON.stringify({ mcpServers: { nexus: { url, headers: { Authorization: `Bearer ${key}` } } } }, null, 2),
    gemini: JSON.stringify({ mcpServers: { nexus: { httpUrl: url, headers: { Authorization: `Bearer ${key}` } } } }, null, 2),
  };
}

// Arquivo de configuração que já tem conteúdo: juntar, não substituir (Desktop, Cursor, Gemini CLI).
const MERGE_NOTE = "Arquivo com outro conteúdo? Já existe \"mcpServers\": cole só o trecho \"nexus\": { … } dentro dele, com uma vírgula entre os servidores. Não existe: acrescente \"mcpServers\": { … } inteiro como mais um item, separado por vírgula.";

// Chave criada: a chave e o bloco pronto da IA escolhida (já com a chave), cada um com Copiar.
function showNewToken(res) {
  const cfg = aiConfigs(res.token);
  const AIS = [
    ["Claude Code", ["No terminal, rode (vale em qualquer pasta):"], cfg.code],
    ["Claude Desktop", ["Precisa do Node.js instalado (versão LTS, em ",
      h("a", { href: "https://nodejs.org", target: "_blank", rel: "noopener noreferrer", text: "nodejs.org" }),
      "). Depois, cole em claude_desktop_config.json (Configurações > Desenvolvedor > Editar configuração) e reabra o Claude Desktop. " + MERGE_NOTE], cfg.desktop],
    ["Cursor", ["Cole em mcp.json, na pasta .cursor da sua pasta de usuário (ou em Cursor Settings > MCP > Add new global MCP server). " + MERGE_NOTE], cfg.cursor],
    ["Gemini CLI", ["Abra settings.json, na pasta .gemini da sua pasta de usuário. Depois do primeiro login ele já tem conteúdo (o login, o tema): não cole por cima. " + MERGE_NOTE], cfg.gemini],
  ];
  // Sem abas: cada IA recolhida (uma aberta por vez), com a nota e o bloco pronto.
  const configs = AIS.map(([name, note, code], i) => h("details", { class: "ai-config", name: "ai-config", open: i === 0 ? "open" : null },
    h("summary", { text: name }), h("p", { class: "dialog-note" }, ...note), codeBox(code)));
  const dlg = modal(
    h("h2", { text: "Chave criada" }),
    h("p", { text: `“${res.name}” — copie agora: ela não aparece de novo.` }),
    h("div", { class: "token-box", text: res.token }),
    h("p", { class: "dialog-note ai-tabs-note", text: "Configuração pronta, já com a chave. Abra a da sua IA:" }),
    ...configs,
    warnBox("Trate como senha: não cole em repositório, print ou chat. Se vazar, revogue aqui."),
    h("div", { class: "dialog-actions" },
      h("button", {
        type: "button", class: "btn btn-ghost", onClick: async () => {
          try { await navigator.clipboard.writeText(res.token); toast("Chave copiada."); }
          catch { toast("Selecione e copie manualmente.", { error: true }); }
        },
      }, icon("copy"), "Copiar chave"),
      h("button", { type: "button", class: "btn btn-primary", text: "Pronto", onClick: () => dlg.close() })));
}

// --------------------------------------------------------------- webhooks --

// Webhook: o Nexus avisa outro sistema (chamados, chat, planilha) a cada mudança.
async function webhooksPanel(rerender) {
  const list = await api.get("/webhooks");
  const url = h("input", { type: "url", maxlength: "500", placeholder: "https://exemplo.com/nexus", required: "required" });
  const events = eventsPicker(["*"]);
  const err = h("p", { class: "error-text" });
  const create = h("button", { type: "submit", class: "btn btn-primary" }, icon("send"), "Criar webhook");
  const form = h("form", {}, field("Endereço (https)", url), events.el, err, create);
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    const evs = events.value();
    if (!evs) { err.textContent = "Escolha pelo menos um evento."; return; }
    create.disabled = true;
    try {
      const res = await api.post("/webhooks", { url: url.value.trim(), events: evs });
      showNewSecret(res);
      rerender();
    } catch (e) {
      err.textContent = e.message || "Não foi possível criar.";
      create.disabled = false;
    }
  }));

  const rows = list.length ? list.map((w) => {
    const meta = [eventsLabel(w.events), w.last_delivered_at ? `entregue ${dateTime(w.last_delivered_at)}` : "nada entregue ainda"];
    if (w.disabled_at) meta.push(`desligado: ${w.last_error || "falhas seguidas"}`);
    else if (w.failures) meta.push(`${w.failures} falha(s): ${w.last_error}`);
    const actions = h("div", { class: "actions" });
    const result = h("p", { class: "token-meta wh-test", role: "status" });
    const test = h("button", {
      type: "button", class: "btn btn-ghost btn-sm", text: "Testar",
      title: "Envia agora um aviso de teste (ping), assinado, e mostra a resposta",
      onClick: async () => {
        test.disabled = true;
        result.className = "token-meta wh-test";
        result.textContent = "Enviando o teste…";
        try {
          const r = await api.post(`/webhooks/${w.id}/test`);
          result.classList.add(r.ok ? "ok" : "bad");
          result.textContent = r.ok ? `Chegou: o destino respondeu HTTP ${r.status} em ${r.ms} ms.`
            : `Não chegou: ${r.error} (${r.ms} ms). O teste não conta como falha.`;
        } catch (e) {
          result.classList.add("bad");
          result.textContent = e.message || "Não foi possível testar.";
        } finally { test.disabled = false; }
      },
    });
    actions.append(test, h("button", { type: "button", class: "btn btn-ghost btn-sm", text: "Editar", "aria-label": "Editar o webhook " + w.url,
      onClick: () => editWebhook(w, rerender) }));
    if (w.disabled_at) {
      actions.append(h("button", {
        type: "button", class: "btn btn-ghost btn-sm", text: "Religar", onClick: async () => {
          try { await api.post(`/webhooks/${w.id}/enable`); toast("Webhook religado: continua de onde parou."); rerender(); }
          catch (e) { errorToast(e); }
        },
      }));
    }
    actions.append(h("button", {
      type: "button", class: "btn btn-danger btn-sm", text: "Excluir", onClick: async () => {
        if (!(await confirmDialog({ title: "Excluir o webhook?", text: `${w.url} deixa de receber os avisos na hora.`, confirm: "Excluir", danger: true }))) return;
        try { await api.del(`/webhooks/${w.id}`); toast("Webhook excluído."); rerender(); }
        catch (e) { errorToast(e); }
      },
    }));
    return h("div", { class: "token-row" + (w.active ? "" : " inactive") },
      h("span", { class: "token-name", text: w.url }), actions, h("span", { class: "token-meta", text: meta.join(" · ") }), result);
  }) : [h("p", { class: "empty", text: "Nenhum webhook ainda." })];

  return h("div", { class: "settings-grid" },
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "Avisar outro sistema (webhook)" })),
      h("p", { class: "help", text: "Webhook: o Nexus avisa outro sistema na hora em que algo muda (tarefa criada, concluída, rotina marcada…), enviando os dados para o endereço que você informar. Serve para fechar o chamado, avisar no chat ou alimentar uma planilha. Até 5. Quem configura o outro sistema encontra os detalhes na documentação da API." }),
      form),
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "Meus webhooks" }), h("span", { class: "count", text: String(list.filter((w) => w.active).length) + " ativos" })),
      ...rows, recipesLine()));
}

// Os eventos que dá para marcar (os nomes do histórico). "Tudo" e "… : tudo" cobrem os de dentro.
const WH_EVENTS = [
  ["*", "Tudo", "qualquer mudança, inclusive as que o Nexus ganhar depois"],
  ["worklog.*", "Tarefas: tudo", "criar, editar, concluir, excluir, receber"],
  ["worklog.create", "Tarefa criada"],
  ["worklog.finish", "Tarefa concluída"],
  ["worklog.update", "Tarefa editada", "inclui reabrir e marcar como aguardando"],
  ["worklog.delete", "Tarefa excluída"],
  ["worklog.assign", "Tarefa recebida", "atribuída a você por alguém"],
  ["assign.returned", "Tarefa devolvida", "uma que você atribuiu voltou, com o motivo"],
  ["note.*", "Anotações"],
  ["checklist.*", "Checklist"],
  ["time.*", "Tempo apontado"],
  ["timer.*", "Cronômetro"],
  ["photo.*", "Fotos"],
  ["recurring.*", "Rotinas", "marcar, criar, editar, pausar e a hora da rotina"],
  ["recurring.due", "Hora da rotina", "o horário chegou e ela ainda não foi marcada (uma vez por dia)"],
  ["followup.*", "Dia de cobrar", "uma tarefa aguardando chegou no dia de cobrar (de manhã)"],
  ["project.*", "Projetos"],
  ["objective.*", "Objetivos"],
  ["renewal.*", "Vencimentos", "cadastrar, editar, renovar e o aviso"],
  ["renewal.warning", "Vencimento no aviso", "entrou na antecedência que você definiu (de manhã, uma vez)"],
];
const WH_NAME = Object.fromEntries(WH_EVENTS.map(([k, l]) => [k, l]));
const eventsLabel = (evs) => evs.map((e) => WH_NAME[e] || e).join(", ");

// Lista para marcar os eventos (sem digitar nomes). Um evento que veio pela API e
// não está na lista aparece também, marcado, com o nome técnico.
function eventsPicker(selected) {
  const sel = new Set(selected);
  const items = [...WH_EVENTS, ...selected.filter((e) => !WH_NAME[e]).map((e) => [e, e, "definido pela API"])];
  const boxes = items.map(([key, label, help]) => {
    const cb = h("input", { type: "checkbox", value: key });
    cb.checked = sel.has(key);
    const line = h("label", { class: "check-line wh-ev" + (key.endsWith(".*") || key === "*" ? " group" : " sub") }, cb,
      h("span", {}, label, help ? h("small", { text: help }) : null));
    return { key, cb, line };
  });
  // Marcado o grupo, os de dentro já estão incluídos: ficam marcados e travados.
  const covered = (key) => {
    const all = boxes.find((b) => b.key === "*").cb.checked;
    if (key !== "*" && all) return true;
    const grp = key.includes(".") && !key.endsWith(".*") ? boxes.find((b) => b.key === key.split(".")[0] + ".*") : null;
    return !!(grp && grp.cb.checked);
  };
  const sync = () => {
    for (const b of boxes) {
      const c = covered(b.key);
      b.cb.disabled = c;
      b.line.classList.toggle("covered", c);
      if (c) b.cb.setAttribute("aria-description", "já incluído pelo grupo marcado"); else b.cb.removeAttribute("aria-description");
    }
  };
  for (const b of boxes) b.cb.addEventListener("change", sync);
  sync();
  const el = h("fieldset", { class: "wh-events" }, h("legend", { class: "field-label", text: "Avisar quando" }),
    h("div", { class: "wh-events-grid" }, ...boxes.map((b) => b.line)));
  return {
    el,
    value() {
      const picked = boxes.filter((b) => b.cb.checked && !covered(b.key)).map((b) => b.key);
      return picked.length ? picked : null;
    },
  };
}

// Editar um webhook (endereço e eventos) sem recriar: o segredo continua o mesmo.
function editWebhook(w, rerender) {
  const url = h("input", { type: "url", maxlength: "500", required: "required", value: w.url });
  const events = eventsPicker(w.events);
  const err = h("p", { class: "error-text", role: "alert" });
  const form = h("form", {}, h("h2", { text: "Editar webhook" }),
    h("p", { class: "dialog-note", text: "O segredo continua o mesmo: o outro sistema não precisa ser configurado de novo." }),
    field("Endereço (https)", url), events.el, err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
      h("button", { type: "submit", class: "btn btn-primary", text: "Salvar" })));
  const dlg = modal(form);
  dlg.classList.add("wh-dialog");
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    const evs = events.value();
    if (!evs) { err.textContent = "Escolha pelo menos um evento."; return; }
    try {
      await api.patch(`/webhooks/${w.id}`, { url: url.value.trim(), events: evs });
      dlg.close();
      toast("Webhook salvo. O segredo continua o mesmo.");
      rerender();
    } catch (e) { err.textContent = e.message || "Não foi possível salvar."; }
  }));
  setTimeout(() => url.focus(), 0);
}

// Receitas prontas ficam no site (a página da API tem as completas): só um link.
function recipesLine() {
  return h("p", { class: "help" }, h("a", { href: "https://shadow.tec.br/nexus-api#r-alerta", target: "_blank", rel: "noopener noreferrer", text: "Receitas na página da API" }),
    ": avisar o Telegram, mandar e-mail, registrar numa planilha, alerta que vira tarefa.");
}

function showNewSecret(res) {
  const dlg = modal(
    h("h2", { text: "Webhook criado" }),
    h("p", { text: "Segredo de assinatura — copie agora: ele não aparece de novo." }),
    h("div", { class: "token-box", text: res.secret }),
    h("p", { class: "dialog-note", text: "Entregue este segredo a quem configura o outro sistema: ele confirma que o aviso veio mesmo do Nexus (assinatura HMAC-SHA256 no cabeçalho X-Nexus-Signature)." }),
    h("div", { class: "dialog-actions" },
      h("button", {
        type: "button", class: "btn btn-ghost", onClick: async () => {
          try { await navigator.clipboard.writeText(res.secret); toast("Segredo copiado."); }
          catch { toast("Selecione e copie manualmente.", { error: true }); }
        },
      }, icon("copy"), "Copiar segredo"),
      h("button", { type: "button", class: "btn btn-primary", text: "Pronto", onClick: () => dlg.close() })));
}

// ------------------------------------------------------- integração com IA --

function aiHelp() {
  const cfg = aiConfigs("nxs_SUA_CHAVE");
  return [
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "Use o Nexus pela sua IA" })),
      h("p", { class: "help", text: "Conte para a IA o que você fez (“troquei o disjuntor do quadro 3 e fiz a ronda da manhã”) e ela registra no Nexus. O Nexus fala MCP, a forma padrão de uma IA usar outros programas." }),
      h("p", { class: "help", text: "1. Crie uma chave em Nova chave, acima (opção “Ler e registrar”): a janela já mostra a configuração pronta de cada IA. 2. Precisa de novo depois? Cole a configuração abaixo, trocando nxs_SUA_CHAVE pela chave:" }),
      h("p", { class: "dialog-note", text: "Claude Code (terminal; com --scope user vale em qualquer pasta):" }),
      codeBox(cfg.code),
      h("p", { class: "dialog-note", text: "Cursor (arquivo mcp.json, na pasta .cursor da sua pasta de usuário, ou Cursor Settings > MCP > Add new global MCP server) e outros programas que aceitam endereço e cabeçalho. Arquivo com outro conteúdo: veja a nota do Claude Desktop, abaixo; vale igual." }),
      codeBox(cfg.cursor),
      h("p", { class: "dialog-note", text: "Claude Desktop (o aplicativo do Claude no computador), passo a passo:" }),
      h("ol", { class: "help" },
        h("li", {}, "Instale o Node.js (versão LTS, a recomendada) pelo site ",
          h("a", { href: "https://nodejs.org", target: "_blank", rel: "noopener noreferrer", text: "nodejs.org" }), ". É um instalador comum: é só avançar até o fim."),
        h("li", { text: "No Claude Desktop, abra Configurações > Desenvolvedor > Editar configuração. Abre a pasta do arquivo claude_desktop_config.json: abra esse arquivo no Bloco de Notas (no Mac, no TextEdit)." }),
        h("li", { text: "Se o arquivo estiver vazio ou só com {}, apague tudo e cole o bloco abaixo. Se já tiver outro conteúdo, veja a nota logo depois do bloco." }),
        h("li", { text: "Salve, feche o Claude Desktop por completo e abra de novo. Para conferir, pergunte “o que tenho hoje no Nexus?”: o nexus aparece no ícone de ferramentas, abaixo da caixa de mensagem." })),
      codeBox(cfg.desktop),
      h("p", { class: "help", text: "Vale para os três arquivos (Claude Desktop, Cursor e Gemini CLI). Se o arquivo já tiver conteúdo, não cole por cima nem no fim: o arquivo deixa de valer e o aplicativo abre sem o Nexus. Já existe \"mcpServers\"? Copie só o trecho \"nexus\": { … } e cole dentro dele, depois do último servidor, com uma vírgula entre os dois. Não existe? Acrescente \"mcpServers\": { … } inteiro como mais um item, também separado por vírgula. Exemplo de um arquivo que já tinha outras coisas:" }),
      codeBox(cfg.desktopMerge),
      h("p", { class: "dialog-note", text: "Gemini CLI (o Gemini que roda no terminal; arquivo settings.json dentro da pasta .gemini, na sua pasta de usuário). Depois do primeiro login esse arquivo já tem conteúdo: junte como na nota acima, sem colar por cima." }),
      codeBox(cfg.gemini),
      h("p", { class: "help", text: "O aplicativo e o site do Gemini (gemini.google.com), o ChatGPT e o Claude no navegador (claude.ai) ainda não ligam no Nexus: os conectores deles pedem um tipo de login (OAuth) que o Nexus não tem. Do Gemini, só o Gemini CLI funciona; nos outros, use um dos programas acima ou a API." })),
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "O que a IA pode fazer" })),
      h("p", { class: "help", text: "Ver o dia e os períodos, buscar, criar, editar e concluir tarefas e rotinas, anotar, apontar tempo, montar projetos e objetivos e consultar ou desfazer o histórico." }),
      h("p", { class: "help", text: "Pelo MCP ela não exclui nada; a chave “ler e registrar” também vale para a API, que exclui (volta pelo Histórico). Para só consultar, crie uma chave “só leitura”." }),
      h("p", { class: "help" }, h("a", { href: "https://shadow.tec.br/nexus-api#mcp", target: "_blank", rel: "noopener noreferrer", text: "Lista completa na documentação" }), "."),
      h("p", { class: "dialog-note", text: "API REST direta (scripts, automações):" }),
      codeBox(`curl -H "Authorization: Bearer nxs_SUA_CHAVE" ${location.origin}/api/board`)),
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "Comandos prontos" })),
      h("p", { class: "help", text: "O Nexus oferece dois comandos para a IA: o resumo da semana (para o time, um cliente ou quem acompanha seu trabalho) e o resumo para a equipe (ontem, hoje e o que está aguardando). No Claude Code eles aparecem como comandos de barra (o /mcp__nexus__daily é o resumo para a equipe):" }),
      codeBox("/mcp__nexus__resumo_semanal o cliente\n/mcp__nexus__daily"),
      h("p", { class: "dialog-note", text: "Em outras IAs, cole o pedido:" }),
      codeBox("Use o Nexus (get_summary e get_today) e escreva um resumo da minha semana para quem acompanha meu trabalho: o que foi entregue por projeto, o tempo por projeto, o que segue em andamento e o que está aguardando. Só com o que está registrado.")),
  ];
}

// ------------------------------------------------------- tarefas atribuídas --

// Os dois aceites num painel só: sem eles, ninguém atribui tarefas nem vê o registro.
function privacyPanel(me) {
  const who = api.get("/me/visibility").catch(() => null); // uma leitura para as duas partes
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Quem vê o seu registro e quem atribui tarefas a você" })),
    ...teamsLine(me),
    h("h3", { class: "sum-h", text: "Receber tarefas" }), ...assignments(me, who),
    h("h3", { class: "sum-h", text: "Ver o seu registro" }), ...seenBy(me, who),
    // Política de privacidade da instância (Admin › Para empresas), quando definida.
    me.privacy_url && /^https:\/\//.test(me.privacy_url)
      ? h("p", { class: "dialog-note" }, h("a", { class: "privacy-link", href: me.privacy_url, target: "_blank", rel: "noopener", text: "Política de privacidade desta instância" }))
      : null);
}

// Equipes da pessoa (só leitura; quem define é a administração, Admin › Equipes).
// Só aparece quando a instância tem equipes.
function teamsLine(me) {
  if (!me.teams_on) return [];
  const mine = me.teams || [];
  return [h("h3", { class: "sum-h", text: "Suas equipes" }),
    h("p", { class: "help account-teams-line" }, mine.length
      ? [h("strong", { text: mine.join(", ") }), " (definido pela administração). Só quem está numa equipe com você — e o admin master, se tiver os papéis ativos — pode ver o seu registro ou atribuir tarefas para você."]
      : ["Você ainda não está em nenhuma equipe (quem define é a administração). Assim, só o admin master pode ver o seu registro ou atribuir tarefas para você, e só se você permitir aqui. As opções da empresa não valem para você: tudo depende das suas escolhas abaixo."])];
}

// Consentimento: sem ele, ninguém consegue atribuir tarefas para esta pessoa.
// "Todos recebem de quem atribui" (Admin › Para empresas): a chave fica
// bloqueada, à vista, com o motivo; a escolha fica guardada para quando voltar.
function assignments(me, who) {
  const managed = !!(me.org && me.org.assign_receive === "all");
  const cb = h("input", { type: "checkbox" });
  cb.checked = managed || !!me.accepts_assignments_at;
  if (managed) { cb.disabled = true; cb.setAttribute("aria-describedby", "assign-locked"); }
  const since = h("p", { class: "dialog-note" });
  const sync = () => {
    since.textContent = managed
      ? "Cada tarefa recebida chega por e-mail e aparece em Tarefas com “de” e o nome de quem atribuiu."
      : me.accepts_assignments_at
      ? `Aceito desde ${dateTime(me.accepts_assignments_at)}. Cada tarefa recebida chega por e-mail e aparece em Tarefas com “de” e o nome de quem atribuiu.`
      : "Desligado: ninguém pode atribuir tarefas a você.";
  };
  sync();
  const guard = lockWhileSaving(cb); // gravando: aria-disabled (o foco fica na chave)
  cb.addEventListener("change", () => guard(async () => {
    try {
      const res = await api.put("/me/assignments", { accept: cb.checked });
      meChanged(me, res);
      sync();
      toast(cb.checked ? "Pronto: você aceita tarefas atribuídas." : "Você não recebe mais tarefas atribuídas. As já recebidas continuam com você.");
    } catch (e) { cb.checked = !cb.checked; errorToast(e); }
  }));
  const lock = managed ? h("p", { class: "dialog-note lock-note", id: "assign-locked" }, icon("lock"),
    (me.teams_on ? "Nesta instância do Nexus, quem está numa equipe recebe tarefas de quem atribui nela (definido pela administração). "
      : "Nesta instância do Nexus, todos recebem tarefas de quem atribui (definido pela administração). ") +
    `A sua escolha (${me.accepts_assignments_at ? "permitir" : "não permitir"}) fica guardada e volta a valer se isso mudar${me.teams_on ? " ou se você sair das equipes" : ""}.`) : null;
  // Transparência: quem pode atribuir tarefas para você agora (o servidor aplica a regra).
  const now = h("p", { class: "dialog-note" });
  if (who) who.then((list) => {
    if (!list) { now.remove(); return; }
    const names = list.filter((p) => p.assigns).map((p) => p.name);
    now.textContent = `Quem pode atribuir tarefas para você agora: ${names.length ? names.join(", ") : "ninguém"}.`;
  });
  return [
    h("p", { class: "help", text: (managed ? "Quem tem o papel “Manda tarefas” (tela Equipe) pode atribuir tarefas para você."
      : "Quem tem o papel “Manda tarefas” (tela Equipe) pode atribuir tarefas para você, mas só se você permitir aqui.") +
      " A tarefa recebida é sua: você edita, conclui, exclui ou devolve com o motivo. Quem atribuiu só corrige ou cancela enquanto ela está a fazer e você não registrou nada nela." }),
    h("label", { class: "check-line" + (managed ? " is-locked" : "") }, cb, h("span", { text: "Permitir que me atribuam tarefas" })),
    lock, since, now];
}

// --------------------------------------------------------- excluir a conta --

// LGPD: a pessoa apaga a conta e tudo o que registrou, com a senha. Sem volta.
function deleteAccount(isUser) {
  const pw = h("input", { type: "password", autocomplete: "current-password", required: "required", maxlength: "128" });
  const err = h("p", { class: "error-text" });
  const form = h("form", {},
    h("p", { class: "help", text: "Apaga a sua conta e tudo o que está nela: tarefas, rotinas, tempo apontado, anotações, chaves de API e histórico. Não dá para desfazer." }),
    isUser ? h("p", { class: "dialog-note" }, "Quer guardar uma cópia? Baixe antes em ", h("a", { href: "#/mes?aba=pdf", text: "Meu mês > Outro período ou formato" }), " (JSON ou CSV).") : null,
    field("Sua senha, para confirmar", pw), err,
    h("button", { type: "submit", class: "btn btn-danger", text: "Excluir minha conta" }));
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    const ok = await confirmDialog({ title: "Excluir a sua conta?", text: "Tudo o que você registrou será excluído agora, sem volta.", confirm: "Excluir para sempre", danger: true });
    if (!ok) return;
    try {
      await api.post("/me/delete", { password: pw.value });
      location.href = "/login";
    } catch (e) { err.textContent = e.message || "Não foi possível excluir."; }
  }));
  return h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Excluir a conta" })), form);
}

// ------------------------------------------------------------------- conta --

// Aparência: segue o aparelho (padrão) ou força claro/escuro; vale em todos os aparelhos da conta.
function themePanel(me) {
  const OPTS = [["auto", "Automático", "Segue o tema do aparelho"], ["light", "Claro", null], ["dark", "Escuro", null]];
  const seg = h("div", { class: "seg", role: "radiogroup", "aria-label": "Tema" });
  const paint = (cur) => { for (const b of seg.children) b.setAttribute("aria-checked", String(b.dataset.v === cur)); };
  for (const [v, label, tip] of OPTS) {
    seg.append(h("button", { type: "button", class: "chip-btn", role: "radio", "data-v": v, title: tip, text: label, onClick: async () => {
      window.nexusTheme.set(v);  // na hora, neste aparelho
      paint(v);
      try { await api.put("/me/theme", { theme: v }); me.theme = v; } catch (e) { errorToast(e, "Não foi possível guardar o tema na conta."); }
    } }));
  }
  paint(me.theme || "dark");
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Aparência" })),
    h("p", { class: "help", text: "Automático acompanha o claro ou escuro do celular e do computador. Claro e Escuro forçam o tema em todos os seus aparelhos." }),
    seg);
}

// Sair dos outros aparelhos sem trocar a senha (celular perdido, computador
// emprestado). Este aparelho continua entrando; chaves de API e calendário seguem.
async function otherDevicesPanel() {
  const { others } = await api.get("/auth/sessions").catch(() => ({ others: null }));
  const line = h("p", { class: "dialog-note", role: "status" });
  const paint = (n) => {
    line.textContent = n === null ? "" : n === 0 ? "Sua conta está aberta só neste aparelho."
      : n === 1 ? "Sua conta também está aberta em 1 outro aparelho ou navegador."
      : `Sua conta também está aberta em ${n} outros aparelhos ou navegadores.`;
    btn.disabled = n === 0;
  };
  const btn = h("button", { type: "button", class: "btn btn-ghost btn-sm" }, icon("logout"), "Sair dos outros aparelhos");
  btn.addEventListener("click", busy(async () => {
    if (!(await confirmDialog({ title: "Sair dos outros aparelhos?", text: "Os outros celulares e computadores voltam para a tela de entrar, e quem estiver neles precisa da senha (ou da digital) de novo. Este aparelho continua. Chaves de API e o link do calendário não mudam.", confirm: "Sair dos outros" }))) return;
    try {
      const r = await api.post("/auth/logout-others");
      paint(0);
      toast(r.ended ? `Pronto: ${r.ended === 1 ? "1 outro aparelho saiu" : `${r.ended} outros aparelhos saíram`} da sua conta.` : "Nenhum outro aparelho estava com a conta aberta.");
    } catch (e) { errorToast(e, "Não foi possível sair dos outros aparelhos."); }
  }));
  paint(others);
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Aparelhos conectados" })),
    h("p", { class: "help", text: "Perdeu o celular ou entrou num computador emprestado? Saia de todos os outros aparelhos sem trocar a senha." }),
    line, h("div", { class: "row-actions" }, btn));
}

// Passkeys: entrar com digital, rosto, Windows Hello ou chave física, sem a senha.
async function passkeysPanel(rerender) {
  const list = await api.get("/auth/passkeys");
  const ua = navigator.userAgent;
  const guess = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Celular Android"
    : /Windows/.test(ua) ? "Windows" : /Mac OS X/.test(ua) ? "Mac" : "Este aparelho";
  const add = h("button", { type: "button", class: "btn btn-primary btn-sm" }, icon("add"), "Usar a digital ou o rosto neste aparelho");
  add.addEventListener("click", busy(async () => {
    try { await registerPasskey(guess); toast("Pronto. Na próxima vez, entre com a digital ou o rosto."); rerender(); }
    catch (e) { if (!cancelled(e)) errorToast(e, "Não foi possível cadastrar a digital ou o rosto."); }
  }));
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Entrar com digital ou rosto" })),
    h("p", { class: "help", text: "Entre sem digitar a senha: com a digital, o rosto, o PIN do Windows ou uma chave física. O acesso (uma chave chamada passkey) fica no aparelho ou no gerenciador de senhas dele; o Nexus guarda só a parte pública. A senha continua valendo." }),
    ...list.map((p) => h("div", { class: "token-row" },
      h("span", { class: "token-name", text: p.name || "Aparelho" }),
      h("span", { class: "token-meta", text: (p.last_used_at ? "usada " + dateTime(p.last_used_at) : "criada " + dateTime(p.created_at)) + (p.backed_up ? " · sincronizada" : "") }),
      h("button", { type: "button", class: "icon", title: "Remover este acesso", "aria-label": "Remover o acesso de " + (p.name || "este aparelho"), onClick: async () => {
        if (!(await confirmDialog({ title: "Remover este acesso?", text: "Este aparelho deixa de entrar no Nexus com a digital ou o rosto. Para tirar também do aparelho, apague nas configurações de senhas dele.", confirm: "Remover", danger: true }))) return;
        try { await api.del(`/auth/passkeys/${p.id}`); rerender(); } catch (e) { errorToast(e); }
      } }, icon("trash")))),
    passkeySupported() ? h("div", { class: "row-actions" }, add) : h("p", { class: "dialog-note", text: "Este navegador não permite entrar com a digital ou o rosto." }));
}

function account(me) {
  const cur = h("input", { type: "password", autocomplete: "current-password", required: "required", maxlength: "128" });
  const nova = h("input", { type: "password", autocomplete: "new-password", minlength: "10", required: "required", maxlength: "128" });
  const nova2 = h("input", { type: "password", autocomplete: "new-password", minlength: "10", required: "required", maxlength: "128" });
  matchPasswords(nova, nova2);
  const err = h("p", { class: "error-text" });
  const form = h("form", {},
    field("Senha atual", cur),
    h("div", { class: "field-row" }, field("Nova senha (mínimo 10 caracteres)", nova), field("Confirme a nova senha", nova2)),
    err, h("button", { type: "submit", class: "btn btn-primary", text: "Trocar senha" }));
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    try {
      await api.post("/auth/change-password", { current_password: cur.value, new_password: nova.value });
      cur.value = nova.value = nova2.value = "";
      toast("Senha trocada. Outras sessões, chaves de API e o link do calendário foram encerrados; integrações (webhooks), desligadas.");
    } catch (e) {
      err.textContent = e.message || "Não foi possível trocar.";
    }
  }));
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Conta" })),
    h("p", { class: "help mono", text: [me.email, ...(me.roles || []).filter((r) => r !== "user").map((r) => `${ROLE_SHORT[r]} (${ROLE_SCREEN[r]})`),
      ...(me.is_master ? ["Admin master (Admin › Equipes)"] : [])].join(" · ") }),
    emailBlock(me),
    h("h3", { class: "sum-h", text: "Senha" }),
    form);
}

// Trocar o próprio e-mail: senha atual + link de confirmação no endereço NOVO
// (24 horas, uso único). Só troca depois de confirmar; o antigo recebe um aviso.
function emailBlock(me) {
  const box = h("div", { class: "email-block" });
  const paint = () => {
    clear(box);
    box.append(h("h3", { class: "sum-h", text: "E-mail" }));
    const input = h("input", { type: "email", maxlength: "254", autocomplete: "email", value: "", placeholder: "nome@empresa.com.br", required: "required" });
    if (identityLocked(me)) {
      input.value = me.email;
      input.disabled = true;
      input.setAttribute("aria-describedby", "email-locked");
      box.append(field("E-mail da conta", input), h("p", { class: "dialog-note lock-note", id: "email-locked" }, icon("lock"), IDENTITY_LOCKED));
      return;
    }
    if (me.email_pending) {
      box.append(h("p", { class: "help" }, "Aguardando a confirmação em ", h("strong", { text: me.email_pending }),
        ". Abra o link que mandamos para lá (vale 24 horas). Até confirmar, você entra com ", h("strong", { text: me.email }), "."),
      h("div", { class: "row-actions" },
        h("button", { type: "button", class: "btn btn-text btn-sm", text: "Desistir da troca", onClick: busy(async () => {
          try { meChanged(me, await api.del("/me/email")); toast("Troca de e-mail cancelada. O link deixa de valer."); paint(); }
          catch (e) { errorToast(e); }
        }) })));
      return;  // um pedido por vez: desistir libera o formulário de novo
    }
    const pw = h("input", { type: "password", autocomplete: "current-password", required: "required", maxlength: "128" });
    const err = h("p", { class: "error-text", role: "alert" });
    const form = h("form", {},
      h("div", { class: "field-row" }, field("E-mail novo", input), field("Sua senha atual", pw)), err,
      h("p", { class: "dialog-note", text: "Mandamos um link de confirmação para o e-mail novo. Ele só passa a valer depois que você confirmar; o endereço atual recebe um aviso." }),
      h("button", { type: "submit", class: "btn btn-ghost", text: "Mandar o link de confirmação" }));
    form.addEventListener("submit", busy(async (ev) => {
      ev.preventDefault();
      err.textContent = "";
      try {
        meChanged(me, await api.post("/me/email", { new_email: input.value.trim(), password: pw.value }));
        toast(`Link mandado para ${me.email_pending}. Confira também o spam.`);
        paint();
      } catch (e) {
        err.textContent = e.message || "Não foi possível pedir a troca.";
        (/senha/i.test(err.textContent) ? pw : input).focus();
      }
    }));
    box.append(form);
  };
  paint();
  return box;
}

// Aceite do visualizador + transparência: quem tem papel que alcança o seu
// registro (visualizador e admin). Desligado, só você vê.
function seenBy(me, who) {
  // "Visível para quem gerencia" (Admin › Para empresas): a chave fica bloqueada,
  // à vista, com o motivo; a escolha da pessoa fica guardada para quando voltar.
  const managed = !!(me.org && me.org.team_visibility === "managers");
  const cb = h("input", { type: "checkbox" });
  cb.checked = !!me.viewers_allowed;
  if (managed) { cb.disabled = true; cb.setAttribute("aria-describedby", "seen-locked"); }
  const help = h("p", { class: "help" });
  const line = h("p", { class: "dialog-note" });
  let list = [];
  const paint = () => {
    // O servidor já manda só quem está no escopo (com equipes: na mesma equipe, ou o admin master).
    const viewers = list.filter((p) => p.roles.includes("viewer")).map((p) => p.name);
    const quem = me.teams_on ? "Quem tem o papel “Vê a equipe” nas suas equipes" : "Quem tem o papel “Vê a equipe”";
    help.textContent = `${quem} (${viewers.length ? viewers.join(", ") : "hoje, ninguém"}) vê na tela Equipe, sem editar, seu quadro, seus números, seus relatórios em PDF, suas horas e suas fotos.` + (managed ? "" : " Só se você permitir.");
    const names = list.filter((p) => p.sees || (p.roles.includes("admin") && !p.roles.includes("viewer")))
      .map((p) => `${p.name} (${p.roles.map((r) => ROLE_SHORT[r]).join(", ")})`);
    line.textContent = managed || cb.checked
      ? `Quem pode ver seu registro: ${names.length ? names.join(", ") : "só você"}.`
      : "Quem pode ver seu registro: só você.";
  };
  paint();
  (who || Promise.resolve(null)).then((res) => { if (!res) { line.remove(); return; } list = res; paint(); });
  const guard = lockWhileSaving(cb); // gravando: aria-disabled (o foco fica na chave)
  cb.addEventListener("change", () => guard(async () => {
    try {
      const res = await api.put("/me/viewers", { accept: cb.checked });
      meChanged(me, res);
      paint();
      toast(cb.checked ? "Pronto: quem vê a equipe vê seu registro." : "Quem vê a equipe não vê mais seu registro.");
    } catch (e) { cb.checked = !cb.checked; errorToast(e); }
  }));
  const lock = managed ? h("p", { class: "dialog-note lock-note", id: "seen-locked" }, icon("lock"),
    (me.teams_on ? "Nesta instância do Nexus, quem gerencia vê as tarefas de quem está na mesma equipe (definido pela administração). "
      : "Nesta instância do Nexus, quem gerencia a equipe vê as tarefas de todos (definido pela administração). ") +
    `A sua escolha (${me.viewers_allowed ? "permitir" : "não permitir"}) fica guardada e volta a valer se isso mudar${me.teams_on ? " ou se você sair das equipes" : ""}.`) : null;
  return [help, h("label", { class: "check-line" + (managed ? " is-locked" : "") }, cb, h("span", { text: "Permitir que quem tem o papel “Vê a equipe” veja meu registro" })), lock, line];
}
