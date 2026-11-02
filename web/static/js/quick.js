// Registro rápido: "Troca de toner — 15min" já entra concluída e com o tempo
// apontado; "@Projeto #chamado !plantão" no fim preenchem esses campos.
// Usado no Hoje e no lembrete de inatividade.
import { api } from "./api.js";
import { parseDuration } from "./task.js";
import { listProjects } from "./projects.js";
import { addDays, localDay, localDateTime, h } from "./dom.js";

// "^sex" = próxima sexta (hoje, se for sexta); "^25/10" = esse dia (ano que vem, se já passou).
const WD = { dom: 0, seg: 1, ter: 2, qua: 3, qui: 4, sex: 5, sab: 6, "sáb": 6 };
function dueFrom(token) {
  const today = localDay(Date.now());
  const k = token.toLowerCase();
  if (k === "hoje") return today;
  if (k === "amanha" || k === "amanhã") return addDays(today, 1);
  if (k in WD) {
    const now = new Date(today + "T12:00:00Z").getUTCDay();
    return addDays(today, (WD[k] - now + 7) % 7);
  }
  const [d, m] = k.split("/").map(Number);
  if (!d || !m || m > 12 || d > 31) return null;
  let y = Number(today.slice(0, 4));
  let iso = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  if (iso < today) iso = `${y + 1}${iso.slice(4)}`;
  const ok = new Date(iso + "T12:00:00Z").toISOString().slice(0, 10) === iso; // 31/02 não existe: fica no título
  return ok ? iso : null;
}

// Lembrete com hora: "^15h", "^8h30", "^15:30" (a próxima vez que der essa hora:
// hoje, ou amanhã se já passou) e "^amanhã 8h", "^sex 9h30", "^25/10 14h" (no dia).
// Devolve "AAAA-MM-DDTHH:MM" no fuso da app (ou null se a hora não existe).
function remindFrom(dayToken, hh, mm) {
  if (Number(hh) > 23 || Number(mm || 0) > 59) return null;
  const hhmm = `${String(hh).padStart(2, "0")}:${String(mm || 0).padStart(2, "0")}`;
  const now = localDateTime(Date.now());
  if (dayToken) {
    const day = dueFrom(dayToken);
    return day ? `${day}T${hhmm}` : null;
  }
  const today = now.slice(0, 10);
  return `${today}T${hhmm}` > now ? `${today}T${hhmm}` : `${addDays(today, 1)}T${hhmm}`;
}
const REMIND_MARK = /\s+\^(?:(hoje|amanh[aã]|seg|ter|qua|qui|sex|s[aá]b|dom|\d{1,2}\/\d{1,2})\s+)?(\d{1,2})(?:h(\d{2})?|:(\d{2}))$/i;

// Marcadores no fim do registro, em qualquer ordem: "@Projeto", "#chamado",
// "!plantão", "^sex" ou "^25/10" (prazo) e "!aguarda motivo" (por último: o motivo vai até o fim;
// "!bloq", o nome antigo, continua valendo). Ex.: "Trocar HD ^qui !aguarda peça da Dell".
// Dois "@": o primeiro é o projeto principal, os outros entram como outros projetos.
const FOLD = (s) => s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim();
async function parseMarks(text) {
  let title = text, ticket = null, afterHours = false, due = null, blocked = null, high = false, remind = null;
  const projects = []; // da esquerda para a direita
  for (;;) {
    let m;
    const bm = blocked === null && title.match(/\s!(?:aguarda|bloq)(?:\s+(.*))?$/i); // sozinho ou com o motivo (não "!aguardando", "!bloqueio")
    if (bm) { blocked = (bm[1] || "").trim().slice(0, 120); title = title.slice(0, bm.index); continue; }
    if ((m = title.match(REMIND_MARK)) && !remind && (remind = remindFrom(m[1], m[2], m[3] || m[4]))) { title = title.slice(0, m.index); continue; }
    if ((m = title.match(/\s+\^(hoje|amanh[aã]|seg|ter|qua|qui|sex|s[aá]b|dom|\d{1,2}\/\d{1,2})$/i)) && !due && (due = dueFrom(m[1]))) { title = title.slice(0, m.index); continue; }
    if ((m = title.match(/\s+!alta$/i)) && !high) { high = true; title = title.slice(0, m.index); continue; }
    if ((m = title.match(/\s+!plant[aã]o$/i))) { afterHours = true; title = title.slice(0, m.index); continue; }
    if ((m = title.match(/\s+#([\w./-]{1,40})$/))) { ticket = m[1]; title = title.slice(0, m.index); continue; }
    // "@Projeto" só vale se for um projeto seu; "Ligar para @Fulano" fica no título.
    const at = title.lastIndexOf(" @");
    if (at > 0) {
      const name = title.slice(at + 2);
      const found = (await listProjects()).find((p) => !p.archived && FOLD(p.name) === FOLD(name));
      if (found) { if (!projects.some((p) => p.id === found.id)) projects.unshift(found); title = title.slice(0, at); continue; }
    }
    break;
  }
  return { title: title.trim(), ticket, afterHours, project: projects[0] || null, extraProjects: projects.slice(1), due, blocked, high, remind };
}

// Duração no fim do registro rápido, depois de um traço: "Troca de toner — 15min",
// "Loja X - 2h", "Backup — 1:30". Sem o traço, "Reunião 14h" e "Ligar 15:30"
// ficam como título (hora do dia não vira tempo gasto).
const QUICK_DUR = /\s+[-–—]\s*(\d+(?:[.,]\d+)?\s*h(?:\s*\d{1,2})?(?:\s*min)?|\d+\s*min|\d+:\d{2})$/i;

// Uma linha do registro → { payload, minutes, durText, marks, extras } (sem enviar).
async function parseLine(text, project_id = null) {
  let title = text.trim();
  const m = title.match(QUICK_DUR);
  const minutes = m ? parseDuration(m[1].replace(/\s+/g, "").replace(",", ".")) : null;
  const comTempo = minutes && minutes <= 1440;
  if (comTempo) title = title.slice(0, m.index).trim();
  const marks = await parseMarks(title);
  const payload = {
    title: marks.title || title, project_id: marks.project ? marks.project.id : project_id,
    extra_project_ids: marks.extraProjects.map((p) => p.id),
    ticket: marks.ticket, after_hours: marks.afterHours, due_date: marks.due, priority: marks.high ? 1 : 2,
    // !aguarda vence o "— 30min": fica aguardando o motivo, e o tempo apontado, sem concluir.
    status: marks.blocked !== null ? "blocked" : comTempo ? "done" : "todo",
    blocked_reason: marks.blocked || null,
  };
  // Lembrete só em tarefa que fica aberta (concluída não lembra).
  if (marks.remind && payload.status !== "done") payload.remind_at = marks.remind;
  const extras = [marks.project && [marks.project, ...marks.extraProjects].map((p) => p.name).join(" + "), marks.ticket && "#" + marks.ticket, marks.afterHours && "plantão", marks.high && "alta",
    marks.due && "prazo " + marks.due.split("-").reverse().slice(0, 2).join("/"),
    payload.remind_at && "lembrete " + remindLabel(payload.remind_at),
    marks.blocked !== null && (marks.blocked ? "aguardando: " + marks.blocked : "aguardando")].filter(Boolean);
  return { payload, minutes: comTempo ? minutes : null, durText: m ? m[1].trim() : "", marks, extras };
}

// "15:00" (hoje), "amanhã 08:00", "05/12 09:30". local: "AAAA-MM-DDTHH:MM" no fuso da app.
export function remindLabel(local) {
  const today = localDay(Date.now());
  const [day, hhmm] = local.slice(0, 16).split("T");
  if (day === today) return hhmm;
  if (day === addDays(today, 1)) return `amanhã ${hhmm}`;
  return `${day.split("-").reverse().slice(0, 2).join("/")} ${hhmm}`;
}

// Cria a tarefa e devolve a frase de confirmação. Erro na criação = exceção;
// erro só no tempo = a tarefa fica e a frase avisa.
// lastDone: a tarefa que o último registro já concluiu (para o "Como resolveu?").
export let lastDone = null;
export async function quickRegister(text, project_id = null) {
  lastDone = null;
  const { payload, minutes, durText, marks, extras } = await parseLine(text, project_id);
  if (!marks.title) throw Object.assign(new Error("Escreva o que foi feito antes dos marcadores."), { status: 400 });
  const created = await api.post("/worklog", payload);
  const com = extras.length ? ` (${extras.join(", ")})` : "";
  if (created && created.queued) {  // sem sinal: o tempo vai junto quando a tarefa for criada
    if (minutes) await api.after(created.qid, "POST", "/worklog/{id}/time", { minutes });
    return `Sem conexão: tarefa guardada${com}. Vai sozinha quando a conexão voltar.`;
  }
  if (!minutes) return `Tarefa registrada${com}.`;
  try {
    await api.post(`/worklog/${created.id}/time`, { minutes });
    if (marks.blocked === null) lastDone = { id: created.id, title: marks.title };
    return `${marks.blocked !== null ? "Registrada" : "Registrada e concluída"} com ${durText}${com}.`;
  } catch {
    return "Tarefa registrada, mas o tempo não entrou. Abra a tarefa e use Apontar.";
  }
}

// ------------------------------------------------- colar uma lista → várias --
// Colar texto com mais de uma linha no registro rápido (ou no título da Nova
// tarefa) abre uma prévia: uma tarefa por linha, já com os marcadores lidos,
// sem os marcadores de lista ("- ", "• ", "1.", "[ ]"), linhas vazias fora.
// Criar envia em série (sem sinal, entra na fila com a hora do aparelho); um
// aviso só no fim, com um Desfazer para o lote inteiro.
const LIST_MAX = 50;
const BULLET = /^\s*(?:[-–—*•·▪◦‣]\s+|\d{1,3}[.)]\s+|[-*]?\s*\[[ xX]?\]\s*)/;

export function pastedLines(text) {
  return String(text || "").split(/\r?\n/)
    .map((l) => l.replace(BULLET, "").replace(/\s+/g, " ").trim().slice(0, 200)).filter(Boolean);
}

// opts.project(): o projeto escolhido ao lado do campo (ou null);
// opts.onDone(): recarrega a tela; opts.before(): ex. fechar a janela da Nova tarefa.
// Devolve o tratador do evento "paste" (campo fixo da página: input.onpaste = ...).
export function pasteHandler(opts = {}) {
  return (ev) => {
    const lines = pastedLines(ev.clipboardData && ev.clipboardData.getData("text"));
    if (lines.length < 2) return;  // uma linha: o colar de sempre
    ev.preventDefault();
    if (opts.before) opts.before();
    openListPreview(lines, opts);
  };
}

async function openListPreview(lines, opts) {
  const { modal, toast, errorToast, busy } = await import("./ui.js");
  const { fillProjectSelect } = await import("./projects.js");
  const over = lines.length > LIST_MAX;
  lines = lines.slice(0, LIST_MAX);
  const proj = h("select", {});
  fillProjectSelect(proj, opts.project ? opts.project() : null).catch(() => {});
  const projectId = () => (proj.value && proj.value !== "__new" ? Number(proj.value) : null);
  const parsed = await Promise.all(lines.map((l) => parseLine(l, null)));
  const boxes = [];
  const list = h("ul", { class: "paste-list" }, ...parsed.map((p, i) => {
    const cb = h("input", { type: "checkbox", checked: "checked" });
    boxes.push(cb);
    const chips = [...p.extras, p.minutes ? (p.payload.status === "done" ? `concluída com ${p.durText}` : p.durText) : ""].filter(Boolean);
    if (chips.length) cb.setAttribute("aria-describedby", `paste-x-${i}`);
    return h("li", {}, h("label", { class: "check-line paste-row" }, cb,
      h("span", { class: "paste-text" }, h("span", { class: "paste-title", text: p.marks.title || lines[i] }),
        chips.length ? h("small", { id: `paste-x-${i}`, text: chips.join(" · ") }) : null)));
  }));
  const count = h("p", { class: "paste-count", "aria-live": "polite" });
  const go = h("button", { type: "submit", class: "btn btn-primary" });
  const sync = () => {
    const n = boxes.filter((b) => b.checked).length;
    go.textContent = n === 1 ? "Criar 1 tarefa" : `Criar ${n} tarefas`;
    go.disabled = !n;
    count.textContent = `${n} de ${lines.length} marcadas`;
  };
  list.addEventListener("change", sync);
  const form = h("form", { class: "paste-form" },
    h("h2", { text: `Criar ${lines.length} tarefas?` }),
    h("p", { class: "dialog-note", text: "Uma tarefa por linha, com os marcadores de cada uma (@projeto, #chamado, !alta, ^sex, ^15h, — 30min). Desmarque o que não for tarefa." +
      (over ? ` Só as ${LIST_MAX} primeiras linhas entram de uma vez.` : "") }),
    h("label", { class: "field" }, "Projeto (das linhas sem @projeto)", proj),
    count, list,
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }), go));
  sync();
  form.addEventListener("submit", busy(async (ev) => {
    ev.preventDefault();
    const chosen = parsed.filter((_, i) => boxes[i].checked);
    const made = [];  // { id, time? } criadas no servidor ou { qid } na fila do aparelho
    let failed = 0, queued = 0;
    for (const [i, p] of chosen.entries()) {
      go.textContent = `Criando ${i + 1} de ${chosen.length}…`;
      if (!p.marks.title) { failed++; continue; }
      const body = { ...p.payload, project_id: p.marks.project ? p.marks.project.id : projectId() };
      try {
        const created = await api.post("/worklog", body);
        if (created && created.queued) {
          queued++;
          if (p.minutes) await api.after(created.qid, "POST", "/worklog/{id}/time", { minutes: p.minutes });
          made.push({ qid: created.qid });
          continue;
        }
        const item = { id: created.id };
        if (p.minutes) { try { item.time = (await api.post(`/worklog/${created.id}/time`, { minutes: p.minutes })).id; } catch { /* a tarefa fica */ } }
        made.push(item);
      } catch (e) {
        if (e.status === 400 || e.status === 422) { failed++; continue; }  // a linha tem algo inválido: segue
        errorToast(e, "Parei no meio: confira o que já entrou.");
        break;
      }
    }
    dlg.close();
    if (opts.onDone) await opts.onDone();
    const n = made.length;
    if (!n) { toast(failed ? "Nenhuma tarefa criada: confira as linhas." : "Nada criado.", { error: !!failed }); return; }
    const msg = (queued ? `Sem conexão: ${n === 1 ? "1 tarefa guardada" : `${n} tarefas guardadas`}; vão quando a conexão voltar.`
      : n === 1 ? "1 tarefa criada." : `${n} tarefas criadas.`)
      + (failed ? ` ${failed} não ${failed > 1 ? "entraram" : "entrou"} (confira o texto).` : "");
    toast(msg, { action: "Desfazer", onAction: () => undoBatch(made, opts.onDone) });
  }));
  const dlg = modal(form);
  dlg.classList.add("paste-dialog");
  go.focus();
}

// Desfaz o lote: o tempo apontado e a criação de cada uma (pelo histórico, da
// mais recente para a mais antiga); as que ainda estão na fila do aparelho saem dela.
async function undoBatch(made, onDone) {
  const { toast } = await import("./ui.js");
  const { cancel } = await import("./fila.js");
  const undo = async (entity, id) => {
    const rows = await api.get(`/history?limit=1&entity=${entity}&entity_id=${id}`);
    if (!rows.length || !rows[0].can_undo) throw new Error("nada para desfazer");
    await api.post(`/history/${rows[0].id}/undo`);
  };
  let ok = 0, bad = 0;
  for (const m of [...made].reverse()) {
    try {
      if (m.qid !== undefined) { if (await cancel(m.qid)) ok++; else bad++; continue; }
      if (m.time) await undo("time", m.time);
      await undo("worklog", m.id);
      ok++;
    } catch { bad++; }
  }
  toast(bad ? `Desfeito em ${ok}; ${bad} já ${bad > 1 ? "mudaram" : "mudou"} (exclua pela tela, se for o caso).`
    : ok === 1 ? "Desfeito." : `Desfeitas as ${ok} tarefas.`, { error: !!bad });
  if (onDone) await onDone();
}
