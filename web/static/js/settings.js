// Configurações: projetos, modelos, avisos, calendário, IA e API (chaves e webhooks), conta (perfil, assistente, chamados, dias úteis e senha).
import { api } from "./api.js";
import { h, icon, clear, dateTime, field, matchPasswords } from "./dom.js";
import { codeBox, confirmDialog, errorToast, modal, toast, warnBox, busy, singleKeysOn, setSingleKeys, calmMotion, hashPage, pager, pageSlice, setHashPage } from "./ui.js";
import { defaultProjectPanel, fillProjectSelect } from "./projects.js";
import { avatar, squarePhoto } from "./profile.js";
import { pushPanel } from "./notificacoes.js";
import { cancelled, register as registerPasskey, supported as passkeySupported } from "./passkey.js";

const TABS = [
  ["conta", "Conta"],
  ["modelos", "Modelos"],
  ["avisos", "Avisos"],
  ["calendario", "Calendário"],
  ["ia", "IA e API"],
];
const OLD_TABS = { dias: "conta", chaves: "ia" }; // links antigos
// Os mesmos nomes do Admin (cada papel com o nome do que ele faz; a tela vem junto).
const ROLE_SHORT = { admin: "Admin", assigner: "Manda tarefas", viewer: "Vê a equipe" };
const ROLE_SCREEN = { admin: "tela Admin", assigner: "tela Atribuir", viewer: "tela Equipe" };

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
  const seg = h("div", { class: "seg", role: "tablist", "aria-label": "Configurações" });
  const body = h("div", { class: "settings-grid" });
  for (const [key, label] of tabs) {
    seg.append(h("button", {
      type: "button", class: "chip-btn", role: "tab", "aria-selected": key === active ? "true" : "false", text: label,
      onClick: () => {
        active = key;
        for (const b of seg.children) b.setAttribute("aria-selected", b.textContent === label ? "true" : "false");
        showActive(true);
        window.history.replaceState(null, "", "#/config?aba=" + key); // recarregar volta à mesma aba
        render();
      },
    }));
  }
  root.append(seg, body);
  // Celular: as abas rolam de lado; a ativa fica à vista (depois do desenho da tela).
  const showActive = (smooth) => requestAnimationFrame(() => {
    const tab = seg.querySelector('[aria-selected="true"]');
    if (!tab || seg.scrollWidth <= seg.clientWidth) return;
    const a = tab.getBoundingClientRect(), r = seg.getBoundingClientRect();
    seg.scrollTo({ left: seg.scrollLeft + (a.left - r.left) - (r.width - a.width) / 2, behavior: smooth && !calmMotion() ? "smooth" : "auto" });
  });
  // A tela pode ser montada fora da página e entrar depois: rola quando aparecer.
  const seen = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { seen.disconnect(); showActive(false); } });
  seen.observe(seg);

  // Troca rápida de aba: só a última resposta entra na tela.
  let seq = 0;
  async function render() {
    const my = ++seq;
    const out = h("div", { class: "settings-grid" });
    try {
      await fill(out);
    } catch (e) {
      clear(out);
      out.append(h("p", { class: "empty", text: e && e.status === 0 ? e.message : "Não foi possível carregar. Tente de novo." }));
    }
    if (my !== seq) return;
    clear(body);
    body.append(...out.childNodes);
  }

  async function fill(body) {
    if (active === "modelos") body.append(await templatesPanel(() => render()));
    else if (active === "avisos") {
      body.append(await notices(await pushPanel(() => render()))); // notificações dos aparelhos primeiro; e-mail depois
    }
    else if (active === "calendario") body.append(await calendarFeed(() => render()));
    else if (active === "ia") body.append(await tokens(() => render()), ...aiHelp(), await webhooksPanel(() => render()));
    // Conta: primeiro o que muda o dia (dias úteis, projeto padrão), depois quem vê e manda tarefas.
    else if (isUser) body.append(workDays(ctx.me), defaultProjectPanel(ctx.me, (r) => meChanged(ctx.me, r)), privacyPanel(ctx.me), profilePanel(ctx.me, render), themePanel(ctx.me), assistantPanel(ctx.me), ticketsPanel(ctx.me), shortcutsPanel(), account(ctx.me), await otherDevicesPanel(), await passkeysPanel(render), deleteAccount(isUser));
    else body.append(profilePanel(ctx.me, render), themePanel(ctx.me), account(ctx.me), await otherDevicesPanel(), await passkeysPanel(render), deleteAccount(isUser));
  }
  await render();
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
  const form = h("form", {}, field("Nome de exibição", name), locked ? null : err,
    locked ? h("p", { class: "dialog-note lock-note", id: "name-locked" }, icon("lock"), IDENTITY_LOCKED)
      : h("button", { type: "submit", class: "btn btn-primary", text: "Salvar nome" }));
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    try {
      meChanged(me, await api.put("/me/profile", { display_name: name.value.trim() || null }));
      toast(`Combinado: vou chamar você de ${me.name}.`);
      rerender();
    } catch (e) {
      err.textContent = e.message || "Não foi possível salvar.";
    }
  }));
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
  const staleDays = h("input", { type: "number", min: "1", max: "60", value: String(a.stale_days ?? 5), class: "input-sm", "aria-label": "Dias aguardando sem data de cobrança" });
  const sync = () => {
    for (const el of [mins, from, to]) el.disabled = !idle.checked;
    reopen.disabled = !falas.checked;
    summaryFrom.disabled = !falas.checked;
    staleDays.disabled = !falas.checked;
    reopenMins.disabled = !falas.checked || !reopen.checked;
  };
  for (const el of [idle, falas, reopen]) el.addEventListener("change", sync);
  sync();
  const save = h("button", { type: "button", class: "btn btn-primary", text: "Salvar assistente" });
  save.addEventListener("click", async () => {
    const body = { enabled: falas.checked, idle_on: idle.checked, idle_minutes: Number(mins.value),
      idle_start: toMin(from.value || "08:00"), idle_end: toMin(to.value || "18:00"),
      reopen_on: reopen.checked, reopen_minutes: Number(reopenMins.value),
      summary_from: Math.min(toMin(summaryFrom.value || "14:00"), 1439),
      stale_days: Math.min(Math.max(Number(staleDays.value) || 5, 1), 60) };
    if (body.idle_start >= body.idle_end) { toast("O início do horário precisa ser antes do fim.", { error: true }); return; }
    try {
      meChanged(me, { assistant: await api.put("/me/assistant", body) });
      toast("Assistente salvo.");
    } catch (e) { errorToast(e, "Não foi possível salvar."); }
  });
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Assistente" })),
    h("div", { class: "notice-row" },
      h("label", { class: "notice-main" }, falas, h("span", {}, h("strong", { text: "Falas do assistente" }),
        h("small", { text: "A saudação e o resumo do Hoje, a prévia do PDF em Meu mês, e as notas em Tarefas e Busca. Tudo calculado a partir dos seus próprios registros." })))),
    h("div", { class: "idle-config" },
      h("label", {}, reopen, "Reabrir uma fala fechada no X depois de", reopenMins, "min"),
      h("small", { class: "muted", text: "Desligado: a fala fechada só volta ao recarregar a página." })),
    h("div", { class: "idle-config" },
      h("label", {}, "Resumo do dia a partir de", summaryFrom),
      h("small", { class: "muted", text: "Ou antes, assim que a primeira tarefa ou rotina do dia for concluída." })),
    h("div", { class: "idle-config" },
      h("label", {}, "Perguntar quando cobrar após", staleDays, "dias aguardando"),
      h("small", { class: "muted", text: "Só para tarefas aguardando sem dia marcado para cobrar." })),
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

const TEMPLATES_PAGE = 15; // linha curta
const TOKENS_OFF_PAGE = 10; // chaves revogadas e vencidas, recolhidas

async function templatesPanel(rerender) {
  const list = await api.get("/templates");
  const rowOf = (t) => h("div", { class: "token-row" },
    h("span", { class: "token-name", text: t.name }),
    h("div", { class: "actions" },
      // Lápis e lixeira, como nas outras listas (Vencimentos, checklist).
      h("button", { type: "button", class: "icon", title: "Editar", "aria-label": "Editar " + t.name, onClick: () => editTemplate(t, rerender) }, icon("edit")),
      h("button", { type: "button", class: "icon", title: "Excluir", "aria-label": "Excluir " + t.name, onClick: async () => {
        if (!(await confirmDialog({ title: `Excluir o modelo “${t.name}”?`, text: "As tarefas já criadas com ele continuam.", confirm: "Excluir", danger: true }))) return;
        try { await api.del(`/templates/${t.id}`); toast("Modelo excluído."); rerender(); } catch (e) { errorToast(e); }
      } }, icon("trash"))),
    h("span", { class: "token-meta", text: [t.title, t.checklist.length ? `${t.checklist.length} itens no checklist` : "sem checklist", t.after_hours ? "plantão" : ""].filter(Boolean).join(" · ") }));
  const box = h("div");
  let page = hashPage("p");
  const paint = () => {
    clear(box);
    if (!list.length) { box.append(h("p", { class: "empty", text: "Nenhum modelo ainda. Salve como modelo uma tarefa que se repete (com checklist) para criá-la em um toque." })); return; }
    const slice = pageSlice(list, page, TEMPLATES_PAGE);
    page = slice.page;
    setHashPage("p", page, "config");
    box.append(...slice.rows.map(rowOf));
    const nav = pager({ page, total: list.length, size: TEMPLATES_PAGE, label: "modelos",
      onPage: (n) => { page = n; paint(); }, focus: () => box.closest(".panel")?.querySelector("h2") });
    if (nav) box.append(nav);
  };
  paint();
  const rows = [box];
  return h("div", { class: "settings-grid" },
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "Modelos de tarefa" }),
        h("button", { type: "button", class: "btn btn-primary btn-sm", onClick: () => editTemplate(null, rerender) }, icon("add"), "Novo modelo")),
      h("p", { class: "help", text: "Procedimentos que se repetem (entrada de colaborador novo, troca de equipamento, servidor novo) viram um modelo com checklist pronto. Use em “+ Tarefa”, escolhendo o modelo, ou salve uma tarefa existente como modelo pelo detalhe dela." })),
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
    h("div", { class: "field-row" }, field("Prioridade", prio), field("Projeto", proj)),
    h("label", { class: "check-line" }, after, h("span", { text: "Plantão / fora do horário" })),
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
    } catch (e) { err.textContent = e.message || "Não foi possível salvar."; }
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
    h("div", { class: "panel-head" }, h("h2", { text: "Chamados e ordens de serviço" })),
    h("p", { class: "help", text: "Opcional. Se a sua equipe usa um sistema de chamados ou de ordens de serviço, cole o endereço de um deles, trocando o número por {id} (ex.: https://sistema.empresa/os/{id}). Sem {id}, o número vai no fim. Com o endereço, o “#4821” das tarefas abre o chamado." }),
    field("Endereço do chamado ou OS", url),
    h("div", { class: "row-actions" }, save));
}

// ---------------------------------------------------------------- atalhos --

function shortcutsPanel() {
  const keys = [["n", "nova tarefa"], ["/", "buscar"], ["h", "Hoje"], ["t", "Tarefas"], ["r", "Meu mês"],
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
      errorToast(e, "Não foi possível salvar.");
    }
  });
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Meus dias úteis" })),
    h("p", { class: "help", text: "As rotinas que repetem “nos dias úteis” seguem estes dias. O que você marcar fora da agenda de uma rotina fica salvo como extra e não entra no percentual. Atenção: mudar os dias úteis recalcula também os números dos dias anteriores." }),
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

// push: o painel das notificações (o mesmo Salvar e o mesmo horário da manhã valem para ele).
async function notices(push) {
  const p = await api.get("/notifications");
  const rows = KINDS.map(([key, title, help]) => {
    const on = h("input", { type: "checkbox", "aria-label": title });
    on.checked = p[key];
    const hour = h("select", { class: "select-sm", "aria-label": `Horário de ${title}` },
      ...HOURS.map((x) => h("option", { value: String(x), text: `${String(x).padStart(2, "0")}:00` })));
    hour.value = String(p[`${key}_hour`]);
    // O horário da manhã vale também para as notificações (cobranças e prazos): fica sempre editável.
    const sync = () => { hour.disabled = !on.checked && key !== "morning"; };
    on.addEventListener("change", sync);
    sync();
    return { key, on, hour, el: h("div", { class: "notice-row" },
      h("label", { class: "notice-main" }, on, h("span", {}, h("strong", { text: title }), h("small", { text: help }))),
      key === "morning" ? h("span", { class: "hour-shared" }, hour, h("small", { text: "horário da manhã: e-mail e notificações" })) : hour) };
  });
  // Semanal: o PDF anexado e uma cópia (quem acompanha o trabalho) — só valem com o resumo da semana ligado.
  const weekly = rows.find((r) => r.key === "weekly");
  const pdf = h("input", { type: "checkbox" });
  pdf.checked = !!p.weekly_pdf;
  const cc = h("input", { type: "email", maxlength: "254", value: p.weekly_cc || "", placeholder: "ex.: colega@empresa.com.br",
    autocomplete: "off", "aria-label": "Mandar cópia do resumo semanal para" });
  const weeklyExtra = h("div", { class: "notice-sub" },
    h("label", { class: "check-line" }, pdf, h("span", { text: "Anexar o relatório da semana em PDF (o mesmo de Meu mês, com os títulos das tarefas)" })),
    field("Mandar cópia para quem acompanha meu trabalho (opcional)", cc),
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
    try {
      await api.put("/notifications", body);
      await api.put("/push/prefs", { ...push.collect(), morning_hour: body.morning_hour });
      toast("Avisos salvos."); setDirty(false);
    }
    catch (e) { if (e.status === 422) toast("O e-mail da cópia não parece válido.", { error: true }); else errorToast(e, "Não foi possível salvar."); }
  });
  const test = h("button", { type: "button", class: "btn btn-ghost" }, icon("mail"), "Mandar um teste");
  test.disabled = !p.mail_configured;
  test.addEventListener("click", async () => {
    test.disabled = true;
    try { const r = await api.post("/notifications/test"); toast(`Teste enviado para ${r.to}.`); }
    catch (e) { errorToast(e, "Não foi possível enviar."); }
    finally { setTimeout(() => { test.disabled = false; }, 4000); }
  });
  // A semana passada como sairia na segunda (só para você; a cópia não recebe). Salve antes.
  const testWeek = h("button", { type: "button", class: "btn btn-ghost", title: "A semana passada como sairia na segunda, só para você (salve antes)" },
    icon("reports"), "Testar a semana");
  testWeek.disabled = !p.mail_configured;
  testWeek.addEventListener("click", async () => {
    testWeek.disabled = true;
    try { const r = await api.post("/notifications/test?kind=weekly"); toast(`Semana enviada para ${r.to}.`); }
    catch (e) { errorToast(e, "Não foi possível enviar."); }
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
      h("div", { class: "panel-head" }, h("h2", { text: "Avisos por e-mail" })),
      h("p", { class: "help" }, "Enviados para ", h("strong", { class: "mono", text: p.email }),
        ". Sem rastreamento de abertura ou de cliques; só sai e-mail quando há algo a avisar."),
      p.mail_configured ? null : warnBox("O envio de e-mail ainda não está configurado neste servidor. Você pode deixar tudo escolhido; os avisos começam quando ele for ligado."),
      ...rows.flatMap((r) => (r === weekly ? [r.el, weeklyExtra] : [r.el])),
      h("label", { class: "check-line notice-titles" }, titles, h("span", { text: "Mostrar os títulos das tarefas no e-mail (desligado: só os números)" })),
      h("div", { class: "row-actions" }, save, test, testWeek));
  for (const ev of ["input", "change"]) mailPanel.addEventListener(ev, (e) => { if (!e.target.closest(".row-actions")) setDirty(true); });
  return h("div", { class: "settings-grid" },
    push, mailPanel,
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
      field("O que a chave pode fazer", scope),
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
      err.textContent = e.message || "Não foi possível criar.";
      create.disabled = false;
    }
  }));

  const rowOf = (t) => {
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
    } else if (!t.revoked_at) {
      actions.append(h("button", { type: "button", class: "btn btn-ghost btn-sm", text: "Renovar", "aria-label": `Renovar a chave ${t.name}`,
        onClick: () => renewToken(t, rerender) }));
    }
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
  const seg = h("div", { class: "seg seg-sm ai-tabs", role: "tablist", "aria-label": "Sua IA" });
  const slot = h("div", { class: "ai-config" });
  const show = (i) => {
    for (const [n, b] of [...seg.children].entries()) b.setAttribute("aria-selected", String(n === i));
    const [, note, code] = AIS[i];
    clear(slot);
    slot.append(h("p", { class: "dialog-note" }, ...note), codeBox(code));
  };
  AIS.forEach(([name], i) => seg.append(h("button", { type: "button", class: "chip-btn", role: "tab", text: name, onClick: () => show(i) })));
  show(0);
  const dlg = modal(
    h("h2", { text: "Chave criada" }),
    h("p", { text: `“${res.name}” — copie agora: ela não aparece de novo.` }),
    h("div", { class: "token-box", text: res.token }),
    h("p", { class: "dialog-note ai-tabs-note", text: "Configuração pronta, já com a chave. Escolha a sua IA:" }),
    seg, slot,
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
      ...rows),
    recipesPanel());
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
  ["note.*", "Anotações"],
  ["checklist.*", "Checklist"],
  ["time.*", "Tempo apontado"],
  ["timer.*", "Cronômetro"],
  ["photo.*", "Fotos"],
  ["recurring.*", "Rotinas", "marcar, criar, editar, pausar"],
  ["project.*", "Projetos"],
  ["objective.*", "Objetivos"],
  ["renewal.*", "Vencimentos"],
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

// Receitas prontas (no site): avisos e planilha usando o webhook e a API, sem conector para produto.
function recipesPanel() {
  const base = "https://shadow.tec.br/nexus-api";
  const link = (hash, text) => h("a", { href: `${base}#${hash}`, target: "_blank", rel: "noopener noreferrer", text });
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Receitas prontas" })),
    h("p", { class: "help", text: "Passo a passo com o código mínimo (que confere a assinatura). O Nexus só avisa o endereço; quem fala com o chat, o e-mail ou a planilha é a sua automação ou um script curto. Depois de criar o webhook, use Testar para ver se o aviso chega." }),
    h("ol", { class: "help" },
      h("li", {}, link("r-telegram", "Avisar um grupo do Telegram"), " quando uma tarefa for concluída ou ficar aguardando."),
      h("li", {}, link("r-email", "Mandar um e-mail"), " a alguém quando algo acontecer."),
      h("li", {}, link("r-planilha", "Registrar cada tarefa concluída numa planilha"), " (Google Sheets)."),
      h("li", {}, link("r-alerta", "Alerta do monitoramento vira tarefa"), ", sem duplicar.")));
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
      h("p", { class: "help", text: "Ver o dia e como foi qualquer período (tempo por projeto), buscar, criar e editar tarefas (com projeto, prioridade e tempo apontado), concluir, criar e marcar rotinas (até 7 dias atrás), anotar progresso, montar checklist, apontar tempo e usar o cronômetro, montar projetos e objetivos, fazer a passagem de turno, ver vencimentos, achar como você resolveu algo parecido antes, consultar o histórico e desfazer um engano dela. Pelo MCP ela não exclui tarefas, rotinas, projetos nem objetivos. Mas a chave “ler e registrar” também vale para a API, que exclui (tudo volta pelo Histórico), e uma IA com terminal no seu computador (Claude Code, Gemini CLI) consegue usar a API. Se você só quer consultas, crie uma chave “só leitura”: com ela, a IA apenas consulta." }),
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

// Os dois aceites num painel só: sem eles, ninguém manda tarefas nem vê o registro.
function privacyPanel(me) {
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Quem vê e quem manda tarefas para você" })),
    h("h3", { class: "sum-h", text: "Receber tarefas" }), ...assignments(me),
    h("h3", { class: "sum-h", text: "Ver o seu registro" }), ...seenBy(me));
}

// Consentimento: sem ele, ninguém consegue mandar tarefas para esta pessoa.
function assignments(me) {
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
  return [
    h("p", { class: "help", text: "Quem tem o papel “Manda tarefas” (tela Atribuir) pode mandar tarefas para você, mas só se você permitir aqui. A tarefa recebida é sua: você edita, conclui ou exclui. Quem mandou só corrige ou cancela enquanto ela está a fazer e você não registrou nada nela." }),
    h("label", { class: "check-line" }, cb, h("span", { text: "Permitir que me atribuam tarefas" })),
    since];
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
    h("p", { class: "help mono", text: [me.email, ...(me.roles || []).filter((r) => r !== "user").map((r) => `${ROLE_SHORT[r]} (${ROLE_SCREEN[r]})`)].join(" · ") }),
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
function seenBy(me) {
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
    const viewers = list.filter((p) => p.roles.includes("viewer")).map((p) => p.name);
    help.textContent = `Quem tem o papel “Vê a equipe” (${viewers.length ? viewers.join(", ") : "hoje, ninguém"}) vê na tela Equipe, sem editar, seu quadro, seus números, seus relatórios em PDF, suas horas e suas fotos.` + (managed ? "" : " Só se você permitir.");
    const names = list.map((p) => `${p.name} (${p.roles.map((r) => ROLE_SHORT[r]).join(", ")})`);
    line.textContent = managed || cb.checked
      ? `Quem pode ver seu registro: ${names.length ? names.join(", ") : "só você"}.`
      : "Quem pode ver seu registro: só você.";
  };
  paint();
  api.get("/me/visibility").then((res) => { list = res; paint(); }).catch(() => line.remove());
  cb.addEventListener("change", async () => {
    cb.disabled = true;
    try {
      const res = await api.put("/me/viewers", { accept: cb.checked });
      meChanged(me, res);
      paint();
      toast(cb.checked ? "Pronto: quem vê a equipe vê seu registro." : "Quem vê a equipe não vê mais seu registro.");
    } catch (e) { cb.checked = !cb.checked; errorToast(e); }
    finally { cb.disabled = false; }
  });
  const lock = managed ? h("p", { class: "dialog-note lock-note", id: "seen-locked" }, icon("lock"),
    "Nesta instância do Nexus, quem gerencia a equipe vê as tarefas de todos (definido pela administração). " +
    `A sua escolha (${me.viewers_allowed ? "permitir" : "não permitir"}) fica guardada e volta a valer se isso mudar.`) : null;
  return [help, h("label", { class: "check-line" + (managed ? " is-locked" : "") }, cb, h("span", { text: "Permitir que quem tem o papel “Vê a equipe” veja meu registro" })), lock, line];
}
