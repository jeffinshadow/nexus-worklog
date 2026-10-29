// Tour guiado: abre sozinho no primeiro acesso e de novo pela Ajuda. Duas
// partes: (1) configurar o Nexus da pessoa com os formulários de verdade
// (nome, dias úteis, projetos, projeto padrão, rotinas) e (2) um passeio pela
// tela Hoje, com destaque em cada parte, mostrando como fica o dia a dia.
// Quem já configurou passa rápido: cada passo vem com o que já está salvo.
import { api } from "./api.js";
import { h, icon, clear, field } from "./dom.js";
import { errorToast } from "./ui.js";
import { listProjects } from "./projects.js";

const DAYS = [[1, "Seg"], [2, "Ter"], [3, "Qua"], [4, "Qui"], [5, "Sex"], [6, "Sáb"], [0, "Dom"]];
const PROJ_HINTS = ["Suporte", "Infraestrutura", "Interno"];
const ROUTINE_HINTS = ["Conferir os backups da noite", "Olhar os alertas do monitoramento", "Revisar a fila de chamados",
  "Conferir o e-mail do plantão"];

let running = false;

// me: o objeto da sessão (é atualizado e avisado com "nexus:me").
export async function startTour(me) {
  if (running) return;
  running = true;
  try {
    const go = await setup(me);
    if (go === "walk") await walk();
  } finally {
    running = false;
    // Visto (ou pulado): não abre sozinho de novo; a Ajuda reabre.
    api.put("/me/tour", { done: true }).then((r) => { me.tour_done_at = r.tour_done_at; }).catch(() => {});
  }
}

function changed(me, res) {
  Object.assign(me, res);
  window.dispatchEvent(new Event("nexus:me"));
}

// ------------------------------------------------------ parte 1: configurar --
// Devolve "walk" (seguir para o passeio) ou "close".
function setup(me) {
  return new Promise((resolve) => {
    let result = "close", step = 0, dir = 1;
    const body = h("div", { class: "tour-body" });
    const dlg = h("dialog", { class: "tour-dialog", "aria-labelledby": "tour-title" }, body);
    document.body.append(dlg);
    dlg.addEventListener("close", () => { dlg.remove(); resolve(result); });
    dlg.addEventListener("cancel", () => { result = "close"; });

    const steps = [welcome, profile, workDays, projects, defaultProject, routines, ready];
    const total = steps.length - 2; // boas-vindas e "pronto" não contam
    const next = () => { step++; dir = 1; paint(); };
    const back = () => { step--; dir = -1; paint(); };
    const end = (r) => { result = r; dlg.close(); };

    async function paint() {
      const content = await steps[step]();
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
        h("p", { class: "tour-step mono", text: `Configuração · ${step} de ${total}` }),
        h("h2", { id: "tour-title", text: title }),
        h("p", { class: "tour-intro", text: intro }),
        ...controls, err,
        h("div", { class: "dialog-actions tour-actions" },
          h("button", { type: "button", class: "btn btn-text tour-skip", text: "Pular o tour", onClick: () => end("close") }),
          h("button", { type: "button", class: "btn btn-text", text: "Voltar", onClick: back }),
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
        h("p", { class: "tour-intro", text: "Primeiro, cinco passos rápidos para deixar o Nexus do seu jeito. Depois, um passeio de um minuto pela tela. Dá para rever tudo depois pela Ajuda." }),
        h("div", { class: "dialog-actions tour-actions" },
          h("button", { type: "button", class: "btn btn-text tour-skip", text: "Agora não", onClick: () => end("close") }),
          h("button", { type: "button", class: "btn btn-ghost", text: "Só o passeio", onClick: () => end("walk") }),
          h("button", { type: "button", class: "btn btn-primary", text: "Começar", onClick: next })),
      ];
    }

    function profile() {
      const name = h("input", { type: "text", maxlength: "60", value: me.display_name || "", placeholder: "Como você quer ser chamado", autocomplete: "name" });
      return frame("Como você quer ser chamado?", "Aparece no menu, nas saudações do assistente e para quem atribui tarefas a você. A foto você coloca depois em Configurações > Conta.",
        [field("Nome", name)],
        async () => {
          const v = name.value.trim() || null;
          if (v !== (me.display_name || null)) changed(me, await api.put("/me/profile", { display_name: v }));
        });
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
          const dot = h("span", { class: "dot" });
          dot.style.background = p.color || "var(--dim)";
          chips.append(h("span", { class: "chip project" }, dot, p.name));
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
          input.value = "";
          paintChips();
          input.focus();
        } catch (e) { err.textContent = e.message || "Não foi possível criar."; }
      }
      input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); add(input.value); } });
      paintChips();
      return frame("Para quem ou em que frente você trabalha?", "Projetos agrupam as tarefas: clientes, filiais, sistemas ou frentes da equipe. Com eles você filtra o quadro, vê o tempo de cada um e tira o relatório só daquele projeto. Uma tarefa pode estar em mais de um.",
        [chips, h("div", { class: "inline-form" }, field("Novo projeto", input),
          h("button", { type: "button", class: "btn btn-ghost", onClick: () => add(input.value) }, icon("add"), "Adicionar")), err],
        async () => { if (input.value.trim()) await add(input.value); },
        list.length ? "Seguir" : "Seguir sem projetos");
    }

    async function defaultProject() {
      const list = await listProjects().catch(() => []);
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
      const board = await api.get("/board").catch(() => ({ recurring: [] }));
      const have = board.recurring.map((r) => r.label.toLowerCase());
      const picks = ROUTINE_HINTS.filter((s) => !have.includes(s.toLowerCase())).map((label) => {
        const cb = h("input", { type: "checkbox" });
        return { label, cb };
      });
      const custom = h("input", { type: "text", maxlength: "200", placeholder: "Ex.: Verificar o link da filial" });
      return frame("O que você confere todo dia?", "Rotinas são as verificações que se repetem. Você marca no Hoje, anota a evidência (“backup OK, 2,1 TB”) e o relatório mostra a aderência. Elas seguem os dias úteis; a agenda de cada uma (semanal, mensal…) muda depois.",
        [board.recurring.length ? h("p", { class: "dialog-note", text: "Você já tem: " + board.recurring.map((r) => r.label).join(", ") + "." }) : null,
          h("div", { class: "tour-picks" }, ...picks.map(({ label, cb }) => h("label", { class: "check-row" }, cb, h("span", { class: "label", text: label })))),
          field("Outra rotina (opcional)", custom)],
        async () => {
          const labels = [...picks.filter((p) => p.cb.checked).map((p) => p.label), custom.value.trim()].filter(Boolean);
          for (const label of labels) await api.post("/recurring", { label });
        },
        "Criar e seguir");
    }

    function ready() {
      return [
        h("p", { class: "tour-step mono", text: "Tudo pronto" }),
        h("h2", { id: "tour-title", text: "Agora, o dia a dia" }),
        h("p", { class: "tour-intro", text: "Um passeio rápido pela tela Hoje: onde registrar, o que filtrar e onde ficam os relatórios. São poucos passos, e dá para sair a qualquer momento." }),
        h("div", { class: "dialog-actions tour-actions" },
          h("button", { type: "button", class: "btn btn-text tour-skip", text: "Fechar", onClick: () => end("close") }),
          h("button", { type: "button", class: "btn btn-text", text: "Voltar", onClick: () => { step = steps.indexOf(routines); paint(); } }),
          h("button", { type: "button", class: "btn btn-primary", text: "Fazer o passeio", onClick: () => end("walk") })),
      ];
    }

    dlg.showModal();
    paint().catch((e) => { errorToast(e); dlg.close(); });
  });
}

// ------------------------------------------------- parte 2: o passeio --
// Cada parada: seletores candidatos (o primeiro visível vale: computador ou
// celular), título e texto. Parada sem alvo visível é pulada.
const STOPS = [
  [[".quick-row input"], "Registro rápido",
    "Escreva o que fez e aperte Enter. No fim, marcadores opcionais: @Projeto (dois @ = dois projetos), #chamado, !alta, ^amanhã e “— 30min”, que já conclui com o tempo. Ex.: “Troca do switch @Matriz #4821 — 45min”."],
  [[".open-filter"], "Filtro das abertas",
    "Para focar: só o que vence hoje (as atrasadas entram junto) ou só as de prioridade alta. A escolha fica até você fechar a aba."],
  [[".t-rec"], "Rotinas do dia",
    "Marque o que conferiu. O bloquinho anota a evidência e o alerta transforma um achado em tarefa. As setas voltam até 7 dias para marcar o que ficou para trás."],
  [["#assist-slot > *"], "O assistente",
    "A saudação, o que pede atenção (atrasadas, bloqueadas há dias) e, à tarde, o resumo do dia. Ele cabe numa linha e se desliga em Configurações > Conta."],
  [["[data-fab]", "#fab"], "Tarefa completa",
    "Quando precisa de mais: prazo, prioridade, projetos, chamado, checklist e tempo. Atalho: tecla n. Depois, tudo se edita no próprio detalhe da tarefa (o lápis ao lado do título)."],
  [["#page-actions .btn-ghost"], "Passagem de turno",
    "No fim do turno, um texto pronto com o que fica aberto, o que está bloqueado e por quê, e o que foi feito. É só colar no chat da equipe."],
  [['#nav [data-view="tarefas"]', '#tabbar [data-view="tarefas"]'], "Tarefas",
    "O quadro com tudo o que está aberto, filtro por projeto e o detalhe de cada tarefa: anotações, checklist, cronômetro e o “como resolveu”, que entra na busca."],
  [['#nav [data-view="relatorios"]', '#tabbar [data-view="relatorios"]', '#tabbar [data-view="mais"]'], "Relatórios e retrospectiva",
    "O PDF do período ou de um projeto inteiro, para prestar contas. A Retrospectiva mostra a semana em números, e o Histórico guarda cada mudança, com desfazer."],
  [["#btn-help", '#tabbar [data-view="mais"]'], "Ajuda",
    "Atalhos, o manual tela por tela e este tour de novo, quando quiser."],
];

function visible(el) {
  if (!el || el.closest(".hidden")) return false;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

function walk() {
  return new Promise((resolve) => {
    // Sempre um Hoje recém-montado (com o que o tour acabou de criar): de outra
    // tela, troca a rota; já no Hoje, monta de novo.
    if (/^#\/hoje\b/.test(location.hash)) dispatchEvent(new HashChangeEvent("hashchange"));
    else location.hash = "#/hoje";
    const zoom = () => parseFloat(getComputedStyle(document.body).zoom) || 1;
    const spot = h("div", { class: "tour-spot", "aria-hidden": "true" });
    const title = h("h2", { id: "tour-pop-title" });
    const text = h("p");
    const count = h("span", { class: "tour-step mono" });
    const prev = h("button", { type: "button", class: "btn btn-text", text: "Voltar" });
    const next = h("button", { type: "button", class: "btn btn-primary" });
    const pop = h("div", { class: "tour-pop", role: "dialog", "aria-modal": "true", "aria-labelledby": "tour-pop-title" },
      count, title, text,
      h("div", { class: "dialog-actions tour-actions" },
        h("button", { type: "button", class: "btn btn-text tour-skip", text: "Encerrar", onClick: () => done() }), prev, next));
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
      if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); done(); }
      else if (ev.key === "ArrowRight") { ev.preventDefault(); show(i + 1); }
      else if (ev.key === "ArrowLeft") { ev.preventDefault(); show(i - 1); }
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
      const pad = 6, x = r.left / z - pad, y = r.top / z - pad, w = r.width / z + pad * 2, hh = r.height / z + pad * 2;
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
    function show(n) {
      if (n < 0 || n >= stops.length) { if (n >= stops.length) done(); return; }
      i = n;
      const [sels, t, body] = stops[i];
      const el = find(sels);
      target = el || null;
      title.textContent = t;
      text.textContent = body;
      count.textContent = `${i + 1} de ${stops.length}`;
      prev.disabled = i === 0;
      next.textContent = i === stops.length - 1 ? "Concluir" : "Próximo";
      if (el) el.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      requestAnimationFrame(place);
      setTimeout(place, 350); // depois da rolagem suave
      next.focus();
    }
    prev.addEventListener("click", () => show(i - 1));
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
      stops = STOPS.filter(([sels]) => find(sels));
      if (!stops.length) { resolve(); return; }
      document.body.append(layer);
      addEventListener("resize", place);
      addEventListener("scroll", place, true);
      document.addEventListener("keydown", onKey, true);
      show(0);
    })();
  });
}
