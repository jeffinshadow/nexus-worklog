// Sem sinal: o que foi feito fica numa fila no aparelho (IndexedDB) e vai ao
// servidor sozinho, na ordem, quando a conexão volta (com o app aberto).
// Entram só ações que não brigam com outro aparelho: criar tarefa, concluir,
// anotar, marcar rotina, iniciar e parar o cronômetro. Cada uma leva a hora em
// que foi feita; criar leva um identificador (external_ref) e reenviar não
// duplica. Uma criação pode ter passos seguintes ({id} = a tarefa criada:
// tempo, checklist, anotação, fotos). A barra no topo mostra a fila e quando
// os dados na tela são de antes (o service worker serve a última leitura).
import { h, icon, localDay, localDateTime } from "./dom.js";

const DB = "nexus", STORE = "fila", FAILED = "falhas";
const QUEUEABLE = [
  /^POST \/worklog$/, /^POST \/worklog\/\d+\/finish$/, /^POST \/worklog\/\d+\/notes$/,
  /^POST \/recurring\/\d+\/toggle$/, /^POST \/timer\/start$/, /^POST \/timer\/stop$/,
  /^POST \/worklog\/\d+\/photos$/, /^POST \/recurring\/\d+\/photos(\?.*)?$/,  // a foto do campo é a evidência
];

export const queueable = (method, path) => QUEUEABLE.some((re) => re.test(`${method} ${path}`));

let dbp = null;
function open() {
  if (!dbp) dbp = new Promise((ok, fail) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore(STORE, { keyPath: "qid", autoIncrement: true });
      req.result.createObjectStore(FAILED, { keyPath: "qid" });
    };
    req.onsuccess = () => ok(req.result);
    req.onerror = () => fail(req.error);
  });
  return dbp;
}

async function tx(store, mode, fn) {
  const db = await open();
  return new Promise((ok, fail) => {
    const t = db.transaction(store, mode);
    const r = fn(t.objectStore(store));
    t.oncomplete = () => ok(r && "result" in r ? r.result : undefined);
    t.onerror = () => fail(t.error);
  });
}

export const all = () => tx(STORE, "readonly", (s) => s.getAll()).catch(() => []);
export const failures = () => tx(FAILED, "readonly", (s) => s.getAll()).catch(() => []);

// Guarda a ação. A hora do aparelho vai junto onde o servidor aceita.
export async function enqueue(method, path, body) {
  const now = new Date();
  body = { ...(body || {}) };
  if (/^\/timer\//.test(path) || /\/(notes|photos)(\?.*)?$/.test(path)) body.at = now.toISOString();  // anotação e foto: a hora em que foram feitas
  if (/\/finish$/.test(path) && !body.completed_at) body.completed_at = localDateTime(now.getTime());
  if (/\/toggle$/.test(path) && !body.day) body.day = localDay(now.toISOString());
  if (path === "/worklog" && !body.created_at) {  // feita agora, mesmo que chegue amanhã
    body.created_at = localDateTime(now.getTime());
    if (body.status === "done" && !body.completed_at) body.completed_at = body.created_at;
  }
  const op = { method, path, body, at: now.toISOString(), then: [] };
  op.what = describe(op, await names());  // "Concluir: Troca do disjuntor", com o nome que a tela mostrava
  const qid = await tx(STORE, "readwrite", (s) => s.add(op));
  changed();
  return qid;
}

// Desfazer algo que ainda está na fila (o lote colado, por exemplo): sai dela sem ir
// ao servidor. false = já foi enviado (ou está indo agora).
export async function cancel(qid) {
  if (sending) return false;
  const found = await tx(STORE, "readwrite", (s) => {
    const g = s.get(qid);
    g.onsuccess = () => { if (g.result && !g.result.created) s.delete(qid); };
    return { get result() { return !!(g.result && !g.result.created); } };
  }).catch(() => false);
  changed();
  return found;
}

// Criações já enviadas por esta aba: qid -> id da tarefa (para um passo que chega atrasado).
const sentIds = new Map();

// Passo seguinte de uma criação que está na fila ({id} = a tarefa criada).
// Tempo e anotação levam o próprio external_ref: reenviar depois de um timeout não duplica.
export async function after(qid, method, path, body) {
  body = { ...(body || {}) };
  if (/\/time$/.test(path) && !body.day) body.day = localDay(new Date().toISOString());
  if (/\/(notes|photos)$/.test(path) && !body.at) body.at = new Date().toISOString();  // a hora em que foram feitas
  if (/\/(time|notes)$/.test(path) && !body.external_ref) body.external_ref = "app-" + crypto.randomUUID();
  const found = await tx(STORE, "readwrite", (s) => {
    const g = s.get(qid);
    g.onsuccess = () => { if (g.result) { g.result.then.push({ method, path, body }); s.put(g.result); } };
    return g;
  });
  if (found) return;
  // A fila enviou a criação enquanto o passo era preparado (ex.: a foto sendo comprimida):
  // o passo entra sozinho na fila, já com o id; sem o id (outra aba enviou), vira falha visível.
  if (sentIds.has(qid)) { await enqueue(method, path.replace("{id}", sentIds.get(qid)), body); return; }
  const step = { method, path, body };
  await tx(FAILED, "readwrite", (s) => s.put({ ...step, qid: `${qid}-tarde-${Date.now()}`, at: new Date().toISOString(),
    error: "a tarefa não estava mais na fila do aparelho; refaça pelo detalhe dela", what: describeStep(step) }));
  changed();
}

// Nomes das tarefas e rotinas na última leitura guardada (a que a tela mostrava).
async function names() {
  const out = { task: {}, rec: {} };
  if (!("caches" in window)) return out;
  try {
    const cache = await caches.open("nexus-dados");  // o mesmo nome de sw.js
    for (const req of await cache.keys()) {
      const p = new URL(req.url).pathname;
      if (!/^\/api\/(board|worklog\/\d+)$/.test(p)) continue;
      const d = await (await cache.match(req)).json();
      if (p !== "/api/board") { out.task[d.id] = d.title; continue; }
      for (const t of [...(d.in_progress || []), ...(d.done || [])]) out.task[t.id] = t.title;
      for (const r of d.recurring || []) out.rec[r.id] = r.label;
    }
  } catch { /* sem cache: a lista diz só o tipo */ }
  return out;
}

// O que descrever na lista ("Nova tarefa: X", "Concluir: Y", "Rotina: Z").
function describe(op, n = { task: {}, rec: {} }) {
  if (op.what) return op.what;
  const b = op.body || {};
  const task = (op.path.match(/^\/worklog\/(\d+)\//) || [])[1], rec = (op.path.match(/^\/recurring\/(\d+)\//) || [])[1];
  const of = (txt, name) => (name ? `${txt}: ${name}` : txt);
  if (op.path === "/worklog") return `Nova tarefa: ${b.title}`;
  if (/\/finish$/.test(op.path)) return of("Concluir", n.task[task]) + (n.task[task] ? "" : " tarefa");
  if (/\/notes$/.test(op.path)) return `Anotação${n.task[task] ? ` em «${n.task[task]}»` : ""}: ${(b.body || "").slice(0, 60)}`;
  if (/\/toggle$/.test(op.path)) return of(b.done ? "Marcar rotina" : "Desmarcar rotina", n.rec[rec]);
  if (/\/timer\/start$/.test(op.path)) return of("Iniciar cronômetro", b.title);
  if (/\/timer\/stop$/.test(op.path)) return "Parar cronômetro";
  if (/\/photos/.test(op.path)) return rec ? of("Foto da rotina", n.rec[rec]) : of("Foto", n.task[task]);
  return `${op.method} ${op.path}`;
}

// Passo seguinte de uma criação, para a lista de falhas.
function describeStep(step) {
  if (/\/time$/.test(step.path)) return "Tempo";
  if (/\/checklist$/.test(step.path)) return "Item do checklist";
  if (/\/notes$/.test(step.path)) return "Anotação";
  if (/\/photos$/.test(step.path)) return "Foto";
  return "Passo";
}

// Sem rede, sem sessão, servidor fora (deploy, reinício) ou limite: tenta depois.
// Só a recusa por regra (4xx) vira falha.
const later = (e) => !e.status || e.status === 401 || e.status === 429 || e.status >= 500;

// ------------------------------------------------------------- envio --
let sending = false, sendFn = null, onSynced = null, flushAgain = false;

// api.js entrega o envio cru (sem fila).
export function configure(send) { sendFn = send; }

// Duas abas abertas: só uma envia a fila de cada vez (a trava `sending` é da aba).
export async function flush() {
  if (navigator.locks) return navigator.locks.request("nexus-fila", { ifAvailable: true }, (lock) => (lock ? flushHere() : null));
  return flushHere();
}

async function flushHere() {
  if (sending || !sendFn || !navigator.onLine) return;
  sending = true;
  changed();  // a barra diz "enviando…"
  let sent = 0;
  try {
    outer: for (const op of await all()) {
      const n0 = op.then.length;  // passos acrescentados durante o envio ficam depois destes
      let res = op.created ? { id: op.created } : null;  // a criação já foi numa tentativa anterior
      if (!res) {
        try { res = await sendFn(op.method, op.path, op.body); }
        catch (e) {
          if (later(e)) break;
          await tx(FAILED, "readwrite", (s) => s.put({ ...op, error: e.message, what: describe(op) }));
          await tx(STORE, "readwrite", (s) => s.delete(op.qid));
          continue;
        }
      }
      // Passos da criação, com o id que o servidor deu. Sem rede ou servidor fora:
      // a operação fica na fila só com o que falta; recusado: vira falha visível.
      while (op.then.length) {
        const step = op.then[0];
        try { await sendFn(step.method, step.path.replace("{id}", res && res.id), step.body); }
        catch (e) {
          if (later(e)) {
            await tx(STORE, "readwrite", (s) => {
              const g = s.get(op.qid);  // o que foi acrescentado enquanto enviava não se perde
              g.onsuccess = () => s.put({ ...op, created: res && res.id, then: [...op.then, ...((g.result && g.result.then) || []).slice(n0)] });
            });
            break outer;
          }
          await tx(FAILED, "readwrite", (s) => s.put({ ...step, qid: `${op.qid}-${op.then.length}`, at: op.at,
            error: e.message, what: `${describeStep(step)} (${describe(op)})` }));
        }
        op.then.shift();
      }
      // Apaga só se nada chegou durante o envio; senão, os passos novos ficam para a próxima volta.
      const rest = await tx(STORE, "readwrite", (s) => {
        const g = s.get(op.qid);
        g.onsuccess = () => {
          const extra = ((g.result && g.result.then) || []).slice(n0);
          if (extra.length) s.put({ ...op, created: res && res.id, then: extra });
          else s.delete(op.qid);
        };
        return { get result() { return ((g.result && g.result.then) || []).slice(n0).length; } };
      });
      if (res && res.id) sentIds.set(op.qid, res.id);
      if (rest) { flushAgain = true; continue; }
      sent++;
    }
  } finally {
    sending = false;
    changed();
  }
  if (flushAgain) { flushAgain = false; setTimeout(flush, 0); }  // passos que chegaram durante o envio
  if (sent) {
    const { toast } = await import("./ui.js");
    toast(sent > 1 ? `${sent} alterações feitas sem conexão foram enviadas.` : "A alteração feita sem conexão foi enviada.");
  }
  if (sent && onSynced) onSynced();
  return sent;
}

// --------------------------------------------- dados de antes, com a fila por cima --
// A leitura veio do cache (sem sinal): aplica o que está na fila para a tela
// não "desfazer" o que a pessoa acabou de fazer.
export async function overlay(path, data) {
  const ops = await all();
  if (!ops.length || !data) return data;
  if (/^\/board/.test(path)) {
    for (const op of ops) {
      if (op.method === "POST" && op.path === "/worklog") {  // criada sem sinal: aparece, marcada
        const t = { id: "fila-" + op.qid, title: op.body.title, status: op.body.status || "todo", priority: op.body.priority || "normal",
          created_at: op.at, completed_at: op.body.status === "done" ? op.at : null, pending: true };
        if (t.status === "done") data.done = [t, ...(data.done || [])];
        else data.in_progress = [...(data.in_progress || []), t];
      }
      const m = op.path.match(/^\/recurring\/(\d+)\/toggle$/);
      if (m) for (const r of data.recurring || []) if (r.id === Number(m[1]) && (!op.body.day || op.body.day === data.day)) {
        r.done_today = !!op.body.done;
        if (op.body.note) r.note = op.body.note;  // a evidência escrita sem sinal aparece na linha
      }
      const f = op.path.match(/^\/worklog\/(\d+)\/finish$/);
      if (f) data.in_progress = (data.in_progress || []).filter((t) => t.id !== Number(f[1]));
    }
  }
  const t = path.match(/^\/worklog\/(\d+)$/);
  if (t) {
    for (const op of ops) {
      if (op.path === `/worklog/${t[1]}/notes`) data.notes = [{ id: "fila-" + op.qid, body: op.body.body, created_at: op.at, actor: "web", pending: true }, ...(data.notes || [])];
      if (op.path === `/worklog/${t[1]}/finish`) { data.status = "done"; data.pending_done = true; }
    }
  }
  if (path === "/timer") {
    for (const op of ops) {
      if (op.path === "/timer/stop") data.timer = null;
      if (op.path === "/timer/start") data.timer = { task_id: op.body.task_id, title: op.body.title || "Tarefa", started_at: op.body.at };
    }
  }
  return data;
}

// ------------------------------------------- deixar pronto para sem sinal --
// Antes de sair para onde não há sinal: lê as telas de abrir o dia e o detalhe
// de cada tarefa aberta (checklist, anotações), em série curta, e o service
// worker guarda como sempre (nexus-dados). Até READY_MAX tarefas, as primeiras
// na ordem do Hoje (atrasadas, vencem hoje, prioridade). Sair apaga tudo.
const READY_KEY = "nexus.pronto", READY_MAX = 60;

// { at, n } da última vez que ficou pronto (ou null).
export function readyInfo() {
  try { return JSON.parse(localStorage.getItem(READY_KEY) || "null"); } catch { return null; }
}

// onStep(feitas, total): para a tela mostrar o andamento. Devolve { n, total, at, failed }.
export async function prepareOffline(onStep) {
  if (!navigator.onLine) throw Object.assign(new Error("Sem conexão agora. Faça isto antes de sair, com sinal."), { status: 0 });
  if (!sendFn) throw new Error("O app ainda está abrindo. Tente de novo.");
  // Pede ao navegador para não apagar estes dados quando faltar espaço (quando ele deixa).
  try { await navigator.storage?.persist?.(); } catch { /* opcional */ }
  // 60 detalhes são poucos centenas de KB; sem nem 5 MB livres, o navegador apagaria o que já está guardado.
  try {
    const est = await navigator.storage?.estimate?.();
    if (est && est.quota && est.quota - (est.usage || 0) < 5e6) throw Object.assign(new Error("Pouco espaço livre no aparelho para guardar as tarefas. Libere espaço e tente de novo."), { status: 507 });
  } catch (e) { if (e.status === 507) throw e; /* sem estimativa: segue */ }
  const board = await sendFn("GET", "/board");
  await Promise.all(["/recurring/reminders", "/projects", "/timer", "/summary"].map((p) => sendFn("GET", p).catch(() => null)));
  const open = (board.in_progress || []).slice(0, READY_MAX);
  let n = 0, failed = 0;
  for (const t of open) {
    try { await sendFn("GET", `/worklog/${t.id}`); n++; } catch (e) { if (!e.status) break; failed++; }
    if (onStep) onStep(n + failed, open.length);
  }
  const info = { at: new Date().toISOString(), n, total: (board.in_progress || []).length, failed };
  try { localStorage.setItem(READY_KEY, JSON.stringify({ at: info.at, n })); } catch { /* sem armazenamento: vale a cópia do SW */ }
  changed();
  return info;
}

// Botão "Deixar pronto para sem sinal": um toque guarda e avisa no fim.
// compact: só o ícone (cabeçalho do Em aberto no Hoje); senão, com o texto (Ajuda).
export function prepareButton({ compact = false } = {}) {
  const label = "Deixar pronto para sem sinal";
  const hint = "Guarda no aparelho o detalhe das tarefas em aberto (checklist e anotações), para abrir sem sinal";
  const btn = compact
    ? h("button", { type: "button", class: "icon", title: `${label}: ${hint.toLowerCase()}`, "aria-label": label }, icon("download"))
    : h("button", { type: "button", class: "btn btn-ghost btn-sm" }, icon("download"), label);
  btn.addEventListener("click", async () => {
    const { toast, errorToast } = await import("./ui.js");
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    try {
      const r = await prepareOffline((done, total) => { btn.title = `Guardando ${done} de ${total}…`; });
      const hora = new Date(r.at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
      const tarefas = r.n === 1 ? "1 tarefa" : `${r.n} tarefas`;
      toast(r.total > r.n + r.failed
        ? `Pronto às ${hora}: ${tarefas} com checklist e anotações no aparelho (as ${READY_MAX} primeiras do Hoje).`
        : `Pronto às ${hora}: ${tarefas} com checklist e anotações no aparelho.`);
    } catch (e) { errorToast(e, "Não deu para guardar. Tente de novo com sinal."); }
    finally { btn.disabled = false; btn.removeAttribute("aria-busy"); if (compact) btn.title = `${label}: ${hint.toLowerCase()}`; }
  });
  return btn;
}

// --------------------------------------------------------------- barra --
let staleAt = null;  // hora da última leitura servida do cache
export function markStale(iso) { staleAt = iso; changed(); }
export function markFresh() { if (staleAt) { staleAt = null; changed(); } }

let bar = null, pending = 0;
async function changed() {
  const [ops, bad] = await Promise.all([all(), failures()]);
  pending = ops.length;
  const offline = !navigator.onLine || staleAt;
  // A barra abre espaço no topo da página (body.has-offline-bar): não cobre o assistente.
  if (!offline && !ops.length && !bad.length) { bar?.remove(); bar = null; document.body.classList.remove("has-offline-bar"); return; }
  document.body.classList.add("has-offline-bar");
  const hora = staleAt ? new Date(staleAt).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : null;
  // "Deixar pronto para sem sinal" de hoje: a barra diz de que hora são os detalhes guardados.
  const ready = readyInfo();
  const readyHour = ready && new Date(ready.at).toDateString() === new Date().toDateString()
    ? new Date(ready.at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : null;
  // A contagem vem primeiro: no celular a barra corta o fim.
  const parts = [
    ops.length ? (sending && navigator.onLine ? `enviando ${ops.length > 1 ? `${ops.length} alterações` : "1 alteração"}…`
      : `${ops.length} ${ops.length > 1 ? "alterações esperando envio" : "alteração esperando envio"}`) : null,
    offline ? (hora ? `sem conexão desde ${hora}` : "sem conexão") : null,
    offline && readyHour ? `${ready.n} ${ready.n === 1 ? "tarefa guardada" : "tarefas guardadas"} às ${readyHour}` : null,
    bad.length ? `${bad.length} não ${bad.length > 1 ? "puderam" : "pôde"} ser ${bad.length > 1 ? "aplicadas" : "aplicada"}` : null,
  ].filter(Boolean);
  const content = [icon(offline ? "alert" : "clock"), h("span", { text: parts.join(" · ") }),
    ops.length || bad.length ? h("button", { type: "button", class: "btn btn-text btn-sm", text: "Ver", onClick: showList }) : null];
  if (!bar) { bar = h("div", { class: "offline-bar", role: "status", "aria-live": "polite" }); document.body.append(bar); }
  bar.classList.toggle("bad", !!bad.length && !offline);
  bar.replaceChildren(...content.filter(Boolean));
}

async function showList() {
  const { modal } = await import("./ui.js");
  const [ops, bad] = await Promise.all([all(), failures()]);
  const when = (iso) => new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  const dlg = modal(h("h2", { text: "Feito sem conexão" }),
    ops.length ? h("p", { class: "dialog-note", text: "Vai sozinho, nesta ordem, quando a conexão voltar (com o Nexus aberto)." }) : null,
    ...ops.map((op) => h("div", { class: "token-row" }, h("span", { class: "token-name", text: describe(op) }), h("span", { class: "token-meta", text: when(op.at) }))),
    bad.length ? h("h3", { text: "Não deu para aplicar" }) : null,
    ...bad.map((op) => {
      // O texto inteiro (anotação, título) com Copiar: dispensar não pode perder o que foi escrito no campo.
      const full = op.body && (op.body.body || op.body.note || op.body.title);
      return h("div", { class: "token-row" }, h("span", { class: "token-name", text: op.what }),
        h("button", { type: "button", class: "icon dismiss", title: "Dispensar", "aria-label": "Dispensar", onClick: async () => {
          await tx(FAILED, "readwrite", (s) => s.delete(op.qid)); dlg.close(); changed();
        } }, icon("close")),
        h("span", { class: "token-meta", text: op.error }),
        full ? h("div", { class: "failed-box" }, h("p", { text: full }),
          h("button", { type: "button", class: "btn btn-text btn-sm", onClick: async () => {
            const { toast } = await import("./ui.js");
            try { await navigator.clipboard.writeText(full); toast("Texto copiado."); }
            catch { toast("Selecione o texto e copie.", { error: true }); }
          } }, icon("copy"), "Copiar")) : null);
    }),
    h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-text", text: "Fechar", onClick: () => dlg.close() })));
}

export const pendingCount = () => pending;

// Sessão expirada: as leituras guardadas saem do aparelho (pode ser compartilhado).
// A fila fica: é trabalho ainda não enviado, e vai quando a mesma pessoa entrar
// (outra conta entrando apaga tudo, em app.js).
export async function wipeReads() {
  try { localStorage.removeItem(READY_KEY); } catch { /* sem armazenamento */ }
  if ("caches" in window) await caches.delete("nexus-dados");  // o mesmo nome de sw.js
}

// Sair: a fila e as leituras guardadas não ficam no aparelho (pode ser compartilhado).
export async function wipe() {
  try { await tx(STORE, "readwrite", (s) => s.clear()); await tx(FAILED, "readwrite", (s) => s.clear()); } catch { /* sem IndexedDB */ }
  try { localStorage.removeItem(READY_KEY); } catch { /* sem armazenamento */ }
  if ("caches" in window) for (const k of await caches.keys()) if (k.startsWith("nexus-")) await caches.delete(k);
}

let started = false;
export function startQueue(refresh) {
  onSynced = refresh;
  if (started) return;
  started = true;
  // Rede de volta: envia a fila e relê a tela mesmo sem nada na fila (a leitura
  // nova tira o "sem conexão desde…" e troca os dados guardados pelos de agora).
  // A primeira tentativa logo na volta da rede costuma falhar (a rede ainda acordando): tenta de novo em 2 s e 5 s.
  addEventListener("online", async () => {
    changed();
    const sent = await flush();
    if (!sent && onSynced) onSynced();
    if (!sent && pending) for (const ms of [2000, 5000]) setTimeout(() => { if (pending) flush(); }, ms);
  });
  addEventListener("offline", changed);
  setInterval(() => { if (pending) flush(); }, 30000);
  changed();
  flush();
}
