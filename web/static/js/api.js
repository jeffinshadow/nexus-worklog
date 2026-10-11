// Wrapper de fetch para /api. Envia o cookie de sessao (same-origin) e o
// header X-CSRF-Token nas mutacoes. Redireciona para o login em 401 de sessao.

let CSRF = null;

export function setCsrf(token) {
  CSRF = token;
}

async function request(method, path, body) {
  const opts = { method, headers: {}, credentials: "same-origin" };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  if (method !== "GET" && CSRF) {
    opts.headers["X-CSRF-Token"] = CSRF;
  }

  const res = await fetch("/api" + path, opts);

  // 401 fora das rotas de auth = sessao expirou -> volta ao login.
  if (res.status === 401 && !path.startsWith("/auth/")) {
    if (location.pathname !== "/login.html") location.href = "/login.html";
    throw new Error("nao autenticado");
  }

  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (data && data.detail) || res.statusText;
    throw Object.assign(new Error(detail), { status: res.status, data });
  }
  return data;
}

// Baixa um arquivo de /api (GET, sem CSRF). Em erro, le o detalhe JSON e
// lanca; em sucesso, dispara o download do blob. O nome vem do
// Content-Disposition (fallback generico).
async function download(path) {
  const res = await fetch("/api" + path, { method: "GET", credentials: "same-origin" });

  if (res.status === 401 && !path.startsWith("/auth/")) {
    if (location.pathname !== "/login.html") location.href = "/login.html";
    throw new Error("nao autenticado");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const d = await res.json();
      detail = (d && d.detail) || detail;
    } catch {
      /* resposta sem JSON */
    }
    throw Object.assign(new Error(detail), { status: res.status });
  }

  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const match = /filename="?([^";]+)"?/.exec(cd);
  const filename = match ? match[1] : "download";

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Envia um arquivo como corpo bruto (sem multipart), com o tipo do arquivo.
async function upload(path, file) {
  const res = await fetch("/api" + path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": file.type || "application/octet-stream", ...(CSRF ? { "X-CSRF-Token": CSRF } : {}) },
    body: file,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw Object.assign(new Error((data && data.detail) || res.statusText), { status: res.status });
  return data;
}

export const api = {
  get: (p) => request("GET", p),
  post: (p, b) => request("POST", p, b),
  patch: (p, b) => request("PATCH", p, b),
  put: (p, b) => request("PUT", p, b),
  upload,
  del: (p) => request("DELETE", p),
  download,
  setCsrf,
};
