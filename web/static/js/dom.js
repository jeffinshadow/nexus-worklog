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

// Campo com rótulo associado (for/id): leitor de tela anuncia o nome e o
// clique no rótulo foca o campo.
let fieldSeq = 0;
export function field(label, control, extraClass = "") {
  if (!control.id) control.id = "f" + ++fieldSeq;
  return h("div", { class: "field" + (extraClass ? " " + extraClass : "") }, h("label", { for: control.id, text: label }), control);
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
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

// Fuso da app (APP_TZ do servidor, vem em /auth/me): horas e "que dia foi"
// de um timestamp seguem o servidor, não o relógio do navegador.
let TZ = "America/Sao_Paulo";
export function setTimeZone(tz) {
  if (tz) TZ = tz;
}

export function dateTime(ts) {
  return new Date(ts).toLocaleString("pt-BR", {
    timeZone: TZ, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

// Dia (YYYY-MM-DD) de um timestamp no fuso da app.
export function localDay(ts) {
  return new Date(ts).toLocaleDateString("sv-SE", { timeZone: TZ });
}
