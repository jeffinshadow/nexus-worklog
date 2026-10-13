// Lembrete de inatividade (opt-in, Configurações > Conta): com o app aberto,
// nos dias úteis e dentro da janela de horário, avisa quando passa X minutos
// sem nenhum registro. Antes de avisar, confere no servidor: registro feito
// pelo celular ou pela IA também conta.
import { api } from "./api.js";
import { h, icon, nowInTz } from "./dom.js";
import { duration } from "./task.js";
import { quickRegister } from "./quick.js";
import { errorToast, toast } from "./ui.js";
import { timerState } from "./timer.js";

const CHECK_MS = 60 * 1000;
let me = null;
let onChange = null;
let timer = null;
let lastKnown = 0;      // último registro conhecido (ms)
let openedAt = 0;       // não cobra o tempo antes de o app abrir
let snoozeUntil = 0;
let box = null;

export function startIdle(user, refresh) {
  me = user;
  onChange = refresh;
  clearInterval(timer);
  timer = null;
  close();
  if (!me.assistant || !me.assistant.idle_on) return;
  openedAt = Date.now();
  lastKnown = 0;
  timer = setInterval(check, CHECK_MS);
}

function windowStart() {
  // Início da janela de hoje, em ms; null fora do dia útil ou da janela.
  const p = me.assistant;
  const t = nowInTz();
  const mins = t.hour * 60 + t.minute;
  if (!((me.work_days >> t.weekday) & 1) || mins < p.idle_start || mins >= p.idle_end) return null;
  return Date.now() - (mins - p.idle_start) * 60000;
}

async function check() {
  if (box || Date.now() < snoozeUntil || document.querySelector("dialog[open]")) return;
  if (timerState()) { lastKnown = Date.now(); return; } // cronômetro rodando = trabalhando
  const start = windowStart();
  if (start === null) return;
  const limit = me.assistant.idle_minutes * 60000;
  if (Date.now() - Math.max(lastKnown, start, openedAt) < limit) return; // ainda no prazo pelo que se sabe
  let r;
  try { r = await api.get("/me/activity"); } catch { return; }
  lastKnown = r.last_activity ? new Date(r.last_activity).getTime() : 0;
  if (r.timer) { lastKnown = Date.now(); return; } // cronômetro rodando em outro aparelho
  if (Date.now() - Math.max(lastKnown, start, openedAt) < limit) return;
  show(lastKnown >= start ? Date.now() - lastKnown : null);
}

function close() {
  if (box) box.remove();
  box = null;
  document.title = document.title.replace(/^• /, "");
}

function snooze() {
  snoozeUntil = Date.now() + me.assistant.idle_minutes * 60000;
  close();
}

// idleMs = tempo desde o último registro de hoje; null = nada registrado hoje ainda.
function show(idleMs) {
  const head = idleMs === null ? "Ainda não há registros hoje."
    : `Nenhum registro há ${duration(Math.max(me.assistant.idle_minutes, Math.round(idleMs / 60000)))}.`;
  const input = h("input", { type: "text", maxlength: "200", placeholder: "O que você está fazendo? · “— 15min” = concluída", "aria-label": "Registrar o que está fazendo" });
  const send = async () => {
    if (!input.value.trim()) { input.focus(); return; }
    input.disabled = true;
    try {
      toast(await quickRegister(input.value));
      lastKnown = Date.now();
      close();
      if (onChange) onChange();
    } catch (e) {
      input.disabled = false;
      errorToast(e, "Erro ao registrar.");
    }
  };
  input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); send(); } });
  box = h("section", { class: "idle-card", role: "status", "aria-live": "polite" },
    h("div", { class: "idle-head" },
      h("span", { class: "assist-mark", "aria-hidden": "true" }, icon("clock")),
      h("p", {}, h("strong", { text: head }), " Deseja anotar o que está fazendo agora?"),
      h("button", { type: "button", class: "icon", title: "Fechar", "aria-label": "Fechar lembrete", onClick: snooze }, icon("close"))),
    input,
    h("div", { class: "assist-actions" },
      h("button", { type: "button", class: "btn btn-primary btn-sm", text: "Registrar", onClick: send }),
      h("button", { type: "button", class: "btn btn-ghost btn-sm", text: `Lembrar em ${duration(me.assistant.idle_minutes)}`, onClick: snooze })));
  document.body.append(box);
  if (!document.title.startsWith("• ")) document.title = "• " + document.title;
}
