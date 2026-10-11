// Configurações: dias úteis, chaves de API, integração com IA e conta.
import { api } from "./api.js";
import { h, icon, clear, dateTime } from "./dom.js";
import { codeBox, confirmDialog, errorToast, modal, toast, warnBox } from "./ui.js";
import { projectsPanel } from "./projects.js";

const TABS = [
  ["dias", "Dias úteis"],
  ["projetos", "Projetos"],
  ["avisos", "Avisos"],
  ["calendario", "Calendário"],
  ["chaves", "Chaves de API"],
  ["ia", "Integração com IA"],
  ["conta", "Conta"],
];

// Dias úteis como máscara de bits, domingo = bit 0 (igual ao backend).
const DAYS = [
  [1, "Seg"], [2, "Ter"], [3, "Qua"], [4, "Qui"], [5, "Sex"], [6, "Sáb"], [0, "Dom"],
];

export async function mount(root, ctx) {
  let active = (location.hash.split("?")[1] || "").replace("aba=", "") || "dias";
  if (!TABS.some(([k]) => k === active)) active = "dias";

  clear(root);
  const seg = h("div", { class: "seg", role: "tablist" });
  const body = h("div", { class: "settings-grid" });
  for (const [key, label] of TABS) {
    seg.append(h("button", {
      type: "button", class: "chip-btn", role: "tab", "aria-selected": key === active ? "true" : "false", text: label,
      onClick: () => {
        active = key;
        for (const b of seg.children) b.setAttribute("aria-selected", b.textContent === label ? "true" : "false");
        render();
      },
    }));
  }
  root.append(seg, body);

  async function render() {
    clear(body);
    if (active === "dias") body.append(workDays(ctx.me));
    else if (active === "projetos") body.append(await projectsPanel(() => render()));
    else if (active === "avisos") body.append(await notices());
    else if (active === "calendario") body.append(await calendarFeed(() => render()));
    else if (active === "chaves") body.append(await tokens(() => render()));
    else if (active === "ia") body.append(...aiHelp());
    else body.append(account(ctx.me));
  }
  await render();
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
    h("p", { class: "help", text: "Recorrentes só contam como devidas nesses dias. O que você marcar fora deles fica salvo como extra e não entra no percentual." }),
    h("fieldset", { class: "weekday-picker" },
      ...boxes.map(({ label, cb }) => h("label", { class: "weekday-option" }, cb, h("span", { text: label })))),
    err, save);
}

// ------------------------------------------------------------------ avisos --

const KINDS = [
  ["morning", "Seu dia", "De manhã: atrasadas, o que vence hoje, rotinas do dia e prioridades altas. Só nos dias úteis."],
  ["evening", "Antes de encerrar", "No fim do dia, se ainda faltar alguma rotina de hoje. Não sai se você já fez tudo."],
  ["weekly", "Resumo da semana", "Às segundas: rotinas, entregas, tempo por projeto e o que ficou para trás na semana anterior."],
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
  const titles = h("input", { type: "checkbox" });
  titles.checked = p.show_titles;
  const save = h("button", { type: "button", class: "btn btn-primary", text: "Salvar avisos" });
  save.addEventListener("click", async () => {
    const body = { show_titles: titles.checked };
    for (const r of rows) { body[r.key] = r.on.checked; body[`${r.key}_hour`] = Number(r.hour.value); }
    try { await api.put("/notifications", body); toast("Avisos salvos."); }
    catch (e) { errorToast(e, "Falha ao salvar."); }
  });
  const test = h("button", { type: "button", class: "btn btn-ghost" }, icon("mail"), "Mandar um teste");
  test.disabled = !p.mail_configured;
  test.addEventListener("click", async () => {
    test.disabled = true;
    try { const r = await api.post("/notifications/test"); toast(`Teste enviado para ${r.to}.`); }
    catch (e) { errorToast(e, "Falha no envio."); }
    finally { setTimeout(() => { test.disabled = false; }, 4000); }
  });
  const KIND_PT = { morning: "seu dia", evening: "fim do dia", weekly: "semana", test: "teste" };
  const recent = p.recent.filter((r) => r.ok !== null || r.error !== "nada a avisar");
  return h("div", { class: "settings-grid" },
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, icon("mail"), h("h2", { text: "Avisos por e-mail" })),
      h("p", { class: "help" }, "Enviados para ", h("strong", { class: "mono", text: p.email }),
        ". Sem rastreamento de abertura ou de cliques; só sai e-mail quando há algo a avisar."),
      p.mail_configured ? null : warnBox("O envio de e-mail ainda não está configurado neste servidor. Você pode deixar tudo escolhido; os avisos começam quando ele for ligado."),
      ...rows.map((r) => r.el),
      h("label", { class: "weekday-option notice-titles" }, titles, h("span", { text: "Mostrar os títulos das tarefas no e-mail (desligado: só os números)" })),
      h("div", { class: "row-actions" }, save, test)),
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
    h("label", { class: "weekday-option" }, rec, h("span", { text: "Incluir as rotinas (recorrentes)" })));

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
    h("div", { class: "field" }, h("label", { text: "Nome (para reconhecer no histórico)" }), name),
    h("div", { class: "field-row" },
      h("div", { class: "field" }, h("label", { text: "Permissão" }), scope),
      h("div", { class: "field" }, h("label", { text: "Validade" }), expires)),
    err, create);
  form.addEventListener("submit", async (ev) => {
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
  });

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
      h("p", { class: "help", text: "1. Crie uma chave em “Chaves de API” (permissão ler e registrar). 2. Conecte a IA:" }),
      h("p", { class: "dialog-note", text: "Claude Code (terminal):" }),
      codeBox(`claude mcp add --transport http nexus ${url} --header "Authorization: Bearer nxs_SUA_CHAVE"`),
      h("p", { class: "dialog-note", text: "Cursor e outros clientes MCP (arquivo de configuração):" }),
      codeBox(JSON.stringify({ mcpServers: { nexus: { url, headers: { Authorization: "Bearer nxs_SUA_CHAVE" } } } }, null, 2))),
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "O que a IA pode fazer" })),
      h("p", { class: "help", text: "Ver o dia, buscar, listar e criar tarefas (com projeto e prioridade), editar, concluir, marcar recorrentes (até 7 dias atrás), anotar progresso, montar e marcar checklist, apontar tempo, consultar o histórico e desfazer um engano dela. Ela não exclui tarefas. Com uma chave “só leitura”, ela apenas consulta." }),
      h("p", { class: "dialog-note", text: "API REST direta (scripts, automações):" }),
      codeBox(`curl -H "Authorization: Bearer nxs_SUA_CHAVE" ${location.origin}/api/board`)),
  ];
}

// ------------------------------------------------------------------- conta --

function account(me) {
  const cur = h("input", { type: "password", autocomplete: "current-password", required: "required" });
  const nova = h("input", { type: "password", autocomplete: "new-password", minlength: "10", required: "required" });
  const err = h("p", { class: "error-text" });
  const form = h("form", {},
    h("div", { class: "field" }, h("label", { text: "Senha atual" }), cur),
    h("div", { class: "field" }, h("label", { text: "Nova senha (mínimo 10 caracteres)" }), nova),
    err, h("button", { type: "submit", class: "btn btn-primary", text: "Trocar senha" }));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    try {
      await api.post("/auth/change-password", { current_password: cur.value, new_password: nova.value });
      cur.value = nova.value = "";
      toast("Senha trocada. Outras sessões foram encerradas.");
    } catch (e) {
      err.textContent = e.message || "Falha ao trocar.";
    }
  });
  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Conta" })),
    h("p", { class: "help mono", text: `${me.email}${me.role === "admin" ? " · admin" : ""}` }),
    form);
}
