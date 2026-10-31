// Cronômetro: um por pessoa, guardado no servidor (vale em qualquer aparelho).
// Aqui ele aparece no menu (e, no celular, acima da barra) e é ligado/parado
// pelos botões das tarefas. Ao parar, o servidor aponta o tempo na tarefa.
import { api } from "./api.js";
import { h, icon, clear } from "./dom.js";
import { duration, openTask } from "./task.js";
import { errorToast, toast } from "./ui.js";

let state = null;    // { task_id, title, started_at } ou null
let tick = null;
let onChange = null; // recarrega a tela atual

export const timerState = () => state;

export function initTimer(refresh) {
  onChange = refresh;
  api.get("/timer").then((r) => setTimer(r.timer)).catch(() => {});
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
    box.append(
      h("span", { class: "timer-dot", "aria-hidden": "true" }),
      h("button", { type: "button", class: "timer-task", title: "Abrir a tarefa", text: state.title,
        onClick: () => openTask(state.task_id, onChange) }),
      h("span", { class: "timer-time" }),
      h("button", { type: "button", class: "icon", title: "Parar e apontar o tempo", "aria-label": "Parar o cronômetro e apontar o tempo", onClick: () => stopTimer() }, icon("stop")));
  }
  if (!state) return;
  const start = new Date(state.started_at).getTime();
  const upd = () => { for (const el of document.querySelectorAll(".timer-time")) el.textContent = elapsed(Date.now() - start); };
  upd();
  tick = setInterval(upd, 1000);
}

export async function startTimer(task, after = onChange) {
  try {
    const r = await api.post("/timer/start", { task_id: task.id, title: task.title });
    if (r.queued) {  // sem sinal: conta a partir de agora; o servidor recebe a hora do aparelho
      setTimer({ task_id: task.id, title: task.title, started_at: new Date().toISOString() });
      toast(`Cronômetro em «${task.title}» (sem conexão: vai quando voltar).`);
      if (after) after();
      return;
    }
    setTimer(r.timer);
    toast(r.stopped ? `Cronômetro em «${task.title}». O anterior apontou ${duration(r.stopped.minutes)}.`
      : `Cronômetro iniciado em «${task.title}».`);
    if (after) after();
  } catch (e) { errorToast(e, "Não foi possível iniciar o cronômetro."); }
}

export async function stopTimer(after = onChange) {
  try {
    const r = await api.post("/timer/stop");
    setTimer(null);
    if (r.queued) { toast("Cronômetro parado. O tempo é apontado quando a conexão voltar."); if (after) after(); return; }
    toast(r.stopped ? `Apontado: ${duration(r.stopped.minutes)}.` : "Cronômetro parado. O dia dele já tinha 24h apontadas, nada foi somado.");
    if (after) after();
  } catch (e) { errorToast(e, "Não foi possível parar o cronômetro."); }
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
