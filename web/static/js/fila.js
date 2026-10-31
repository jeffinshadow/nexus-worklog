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
  if (/^\/timer\//.test(path)) body.at = now.toISOString();
  if (/\/finish$/.test(path) && !body.completed_at) body.completed_at = localDateTime(now.getTime());
  if (/\/toggle$/.test(path) && !body.day) body.day = localDay(now.toISOString());
  const op = { method, path, body, at: now.toISOString(), then: [] };
  const qid = await tx(STORE, "readwrite", (s) => s.add(op));
  changed();
  return qid;
}

// Passo seguinte de uma criação que está na fila ({id} = a tarefa criada).
export async function after(qid, method, path, body) {
  await tx(STORE, "readwrite", (s) => {
    const g = s.get(qid);
    g.onsuccess = () => { if (g.result) { g.result.then.push({ method, path, body }); s.put(g.result); } };
  });
}

// O que descrever na lista ("Nova tarefa: X").
function describe(op) {
  const b = op.body || {};
  if (op.path === "/worklog") return `Nova tarefa: ${b.title}`;
  if (/\/finish$/.test(op.path)) return "Concluir tarefa";
  if (/\/notes$/.test(op.path)) return `Anotação: ${(b.body || "").slice(0, 60)}`;
  if (/\/toggle$/.test(op.path)) return b.done ? "Marcar rotina" : "Desmarcar rotina";
  if (/\/timer\/start$/.test(op.path)) return "Iniciar cronômetro";
  if (/\/timer\/stop$/.test(op.path)) return "Parar cronômetro";
  return `${op.method} ${op.path}`;
}

// ------------------------------------------------------------- envio --
let sending = false, sendFn = null, onSynced = null;

// api.js entrega o envio cru (sem fila).
export function configure(send) { sendFn = send; }

export async function flush() {
  if (sending || !sendFn || !navigator.onLine) return;
  sending = true;
  let sent = 0;
  try {
    for (const op of await all()) {
      let res;
      try { res = await sendFn(op.method, op.path, op.body); }
      catch (e) {
        if (!e.status || e.status === 401) break;  // sem rede ou sem sessão: tenta depois
        await tx(FAILED, "readwrite", (s) => s.put({ ...op, error: e.message, what: describe(op) }));
        await tx(STORE, "readwrite", (s) => s.delete(op.qid));
        continue;
      }
      for (const step of op.then) {  // passos da criação, com o id que o servidor deu
        try { await sendFn(step.method, step.path.replace("{id}", res && res.id), step.body); } catch { /* o principal já foi */ }
      }
      await tx(STORE, "readwrite", (s) => s.delete(op.qid));
      sent++;
    }
  } finally {
    sending = false;
    changed();
  }
  if (sent && onSynced) onSynced();
}

// --------------------------------------------- dados de antes, com a fila por cima --
// A leitura veio do cache (sem sinal): aplica o que está na fila para a tela
// não "desfazer" o que a pessoa acabou de fazer.
export async function overlay(path, data) {
  const ops = await all();
  if (!ops.length || !data) return data;
  if (/^\/board/.test(path)) {
    for (const op of ops) {
      const m = op.path.match(/^\/recurring\/(\d+)\/toggle$/);
      if (m) for (const r of data.recurring || []) if (r.id === Number(m[1]) && (!op.body.day || op.body.day === data.day)) r.done_today = !!op.body.done;
      const f = op.path.match(/^\/worklog\/(\d+)\/finish$/);
      if (f) data.in_progress = (data.in_progress || []).filter((t) => t.id !== Number(f[1]));
    }
  }
  const t = path.match(/^\/worklog\/(\d+)$/);
  if (t) {
    for (const op of ops) {
      if (op.path === `/worklog/${t[1]}/notes`) data.notes = [{ id: "fila-" + op.qid, body: op.body.body, created_at: op.at, actor: "web", pending: true }, ...(data.notes || [])];
      if (op.path === `/worklog/${t[1]}/finish`) data.status = "done";
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

// --------------------------------------------------------------- barra --
let staleAt = null;  // hora da última leitura servida do cache
export function markStale(iso) { staleAt = iso; changed(); }
export function markFresh() { if (staleAt) { staleAt = null; changed(); } }

let bar = null, pending = 0;
async function changed() {
  const [ops, bad] = await Promise.all([all(), failures()]);
  pending = ops.length;
  const offline = !navigator.onLine || staleAt;
  if (!offline && !ops.length && !bad.length) { bar?.remove(); bar = null; return; }
  const hora = staleAt ? new Date(staleAt).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : null;
  const parts = [
    offline ? (hora ? `Sem conexão · mostrando o que havia às ${hora}` : "Sem conexão") : null,
    ops.length ? `${ops.length} ${ops.length > 1 ? "alterações esperando" : "alteração esperando"} conexão` : null,
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
    ...bad.map((op) => h("div", { class: "token-row" }, h("span", { class: "token-name", text: op.what }),
      h("span", { class: "token-meta", text: op.error }),
      h("button", { type: "button", class: "icon", title: "Dispensar", "aria-label": "Dispensar", onClick: async () => {
        await tx(FAILED, "readwrite", (s) => s.delete(op.qid)); dlg.close(); changed();
      } }, icon("close")))),
    h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-primary", text: "Fechar", onClick: () => dlg.close() })));
}

export const pendingCount = () => pending;

// Sair: a fila e as leituras guardadas não ficam no aparelho (pode ser compartilhado).
export async function wipe() {
  try { await tx(STORE, "readwrite", (s) => s.clear()); await tx(FAILED, "readwrite", (s) => s.clear()); } catch { /* sem IndexedDB */ }
  if ("caches" in window) for (const k of await caches.keys()) if (k.startsWith("nexus-")) await caches.delete(k);
}

export function startQueue(refresh) {
  onSynced = refresh;
  addEventListener("online", () => { changed(); flush(); });
  addEventListener("offline", changed);
  setInterval(() => { if (pending) flush(); }, 30000);
  changed();
  flush();
}
