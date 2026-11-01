// Wrapper de fetch para /api. Envia o cookie de sessao (same-origin) e o
// header X-CSRF-Token nas mutacoes. Redireciona para o login em 401 de sessao.

import { after as queueAfter, configure, enqueue, markFresh, markStale, overlay, queueable, wipeReads } from "./fila.js";

let CSRF = null;

// Mensagem para a tela, sempre em português: o detail do backend quando ele
// é texto; validação (lista do FastAPI), rede e respostas sem JSON, genéricas.
function messageFor(status, data) {
  const d = data && data.detail;
  if (typeof d === "string" && d) return d[0].toUpperCase() + d.slice(1) + (/[.!?]$/.test(d) ? "" : ".");
  if (Array.isArray(d)) {
    // Os validadores de schemas.py falam português ("Value error, ..."); o resto
    // é inglês do pydantic e vira o texto genérico.
    const raw = String((d[0] && d[0].msg) || "");
    const m = raw.replace(/^Value error, /, "").trim();
    if (m && (raw !== m || /[à-ú]/i.test(m))) return m[0].toUpperCase() + m.slice(1) + (/[.!?]$/.test(m) ? "" : ".");
    return "Algum campo está inválido. Confira e tente de novo.";
  }
  if (status === 429) return "Muitas tentativas. Aguarde um pouco e tente de novo.";
  if (status >= 500) return "O servidor teve um problema. Tente de novo em instantes.";
  return "Não foi possível concluir. Tente de novo.";
}

// Uma ida ao servidor: CSRF nas mutacoes, 401 -> login (voltando à mesma tela),
// erro -> Error(mensagem). Sem resposta em `timeout` ms, desiste.
async function send(method, path, { body, type, timeout = 20000, publicCall = false, retried = false } = {}) {
  const headers = {};
  if (type) headers["Content-Type"] = type;
  if (method !== "GET" && CSRF) headers["X-CSRF-Token"] = CSRF;
  let res;
  try {
    res = await fetch("/api" + path, { method, headers, body, credentials: "same-origin", signal: AbortSignal.timeout(timeout) });
  } catch (e) {
    const slow = e && (e.name === "TimeoutError" || e.name === "AbortError");
    throw Object.assign(new Error(slow ? "O servidor demorou para responder. Tente de novo." : "Sem conexão com o servidor. Confira a internet e tente de novo."), { status: 0 });
  }

  // 401 fora das rotas de auth = sessao expirou -> volta ao login.
  if (res.status === 401 && !publicCall && !path.startsWith("/auth/")) {
    if (location.pathname !== "/login") toLogin();
    throw new Error("nao autenticado");
  }
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    // Login de novo em outra aba troca a sessão (e o CSRF): pega o novo e tenta uma vez.
    if (res.status === 403 && /CSRF/.test((data && data.detail) || "") && !retried) {
      const me = await send("GET", "/auth/me").then((r) => r.json()).catch(() => null);
      if (me && me.csrf_token) {
        CSRF = me.csrf_token;
        return send(method, path, { body, type, timeout, publicCall, retried: true });
      }
    }
    if (res.status === 403 && /CSRF/.test((data && data.detail) || "")) {
      throw Object.assign(new Error("Sua sessão mudou em outra aba. Recarregue a página."), { status: 403, data });
    }
    throw Object.assign(new Error(messageFor(res.status, data)), { status: res.status, data });
  }
  return res;
}

// Login guardando a tela atual (#/...), para voltar a ela depois.
export function toLogin() {
  const next = location.hash.startsWith("#/") ? "?next=" + encodeURIComponent(location.hash) : "";
  wipeReads().catch(() => {}).finally(() => { location.href = "/login" + next; });
}

// Foto (base64, até ~1,3 MB) no 3G do campo passa dos 20 s: espera mais.
const waitFor = (path) => (/\/photos(\?|$)/.test(path) ? 90000 : 20000);

async function raw(method, path, body) {
  const res = await send(method, path, body === undefined ? { timeout: waitFor(path) } : { body: JSON.stringify(body), type: "application/json", timeout: waitFor(path) });
  return res.status === 204 ? null : res.json().catch(() => null);
}
configure(raw);

// Sem sinal, as ações da fila (fila.js) ficam guardadas e a resposta é
// { queued: true, qid }; leituras servidas do cache avisam a barra e recebem
// por cima o que está na fila.
async function request(method, path, body, opts = {}) {
  if (method === "POST" && /^\/(worklog(\/\d+\/(notes|time|photos))?|recurring\/\d+\/photos(\?.*)?)$/.test(path) && body && !body.external_ref)
    body = { ...body, external_ref: "app-" + crypto.randomUUID() };  // reenviar (fila, timeout) nunca duplica
  let res;
  try {
    res = await send(method, path, body === undefined ? { timeout: opts.timeout || waitFor(path) } : { body: JSON.stringify(body), type: "application/json", timeout: waitFor(path) });
  } catch (e) {
    if (e.status === 0 && queueable(method, path)) return { queued: true, qid: await enqueue(method, path, body), id: null };
    throw e;
  }
  if (method === "GET") {
    const cached = res.headers.get("X-Nexus-Cache");
    const total = Number(res.headers.get("X-Total-Count"));
    const withTotal = (rows) => (opts.total ? { rows: rows || [], total: Number.isFinite(total) && res.headers.has("X-Total-Count") ? total : (rows || []).length } : rows);
    if (cached) { markStale(cached); return withTotal(await overlay(path.split("?")[0], await res.json().catch(() => null))); }
    markFresh();
    return withTotal(await res.json().catch(() => null));
  }
  return res.status === 204 ? null : res.json().catch(() => null);
}

// Baixa um arquivo (o nome vem do Content-Disposition).
async function download(path) {
  const res = await send("GET", path, { timeout: 90000 }); // PDF grande demora
  const match = /filename="?([^";]+)"?/.exec(res.headers.get("Content-Disposition") || "");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = match ? match[1] : "download";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Envia um arquivo como corpo bruto (sem multipart), com o tipo do arquivo.
async function upload(path, file) {
  const res = await send("POST", path, { body: file, type: file.type || "application/octet-stream", timeout: 60000 });
  return res.json().catch(() => null);
}

export const api = {
  // opts.timeout: espera menor (a abertura do app não fica 20 s parada com o servidor fora).
  get: (p, opts) => request("GET", p, undefined, opts),
  // Lista paginada: { rows, total } (o total vem no cabeçalho X-Total-Count).
  page: (p, opts) => request("GET", p, undefined, { ...opts, total: true }),
  // Rotas públicas (ex.: identidade visual na tela de login): 401 não redireciona.
  getPublic: async (p) => (await send("GET", p, { publicCall: true })).json(),
  post: (p, b) => request("POST", p, b),
  patch: (p, b) => request("PATCH", p, b),
  put: (p, b) => request("PUT", p, b),
  del: (p) => request("DELETE", p),
  upload,
  download,
  setCsrf: (token) => { CSRF = token; },
  after: queueAfter,  // passo seguinte de uma criação que ficou na fila

};
