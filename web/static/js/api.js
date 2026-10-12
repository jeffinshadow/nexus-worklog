// Wrapper de fetch para /api. Envia o cookie de sessao (same-origin) e o
// header X-CSRF-Token nas mutacoes. Redireciona para o login em 401 de sessao.

let CSRF = null;

// Uma ida ao servidor: CSRF nas mutacoes, 401 -> login, erro -> Error(detail).
async function send(method, path, { body, type } = {}) {
  const headers = {};
  if (type) headers["Content-Type"] = type;
  if (method !== "GET" && CSRF) headers["X-CSRF-Token"] = CSRF;
  const res = await fetch("/api" + path, { method, headers, body, credentials: "same-origin" });

  // 401 fora das rotas de auth = sessao expirou -> volta ao login.
  if (res.status === 401 && !path.startsWith("/auth/")) {
    if (location.pathname !== "/login.html") location.href = "/login.html";
    throw new Error("nao autenticado");
  }
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw Object.assign(new Error((data && data.detail) || res.statusText), { status: res.status, data });
  }
  return res;
}

async function request(method, path, body) {
  const res = await send(method, path, body === undefined ? {} : { body: JSON.stringify(body), type: "application/json" });
  return res.status === 204 ? null : res.json().catch(() => null);
}

// Baixa um arquivo (o nome vem do Content-Disposition).
async function download(path) {
  const res = await send("GET", path);
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
  const res = await send("POST", path, { body: file, type: file.type || "application/octet-stream" });
  return res.json().catch(() => null);
}

export const api = {
  get: (p) => request("GET", p),
  post: (p, b) => request("POST", p, b),
  patch: (p, b) => request("PATCH", p, b),
  put: (p, b) => request("PUT", p, b),
  del: (p) => request("DELETE", p),
  upload,
  download,
  setCsrf: (token) => { CSRF = token; },
};
