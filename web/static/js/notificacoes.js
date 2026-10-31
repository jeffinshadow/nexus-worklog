// Notificações do sistema neste aparelho (Web Push; ver app/push.py e sw.js):
// ligar e desligar por aparelho, o convite depois de instalado e o painel de
// Configurações › Avisos. No iPhone, só com o Nexus na tela de início (iOS 16.4+).
import { api } from "./api.js";
import { h, icon, dateTime } from "./dom.js";
import { errorToast, toast } from "./ui.js";
import { install, installed } from "./instalar.js";

const DISMISS_KEY = "nexus.notificacoes.dispensado";
const DISMISS_DAYS = 30;

export const supported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
const ios = () => /iPhone|iPad|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
// iPhone/iPad fora do app instalado: o navegador nem oferece (precisa instalar antes).
export const needsInstall = () => ios() && !installed();

// "Chrome · Android", "Safari · iPhone", "Edge · Windows"…
function deviceLabel() {
  const ua = navigator.userAgent;
  const browser = /Edg\//.test(ua) ? "Edge" : /SamsungBrowser/.test(ua) ? "Samsung" : /Firefox\//.test(ua) ? "Firefox"
    : /CriOS|Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "Navegador";
  const os = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1) ? "iPad"
    : /Android/.test(ua) ? "Android" : /Windows/.test(ua) ? "Windows" : /Mac OS X/.test(ua) ? "Mac" : /Linux/.test(ua) ? "Linux" : "";
  return [browser, os].filter(Boolean).join(" · ");
}

const b64ToBytes = (s) => Uint8Array.from(atob((s + "=".repeat((4 - (s.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));

async function registration() {
  return navigator.serviceWorker.ready;
}

export async function currentSubscription() {
  if (!supported()) return null;
  try { return await (await registration()).pushManager.getSubscription(); } catch { return null; }
}

async function save(sub) {
  const j = sub.toJSON();
  await api.post("/push/devices", { endpoint: j.endpoint, keys: j.keys, label: deviceLabel() });
}

// Liga neste aparelho. Precisa vir de um clique (o navegador só pergunta assim).
export async function enable() {
  if (!supported()) throw new Error("Este navegador não tem notificações.");
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error(perm === "denied"
    ? "As notificações estão bloqueadas para o Nexus neste navegador. Libere nas configurações do site (o cadeado na barra de endereço) e tente de novo."
    : "Sem permissão, o aparelho não recebe as notificações.");
  const { public_key: key } = await api.get("/push");
  const reg = await registration();
  let sub = await reg.pushManager.getSubscription();
  if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(key) });
  await save(sub);
  return sub;
}

export async function disable(deviceId) {
  const sub = await currentSubscription();
  if (sub) await sub.unsubscribe().catch(() => {});
  if (deviceId) await api.del(`/push/devices/${deviceId}`).catch(() => {});
}

// Ao abrir: com a permissão já dada, renova a inscrição no servidor (o
// navegador pode trocá-la; outra conta pode ter entrado neste aparelho).
export async function syncOnBoot() {
  if (!supported() || Notification.permission !== "granted") return;
  const sub = await currentSubscription();
  if (sub) save(sub).catch(() => {});
}

// Tira da bandeja as notificações de rotinas já marcadas (neste aparelho).
export async function closeRoutine(id, day) {
  if (!supported()) return;
  try {
    for (const n of await (await registration()).getNotifications({ tag: `rotina-${id}-${day}` })) n.close();
  } catch { /* sem service worker: nada a fechar */ }
}

// ------------------------------------------------------------- o convite --
// Aberto como app instalado, com login e sem decidir ainda: um aviso no canto.
function dismissed() {
  try { return Date.now() - Number(localStorage.getItem(DISMISS_KEY) || 0) < DISMISS_DAYS * 864e5; } catch { return false; }
}

export function offerNotifications(me) {
  if (!supported() || !installed() || Notification.permission !== "default" || dismissed() || !me.tour_done_at) return;
  setTimeout(async () => {
    if (document.querySelector(".push-card") || (await currentSubscription())) return;
    const close = () => card.remove();
    const later = () => { try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch { /* só agora */ } close(); };
    const card = h("section", { class: "idle-card push-card", role: "dialog", "aria-label": "Ativar notificações" },
      h("div", { class: "idle-head" },
        h("span", { class: "assist-mark", "aria-hidden": "true" }, icon("bell")),
        h("p", {}, h("strong", { text: "Ativar notificações neste aparelho?" }),
          " O Nexus avisa a rotina na hora, as cobranças e os prazos do dia e as tarefas que chegarem, mesmo com o app fechado."),
        h("button", { type: "button", class: "icon", title: "Agora não", "aria-label": "Agora não", onClick: later }, icon("close"))),
      h("div", { class: "assist-actions" },
        h("button", { type: "button", class: "btn btn-primary btn-sm", text: "Ativar", onClick: async () => {
          try { await enable(); close(); toast("Notificações ligadas neste aparelho."); }
          catch (e) { close(); errorToast(e, "Não foi possível ligar."); }
        } }),
        h("button", { type: "button", class: "btn btn-ghost btn-sm", text: "Agora não", onClick: later })));
    document.body.append(card);
  }, 2500);
}

// --------------------------------------------- Configurações › Avisos --
const TYPES = [
  ["routine", "Rotina na hora", "No horário da rotina, com Marcar feita e Adiar 10 min; repete 10 e 30 min depois até ser marcada."],
  ["follow_up", "Cobrar hoje", "De manhã, as bloqueadas com o dia de cobrar chegando."],
  ["deadline", "Prazos de hoje", "De manhã, as atrasadas e o que vence hoje."],
  ["assigned", "Tarefa atribuída a você", "Quando alguém manda uma tarefa pelo Nexus."],
];
const HOURS = Array.from({ length: 24 }, (_, i) => i);

export async function pushPanel(rerender) {
  const sub = await currentSubscription();
  const p = await api.get("/push" + (sub ? "?endpoint=" + encodeURIComponent(sub.endpoint) : ""));
  const here = p.devices.find((d) => d.current);

  // Este aparelho
  let status, action = null;
  if (!supported() && !needsInstall()) status = "Este navegador não tem notificações do sistema.";
  else if (needsInstall()) {
    status = "No iPhone e no iPad, as notificações só funcionam com o Nexus instalado na tela de início.";
    action = h("button", { type: "button", class: "btn btn-primary btn-sm", onClick: install }, icon("download"), "Como instalar");
  } else if (Notification.permission === "denied") status = "Bloqueadas neste navegador. Libere nas configurações do site (o cadeado na barra de endereço) e volte aqui.";
  else if (here) {
    status = "Ligadas neste aparelho.";
    action = h("button", { type: "button", class: "btn btn-ghost btn-sm", onClick: async () => { await disable(here.id); toast("Desligadas neste aparelho."); rerender(); } }, "Desligar aqui");
  } else {
    status = "Desligadas neste aparelho.";
    action = h("button", { type: "button", class: "btn btn-primary btn-sm", onClick: async () => {
      try { await enable(); toast("Notificações ligadas neste aparelho."); rerender(); }
      catch (e) { errorToast(e, "Não foi possível ligar."); }
    } }, icon("bell"), "Ligar neste aparelho");
  }

  // Tipos e privacidade
  const checks = TYPES.map(([key, title, help]) => {
    const on = h("input", { type: "checkbox", "aria-label": title });
    on.checked = p.prefs[key];
    return { key, on, el: h("label", { class: "notice-main notice-row" }, on, h("span", {}, h("strong", { text: title }), h("small", { text: help }))) };
  });
  const hour = h("select", { class: "select-sm", "aria-label": "Horário dos avisos da manhã" },
    ...HOURS.map((x) => h("option", { value: String(x), text: `${String(x).padStart(2, "0")}:00` })));
  hour.value = String(p.prefs.morning_hour);
  const hide = h("input", { type: "checkbox" });
  hide.checked = p.prefs.hide_content;
  const saveBtn = h("button", { type: "button", class: "btn btn-primary", text: "Salvar notificações" });
  saveBtn.addEventListener("click", async () => {
    const body = { morning_hour: Number(hour.value), hide_content: hide.checked };
    for (const c of checks) body[c.key] = c.on.checked;
    try { await api.put("/push/prefs", body); toast("Notificações salvas."); } catch (e) { errorToast(e, "Falha ao salvar."); }
  });
  const test = h("button", { type: "button", class: "btn btn-ghost" }, icon("bell"), "Testar");
  test.disabled = !p.devices.length;
  test.addEventListener("click", async () => {
    test.disabled = true;
    try { const r = await api.post("/push/test"); toast(r.sent > 1 ? `Teste enviado para ${r.sent} aparelhos.` : "Teste enviado."); }
    catch (e) { errorToast(e, "O teste não saiu."); }
    finally { setTimeout(() => { test.disabled = false; }, 4000); }
  });

  return h("section", { class: "panel" },
    h("div", { class: "panel-head" }, icon("bell"), h("h2", { text: "Notificações nos aparelhos" })),
    h("p", { class: "help", text: "Avisos do sistema no celular e no computador, mesmo com o Nexus fechado. Cada aparelho liga separado; o conteúdo vai criptografado, sem serviço de terceiros além do push do próprio navegador." }),
    h("div", { class: "push-here" }, h("p", { text: status }), action),
    ...checks.map((c) => c.el),
    h("div", { class: "notice-row" }, h("span", { class: "notice-main" }, h("span", {}, h("strong", { text: "Horário dos avisos da manhã" }), h("small", { text: "Cobranças e prazos, nos dias úteis." }))), hour),
    h("label", { class: "weekday-option notice-titles" }, hide, h("span", { text: "Esconder nomes de tarefas e rotinas na tela bloqueada (só o tipo do aviso)" })),
    h("div", { class: "row-actions" }, saveBtn, test),
    p.devices.length ? h("div", { class: "push-devices" },
      h("h3", { text: "Aparelhos ligados" }),
      ...p.devices.map((d) => h("div", { class: "token-row" },
        h("span", { class: "token-name", text: (d.label || "Aparelho") + (d.current ? " (este)" : "") }),
        h("span", { class: "token-meta", text: d.last_ok_at ? "último aviso " + dateTime(d.last_ok_at) : "ligado " + dateTime(d.created_at) }),
        h("button", { type: "button", class: "icon", title: "Remover este aparelho", "aria-label": "Remover " + (d.label || "aparelho"),
          onClick: async () => { if (d.current) await disable(d.id); else await api.del(`/push/devices/${d.id}`); rerender(); } }, icon("trash"))))) : null);
}
