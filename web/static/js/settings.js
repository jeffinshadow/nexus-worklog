// Configurações: projetos, modelos, avisos, calendário, IA e API (chaves), conta (perfil, assistente, chamados, dias úteis e senha).
import { api } from "./api.js";
import { h, icon, clear, dateTime, field, matchPasswords } from "./dom.js";
import { codeBox, confirmDialog, errorToast, modal, toast, warnBox, busy } from "./ui.js";
import { defaultProjectPanel, fillProjectSelect } from "./projects.js";
import { avatar, squarePhoto } from "./profile.js";
import { pushPanel } from "./notificacoes.js";
import { cancelled, register as registerPasskey, supported as passkeySupported } from "./passkey.js";

const TABS = [
  ["modelos", "Modelos"],
  ["avisos", "Avisos"],
  ["calendario", "Calendário"],
  ["ia", "IA e API"],
  ["conta", "Conta"],
];
const OLD_TABS = { dias: "conta", chaves: "ia" }; // links antigos
const ROLE_SHORT = { admin: "admin", assigner: "atribuidor", viewer: "visualizador" };

// Dias úteis como máscara de bits, domingo = bit 0 (igual ao backend).
const DAYS = [
  [1, "Seg"], [2, "Ter"], [3, "Qua"], [4, "Qui"], [5, "Sex"], [6, "Sáb"], [0, "Dom"],
];

export async function mount(root, ctx) {
  // Vencimentos e Projetos viraram itens do menu: link antigo vai para a tela nova.
  if (/aba=vencimentos/.test(location.hash)) { location.hash = "#/vencimentos"; return; }
  if (/aba=projetos/.test(location.hash)) { location.hash = "#/projetos"; return; }
  // Conta sem registro próprio (só Admin/Visualizador/Atribuidor): só IA/API e Conta.
  const isUser = (ctx.me.roles || []).includes("user");
  const tabs = isUser ? TABS : TABS.filter(([k]) => k === "ia" || k === "conta");
  let active = (location.hash.split("?")[1] || "").replace("aba=", "") || tabs[0][0];
  active = OLD_TABS[active] || active;
  if (!tabs.some(([k]) => k === active)) active = tabs[0][0];

  clear(root);
  const seg = h("div", { class: "seg", role: "tablist" });
  const body = h("div", { class: "settings-grid" });
  for (const [key, label] of tabs) {
    seg.append(h("button", {
      type: "button", class: "chip-btn", role: "tab", "aria-selected": key === active ? "true" : "false", text: label,
      onClick: () => {
        active = key;
        for (const b of seg.children) b.setAttribute("aria-selected", b.textContent === label ? "true" : "false");
        window.history.replaceState(null, "", "#/config?aba=" + key); // recarregar volta à mesma aba
        render();
      },
    }));
  }
  root.append(seg, body);

  // Troca rápida de aba: só a última resposta entra na tela.
  let seq = 0;
  async function render() {
    const my = ++seq;
    const out = h("div", { class: "settings-grid" });
    try {
      await fill(out);
    } catch (e) {
      clear(out);
      out.append(h("p", { class: "empty", text: e && e.status === 0 ? e.message : "Erro ao carregar. Tente de novo." }));
    }
    if (my !== seq) return;
    clear(body);
    body.append(...out.childNodes);
  }

  async function fill(body) {
    if (active === "modelos") body.append(await templatesPanel(() => render()));
    else if (active === "avisos") {
      const grid = await notices();
      grid.prepend(await pushPanel(() => render())); // notificações dos aparelhos primeiro; e-mail depois
      body.append(grid);
    }
    else if (active === "calendario") body.append(await calendarFeed(() => render()));
    else if (active === "ia") body.append(...aiHelp(), await tokens(() => render()));
    else if (isUser) body.append(profilePanel(ctx.me, render), assignmentsPanel(ctx.me), assistantPanel(ctx.me), defaultProjectPanel(ctx.me, (r) => meChanged(ctx.me, r)), ticketsPanel(ctx.me), workDays(ctx.me), shortcutsPanel(), account(ctx.me), await passkeysPanel(render), deleteAccount(isUser));
    else body.append(profilePanel(ctx.me, render), account(ctx.me), await passkeysPanel(render), deleteAccount(isUser));
  }
  await render();
}

// ----------------------------------------------------------------- perfil --

// O app inteiro usa o mesmo objeto `me`: atualiza e avisa (menu, lembrete).
function meChanged(me, res) {
  Object.assign(me, res);
  window.dispatchEvent(new Event("nexus:me"));
}

function profilePanel(me, rerender) {
  const name = h("input", { type: "text", maxlength: "60", value: me.display_name || "", placeholder: me.name });
  const err = h("p", { class: "error-text" });
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
  const form = h("form", {}, field("Nome de exibição", name), err,
    h("button", { type: "submit", class: "btn btn-primary", text: "Salvar nome" }));
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    try {
      meChanged(me, await api.put("/me/profile", { display_name: name.value.trim() || null }));
      toast(`Combinado: vou chamar você de ${me.name}.`);
      rerender();
    } catch (e) {
      err.textContent = e.message || "Falha ao salvar.";
    }
  }));
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Perfil" })),
    h("div", { class: "profile-row" }, avatar(me, "lg"),
      h("div", {}, h("div", { class: "row-actions" }, pick, remove), file,
        h("p", { class: "help", text: "PNG, JPEG ou WebP. A foto é recortada em quadrado e reduzida no seu navegador antes do envio; os dados de localização dela não saem daqui." }))),
    h("p", { class: "help", text: "Aparece no menu, nas saudações e no cabeçalho dos relatórios. " +
      (me.display_name ? "Em branco, volto a usar o nome tirado do seu e-mail." : `Em branco, uso “${me.name}”, tirado do seu e-mail.`) }),
    form);
}

// ------------------------------------------------------------- assistente --

const hhmm = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
const toMin = (v) => { const [a, b] = v.split(":").map(Number); return a * 60 + (b || 0); };

function assistantPanel(me) {
  const a = me.assistant;
  const falas = h("input", { type: "checkbox" });
  falas.checked = a.enabled;
  const idle = h("input", { type: "checkbox" });
  idle.checked = a.idle_on;
  const mins = h("input", { type: "number", min: "5", max: "480", step: "5", value: String(a.idle_minutes), class: "input-sm", "aria-label": "Minutos sem registro" });
  const from = h("input", { type: "time", value: hhmm(a.idle_start), class: "input-sm", "aria-label": "Início do horário" });
  const to = h("input", { type: "time", value: hhmm(Math.min(a.idle_end, 1439)), class: "input-sm", "aria-label": "Fim do horário" });
  const reopen = h("input", { type: "checkbox" });
  reopen.checked = a.reopen_on;
  const reopenMins = h("input", { type: "number", min: "1", max: "240", value: String(a.reopen_minutes), class: "input-sm", "aria-label": "Minutos até reabrir" });
  const summaryFrom = h("input", { type: "time", value: hhmm(a.summary_from ?? 840), class: "input-sm", "aria-label": "Horário do resumo do dia" });
  const sync = () => {
    for (const el of [mins, from, to]) el.disabled = !idle.checked;
    reopen.disabled = !falas.checked;
    summaryFrom.disabled = !falas.checked;
    reopenMins.disabled = !falas.checked || !reopen.checked;
  };
  for (const el of [idle, falas, reopen]) el.addEventListener("change", sync);
  sync();
  const save = h("button", { type: "button", class: "btn btn-primary", text: "Salvar assistente" });
  save.addEventListener("click", async () => {
    const body = { enabled: falas.checked, idle_on: idle.checked, idle_minutes: Number(mins.value),
      idle_start: toMin(from.value || "08:00"), idle_end: toMin(to.value || "18:00"),
      reopen_on: reopen.checked, reopen_minutes: Number(reopenMins.value),
      summary_from: Math.min(toMin(summaryFrom.value || "14:00"), 1439) };
    if (body.idle_start >= body.idle_end) { toast("O início do horário precisa ser antes do fim.", { error: true }); return; }
    try {
      meChanged(me, { assistant: await api.put("/me/assistant", body) });
      toast("Assistente salvo.");
    } catch (e) { errorToast(e, "Falha ao salvar."); }
  });
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, icon("spark"), h("h2", { text: "Assistente" })),
    h("div", { class: "notice-row" },
      h("label", { class: "notice-main" }, falas, h("span", {}, h("strong", { text: "Falas do assistente" }),
        h("small", { text: "A saudação e o resumo do Hoje, a leitura da Retrospectiva e as notas em Tarefas, Relatórios e Busca. Tudo calculado a partir dos seus próprios registros." })))),
    h("div", { class: "idle-config" },
      h("label", {}, reopen, "Reabrir uma fala fechada no X depois de", reopenMins, "min"),
      h("small", { class: "muted", text: "Desligado: a fala fechada só volta ao recarregar a página." })),
    h("div", { class: "idle-config" },
      h("label", {}, "Resumo do dia a partir de", summaryFrom),
      h("small", { class: "muted", text: "Ou antes, assim que a primeira tarefa ou rotina do dia for concluída." })),
    h("div", { class: "notice-row" },
      h("label", { class: "notice-main" }, idle, h("span", {}, h("strong", { text: "Lembrete quando passar um tempo sem registro" }),
        h("small", { text: "Só com o app aberto, nos seus dias úteis e dentro do horário abaixo. Vale registro de qualquer origem: app, celular ou IA." })))),
    h("div", { class: "idle-config" },
      h("label", {}, "Avisar após", mins, "min sem registro"),
      h("label", {}, "entre", from, "e", to)),
    h("div", { class: "row-actions" }, save));
}

// ---------------------------------------------------------------- modelos --

const PRIO = [["1", "Alta"], ["2", "Normal"], ["3", "Baixa"]];

async function templatesPanel(rerender) {
  const list = await api.get("/templates");
  const rows = list.length ? list.map((t) => h("div", { class: "token-row" },
    h("span", { class: "token-name", text: t.name }),
    h("div", { class: "actions" },
      // Lápis e lixeira, como nas outras listas (Vencimentos, checklist).
      h("button", { type: "button", class: "icon", title: "Editar", "aria-label": "Editar " + t.name, onClick: () => editTemplate(t, rerender) }, icon("edit")),
      h("button", { type: "button", class: "icon", title: "Excluir", "aria-label": "Excluir " + t.name, onClick: async () => {
        if (!(await confirmDialog({ title: `Excluir o modelo “${t.name}”?`, text: "As tarefas já criadas com ele continuam.", confirm: "Excluir", danger: true }))) return;
        try { await api.del(`/templates/${t.id}`); toast("Modelo excluído."); rerender(); } catch (e) { errorToast(e); }
      } }, icon("trash"))),
    h("span", { class: "token-meta", text: [t.title, t.checklist.length ? `${t.checklist.length} itens no checklist` : "sem checklist", t.after_hours ? "plantão" : ""].filter(Boolean).join(" · ") })))
    : [h("p", { class: "empty", text: "Nenhum modelo ainda." })];
  return h("div", { class: "settings-grid" },
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, icon("list"), h("h2", { text: "Modelos de tarefa" }),
        h("button", { type: "button", class: "btn btn-primary btn-sm", onClick: () => editTemplate(null, rerender) }, icon("add"), "Novo modelo")),
      h("p", { class: "help", text: "Procedimentos que se repetem (onboarding de colaborador, troca de equipamento, servidor novo) viram um modelo com checklist pronto. Use em “+ Tarefa”, escolhendo o modelo, ou salve uma tarefa existente como modelo pelo detalhe dela." })),
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "Meus modelos" }), h("span", { class: "count", text: String(list.length) })),
      ...rows));
}

function editTemplate(t, rerender) {
  const name = h("input", { type: "text", maxlength: "60", required: "required", value: t ? t.name : "" });
  const title = h("input", { type: "text", maxlength: "200", required: "required", value: t ? t.title : "" });
  const desc = h("input", { type: "text", maxlength: "300", value: t && t.description ? t.description : "" });
  const prio = h("select", {}, ...PRIO.map(([v, l]) => h("option", { value: v, text: l })));
  prio.value = String(t ? t.priority : 2);
  const proj = h("select", {});
  fillProjectSelect(proj, t ? t.project_id : null).catch(() => {});
  const after = h("input", { type: "checkbox" });
  after.checked = !!(t && t.after_hours);
  const items = h("textarea", { rows: "6", maxlength: "6200", placeholder: "Um item por linha" });
  items.value = t ? t.checklist.join("\n") : "";
  const err = h("p", { class: "error-text" });
  const form = h("form", {}, h("h2", { text: t ? "Editar modelo" : "Novo modelo" }),
    field("Nome do modelo", name), field("Título da tarefa", title), field("Descrição (uma linha)", desc),
    h("div", { class: "field-row" }, field("Prioridade", prio), field("Projeto / cliente", proj)),
    h("label", { class: "weekday-option" }, after, h("span", { text: "Plantão / fora do horário" })),
    field("Checklist (um item por linha, até 30)", items), err,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
      h("button", { type: "submit", class: "btn btn-primary", text: "Salvar modelo" })));
  const dlg = modal(form);
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    const body = { name: name.value.trim(), title: title.value.trim(), description: desc.value.trim() || null,
      priority: Number(prio.value), project_id: proj.value && proj.value !== "__new" ? Number(proj.value) : null,
      after_hours: after.checked, checklist: items.value.split("\n").map((x) => x.trim()).filter(Boolean).slice(0, 30) };
    try {
      if (t) await api.put(`/templates/${t.id}`, body); else await api.post("/templates", body);
      dlg.close(); toast("Modelo salvo."); rerender();
    } catch (e) { err.textContent = e.message || "Falha ao salvar."; }
  }));
  setTimeout(() => (t ? title : name).focus(), 0);
}

// --------------------------------------------------------------- chamados --

function ticketsPanel(me) {
  const url = h("input", { type: "url", maxlength: "300", value: me.ticket_url || "",
    placeholder: "https://glpi.empresa.com.br/front/ticket.form.php?id={id}" });
  const save = h("button", { type: "button", class: "btn btn-primary", text: "Salvar endereço" });
  save.addEventListener("click", async () => {
    try {
      const r = await api.put("/me/tickets", { ticket_url: url.value.trim() || null });
      meChanged(me, r);
      toast(r.ticket_url ? "Endereço salvo: o número do chamado vira link." : "Endereço removido.");
    } catch (e) { errorToast(e, "Use um endereço começando com http:// ou https://."); }
  });
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Chamados" })),
    h("p", { class: "help", text: "Endereço do sistema de chamados da sua equipe (GLPI, TomTicket, Jira...). Onde estiver {id} entra o número do chamado; sem {id}, ele vai no fim. Com o endereço, o “#4821” das tarefas abre o chamado." }),
    field("Endereço do chamado", url),
    h("div", { class: "row-actions" }, save));
}

// ---------------------------------------------------------------- atalhos --

function shortcutsPanel() {
  const keys = [["n", "nova tarefa"], ["/", "buscar"], ["h", "Hoje"], ["t", "Tarefas"], ["r", "Retrospectiva"],
    ["l", "Relatórios"], ["s", "parar o cronômetro"], ["?", "ver todos os atalhos"]];
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Atalhos de teclado" })),
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
  const err = h("p", { class: "error-text" });
  const save = h("button", { type: "button", class: "btn btn-primary", text: "Salvar" });
  save.addEventListener("click", async () => {
    const mask = boxes.reduce((m, { bit, cb }) => (cb.checked ? m | (1 << bit) : m), 0);
    err.textContent = "";
    if (!mask) { err.textContent = "Escolha pelo menos um dia."; return; }
    try {
      const res = await api.post("/auth/settings", { work_days: mask });
      me.work_days = res.work_days;
      toast("Dias úteis salvos.");
    } catch (e) {
      errorToast(e, "Falha ao salvar.");
    }
  });
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Meus dias úteis" })),
    h("p", { class: "help", text: "As rotinas que repetem “nos dias úteis” seguem estes dias. O que você marcar fora da agenda de uma rotina fica salvo como extra e não entra no percentual. Atenção: mudar os dias úteis recalcula também os indicadores dos dias anteriores." }),
    h("fieldset", { class: "weekday-picker" },
      ...boxes.map(({ label, cb }) => h("label", { class: "weekday-option" }, cb, h("span", { text: label })))),
    err, save);
}

// ------------------------------------------------------------------ avisos --

const KINDS = [
  ["morning", "Seu dia", "De manhã: atrasadas, o que vence hoje, rotinas do dia e prioridades altas. Só nos dias úteis."],
  ["evening", "Antes de encerrar", "No fim do dia, se ainda faltar alguma rotina de hoje. Não sai se você já fez tudo."],
  ["weekly", "Resumo da semana", "Às segundas: rotinas, tarefas concluídas, tempo por projeto e o que ficou para trás na semana anterior."],
];
const HOURS = Array.from({ length: 24 }, (_, i) => i);

async function notices() {
  const p = await api.get("/notifications");
  const rows = KINDS.map(([key, title, help]) => {
    const on = h("input", { type: "checkbox", "aria-label": title });
    on.checked = p[key];
    const hour = h("select", { class: "select-sm", "aria-label": `Horário de ${title}` },
      ...HOURS.map((x) => h("option", { value: String(x), text: `${String(x).padStart(2, "0")}:00` })));
    hour.value = String(p[`${key}_hour`]);
    const sync = () => { hour.disabled = !on.checked; };
    on.addEventListener("change", sync);
    sync();
    return { key, on, hour, el: h("div", { class: "notice-row" },
      h("label", { class: "notice-main" }, on, h("span", {}, h("strong", { text: title }), h("small", { text: help }))), hour) };
  });
  // Semanal: o PDF anexado e uma cópia (gestor, cliente) — só valem com o resumo da semana ligado.
  const weekly = rows.find((r) => r.key === "weekly");
  const pdf = h("input", { type: "checkbox" });
  pdf.checked = !!p.weekly_pdf;
  const cc = h("input", { type: "email", maxlength: "254", value: p.weekly_cc || "", placeholder: "ex.: gestor@empresa.com.br (opcional)",
    autocomplete: "off", "aria-label": "Mandar cópia do resumo semanal para" });
  const weeklyExtra = h("div", { class: "notice-sub" },
    h("label", { class: "weekday-option" }, pdf, h("span", { text: "Anexar o relatório da semana em PDF (o mesmo de Relatórios, com os títulos das tarefas)" })),
    field("Mandar cópia para (gestor, cliente)", cc),
    h("p", { class: "dialog-note", text: "A cópia recebe o mesmo e-mail, com o PDF se estiver ligado. Use só com quem já acompanha o seu trabalho." }));
  const syncWeekly = () => { pdf.disabled = cc.disabled = !weekly.on.checked; weeklyExtra.classList.toggle("off", !weekly.on.checked); };
  weekly.on.addEventListener("change", syncWeekly);
  syncWeekly();
  const titles = h("input", { type: "checkbox" });
  titles.checked = p.show_titles;
  const save = h("button", { type: "button", class: "btn btn-primary", text: "Salvar avisos" });
  save.addEventListener("click", async () => {
    const body = { show_titles: titles.checked, weekly_pdf: pdf.checked, weekly_cc: cc.value.trim() || null };
    for (const r of rows) { body[r.key] = r.on.checked; body[`${r.key}_hour`] = Number(r.hour.value); }
    try { await api.put("/notifications", body); toast("Avisos salvos."); setDirty(false); }
    catch (e) { errorToast(e, e.status === 422 ? "O e-mail da cópia não parece válido." : "Falha ao salvar."); }
  });
  const test = h("button", { type: "button", class: "btn btn-ghost" }, icon("mail"), "Mandar um teste");
  test.disabled = !p.mail_configured;
  test.addEventListener("click", async () => {
    test.disabled = true;
    try { const r = await api.post("/notifications/test"); toast(`Teste enviado para ${r.to}.`); }
    catch (e) { errorToast(e, "Falha no envio."); }
    finally { setTimeout(() => { test.disabled = false; }, 4000); }
  });
  // A semana passada como sairia na segunda (só para você; a cópia não recebe). Salve antes.
  const testWeek = h("button", { type: "button", class: "btn btn-ghost", title: "A semana passada como sairia na segunda, só para você (salve antes)" },
    icon("reports"), "Testar a semana");
  testWeek.disabled = !p.mail_configured;
  testWeek.addEventListener("click", async () => {
    testWeek.disabled = true;
    try { const r = await api.post("/notifications/test?kind=weekly"); toast(`Semana enviada para ${r.to}.`); }
    catch (e) { errorToast(e, "Falha no envio."); }
    finally { setTimeout(() => { testWeek.disabled = false; }, 4000); }
  });
  // Os testes saem com o que está salvo: com alteração pendente, esperam o "Salvar avisos".
  const testTitles = [test.title || "", testWeek.title || ""];
  const setDirty = (dirty) => {
    for (const [i, b] of [test, testWeek].entries()) {
      b.disabled = dirty || !p.mail_configured;
      b.title = dirty ? "Salve os avisos antes de testar" : testTitles[i];
    }
  };
  const KIND_PT = { morning: "seu dia", evening: "fim do dia", weekly: "semana", test: "teste" };
  const recent = p.recent.filter((r) => r.ok !== null || r.error !== "nada a avisar");
  const mailPanel = h("section", { class: "panel" },
      h("div", { class: "panel-head" }, icon("mail"), h("h2", { text: "Avisos por e-mail" })),
      h("p", { class: "help" }, "Enviados para ", h("strong", { class: "mono", text: p.email }),
        ". Sem rastreamento de abertura ou de cliques; só sai e-mail quando há algo a avisar."),
      p.mail_configured ? null : warnBox("O envio de e-mail ainda não está configurado neste servidor. Você pode deixar tudo escolhido; os avisos começam quando ele for ligado."),
      ...rows.flatMap((r) => (r === weekly ? [r.el, weeklyExtra] : [r.el])),
      h("label", { class: "weekday-option notice-titles" }, titles, h("span", { text: "Mostrar os títulos das tarefas no e-mail (desligado: só os números)" })),
      h("div", { class: "row-actions" }, save, test, testWeek));
  for (const ev of ["input", "change"]) mailPanel.addEventListener(ev, (e) => { if (!e.target.closest(".row-actions")) setDirty(true); });
  return h("div", { class: "settings-grid" },
    mailPanel,
    recent.length ? h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "Últimos envios" })),
      ...recent.map((r) => h("div", { class: "token-row" },
        h("span", { class: "token-name", text: `${KIND_PT[r.kind] || r.kind} · ${r.ref_date.split("-").reverse().slice(0, 2).join("/")}` }),
        h("span", { class: "chip " + (r.ok ? "done" : "late"), text: r.ok ? "enviado" : "falhou" }),
        h("span", { class: "token-meta", text: r.ok ? dateTime(r.sent_at) : (r.error || "") })))) : null);
}

// -------------------------------------------------------------- calendário --

async function calendarFeed(rerender) {
  const st = await api.get("/calendar");
  const rec = h("input", { type: "checkbox" });
  rec.checked = st.active ? st.include_recurring : true;
  const panel = h("section", { class: "panel" },
    h("div", { class: "panel-head" }, icon("calendar"), h("h2", { text: "Calendário" })),
    h("p", { class: "help", text: "Assine o Nexus no Google Agenda, Outlook ou no celular: os prazos das tarefas abertas aparecem como eventos de dia inteiro e as rotinas como eventos repetidos. A agenda atualiza sozinha (o Google pode levar algumas horas)." }),
    h("label", { class: "weekday-option" }, rec, h("span", { text: "Incluir as rotinas" })));

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
    h("p", { class: "dialog-note", text: "Google Agenda: Outras agendas › + › Do URL › cole o link." }),
    h("p", { class: "dialog-note", text: "Outlook: Adicionar calendário › Assinar da Web." }),
    h("p", { class: "dialog-note" }, "iPhone/Mac: ", h("a", { href: webcal, text: "abrir no Calendário" }), "."),
    h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-primary", text: "Pronto", onClick: () => dlg.close() })));
}

// ----------------------------------------------------------- chaves de API --

const VALIDADES = [["30", "30 dias"], ["90", "90 dias"], ["180", "180 dias"], ["365", "1 ano"], ["", "sem validade"]];

async function tokens(rerender) {
  const list = await api.get("/tokens");
  const name = h("input", { type: "text", maxlength: "60", placeholder: "Ex.: Claude do notebook", required: "required" });
  const scope = h("select", {},
    h("option", { value: "write", text: "Ler e registrar (recomendado para IA)" }),
    h("option", { value: "read", text: "Só leitura" }));
  const expires = h("select", {}, ...VALIDADES.map(([v, t]) => h("option", { value: v, text: t })));
  expires.value = "90";
  const err = h("p", { class: "error-text" });
  const create = h("button", { type: "submit", class: "btn btn-primary" }, icon("key"), "Criar chave");
  const form = h("form", {},
    field("Nome (para reconhecer no histórico)", name),
    h("div", { class: "field-row" },
      field("Permissão", scope),
      field("Validade", expires)),
    err, create);
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
      err.textContent = e.message || "Falha ao criar.";
      create.disabled = false;
    }
  }));

  const rows = list.length ? list.map((t) => {
    const meta = [
      `${t.prefix}…`, t.scope === "write" ? "ler e registrar" : "só leitura",
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
    }
    return h("div", { class: "token-row" + (t.active ? "" : " inactive") },
      h("span", { class: "token-name", text: t.name }), actions, h("span", { class: "token-meta", text: meta.join(" · ") }));
  }) : [h("p", { class: "empty", text: "Nenhuma chave ainda." })];

  return h("div", { class: "settings-grid" },
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "Nova chave" })),
      h("p", { class: "help", text: "Uma chave deixa uma IA ou automação usar o Nexus em seu nome, sem a sua senha. Tudo o que ela fizer aparece no Histórico com o nome que você der aqui." }),
      form),
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "Minhas chaves" }), h("span", { class: "count", text: String(list.filter((t) => t.active).length) + " ativas" })),
      ...rows));
}

function showNewToken(res) {
  const url = `${location.origin}/mcp`;
  const dlg = modal(
    h("h2", { text: "Chave criada" }),
    h("p", { text: `“${res.name}” — copie agora: ela não aparece de novo.` }),
    h("div", { class: "token-box", text: res.token }),
    h("p", { class: "dialog-note", text: "Para conectar no Claude Code:" }),
    codeBox(`claude mcp add --transport http nexus ${url} --header "Authorization: Bearer ${res.token}"`),
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

// ------------------------------------------------------- integração com IA --

function aiHelp() {
  const url = `${location.origin}/mcp`;
  return [
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, icon("spark"), h("h2", { text: "Use o Nexus pela sua IA" })),
      h("p", { class: "help", text: "Em vez de registrar à mão, conte para a IA o que você fez (“terminei a migração do Exchange, e fiz os backups”) e ela registra no Nexus. O Nexus fala MCP, o protocolo que Claude, Cursor e outros usam para chamar ferramentas." }),
      h("p", { class: "help", text: "1. Crie uma chave logo abaixo (permissão ler e registrar). 2. Conecte a IA:" }),
      h("p", { class: "dialog-note", text: "Claude Code (terminal):" }),
      codeBox(`claude mcp add --transport http nexus ${url} --header "Authorization: Bearer nxs_SUA_CHAVE"`),
      h("p", { class: "dialog-note", text: "Cursor e outros clientes MCP (arquivo de configuração):" }),
      codeBox(JSON.stringify({ mcpServers: { nexus: { url, headers: { Authorization: "Bearer nxs_SUA_CHAVE" } } } }, null, 2))),
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "O que a IA pode fazer" })),
      h("p", { class: "help", text: "Ver o dia, buscar, listar e criar tarefas (com projeto e prioridade), editar, concluir, marcar rotinas (até 7 dias atrás), anotar progresso, montar e marcar checklist, apontar tempo, consultar o histórico e desfazer um engano dela. Ela não exclui tarefas. Com uma chave “só leitura”, ela apenas consulta." }),
      h("p", { class: "dialog-note", text: "API REST direta (scripts, automações):" }),
      codeBox(`curl -H "Authorization: Bearer nxs_SUA_CHAVE" ${location.origin}/api/board`)),
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, icon("spark"), h("h2", { text: "Comandos prontos" })),
      h("p", { class: "help", text: "O Nexus oferece dois comandos para a IA: o resumo da semana (para o gestor, o time ou um cliente) e o texto da daily. No Claude Code eles aparecem como comandos de barra:" }),
      codeBox("/mcp__nexus__resumo_semanal o cliente\n/mcp__nexus__daily"),
      h("p", { class: "dialog-note", text: "Em outros clientes, cole o pedido:" }),
      codeBox("Use o Nexus (get_summary e get_today) e escreva um resumo da minha semana para o meu gestor: o que foi entregue por projeto, o tempo por projeto, o que segue em andamento e os impedimentos. Só com o que está registrado.")),
  ];
}

// ------------------------------------------------------- tarefas atribuídas --

// Consentimento: sem ele, ninguém consegue mandar tarefas para esta pessoa.
function assignmentsPanel(me) {
  const cb = h("input", { type: "checkbox" });
  cb.checked = !!me.accepts_assignments_at;
  const since = h("p", { class: "dialog-note" });
  const sync = () => {
    since.textContent = me.accepts_assignments_at
      ? `Aceito desde ${dateTime(me.accepts_assignments_at)}. Cada tarefa recebida chega por e-mail e aparece em Tarefas com “de” e o nome de quem mandou.`
      : "Desligado: ninguém pode atribuir tarefas a você.";
  };
  sync();
  cb.addEventListener("change", async () => {
    cb.disabled = true;
    try {
      const res = await api.put("/me/assignments", { accept: cb.checked });
      meChanged(me, res);
      sync();
      toast(cb.checked ? "Pronto: você aceita tarefas atribuídas." : "Você não recebe mais tarefas atribuídas. As já recebidas continuam com você.");
    } catch (e) { cb.checked = !cb.checked; errorToast(e); }
    finally { cb.disabled = false; }
  });
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, icon("send"), h("h2", { text: "Tarefas atribuídas" })),
    h("p", { class: "help", text: "Quem tem a função de atribuidor de tarefas pode mandar tarefas para você, mas só se você permitir aqui. A tarefa recebida é sua: você edita, conclui ou exclui." }),
    h("label", { class: "weekday-option" }, cb, h("span", { text: "Permitir que me atribuam tarefas" })),
    since);
}

// --------------------------------------------------------- excluir a conta --

// LGPD: a pessoa apaga a conta e tudo o que registrou, com a senha. Sem volta.
function deleteAccount(isUser) {
  const pw = h("input", { type: "password", autocomplete: "current-password", required: "required", maxlength: "128" });
  const err = h("p", { class: "error-text" });
  const form = h("form", {},
    h("p", { class: "help", text: "Apaga a sua conta e tudo o que está nela: tarefas, rotinas, tempo apontado, anotações, chaves de API e histórico. Não dá para desfazer." }),
    isUser ? h("p", { class: "dialog-note" }, "Quer guardar uma cópia? Baixe antes em ", h("a", { href: "#/relatorios", text: "Relatórios" }), " (JSON ou CSV).") : null,
    field("Sua senha, para confirmar", pw), err,
    h("button", { type: "submit", class: "btn btn-danger", text: "Excluir minha conta" }));
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    const ok = await confirmDialog({ title: "Excluir a sua conta?", text: "Tudo o que você registrou será apagado agora, sem volta.", confirm: "Excluir para sempre", danger: true });
    if (!ok) return;
    try {
      await api.post("/me/delete", { password: pw.value });
      location.href = "/login";
    } catch (e) { err.textContent = e.message || "Não foi possível excluir."; }
  }));
  return h("section", { class: "panel" }, h("div", { class: "panel-head" }, icon("trash"), h("h2", { text: "Excluir a conta" })), form);
}

// ------------------------------------------------------------------- conta --

// Passkeys: entrar com digital, rosto, Windows Hello ou chave física, sem a senha.
async function passkeysPanel(rerender) {
  const list = await api.get("/auth/passkeys");
  const ua = navigator.userAgent;
  const guess = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Celular Android"
    : /Windows/.test(ua) ? "Windows" : /Mac OS X/.test(ua) ? "Mac" : "Este aparelho";
  const add = h("button", { type: "button", class: "btn btn-primary btn-sm" }, icon("add"), "Adicionar passkey neste aparelho");
  add.addEventListener("click", busy(async () => {
    try { await registerPasskey(guess); toast("Passkey criada. Na próxima vez, entre com ela."); rerender(); }
    catch (e) { if (!cancelled(e)) errorToast(e, "Não foi possível criar a passkey."); }
  }));
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, icon("key"), h("h2", { text: "Passkeys" })),
    h("p", { class: "help", text: "Entre sem digitar a senha: com a digital, o rosto, o PIN do Windows ou uma chave física. A passkey fica no aparelho (ou no gerenciador de senhas dele); o Nexus guarda só a parte pública. A senha continua valendo." }),
    ...list.map((p) => h("div", { class: "token-row" },
      h("span", { class: "token-name", text: p.name || "Passkey" }),
      h("span", { class: "token-meta", text: (p.last_used_at ? "usada " + dateTime(p.last_used_at) : "criada " + dateTime(p.created_at)) + (p.backed_up ? " · sincronizada" : "") }),
      h("button", { type: "button", class: "icon", title: "Remover esta passkey", "aria-label": "Remover " + (p.name || "passkey"), onClick: async () => {
        if (!(await confirmDialog({ title: "Remover a passkey?", text: "Ela deixa de entrar no Nexus. Para tirar também do aparelho, apague nas configurações de senhas dele.", confirm: "Remover", danger: true }))) return;
        try { await api.del(`/auth/passkeys/${p.id}`); rerender(); } catch (e) { errorToast(e); }
      } }, icon("trash")))),
    passkeySupported() ? h("div", { class: "row-actions" }, add) : h("p", { class: "dialog-note", text: "Este navegador não cria passkeys." }));
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
      toast("Senha trocada. Outras sessões, chaves de API e o link do calendário foram encerrados.");
    } catch (e) {
      err.textContent = e.message || "Falha ao trocar.";
    }
  }));
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Conta" })),
    h("p", { class: "help mono", text: [me.email, ...(me.roles || []).filter((r) => r !== "user").map((r) => ROLE_SHORT[r])].join(" · ") }),
    form);
}
