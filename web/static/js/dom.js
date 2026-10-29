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

// "YYYY-MM-DDTHH:MM" de um timestamp no fuso da app (valor de <input type=datetime-local>).
export function localDateTime(ts) {
  return new Date(ts).toLocaleString("sv-SE", { timeZone: TZ, hour12: false }).slice(0, 16).replace(" ", "T");
}

// Hora, minuto e dia da semana (0 = domingo) agora, no fuso da app: saudação
// do assistente e janela do lembrete.
const WD_EN = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
export function nowInTz() {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", minute: "numeric", weekday: "short", hourCycle: "h23" })
    .formatToParts(new Date());
  const p = Object.fromEntries(parts.map((x) => [x.type, x.value]));
  return { hour: Number(p.hour), minute: Number(p.minute), weekday: WD_EN.indexOf(p.weekday) };
}

// N dias úteis depois de `iso` (máscara de dias úteis, domingo = bit 0).
export function addWorkDays(iso, n, mask = 62) {
  let d = iso;
  while (n > 0) {
    d = addDays(d, 1);
    const wd = new Date(d + "T12:00:00Z").getUTCDay();
    if ((mask >> wd) & 1) n--;
  }
  return d;
}

// Dias de calendário entre duas datas ISO (YYYY-MM-DD): b - a.
export function daysBetween(a, b) {
  const t = (iso) => { const [y, m, d] = iso.split("-").map(Number); return Date.UTC(y, m - 1, d); };
  return Math.round((t(b) - t(a)) / 86400000);
}

// Senha + confirmação: o navegador recusa o envio enquanto as duas não baterem.
export function matchPasswords(pw, confirm) {
  const check = () => confirm.setCustomValidity(confirm.value && confirm.value !== pw.value ? "As senhas não são iguais." : "");
  pw.addEventListener("input", check);
  confirm.addEventListener("input", check);
  return check;
}
