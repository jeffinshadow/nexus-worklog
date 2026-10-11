// Helpers minimos de DOM. Eventos via addEventListener (nao ha handlers
// inline, respeitando a CSP).

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else {
      el.setAttribute(key, value);
    }
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function icon(name) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "ico");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("viewBox", "0 0 24 24");
  const use = document.createElementNS(NS, "use");
  use.setAttribute("href", "#icon-" + name);
  svg.appendChild(use);
  return svg;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
}

export function formatDate(value) {
  if (!value) return "";
  const d = new Date(value.length <= 10 ? value + "T00:00:00" : value);
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

// Datas ISO (YYYY-MM-DD) em UTC puro: o "hoje" vem do servidor (fuso do app),
// o navegador só soma dias e formata, sem depender do fuso local.
export function addDays(iso, n) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

const WD = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"];
const MES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

export function longDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return `${WD[wd]}, ${d} de ${MES[m - 1]}`;
}

export function shortDate(iso) {
  if (!iso) return "";
  const [, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}`;
}

// Data/hora de um timestamp ISO no fuso de Brasília.
export function dateTime(ts) {
  return new Date(ts).toLocaleString("pt-BR", {
    timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}
