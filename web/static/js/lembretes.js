// Lembrete das rotinas com horário: com o app aberto, 10 min antes avisa na
// tela (sem som); no horário, o aviso toca a cada poucos segundos até a rotina
// ser marcada (aqui, no Hoje, no celular ou pela IA) ou adiada. O som é deste
// aparelho: dá para desligar no próprio aviso (fica salvo no navegador).
import { api } from "./api.js";
import { h, icon, nowInTz } from "./dom.js";
import { errorToast, toast } from "./ui.js";
import { appBadge } from "./instalar.js";
import { closeRoutine } from "./notificacoes.js";

const SOON_MIN = 10;          // aviso silencioso antes do horário
const SNOOZE_MS = 10 * 60000; // "Adiar 10 min"
const RING_MS = 5000;         // intervalo entre os toques
const SOUND_KEY = "nexus.lembrete.som";

let items = [];
let today = "";
let onChange = null;
let tick = null, ring = null, lastFetch = 0;
const snoozed = new Map();    // id → até quando (ms)
const seenSoon = new Set();   // avisos "daqui a pouco" já fechados (id:dia)
let box = null, boxKey = "";
let audio = null;

export function startReminders(refresh) {
  onChange = refresh;
  if (tick) return refreshReminders();
  // O navegador só deixa tocar depois de um clique ou tecla na página.
  for (const ev of ["pointerdown", "keydown"]) addEventListener(ev, unlock, { once: true, capture: true });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshReminders(); });
  tick = setInterval(check, 15000);
  refreshReminders();
}

// Chamado quando uma rotina muda (marcou, editou o horário) para o aviso acompanhar.
export async function refreshReminders() {
  lastFetch = Date.now(); // falhou: tenta de novo no próximo intervalo, sem martelar
  try { ({ items, today } = await api.get("/recurring/reminders")); } catch { return; }
  // Marcada (aqui, no celular ou pela IA): a notificação deste aparelho sai da bandeja.
  for (const r of items) if (r.done) closeRoutine(r.id, today);
  check();
}

export const soundOn = () => { try { return localStorage.getItem(SOUND_KEY) !== "off"; } catch { return true; } };
export function setSound(on) {
  try { localStorage.setItem(SOUND_KEY, on ? "on" : "off"); } catch { /* sem armazenamento: vale só agora */ }
  if (box) check(true);
}

const minutesNow = () => { const t = nowInTz(); return t.hour * 60 + t.minute; };
const toMin = (hhmm) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));

// Estado de uma rotina com horário agora: "soon" (até 10 min antes), "due" (passou do horário) ou null.
export function reminderState(r, now = minutesNow()) {
  if (!r.remind_at || r.done_today || r.done) return null;
  const at = toMin(r.remind_at);
  if (now >= at) return "due";
  return at - now <= SOON_MIN ? "soon" : null;
}

function check(force = false) {
  // Tocando, confere no servidor a cada minuto (marcada em outro aparelho para o som).
  const ringing = items.some((r) => reminderState(r) === "due");
  if (Date.now() - lastFetch > (ringing ? 60000 : 5 * 60000)) { refreshReminders(); return; }
  const now = minutesNow();
  const due = items.filter((r) => reminderState(r, now) === "due" && !(snoozed.get(r.id) > Date.now()));
  appBadge("rotinas", items.filter((r) => reminderState(r, now) === "due").length); // no ícone, mesmo adiadas
  const soon = items.filter((r) => reminderState(r, now) === "soon" && !seenSoon.has(`${r.id}:${r.remind_at}`));
  const key = (due.length ? "due:" + due.map((r) => r.id).join(",") : soon.length ? "soon:" + soon.map((r) => r.id).join(",") : "") + (soundOn() ? "" : ":mudo");
  if (key === boxKey && !force) return;
  boxKey = key;
  close();
  if (due.length) show(due, true);
  else if (soon.length) show(soon, false);
}

function close() {
  clearInterval(ring);
  ring = null;
  if (box) box.remove();
  box = null;
  document.title = document.title.replace(/^⏰ /, "");
}

async function markDone(r, note) {
  try {
    await api.post(`/recurring/${r.id}/toggle`, note ? { done: true, note } : { done: true });
    r.done = true;
    closeRoutine(r.id, today);
    toast(`Rotina marcada: ${r.label}`);
    check(true);
    if (onChange) onChange();
  } catch (e) { errorToast(e, "Não foi possível marcar."); }
}

function row(r, ringing) {
  const late = toMin(r.remind_at) < minutesNow();
  const when = ringing ? (late ? `era às ${r.remind_at}` : `agora, ${r.remind_at}`) : `às ${r.remind_at}`;
  const line = h("div", { class: "rem-row" },
    h("p", {}, h("strong", { text: r.label }), h("small", { text: when })));
  if (r.require_note) { // exige evidência: o campo vem junto, como no Hoje
    const input = h("input", { type: "text", maxlength: "200", placeholder: "O que foi conferido", "aria-label": `Evidência de ${r.label}` });
    const send = () => (input.value.trim() ? markDone(r, input.value.trim()) : input.focus());
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); send(); } });
    line.append(input, h("button", { type: "button", class: "btn btn-primary btn-sm", onClick: send }, icon("check"), "Marcar"));
  } else {
    line.append(h("button", { type: "button", class: "btn btn-primary btn-sm", onClick: () => markDone(r) }, icon("check"), "Marcar feita"));
  }
  return line;
}

function show(list, ringing) {
  const head = ringing
    ? (list.length > 1 ? `${list.length} rotinas na hora` : "Rotina na hora")
    : `Daqui a pouco${list.length > 1 ? ` (${list.length} rotinas)` : ""}`;
  const mute = h("button", { type: "button", class: "icon", title: soundOn() ? "Desligar o som neste aparelho" : "Ligar o som neste aparelho",
    "aria-label": soundOn() ? "Desligar o som neste aparelho" : "Ligar o som neste aparelho", onClick: () => setSound(!soundOn()) },
  icon(soundOn() ? "bell" : "bell-off"));
  const later = ringing
    ? h("button", { type: "button", class: "btn btn-ghost btn-sm", text: "Adiar 10 min", onClick: () => {
      for (const r of list) {
        snoozed.set(r.id, Date.now() + SNOOZE_MS);
        api.post(`/recurring/${r.id}/snooze`, { minutes: SNOOZE_MS / 60000 }).catch(() => {}); // os aparelhos também esperam
      }
      check(true);
    } })
    : h("button", { type: "button", class: "btn btn-ghost btn-sm", text: "Ok", onClick: () => {
      for (const r of list) seenSoon.add(`${r.id}:${r.remind_at}`);
      check(true);
    } });
  box = h("section", { class: "idle-card rem-card" + (ringing ? " ringing" : ""), role: ringing ? "alert" : "status", "aria-live": ringing ? "assertive" : "polite" },
    h("div", { class: "idle-head" },
      h("span", { class: "assist-mark", "aria-hidden": "true" }, icon("clock")),
      h("p", {}, h("strong", { text: head })),
      ringing ? mute : null),
    ...list.map((r) => row(r, ringing)),
    h("div", { class: "assist-actions" }, later));
  document.body.append(box);
  if (!ringing) return;
  if (!document.title.startsWith("⏰ ")) document.title = "⏰ " + document.title;
  if (soundOn()) { chime(); ring = setInterval(chime, RING_MS); }
}

// ------------------------------------------------------------------ som --
// Dois tons curtos (sem arquivo de áudio). Antes do primeiro clique na página
// o navegador bloqueia: o aviso aparece e o título pisca do mesmo jeito.
function unlock() {
  try {
    audio = audio || new AudioContext();
    if (audio.state === "suspended") audio.resume();
  } catch { audio = null; }
}

function chime() {
  if (!audio || audio.state !== "running") return;
  const t0 = audio.currentTime;
  for (const [i, f] of [[0, 880], [1, 1318.5]]) {
    const o = audio.createOscillator(), g = audio.createGain();
    o.type = "sine";
    o.frequency.value = f;
    const t = t0 + i * 0.18;
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(0.18, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.6);
    o.connect(g).connect(audio.destination);
    o.start(t);
    o.stop(t + 0.65);
  }
}
