// Wrapper de fetch para /api. Envia o cookie de sessao (same-origin) e o
// header X-CSRF-Token nas mutacoes. Redireciona para o login em 401 de sessao.

let CSRF = null;

// Mensagem para a tela, sempre em português: o detail do backend quando ele
// é texto; validação (lista do FastAPI), rede e respostas sem JSON, genéricas.
function messageFor(status, data) {
  const d = data && data.detail;
  if (typeof d === "string" && d) return d;
  if (Array.isArray(d)) return "Dados inválidos: confira os campos.";
  if (status === 429) return "Muitas tentativas. Aguarde um pouco e tente de novo.";
  if (status >= 500) return "O servidor teve um problema. Tente de novo em instantes.";
  return "Não foi possível concluir. Tente de novo.";
}

// Uma ida ao servidor: CSRF nas mutacoes, 401 -> login (voltando à mesma tela),
// erro -> Error(mensagem). Sem resposta em `timeout` ms, desiste.
async function send(method, path, { body, type, timeout = 20000, publicCall = false } = {}) {
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
    if (location.pathname !== "/login.html") toLogin();
    throw new Error("nao autenticado");
  }
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw Object.assign(new Error(messageFor(res.status, data)), { status: res.status, data });
  }
  return res;
}

// Login guardando a tela atual (#/...), para voltar a ela depois.
export function toLogin() {
  const next = location.hash.startsWith("#/") ? "?next=" + encodeURIComponent(location.hash) : "";
  location.href = "/login.html" + next;
}

async function request(method, path, body) {
  const res = await send(method, path, body === undefined ? {} : { body: JSON.stringify(body), type: "application/json" });
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
  get: (p) => request("GET", p),
  // Rotas públicas (ex.: identidade visual na tela de login): 401 não redireciona.
  getPublic: async (p) => (await send("GET", p, { publicCall: true })).json(),
  post: (p, b) => request("POST", p, b),
  patch: (p, b) => request("PATCH", p, b),
  put: (p, b) => request("PUT", p, b),
  del: (p) => request("DELETE", p),
  upload,
  download,
  setCsrf: (token) => { CSRF = token; },
};
