// Revisão da semana: três passos curtos para fechar a semana do próprio jeito
// (o que fechou, o que ficou, o que vem) e um texto pronto para copiar. Nada é
// obrigatório: cada passo pode ser pulado, e fechar no meio não perde o que já
// foi salvo (cada toque grava na hora, pelas rotas de sempre da tarefa).
import { api } from "./api.js";
import { h, icon, clear, shortDate, localDateTime } from "./dom.js";
import { errorToast, modal, pager, pageSlice, toast } from "./ui.js";
import { blockTask, followUpTask } from "./board.js";

const NEXT_MAX = 3;
const PAGE = 10; // passos 1 e 2: uma ação por linha; 10 por vez dá para resolver sem rolar
const today = () => localDateTime(Date.now()).slice(0, 10);
const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;
const btn = (label, onClick, cls = "btn-ghost", extra = {}) =>
  h("button", { type: "button", class: "btn btn-sm " + cls, text: label, onClick, ...extra });

function prazo(t) {
  if (!t.due_date) return null;
  const d = today();
  return h("span", { class: "chip" + (t.due_date < d ? " late" : t.due_date === d ? " today" : ""),
    text: t.due_date < d ? `atrasada · ${shortDate(t.due_date)}` : t.due_date === d ? "vence hoje" : `prazo ${shortDate(t.due_date)}` });
}

function esperando(t) {
  if (t.status !== "blocked") return null;
  const dias = t.waiting_days ? ` há ${t.waiting_days} d` : "";
  return h("span", { class: "chip blocked-reason", text: (t.blocked_reason ? `aguardando ${t.blocked_reason}` : "aguardando") + dias });
}

// Uma linha da revisão: título, etiquetas, um estado (o que foi decidido) e as ações.
function row(t, chips = []) {
  const state = h("span", { class: "review-state", "aria-live": "polite" });
  const acts = h("div", { class: "review-acts" });
  const el = h("div", { class: "review-row" },
    h("div", { class: "review-t" }, h("span", { class: "review-title", text: t.title }),
      h("span", { class: "card-meta" }, ...chips.filter(Boolean), state)),
    acts);
  return { el, state, acts };
}

export async function openReview(onDone) {
  let r;
  try { r = await api.get("/review/week"); } catch (e) { errorToast(e, "Não foi possível abrir a revisão."); return; }
  let step = 0, changed = false;
  const pages = [1, 1]; // página dos passos 1 e 2 (mantida ao voltar)
  const chosen = new Set();
  const decided = new Map(); // id -> texto do estado (passo 2), mantido ao voltar
  const notes = new Map();   // id -> como resolveu salvo agora (passo 1)

  const stepLabel = h("span", { class: "tour-step", id: "review-step" });
  const title = h("h2", { "aria-describedby": "review-step" });
  const intro = h("p", { class: "review-intro" });
  const body = h("div", { class: "review-body" });
  // "Passo anterior/Próximo passo": não se confunde com "Anterior/Próxima" das páginas da lista.
  const back = btn("Passo anterior", () => go(step - 1), "btn-text");
  const fwd = h("button", { type: "button", class: "btn btn-primary" });
  // Fechar a qualquer hora (o que já foi tocado está salvo): o X no canto.
  const close = h("button", { type: "button", class: "icon review-close", title: "Fechar a revisão", "aria-label": "Fechar a revisão",
    onClick: () => dlg.close() }, icon("close"));
  const actions = h("div", { class: "dialog-actions" }, back, fwd);
  const dlg = modal(close, stepLabel, title, intro, body, actions);
  dlg.classList.add("review-dialog");
  dlg.addEventListener("close", () => { if (changed && onDone) onDone(); });
  const touch = () => { changed = true; };
  const periodo = `${shortDate(r.week_start)} a ${shortDate(r.week_end)}`;

  // ---- passo 1: o que fechou
  function fechou() {
    title.textContent = "O que fechou";
    intro.textContent = r.done.length
      ? `${plural(r.done.length, "tarefa concluída", "tarefas concluídas")} nesta semana (${periodo}). Quer anotar como resolveu alguma? Ajuda a busca da próxima vez.`
      : `Nenhuma tarefa concluída nesta semana (${periodo}). Tudo bem: siga para o que ficou.`;
    paged(0, r.done, "tarefas concluídas", (t) => {
      const res = notes.get(t.id) ?? t.resolution;
      const { el, acts } = row(t, [t.project_name ? h("span", { class: "chip", text: t.project_name }) : null]);
      if (res) el.querySelector(".review-t").append(h("small", { class: "review-res", text: res }));
      else {
        const open = btn("Como resolveu?", () => {
          clear(acts);
          const input = h("input", { type: "text", maxlength: "1000", placeholder: "ex.: reiniciei o serviço e testei", "aria-label": `Como resolveu: ${t.title}` });
          const save = btn("Salvar", async () => {
            const text = input.value.trim();
            if (!text) { input.focus(); return; }
            save.disabled = true;
            try {
              await api.patch(`/worklog/${t.id}`, { resolution: text });
              notes.set(t.id, text); touch();
              clear(acts);
              el.querySelector(".review-t").append(h("small", { class: "review-res", text }));
            } catch (e) { save.disabled = false; errorToast(e, "Não foi possível salvar."); }
          }, "btn-primary");
          input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); save.click(); } });
          acts.append(h("div", { class: "review-inline" }, input, save));
          input.focus();
        }, "btn-text");
        acts.append(open);
      }
      return el;
    });
  }

  // Uma página da lista do passo, com as páginas embaixo (redesenha só a lista).
  function paged(i, items, label, build) {
    const box = h("div", { class: "review-list" });
    const paint = () => {
      clear(box);
      const { rows, page } = pageSlice(items, pages[i], PAGE);
      pages[i] = page;
      box.append(...rows.map(build));
      const nav = pager({ page, total: items.length, size: PAGE, label, compact: true,
        onPage: (n) => { pages[i] = n; paint(); }, focus: title });
      if (nav) box.append(nav);
    };
    paint();
    body.append(box);
  }

  // ---- passo 2: o que ficou
  function ficou() {
    const lista = [...r.open, ...r.waiting];
    title.textContent = "O que ficou";
    intro.textContent = lista.length
      ? `${plural(lista.length, "tarefa segue aberta", "tarefas seguem abertas")}. Mude só o que precisar (prazo, aguardando ou concluir): o resto fica como está.`
      : "Nada ficou em aberto. Semana fechada.";
    paged(1, lista, "tarefas em aberto", (t) => {
      const { el, state, acts } = row(t, [prazo(t), esperando(t)]);
      acts.classList.add("review-choices");
      const done = (txt) => { decided.set(t.id, txt); touch(); paintState(); };
      const paintState = () => {
        const txt = decided.get(t.id);
        state.textContent = txt || "";
        state.classList.toggle("hidden", !txt);
        el.classList.toggle("decided", !!txt);
        clear(acts);
        if (txt) { acts.append(btn("Mudar", () => { decided.delete(t.id); paintState(); }, "btn-text")); return; }
        const date = h("input", { type: "date", class: "input-sm hidden", min: today(), "aria-label": `Novo prazo: ${t.title}` });
        date.addEventListener("change", async () => {
          if (!date.value) return;
          try {
            await api.patch(`/worklog/${t.id}`, { due_date: date.value });
            t.due_date = date.value;
            done(`novo prazo ${shortDate(date.value)}`);
          } catch (e) { errorToast(e, "Não foi possível mudar o prazo."); }
        });
        acts.append(
          btn("Reagendar", (ev) => { ev.currentTarget.classList.add("hidden"); date.classList.remove("hidden"); date.focus(); try { date.showPicker(); } catch { /* sem seletor: digita */ } }),
          date,
          t.status === "blocked"
            ? btn(t.follow_up_on ? `Cobrar ${shortDate(t.follow_up_on)}` : "Quando cobrar", () => followUpTask(t, (d) => { t.follow_up_on = d; done(`cobrar ${shortDate(d)}`); }))
            : btn("Aguardando", () => blockTask(t, () => { t.status = "blocked"; done("aguardando"); })),
          btn("Concluir", async (ev) => {
            ev.currentTarget.disabled = true;
            try {
              await api.post(`/worklog/${t.id}/finish`);
              t.status = "done";
              r.open = r.open.filter((x) => x.id !== t.id);
              chosen.delete(t.id);
              done("concluída");
            } catch (e) { ev.currentTarget.disabled = false; errorToast(e, "Não foi possível concluir."); }
          }));
      };
      paintState();
      return el;
    });
  }

  // ---- passo 3: o que vem
  function vem() {
    title.textContent = "Primeiro amanhã";
    const abertas = r.open.filter((t) => t.status !== "done" && t.status !== "blocked");
    const sug = new Set(r.suggestions);
    const ordem = [...abertas.filter((t) => sug.has(t.id)), ...abertas.filter((t) => !sug.has(t.id))];
    intro.textContent = ordem.length
      ? `Escolha até ${NEXT_MAX} tarefas para começar: elas abrem o Hoje do próximo dia útil (o Primeiro amanhã). Se quiser, marque também prioridade alta ou um prazo.`
      : "Nada em aberto para começar. Se já sabe de algo, escreva abaixo.";
    const count = h("p", { class: "review-count", "aria-live": "polite" });
    const paintCount = () => { count.textContent = `${chosen.size} de ${NEXT_MAX} escolhidas`; };
    body.append(count);
    const rows = [];
    const sync = () => {
      paintCount();
      for (const f of rows) f();
    };
    const add = (t) => {
      const { el, acts } = row(t, [sug.has(t.id) ? h("span", { class: "chip", text: "sugestão" }) : null, prazo(t)]);
      const pick = h("button", { type: "button", class: "btn btn-sm btn-ghost review-pick", "aria-pressed": "false" });
      pick.addEventListener("click", () => {
        if (chosen.has(t.id)) chosen.delete(t.id);
        else if (chosen.size < NEXT_MAX) chosen.add(t.id);
        else { toast(`Até ${NEXT_MAX} no Primeiro amanhã. Desmarque uma para trocar.`); return; }
        sync();
      });
      const high = h("button", { type: "button", class: "btn btn-sm btn-ghost", "aria-pressed": "false", text: "Prioridade alta" });
      high.addEventListener("click", async () => {
        const nova = t.priority === 1 ? 2 : 1;
        high.disabled = true;
        try { await api.patch(`/worklog/${t.id}`, { priority: nova }); t.priority = nova; touch(); }
        catch (e) { errorToast(e, "Não foi possível salvar."); }
        high.disabled = false;
        sync();
      });
      const due = h("input", { type: "date", class: "input-sm", min: today(), "aria-label": `Prazo: ${t.title}` });
      due.value = t.due_date && t.due_date >= today() ? t.due_date : "";
      due.addEventListener("change", async () => {
        try { await api.patch(`/worklog/${t.id}`, { due_date: due.value || null }); t.due_date = due.value || null; touch(); }
        catch (e) { errorToast(e, "Não foi possível salvar o prazo."); }
      });
      const extras = h("div", { class: "review-inline" }, high, h("label", { class: "review-due" }, h("span", { text: "Prazo" }), due));
      acts.append(pick, extras);
      rows.push(() => {
        const on = chosen.has(t.id);
        pick.setAttribute("aria-pressed", String(on));
        pick.textContent = on ? "Escolhida" : "Escolher";
        el.classList.toggle("decided", on);
        extras.classList.toggle("hidden", !on);
        high.setAttribute("aria-pressed", String(t.priority === 1));
      });
      body.append(el);
    };
    for (const t of ordem.slice(0, 15)) add(t);
    // Algo que ainda não está no Nexus: vira tarefa de prioridade alta, já escolhida.
    const nova = h("input", { type: "text", maxlength: "200", placeholder: "Outra coisa para começar (vira tarefa)", "aria-label": "Nova tarefa para o Primeiro amanhã" });
    const criar = btn("Adicionar", async () => {
      const titulo = nova.value.trim();
      if (!titulo) { nova.focus(); return; }
      if (chosen.size >= NEXT_MAX) { toast(`Até ${NEXT_MAX} no Primeiro amanhã. Desmarque uma para trocar.`); return; }
      criar.disabled = true;
      try {
        const c = await api.post("/worklog", { title: titulo, priority: 1 });
        if (c && c.queued) { toast("Sem conexão: a tarefa vai quando a conexão voltar."); criar.disabled = false; return; }
        const t = { id: c.id, title: titulo, status: "todo", priority: 1, due_date: null };
        r.open.push(t); chosen.add(t.id); touch();
        nova.value = "";
        add(t);
        body.append(newRow); // o campo continua no fim
        sync();
      } catch (e) { errorToast(e, "Não foi possível criar."); }
      criar.disabled = false;
    });
    nova.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); criar.click(); } });
    const newRow = h("div", { class: "review-inline review-new" }, nova, criar);
    body.append(newRow);
    sync();
  }

  // ---- fim: o texto da semana
  async function fim() {
    fwd.disabled = true;
    let res;
    try { res = await api.post("/review/week/done", { next: [...chosen] }); }
    catch (e) { fwd.disabled = false; errorToast(e, "Não foi possível concluir a revisão."); return; }
    touch();
    step = 3;
    stepLabel.textContent = "Pronto";
    title.textContent = "Sua semana";
    intro.textContent = "Revisão feita. O texto abaixo está pronto para colar no chat da equipe ou guardar." +
      (res.first && res.first.length ? ` O Primeiro amanhã (${plural(res.first.length, "tarefa", "tarefas")}) abre o Hoje de ${shortDate(res.first_day)}.` : "");
    clear(body);
    const area = h("textarea", { rows: "12", readonly: "readonly", class: "handoff-text", "aria-label": "Texto da semana" });
    area.value = res.text;
    body.append(area);
    clear(actions);
    actions.append(
      h("button", { type: "button", class: "btn btn-text", text: "Fechar", onClick: () => dlg.close() }),
      h("button", { type: "button", class: "btn btn-primary", onClick: async () => {
        try { await navigator.clipboard.writeText(res.text); toast("Copiado."); dlg.close(); }
        catch { area.select(); toast("Selecione e copie (Ctrl+C).", { error: true }); }
      } }, icon("copy"), "Copiar"));
    area.focus();
    area.setSelectionRange(0, 0); // o texto começa do topo (o título da semana)
    area.scrollTop = 0;
  }

  function go(n) {
    step = Math.max(0, Math.min(2, n));
    stepLabel.textContent = `Passo ${step + 1} de 3`;
    clear(body);
    body.scrollTop = 0;
    [fechou, ficou, vem][step]();
    back.classList.toggle("hidden", step === 0);
    fwd.disabled = false;
    fwd.textContent = step === 2 ? "Concluir a revisão" : "Próximo passo";
    fwd.onclick = step === 2 ? fim : () => go(step + 1);
    title.focus({ preventScroll: true });
  }
  title.tabIndex = -1;
  go(0);
}
