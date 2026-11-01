// Meu mês: os números (a antiga Retrospectiva) e o PDF (os antigos Relatórios)
// numa tela só, com o mês escolhido uma vez no topo (o corrente por padrão).
// Números mostra o mês; no PDF, o mesmo mês preenche as datas (dá para ajustar
// lá, ou pegar uma semana). #/mes?aba=numeros|pdf; #/dashboard e #/relatorios
// chegam aqui pelo app.js.
import { h, icon, clear, addDays, localDay } from "./dom.js";
import { errorToast } from "./ui.js";
import * as dashboard from "./dashboard.js";
import * as reports from "./reports.js";

const MONTHS_LONG = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const TABS = [["numeros", "Números"], ["pdf", "PDF"]];

// Ficam enquanto o app estiver aberto: voltar à tela mostra o que estava.
let month = null;   // "AAAA-MM"
let months = null;  // do mais recente ao primeiro registro (vem com os números)
let tab = "numeros";

const thisMonth = () => localDay(Date.now()).slice(0, 7);
const prevOf = (m) => { const [y, n] = m.split("-").map(Number); return n === 1 ? `${y - 1}-12` : `${y}-${String(n - 1).padStart(2, "0")}`; };
const nextOf = (m) => { const [y, n] = m.split("-").map(Number); return n === 12 ? `${y + 1}-01` : `${y}-${String(n + 1).padStart(2, "0")}`; };
// Do dia 1 ao último dia do mês (o corrente, até hoje).
function rangeOf(m) {
  const today = localDay(Date.now());
  return [m + "-01", m === today.slice(0, 7) ? today : addDays(nextOf(m) + "-01", -1)];
}

export async function mount(root, ctx) {
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  if (TABS.some(([k]) => k === q.get("aba"))) tab = q.get("aba");
  const week = q.get("periodo") === "semana";  // "Gerar relatório" da sexta: o PDF da semana
  if (week) window.history.replaceState(null, "", "#/mes?aba=pdf");
  const cur = thisMonth();
  if (!month || month > cur) month = cur;  // virou o mês com o app aberto

  const label = h("span", { class: "day-nav-label", "aria-live": "polite" });
  const prev = h("button", { type: "button", class: "icon", title: "Mês anterior", "aria-label": "Mês anterior", onClick: () => pick(prevOf(month)) }, icon("left"));
  const next = h("button", { type: "button", class: "icon", title: "Próximo mês", "aria-label": "Próximo mês", onClick: () => pick(nextOf(month)) }, icon("right"));
  const paintNav = () => {
    label.textContent = MONTHS_LONG[Number(month.slice(5)) - 1] + " de " + month.slice(0, 4) + (month === thisMonth() ? " · até hoje" : "");
    next.disabled = month >= thisMonth();
    prev.disabled = !!months && months.length > 0 && month <= months[months.length - 1];
  };
  const tabs = h("div", { class: "seg seg-sm", role: "tablist", "aria-label": "Meu mês" },
    ...TABS.map(([key, text]) => h("button", { type: "button", class: "chip-btn", role: "tab", text, "data-tab": key,
      onClick: () => { if (key === tab) return; tab = key; window.history.replaceState(null, "", "#/mes?aba=" + key); paintTabs(); show().catch((e) => errorToast(e)); } })));
  const paintTabs = () => { for (const b of tabs.children) b.setAttribute("aria-selected", String(b.dataset.tab === tab)); };
  const content = h("div", { class: "mes-content" });

  let pdf = null, seq = 0;
  // Monta a aba fora da tela e só a última resposta entra (troca rápida de aba ou mês).
  async function show() {
    const my = ++seq;
    const box = h("div", {});
    content.classList.add("refreshing");
    try {
      if (tab === "numeros") {
        pdf = null;
        await dashboard.mount(box, { me: ctx.me, setAssist: (n) => { if (my === seq) ctx.setAssist(n); }, month,
          onMonths: (list) => { months = list; paintNav(); } });
      } else {
        const [start, end] = rangeOf(month);
        const ctl = await reports.mount(box, { me: ctx.me, range: { start, end }, week });
        if (my === seq) { pdf = ctl; ctx.setAssist(null); }
      }
    } catch (e) {
      if (my !== seq) return;
      content.classList.remove("refreshing");
      throw e;
    }
    if (my !== seq) return;
    content.classList.remove("refreshing");
    clear(content);
    content.append(box);
  }
  async function pick(m) {
    month = m;
    paintNav();
    if (tab === "pdf" && pdf) { const [start, end] = rangeOf(month); pdf.setRange(start, end); return; }
    try { await show(); } catch (e) { errorToast(e); }
  }

  paintNav();
  paintTabs();
  await show();
  clear(root);
  root.append(h("div", { class: "mes-bar" }, tabs, h("div", { class: "day-nav dash-period" }, prev, label, next)), content);
}
