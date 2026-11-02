// Cronômetro: um por pessoa, guardado no servidor (vale em qualquer aparelho).
// Aqui ele aparece no menu (e, no celular, acima da barra) e é ligado/parado
// pelos botões das tarefas. Ao parar, o servidor aponta o tempo na tarefa.
import { api } from "./api.js";
import { h, icon, clear } from "./dom.js";
import { duration, openTask } from "./task.js";
import { errorToast, toast, keepFocus } from "./ui.js";

let state = null;    // { task_id, title, started_at } ou null
let tick = null;
let onChange = null; // recarrega a tela atual

export const timerState = () => state;

// Interrompida: o cronômetro estava numa tarefa e outra começou (o telefone tocou).
// Guarda só a última, neste aparelho: { task_id, title, by, at } — `by` = a tarefa
// da interrupção. Ao parar ou concluir a `by` (até 2 h depois), o aviso oferece
// "Voltar para «X»", que reinicia o cronômetro lá.
const PREV_KEY = "nexus.cronometro.interrompida";
const PREV_MAX_MS = 2 * 3600 * 1000;
function getPrev() {
  try {
    const p = JSON.parse(localStorage.getItem(PREV_KEY) || "null");
    return p && Date.now() - new Date(p.at).getTime() < PREV_MAX_MS ? p : null;
  } catch { return null; }
}
function setPrev(p) {
  try { if (p) localStorage.setItem(PREV_KEY, JSON.stringify(p)); else localStorage.removeItem(PREV_KEY); } catch { /* sem armazenamento */ }
}
const shortTitle = (t) => (t.length > 32 ? t.slice(0, 31) + "…" : t);

// A interrupção terminou (parou ou concluiu a tarefa `taskId`): a ação "Voltar para «X»"
// para o aviso, ou null. Usa uma vez só.
export function backAction(taskId, after = onChange) {
  const p = getPrev();
  if (!p || p.by !== taskId) return null;
  setPrev(null);
  return [`Voltar para «${shortTitle(p.title)}»`, () => startTimer({ id: p.task_id, title: p.title }, after)];
}

// Concluir com o cronômetro rodando na tarefa: o servidor já parou e apontou; a barra some.
export function finishedTask(taskId) {
  if (state && state.task_id === taskId) setTimer(null);
}

// O cronômetro é um só em todos os aparelhos: relê ao voltar para o app.
const reload = () => api.get("/timer").then((r) => setTimer(r.timer)).catch(() => {});

export function initTimer(refresh) {
  onChange = refresh;
  reload();
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") reload(); });
}

function elapsed(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  return (hh ? `${hh}:${String(mm).padStart(2, "0")}` : String(mm)) + ":" + String(ss).padStart(2, "0");
}

export function setTimer(t) {
  state = t || null;
  clearInterval(tick);
  for (const id of ["timer-side", "timer-mobile"]) {
    const box = document.getElementById(id);
    if (!box) continue;
    clear(box);
    box.classList.toggle("hidden", !state);
    if (!state) continue;
    // Rodando numa interrupção: uma linha pequena lembra a tarefa que ficou parada.
    const prev = getPrev();
    const by = prev && prev.by === state.task_id ? prev : null;
    box.append(
      h("span", { class: "timer-dot", "aria-hidden": "true" }),
      h("button", { type: "button", class: "timer-task" + (by ? " with-prev" : ""), title: `Abrir a tarefa: ${state.title}` + (by ? ` (interrompeu «${by.title}»)` : ""),
        onClick: () => openTask(state.task_id, onChange) },
      h("span", { class: "timer-title", text: state.title }),
      by ? h("small", { class: "timer-prev", text: `interrompeu «${by.title}»` }) : null),
      h("span", { class: "timer-time", "aria-hidden": "true" }), // muda a cada segundo: fora do leitor de tela
      h("button", { type: "button", class: "icon", title: "Parar e apontar o tempo", "aria-label": "Parar o cronômetro e apontar o tempo", onClick: () => stopTimer(),
        // O tempo corrido vai no nome do botão ao chegar nele (sem região viva).
        onFocus: (ev) => ev.currentTarget.setAttribute("aria-label", `Parar o cronômetro (${elapsed(Date.now() - new Date(state.started_at).getTime())}) e apontar o tempo`) }, icon("stop")));
  }
  if (!state) return;
  const start = new Date(state.started_at).getTime();
  const upd = () => { for (const el of document.querySelectorAll(".timer-time")) el.textContent = elapsed(Date.now() - start); };
  upd();
  tick = setInterval(upd, 1000);
}

// Cronômetro esquecido (mais de 12 h): o servidor parou sem apontar; a pessoa informa o tempo.
function forgotten(st) {
  const when = new Date(st.started_at).toLocaleString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  toast(`O cronômetro de «${st.title}» rodava desde ${when}: parei sem apontar. Informe o tempo certo.`,
    { action: "Apontar", onAction: () => openTask(st.task_id) });
}

export async function startTimer(task, after = onChange) {
  const back = keepFocus(); // o cartão é redesenhado: o foco volta para ele
  const redraw = () => Promise.resolve(after && after()).then(back);
  const was = state && state.task_id !== task.id ? state : null;  // a que vai ser interrompida
  try {
    const r = await api.post("/timer/start", { task_id: task.id, title: task.title });
    // Trocou de tarefa com o cronômetro rodando: lembra a anterior (só a última).
    // Voltar para ela (ou começar outra) encerra a interrupção.
    const back = getPrev();
    if (was && !(r.stopped && r.stopped.needs_review)) setPrev({ task_id: was.task_id, title: was.title, by: task.id, at: new Date().toISOString() });
    else if (back && (back.task_id === task.id || back.by !== task.id)) setPrev(null);
    if (r.queued) {  // sem sinal: conta a partir de agora; o servidor recebe a hora do aparelho
      setTimer({ task_id: task.id, title: task.title, started_at: new Date().toISOString() });
      toast(`Cronômetro em «${task.title}» (sem conexão: vai quando voltar).`);
      redraw();
      return;
    }
    setTimer(r.timer);
    if (r.stopped && r.stopped.needs_review) forgotten(r.stopped);
    else toast(r.stopped ? `Cronômetro em «${task.title}». O anterior apontou ${duration(r.stopped.minutes)}.`
      : `Cronômetro iniciado em «${task.title}».`);
    redraw();
  } catch (e) { errorToast(e, "Não foi possível iniciar o cronômetro."); }
}

export async function stopTimer(after = onChange) {
  const back = keepFocus();
  const redraw = () => Promise.resolve(after && after()).then(back);
  const stoppedId = state && state.task_id;
  try {
    const r = await api.post("/timer/stop", state ? { task_id: state.task_id } : {});
    setTimer(null);
    // Fim da interrupção: oferece voltar para a tarefa que ficou parada.
    const ret = backAction(stoppedId, after);
    const opts = ret ? { actions: [ret] } : {};
    if (r.queued) { toast("Cronômetro parado. O tempo é apontado quando a conexão voltar.", opts); redraw(); return; }
    if (r.stopped && r.stopped.needs_review) forgotten(r.stopped);
    else toast(r.stopped ? `Apontado: ${duration(r.stopped.minutes)}.` : "Cronômetro parado. O dia dele já tinha 24h apontadas, nada foi somado.", opts);
    redraw();
  } catch (e) {
    if (e.status === 409) { reload(); redraw(); }  // outro aparelho parou ou trocou
    errorToast(e, "Não foi possível parar o cronômetro.");
  }
}

// Botão de uma tarefa aberta: inicia (ou, se já está rodando nela, para).
export function timerButton(task, after) {
  if (task.status === "done") return null;
  const running = state && state.task_id === task.id;
  return h("button", { type: "button", class: "icon" + (running ? " timer-on" : ""),
    title: running ? "Parar o cronômetro e apontar" : "Iniciar o cronômetro",
    "aria-label": (running ? "Parar o cronômetro de " : "Iniciar o cronômetro em ") + task.title,
    onClick: () => (running ? stopTimer(after) : startTimer(task, after)) }, icon(running ? "stop" : "play"));
}
