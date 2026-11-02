// Tour guiado: abre sozinho no primeiro acesso e de novo pela Ajuda. Duas
// partes: (1) configurar o Nexus da pessoa com os formulários de verdade
// (nome, tema, dias úteis, projetos, projeto padrão, rotinas) e (2) um passeio pela
// tela Hoje, com destaque em cada parte, mostrando como fica o dia a dia.
// Quem já configurou passa rápido: cada passo vem com o que já está salvo.
// Tour obrigatório no primeiro acesso de toda conta nova (sempre, desde 01/11): sem "Pular"
// nem Esc até concluir (Voltar continua); a conclusão vai para o servidor.
// Parada que falha (passo que não carrega, alvo ausente) segue para a próxima.
import { api } from "./api.js";
import { h, icon, clear, field } from "./dom.js";
import { errorToast, modal } from "./ui.js";
import { listProjects, projectChip } from "./projects.js";
import { applyPack, loadPacks, packAreas, packPicker } from "./pacotes.js";

const DAYS = [[1, "Seg"], [2, "Ter"], [3, "Qua"], [4, "Qui"], [5, "Sex"], [6, "Sáb"], [0, "Dom"]];
// Exemplos de várias áreas de suporte (TI, manutenção, atendimento): ninguém se sente fora.
const PROJ_HINTS = ["Atendimento", "Manutenção", "Interno"];
const ROUTINE_HINTS = ["Revisar a fila de pedidos", "Conferir os backups da noite", "Fazer a ronda do prédio",
  "Conferir o e-mail do plantão"];

let running = false;

// Com equipes (sql/043), "Para empresas" vale só para quem está em alguma e
// alcança só quem compartilha equipe: os textos dizem isso (com o nome delas).
const teamsOf = (me) => (me.teams || []).join(", ");
const VIS_TEXT = (me) => me.teams_on && (me.teams || []).length
  ? `Nesta instância do Nexus, quem gerencia vê as tarefas de quem está na mesma equipe (definido pela administração). Você está em: ${teamsOf(me)}. Quem tem o papel “Vê a equipe” nessas equipes vê, sem editar, o seu quadro, os seus números, relatórios, horas e fotos.`
  : "Nesta instância do Nexus, quem gerencia a equipe vê as tarefas de todos (definido pela administração). Quem tem o papel “Vê a equipe” vê, sem editar, o seu quadro, os seus números, relatórios, horas e fotos.";
const assignText = (me) => me.teams_on && (me.teams || []).length
  ? `Nesta instância do Nexus, quem está na mesma equipe recebe tarefas de quem atribui (definido pela administração). Você está em: ${teamsOf(me)}. Quem tem o papel “Manda tarefas” nessas equipes pode atribuir tarefas para você; cada uma chega por e-mail e aparece em Tarefas com “de” e o nome de quem mandou.`
  : ASSIGN_TEXT;

const ASSIGN_TEXT = "Nesta instância do Nexus, todos recebem tarefas de quem atribui (definido pela administração). Quem tem o papel “Manda tarefas” pode atribuir tarefas para você; cada uma chega por e-mail e aparece em Tarefas com “de” e o nome de quem mandou.";
const ASSIGN_OWN = "A tarefa recebida é sua: você edita, conclui ou devolve com o motivo.";
// Aviso único de papel ganho ou retirado pela administração (o menu já mudou;
// isto explica o porquê). Só "Entendi" grava; Esc mostra de novo depois.
const ROLE_INFO = {
  user: ["Usuário", "Você tem o próprio registro: Hoje, Tarefas, Rotinas e relatórios."],
  admin: ["Admin", "Você administra o Nexus: convites, contas, papéis e configurações. Fica em Admin, no menu."],
  assigner: ["Manda tarefas", "Você pode atribuir tarefas a quem aceitou receber e acompanhar o que atribuiu."],
  viewer: ["Vê a equipe", "Você vê, sem editar, o registro da equipe na tela Equipe, no menu."],
  master: ["Admin master", "Você é o admin master: com “Vê a equipe” e “Manda tarefas” ligados (Admin › Equipes), vê e atribui tarefas para todos, com ou sem equipe. O que você abrir do registro dos outros fica no log de admin, e só você passa este papel adiante."],
};
// Com Para empresas ligado, "Manda tarefas" e "Vê a equipe" valem para todos (sem aceite).
function roleText(k, me) {
  const org = me.org || {};
  const inTeams = me.teams_on && !me.is_master;
  if (inTeams && k === "assigner") return (me.teams || []).length ? `Você pode atribuir tarefas para quem está nas suas equipes (${teamsOf(me)}) e acompanhar o que atribuiu, na tela Equipe.` : "Você pode atribuir tarefas para quem está nas suas equipes. Hoje você não está em nenhuma: peça à administração para incluir você.";
  if (inTeams && k === "viewer") return (me.teams || []).length ? `Você vê, sem editar, o registro de quem está nas suas equipes (${teamsOf(me)}) na tela Equipe, no menu.` : "Você vê, sem editar, o registro de quem está nas suas equipes. Hoje você não está em nenhuma: peça à administração para incluir você.";
  if (k === "assigner" && org.assign_receive === "all") return "Você pode atribuir tarefas para todos da equipe (nesta instância, todos recebem de quem atribui) e acompanhar o que atribuiu, na tela Equipe.";
  if (k === "viewer" && org.team_visibility === "managers") return "Você vê, sem editar, o registro de toda a equipe na tela Equipe, no menu (nesta instância, visível para quem gerencia).";
  return ROLE_INFO[k][1];
}
// "O que mudou para você": UM diálogo para todos os avisos únicos (visibilidade, receber tarefas,
// papéis ganhos ou retirados, inclusive master e equipe). Um "Entendi" dá todos como vistos;
// Esc mostra de novo depois. Devolve o diálogo (ou null, sem nada a avisar).
export async function changesNotice(me) {
  const items = [];
  if (me.visibility_notice) {
    const list = await api.get("/me/visibility").catch(() => []);
    const viewers = list.filter((p) => p.roles.includes("viewer")).map((p) => p.name);
    items.push(["Quem gerencia a equipe vê o seu registro", [VIS_TEXT(me),
      viewers.length ? `Hoje, com esse papel: ${viewers.join(", ")}.` : "Hoje, ninguém tem esse papel.",
      "A sua escolha em Configurações > Conta fica guardada e volta a valer se a administração mudar isso" + (me.teams_on ? " ou se você sair das equipes." : ".")]]);
  }
  if (me.assign_notice) items.push(["Você pode receber tarefas de quem atribui", [assignText(me), ASSIGN_OWN,
    "A sua escolha em Configurações > Conta fica guardada e volta a valer se a administração mudar isso."]]);
  const n = me.role_notice || {};
  for (const k of (n.added || []).filter((x) => ROLE_INFO[x])) items.push([`Papel novo: ${ROLE_INFO[k][0]}`, [roleText(k, me)]]);
  for (const k of (n.removed || []).filter((x) => ROLE_INFO[x]))
    items.push([`Papel retirado: ${ROLE_INFO[k][0]}`, ["O que vinha com esse papel saiu do menu. Os seus dados continuam guardados."]]);
  if (!items.length) return null;
  const ok = h("button", { type: "button", class: "btn btn-primary", text: "Entendi", onClick: async () => {
    try {
      await api.put("/me/notices-seen");
      Object.assign(me, { visibility_notice: false, assign_notice: false, role_notice: null });
      dlg.close();
    } catch (e) { errorToast(e); }
  } });
  const list = h("ul", { class: "role-notice-list", id: "changes-notice-list" },
    ...items.map(([title, lines]) => h("li", {}, h("strong", { text: title }), ...lines.map((t) => h("span", { text: t })))));
  const dlg = modal(h("h2", { text: "O que mudou para você" }), list, h("div", { class: "dialog-actions" }, ok));
  dlg.setAttribute("aria-describedby", list.id);
  ok.focus();
  return dlg;
}

// me: o objeto da sessão (é atualizado e avisado com "nexus:me").
// Onde a pessoa estava no tour (recarregou a página no meio): {uid, step} ou {uid, walk: true}.
const TOUR_KEY = "nexus.tour.passo";
const tourSaved = (me) => { try { const s = JSON.parse(localStorage.getItem(TOUR_KEY) || "null"); return s && s.uid === me.id ? s : null; } catch { return null; } };
const tourSave = (me, s) => { try { localStorage.setItem(TOUR_KEY, JSON.stringify({ uid: me.id, ...s })); } catch { /* sem armazenamento */ } };
const tourForget = () => { try { localStorage.removeItem(TOUR_KEY); } catch { /* idem */ } };

export async function startTour(me) {
  if (running) return;
  running = true;
  const must = !!me.tour_required;
  let completed = false;
  // Só o obrigatório retoma: aberto pela Ajuda, começa do começo.
  const saved = must ? tourSaved(me) : null;
  try {
    const go = saved && saved.walk ? "walk" : await setup(me, must, saved ? saved.step : 0);
    if (go === "walk") { if (must) tourSave(me, { walk: true }); await walk(must); completed = true; }
  } finally {
    running = false;
    if (completed) tourForget();
    // Visto (ou pulado, quando pode): não abre sozinho de novo; a Ajuda reabre.
    // Obrigatório e interrompido (aba fechada, erro): abre de novo no próximo acesso.
    if (!must || completed) {
      api.put("/me/tour", { done: true }).then((r) => {
        Object.assign(me, { tour_done_at: r.tour_done_at, tour_required: !!r.tour_required, visibility_notice: !!r.visibility_notice,
          assign_notice: !!r.assign_notice });
      }).catch(() => {});
    }
  }
}

const NUM = { 5: "cinco", 6: "seis", 7: "sete", 8: "oito" };

function changed(me, res) {
  Object.assign(me, res);
  window.dispatchEvent(new Event("nexus:me"));
}

// ------------------------------------------------------ parte 1: configurar --
// Devolve "walk" (seguir para o passeio) ou "close".
function setup(me, must, from = 0) {
  return new Promise((resolve) => {
    let result = "close", step = from, dir = 1;
    const body = h("div", { class: "tour-body" });
    const dlg = h("dialog", { class: "tour-dialog", "aria-labelledby": "tour-title" }, body);
    document.body.append(dlg);
    let ended = false;
    dlg.addEventListener("close", () => {
      // Obrigatório: só sai pelo botão principal. Se o navegador fechou mesmo assim
      // (Esc repetido, gesto de voltar), abre de novo no mesmo passo.
      if (must && !ended) { dlg.showModal(); paint().catch(() => {}); return; }
      dlg.remove(); resolve(result);
    });
    // Obrigatório: Esc não fecha (o tour termina pelo botão principal).
    dlg.addEventListener("keydown", (ev) => { if (must && ev.key === "Escape") ev.preventDefault(); });
    dlg.addEventListener("cancel", (ev) => { if (must) ev.preventDefault(); else result = "close"; });

    const org = me.org || {};
    const nameLocked = !!org.identity_managed;
    const visOn = org.team_visibility === "managers";
    const assignOn = org.assign_receive === "all";
    const steps = [welcome, profile, theme, ...(visOn ? [visibility] : []), ...(assignOn ? [receiving] : []),
      workDays, projects, defaultProject, routines, ready];
    // Boas-vindas e "pronto" não contam; sem projetos, "Projeto padrão" é pulado e também não conta.
    let noProjects = false;
    listProjects().then((l) => { noProjects = !l.length; }).catch(() => {});
    const dp = steps.indexOf(defaultProject);
    const total = () => steps.length - 2 - (noProjects ? 1 : 0);
    const shown = () => step - (noProjects && step > dp ? 1 : 0);
    const next = () => { step++; dir = 1; paint(); };
    const back = () => { step--; dir = -1; paint(); };
    const end = (r) => { ended = true; result = r; dlg.close(); };

    // Passo que não carrega (rede, servidor) não prende ninguém: segue na mesma direção.
    async function paint() {
      let content;
      try { content = await steps[step](); }
      catch (e) {
        const to = Math.min(steps.length - 1, Math.max(0, step + dir));
        if (to === step) throw e;
        step = to;
        return paint();
      }
      if (must) tourSave(me, { step }); // recarregou no meio: volta a este passo
      clear(body);
      body.append(...content);
      const first = body.querySelector("input:not([type=checkbox]), select, .btn-primary");
      if (first) first.focus();
    }

    // Cabeçalho e rodapé comuns: passo N de M, Pular, Voltar e o botão principal.
    function frame(title, intro, controls, save, primary = "Salvar e seguir") {
      const err = h("p", { class: "error-text" });
      const ok = h("button", { type: "submit", class: "btn btn-primary", text: primary });
      const form = h("form", {},
        h("p", { class: "tour-step mono", text: `Configuração · ${shown()} de ${total()}` }),
        h("h2", { id: "tour-title", text: title }),
        h("p", { class: "tour-intro", text: intro }),
        ...controls, err,
        h("div", { class: "dialog-actions tour-actions" },
          must ? null : h("button", { type: "button", class: "btn btn-text tour-skip", text: "Pular o tour", onClick: () => end("close") }),
          h("button", { type: "button", class: "btn btn-text" + (must ? " tour-skip" : ""), text: "Voltar", onClick: back }),
          ok));
      form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        err.textContent = "";
        ok.disabled = true;
        try { if (save) await save(); next(); }
        catch (e) { err.textContent = e.message || "Não foi possível salvar."; }
        finally { ok.disabled = false; }
      });
      return [form];
    }

    function welcome() {
      const nome = me.display_name ? `, ${me.display_name}` : "";
      return [
        h("div", { class: "tour-hero" }, h("img", { src: "/img/dragon-mark.svg", alt: "", width: "40", height: "46" })),
        h("h2", { id: "tour-title", text: `Boas-vindas ao Nexus${nome}` }),
        h("p", { class: "tour-intro", text: "O Nexus guarda o seu dia de trabalho: as rotinas que você confere, as tarefas que aparecem e o tempo de cada uma. No fim do dia, da semana ou do mês, o relatório sai pronto." }),
        h("p", { class: "tour-intro", text: `Primeiro, ${NUM[total()] || total()} passos rápidos para deixar o Nexus do seu jeito. Depois, um passeio de um minuto pela tela. ` +
          (must ? "Neste primeiro acesso o tour vai até o fim; dá para rever tudo depois pela Ajuda." : "Dá para rever tudo depois pela Ajuda.") }),
        h("div", { class: "dialog-actions tour-actions" },
          must ? null : h("button", { type: "button", class: "btn btn-text tour-skip", text: "Agora não", onClick: () => end("close") }),
          must ? null : h("button", { type: "button", class: "btn btn-ghost", text: "Só o passeio", onClick: () => end("walk") }),
          h("button", { type: "button", class: "btn btn-primary", text: "Começar", onClick: next })),
      ];
    }

    function profile() {
      // Nome definido pela administração: o tour só mostra (sem campo para editar).
      if (nameLocked) {
        return frame("O seu nome no Nexus", "Aparece no menu, nas saudações do assistente e para quem atribui tarefas a você. Nesta instância, nome e e-mail são definidos pela administração: para mudar, fale com quem administra.",
          [h("p", { class: "tour-name-locked" }, h("strong", { text: me.name }), h("span", { class: "mono", text: me.email }))], null, "Seguir");
      }
      const name = h("input", { type: "text", maxlength: "60", value: me.display_name || "", placeholder: "Seu nome", autocomplete: "name" });
      const intro = me.display_name
        ? "Quem convidou você colocou este nome. Confira e ajuste se quiser: aparece no menu, nas saudações do assistente e para quem atribui tarefas a você."
        : "Aparece no menu, nas saudações do assistente e para quem atribui tarefas a você. A foto você coloca depois em Configurações > Conta.";
      return frame(me.display_name ? "Este é o seu nome?" : "Qual nome devemos usar?", intro,
        [field("Nome", name)],
        async () => {
          const v = name.value.trim() || null;
          if (v !== (me.display_name || null)) changed(me, await api.put("/me/profile", { display_name: v }));
        });
    }

    // Tema: muda na hora e fica guardado na conta (como em Configurações > Conta).
    function theme() {
      const OPTS = [["auto", "Automático", "Segue o tema do aparelho"], ["light", "Claro", null], ["dark", "Escuro", null]];
      const seg = h("div", { class: "seg tour-theme", role: "radiogroup", "aria-label": "Tema" });
      const paint = (cur) => { for (const b of seg.children) b.setAttribute("aria-checked", String(b.dataset.v === cur)); };
      for (const [v, label, tip] of OPTS) {
        seg.append(h("button", { type: "button", class: "chip-btn", role: "radio", "data-v": v, title: tip, text: label, onClick: async () => {
          window.nexusTheme.set(v);
          paint(v);
          try { await api.put("/me/theme", { theme: v }); me.theme = v; } catch (e) { errorToast(e, "Não foi possível guardar o tema na conta."); }
        } }));
      }
      paint(me.theme || "dark");
      return frame("Claro ou escuro?", "Automático segue o aparelho: se ele escurece à noite, o Nexus também. Toque para ver como fica. Dá para trocar depois em Configurações > Conta.",
        [seg], null, "Seguir");
    }

    // Só quando a administração ligou "Visível para quem gerencia": quem vê o quê.
    async function visibility() {
      const list = await api.get("/me/visibility").catch(() => []);
      const viewers = list.filter((p) => p.roles.includes("viewer")).map((p) => p.name);
      return frame("Quem vê o seu registro", VIS_TEXT(me),
        [h("p", { class: "dialog-note", text: viewers.length ? `Hoje, com esse papel: ${viewers.join(", ")}.` : "Hoje, ninguém tem esse papel." }),
          h("p", { class: "dialog-note", text: "A lista fica sempre em Configurações > Conta." })],
        async () => { await api.put("/me/visibility-notice"); me.visibility_notice = false; }, "Entendi");
    }

    // Só quando a administração ligou "Todos recebem de quem atribui".
    function receiving() {
      return frame("Tarefas de quem atribui", assignText(me),
        [h("p", { class: "dialog-note", text: ASSIGN_OWN })],
        async () => { await api.put("/me/assign-notice"); me.assign_notice = false; }, "Entendi");
    }

    function workDays() {
      const boxes = DAYS.map(([bit, label]) => {
        const cb = h("input", { type: "checkbox" });
        cb.checked = ((me.work_days >> bit) & 1) === 1;
        return { bit, label, cb };
      });
      return frame("Quais são os seus dias úteis?", "As rotinas “nos dias úteis” seguem estes dias, e o assistente só cobra registro neles. Plantão no fim de semana não precisa entrar: marque a tarefa como plantão.",
        [h("fieldset", { class: "weekday-picker" }, ...boxes.map(({ label, cb }) => h("label", { class: "weekday-option" }, cb, h("span", { text: label }))))],
        async () => {
          const mask = boxes.reduce((m, { bit, cb }) => (cb.checked ? m | (1 << bit) : m), 0);
          if (!mask) throw new Error("Escolha pelo menos um dia.");
          if (mask !== me.work_days) {
            const res = await api.post("/auth/settings", { work_days: mask });
            changed(me, { work_days: res.work_days });
          }
        });
    }

    async function projects() {
      let list = await listProjects(true).catch(() => []);
      const chips = h("div", { class: "tour-chips" });
      const input = h("input", { type: "text", maxlength: "60", placeholder: "Ex.: Loja Centro, Clínica Vida, Rede" });
      const err = h("p", { class: "error-text" });
      const paintChips = () => {
        clear(chips);
        for (const p of list) {
          chips.append(projectChip({ project_name: p.name, project_color: p.color, project_icon: p.icon }));
        }
        for (const s of PROJ_HINTS.filter((s) => !list.some((p) => p.name.toLowerCase() === s.toLowerCase())))
          chips.append(h("button", { type: "button", class: "chip tour-suggest", title: "Criar o projeto " + s, onClick: () => add(s) }, icon("add"), s));
      };
      async function add(name) {
        err.textContent = "";
        name = name.trim();
        if (!name) return;
        try {
          await api.post("/projects", { name });
          list = await listProjects(true);
          noProjects = false;
          input.value = "";
          paintChips();
          // Criou: o botão deixa de dizer "sem projetos" (soava como descartar o que acabou de criar).
          const ok = input.closest("form")?.querySelector("[type=submit]");
          if (ok) ok.textContent = "Seguir";
          input.focus();
        } catch (e) { err.textContent = e.message || "Não foi possível criar."; }
      }
      input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); add(input.value); } });
      paintChips();
      return frame("Para quem ou em que frente você trabalha?", "Projetos agrupam as tarefas: clientes, filiais, sistemas ou frentes da equipe. Com eles você filtra o quadro, vê o tempo de cada um e tira o relatório só daquele projeto. No menu Projetos, cada um ganha objetivos em ordem de execução.",
        [chips, h("div", { class: "inline-form" }, field("Novo projeto", input),
          h("button", { type: "button", class: "btn btn-ghost", onClick: () => add(input.value) }, icon("add"), "Adicionar")), err],
        async () => { if (input.value.trim()) await add(input.value); },
        list.length ? "Seguir" : "Seguir sem projetos");
    }

    async function defaultProject() {
      const list = await listProjects().catch(() => []);
      noProjects = !list.length;
      if (!list.length) { step += dir; return steps[step](); } // sem projetos não há o que escolher: passa reto
      const sel = h("select", {},
        h("option", { value: "", text: "Nenhum (a tarefa fica sem projeto)" }),
        ...list.map((p) => h("option", { value: String(p.id), text: p.name })));
      sel.value = list.some((p) => p.id === me.default_project_id) ? String(me.default_project_id) : "";
      return frame("Projeto padrão", "Se quase tudo o que você faz é de uma frente, escolha-a aqui: a tarefa criada sem projeto entra nela (no registro rápido, nos modelos, pela IA e nas que você recebe). Na hora de criar, dá para trocar.",
        [field("Projeto padrão", sel)],
        async () => {
          const id = sel.value ? Number(sel.value) : null;
          if (id !== (me.default_project_id || null)) changed(me, await api.put("/me/default-project", { project_id: id }));
        });
    }

    async function routines() {
      const [board, packs] = await Promise.all([api.get("/board").catch(() => ({ recurring: [] })), loadPacks().catch(() => [])]);
      const have = board.recurring.map((r) => r.label.toLowerCase());
      const picks = ROUTINE_HINTS.filter((s) => !have.includes(s.toLowerCase())).map((label) => {
        const cb = h("input", { type: "checkbox" });
        return { label, cb };
      });
      const custom = h("input", { type: "text", maxlength: "200", placeholder: "Ex.: Verificar o link da filial" });
      // Pacote da área: tocar numa área mostra os itens dela para marcar; tocar de novo desmarca.
      let pack = null, picker = null;
      const packBox = h("div", { class: "tour-pack" });
      const paintPack = () => {
        clear(packBox);
        packBox.append(packAreas(packs, (p) => { pack = pack && pack.id === p.id ? null : p; paintPack(); }, pack && pack.id));
        picker = pack ? packPicker(pack) : null;
        if (picker) packBox.append(picker.el);
      };
      paintPack();
      return frame("O que você confere todo dia?", "Rotinas são as verificações que se repetem. Você marca no Hoje, anota a evidência (“quadro 3 sem aquecimento”, “backup OK”) e o relatório mostra quantas foram feitas. Agenda e horário de cada uma mudam depois.",
        [board.recurring.length ? h("p", { class: "dialog-note", text: "Você já tem: " + board.recurring.map((r) => r.label).join(", ") + "." }) : null,
          packs.length ? h("p", { class: "pack-sub", text: "Começar com um pacote da sua área" }) : null,
          packs.length ? packBox : null,
          h("p", { class: "pack-sub", text: packs.length ? "Ou escolha avulsas (nos dias úteis)" : "Sugestões (nos dias úteis)" }),
          h("div", { class: "tour-picks" }, ...picks.map(({ label, cb }) => h("label", { class: "check-row" }, cb, h("span", { class: "label", text: label })))),
          field("Outra rotina (opcional)", custom)],
        async () => {
          const done = new Set();
          if (pack && picker) {
            const sel = picker.value();
            if (sel.items.length || sel.project) {
              const res = await applyPack(pack, sel);
              for (const r of res.created) done.add(r.label.toLowerCase());
              for (const l of res.skipped) done.add(l.toLowerCase());
            }
          }
          const labels = [...picks.filter((p) => p.cb.checked).map((p) => p.label), custom.value.trim()].filter(Boolean);
          for (const label of labels) if (!done.has(label.toLowerCase())) await api.post("/recurring", { label });
        },
        "Criar e seguir");
    }

    function ready() {
      return [
        h("p", { class: "tour-step mono", text: "Tudo pronto" }),
        h("h2", { id: "tour-title", text: "Agora, o dia a dia" }),
        h("p", { class: "tour-intro", text: must
          ? "Um passeio rápido pela tela Hoje: onde registrar, o que filtrar e onde ficam os relatórios. São poucos passos."
          : "Um passeio rápido pela tela Hoje: onde registrar, o que filtrar e onde ficam os relatórios. São poucos passos, e dá para sair a qualquer momento." }),
        h("div", { class: "dialog-actions tour-actions" },
          must ? null : h("button", { type: "button", class: "btn btn-text tour-skip", text: "Fechar", onClick: () => end("close") }),
          h("button", { type: "button", class: "btn btn-text" + (must ? " tour-skip" : ""), text: "Voltar", onClick: () => { step = steps.indexOf(routines); dir = -1; paint(); } }),
          h("button", { type: "button", class: "btn btn-primary", text: "Fazer o passeio", onClick: () => end("walk") })),
      ];
    }

    dlg.showModal();
    paint().catch((e) => { errorToast(e); end(must ? "walk" : "close"); });
  });
}

// ------------------------------------------------- parte 2: o passeio --
// Cada parada: seletores candidatos (o primeiro visível vale: computador ou
// celular), título e texto. Parada sem alvo visível é pulada.
const QUICK = [[".quick-row input"], "Registro rápido",
  "Escreva o que fez e aperte Enter. Dois atalhos ajudam: @Projeto escolhe o projeto e “— 30min” já conclui com o tempo. Ex.: “Troca do disjuntor @Matriz — 45min”. Os outros (#chamado, !alta, ^amanhã) estão na Ajuda."];
const ROUTINES = [[".t-rec"], "Rotinas do dia",
  "Marque o que conferiu. Depois de marcar, o bloquinho anota a evidência; no ⋮, um achado vira tarefa. As setas voltam até 7 dias para marcar o que ficou para trás."];
const HANDOFF = [["#page-actions .btn-ghost"], "Passagem de turno",
  "No fim do turno, um texto pronto com o que fica aberto, o que está aguardando e por quê, e o que foi feito. É só colar no chat da equipe."];
// Celular: só o essencial do dia, em quatro paradas (o resto se descobre usando).
const PHONE_STOPS = [
  QUICK,
  ROUTINES,
  [[".t-open .list-row[data-task-id]"], "Uma tarefa", // sem tarefas ainda (primeiro dia), a parada é pulada
    "Toque no nome para abrir: anotações, checklist, fotos e tempo. O ✓ conclui. No ⋮ ficam o cronômetro, “Marcar como aguardando…” e “Duplicar tarefa”."],
  HANDOFF,
];
const STOPS = [
  QUICK,
  [[".open-filter"], "Filtro das abertas",
    "Para focar: só o que vence hoje (as atrasadas entram junto) ou só as de prioridade alta. A escolha fica até você fechar a aba."],
  ROUTINES,
  [["#assist-slot > *"], "O assistente",
    "A saudação, o que pede atenção (atrasadas, aguardando há dias) e, à tarde, o resumo do dia. Ele cabe numa linha e se desliga em Configurações > Conta."],
  [["[data-fab]", "#fab"], "Tarefa completa",
    "Quando precisa de mais: prazo, prioridade, projetos, chamado, checklist e tempo. Depois, tudo se edita no próprio detalhe da tarefa (o lápis ao lado do título)."],
  HANDOFF,
  [['#nav [data-view="tarefas"]', '#tabbar [data-view="tarefas"]'], "Tarefas",
    "O quadro com tudo o que está aberto, filtro por projeto e o detalhe de cada tarefa: anotações, checklist, cronômetro e o “como resolveu”, que entra na busca."],
  [['#nav [data-view="projetos"]'], "Projetos",
    "Cada projeto com os objetivos (as demandas principais) na ordem de execução e as tarefas de cada um. Arraste para mudar a ordem; o progresso de cada objetivo se calcula sozinho."],
  [['#nav [data-view="mes"]', '#tabbar [data-view="mes"]'], "Meu mês",
    "Como foi o mês numa frase e num painel: rotinas, tarefas e horas com os últimos 6 meses ao lado, o calendário do mês e o tempo por projeto. O PDF do mês sai num botão, para prestar contas. O Histórico guarda cada mudança, com desfazer."],
  [["#btn-help", '#tabbar [data-view="mais"]'], "Ajuda",
    "Atalhos, o manual tela por tela e este tour de novo, quando quiser."],
];

function visible(el) {
  if (!el || el.closest(".hidden")) return false;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

function walk(must = false) {
  return new Promise((resolve) => {
    // Sempre um Hoje recém-montado (com o que o tour acabou de criar): de outra
    // tela, troca a rota; já no Hoje, monta de novo.
    if (/^#\/hoje\b/.test(location.hash)) dispatchEvent(new HashChangeEvent("hashchange"));
    else location.hash = "#/hoje";
    const zoom = () => parseFloat(getComputedStyle(document.body).zoom) || 1;
    const spot = h("div", { class: "tour-spot", "aria-hidden": "true" });
    const title = h("h2", { id: "tour-pop-title" });
    const text = h("p", { id: "tour-pop-text" });
    const count = h("span", { class: "tour-step mono" });
    const live = h("p", { class: "sr-only", "aria-live": "polite" }); // o foco fica no "Próximo": a parada nova é lida daqui
    const prev = h("button", { type: "button", class: "btn btn-text", text: "Voltar" });
    const next = h("button", { type: "button", class: "btn btn-primary" });
    if (must) prev.classList.add("tour-skip");
    const pop = h("div", { class: "tour-pop", role: "dialog", "aria-modal": "true", "aria-labelledby": "tour-pop-title", "aria-describedby": "tour-pop-text" },
      count, title, text, live,
      h("div", { class: "dialog-actions tour-actions" },
        must ? null : h("button", { type: "button", class: "btn btn-text tour-skip", text: "Encerrar", onClick: () => done() }), prev, next));
    // Fundo escuro em quatro faixas em volta do alvo (cima, baixo, esquerda, direita).
    const shades = [0, 1, 2, 3].map(() => h("div", { class: "tour-shade", "aria-hidden": "true" }));
    const layer = h("div", { class: "tour-layer" }, ...shades, spot, pop);
    const rect = (el, x, y, w, hh) => Object.assign(el.style, { left: x + "px", top: y + "px", width: Math.max(0, w) + "px", height: Math.max(0, hh) + "px" });
    let stops = [], i = 0, target = null;

    function done() {
      removeEventListener("resize", place);
      removeEventListener("scroll", place, true);
      document.removeEventListener("keydown", onKey, true);
      layer.remove();
      resolve();
    }
    function onKey(ev) {
      if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); if (!must) done(); }
      else if (ev.key === "ArrowRight") { ev.preventDefault(); show(i + 1); }
      else if (ev.key === "ArrowLeft") { ev.preventDefault(); show(i - 1, -1); }
      else if (ev.key === "Tab") { // o foco fica no cartão
        const btns = [...pop.querySelectorAll("button:not([disabled])")];
        const at = btns.indexOf(document.activeElement);
        ev.preventDefault();
        btns[(at + (ev.shiftKey ? -1 : 1) + btns.length) % btns.length].focus();
      }
      else ev.stopPropagation(); // atalhos do app não disparam por baixo
    }
    // Destaque sobre o alvo; o cartão embaixo (ou em cima, se não couber).
    function place() {
      const z = zoom(), vw = innerWidth / z, vh = innerHeight / z;
      if (!target) {
        spot.classList.add("hidden");
        rect(shades[0], 0, 0, vw, vh);
        for (const sh of shades.slice(1)) rect(sh, 0, 0, 0, 0);
        pop.style.left = Math.max(16, (vw - pop.offsetWidth) / 2) + "px";
        pop.style.top = Math.max(16, (vh - pop.offsetHeight) / 2) + "px";
        return;
      }
      spot.classList.remove("hidden");
      const r = target.getBoundingClientRect();
      // Alvo mais alto que meia tela (o painel de Rotinas): destaca só o começo dele
      // (título e as primeiras linhas), e o cartão vem logo abaixo, sem cobrir o destaque.
      const pad = 6, x = r.left / z - pad, y = r.top / z - pad, w = r.width / z + pad * 2, hh = Math.min(r.height / z + pad * 2, vh * 0.45);
      rect(spot, x, y, w, hh);
      rect(shades[0], 0, 0, vw, y);
      rect(shades[1], 0, y + hh, vw, vh - y - hh);
      rect(shades[2], 0, y, x, hh);
      rect(shades[3], x + w, y, vw - x - w, hh);
      const pw = pop.offsetWidth, ph = pop.offsetHeight, gap = 12;
      let top = y + hh + gap;
      if (top + ph > vh - 16) top = y - ph - gap;
      if (top < 16) top = Math.min(vh - ph - 16, Math.max(16, y + hh + gap));
      const left = Math.min(Math.max(16, x), Math.max(16, vw - pw - 16));
      pop.style.left = left + "px";
      pop.style.top = top + "px";
    }
    // O alvo é procurado na hora: a tela pode ter sido montada de novo no meio.
    const find = (sels) => sels.map((s) => document.querySelector(s)).find(visible);
    // Alvo que sumiu (a tela mudou no meio): a parada é pulada na mesma direção.
    function show(n, dir = 1) {
      while (n >= 0 && n < stops.length && !find(stops[n][0])) n += dir;
      if (n < 0 || n >= stops.length) { if (n >= stops.length) done(); return; }
      i = n;
      const [sels, t, body] = stops[i];
      const el = find(sels);
      target = el || null;
      title.textContent = t;
      text.textContent = body;
      count.textContent = `${i + 1} de ${stops.length}`;
      live.textContent = "";
      setTimeout(() => { live.textContent = `Parada ${i + 1} de ${stops.length}: ${t}. ${body}`; }, 60);
      prev.disabled = i === 0;
      next.textContent = i === stops.length - 1 ? "Concluir" : "Próximo";
      const tall = el && el.getBoundingClientRect().height / zoom() > (innerHeight / zoom()) * 0.45;
      if (el) el.scrollIntoView({ block: tall ? "start" : "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      requestAnimationFrame(place);
      setTimeout(place, 350); // depois da rolagem suave
      next.focus();
    }
    prev.addEventListener("click", () => show(i - 1, -1));
    next.addEventListener("click", () => show(i + 1));
    layer.addEventListener("click", (ev) => { if (ev.target === layer) next.focus(); }); // clique fora não fecha por engano

    // Espera o Hoje aparecer montado (a tela da visita anterior fica no DOM,
    // escondida: só existir não basta). Pronto em duas olhadas seguidas.
    const view = document.getElementById("view-hoje");
    const ready = () => !view.classList.contains("hidden") && !view.hasAttribute("aria-busy")
      && visible(view.querySelector(".quick-row input"));
    let tries = 0, streak = 0;
    (function wait() {
      streak = ready() ? streak + 1 : 0;
      if (streak < 2 && tries++ < 80) { setTimeout(wait, 150); return; }
      // "Celular" como no resto do app (a mesma largura do menu de baixo).
      stops = (matchMedia("(max-width: 860px)").matches ? PHONE_STOPS : STOPS).filter(([sels]) => find(sels));
      if (!stops.length) { resolve(); return; }
      document.body.append(layer);
      addEventListener("resize", place);
      addEventListener("scroll", place, true);
      document.addEventListener("keydown", onKey, true);
      show(0);
    })();
  });
}
