// O Nexus como app instalado: o convite para instalar (Chrome, Edge e Android
// têm o botão; iPhone e iPad, o passo a passo do Safari), o número no ícone
// (atrasadas + rotinas na hora), os atalhos do ícone e o "compartilhar para o
// Nexus" de outros apps. O que o aparelho não suporta some sem aviso.
import { h, icon } from "./dom.js";
import { modal, toast } from "./ui.js";

const DISMISS_KEY = "nexus.instalar.dispensado";
const DISMISS_DAYS = 30;
const SHARE_KEY = "nexus.compartilhado";

let deferred = null;  // o pedido de instalação que o navegador guardou pra nós
let card = null;

// O navegador avisa que dá pra instalar antes de o app terminar de abrir: guarda já.
addEventListener("beforeinstallprompt", (ev) => {
  ev.preventDefault();  // sem a barrinha do navegador; o convite é o nosso
  deferred = ev;
});
addEventListener("appinstalled", () => {
  deferred = null;
  closeCard();
  toast("Nexus instalado. Ele abre direto da tela de início ou do menu.");
});

export const installed = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
// iPhone e iPad (o iPad se apresenta como Mac, mas tem toque).
const ios = () => /iPhone|iPad|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);

function dismissed() {
  try { return Date.now() - Number(localStorage.getItem(DISMISS_KEY) || 0) < DISMISS_DAYS * 864e5; } catch { return false; }
}
function dismiss() {
  try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch { /* sem armazenamento: só nesta visita */ }
  closeCard();
}
function closeCard() { if (card) card.remove(); card = null; }

// Instala: com o pedido guardado, a janela do próprio navegador; senão, o passo a passo.
export async function install() {
  if (deferred) {
    const ev = deferred;
    deferred = null;
    ev.prompt();
    const { outcome } = await ev.userChoice.catch(() => ({ outcome: "dismissed" }));
    if (outcome !== "accepted") dismiss();
    else closeCard();
    return;
  }
  showSteps();
}

// O que dizer em cada aparelho quando o navegador não oferece o botão.
function steps() {
  if (ios()) return [
    h("li", {}, "Toque em ", h("strong", {}, icon("share"), " Compartilhar"), " (no Safari, na barra de baixo; no Chrome, no topo)."),
    h("li", {}, "Escolha ", h("strong", { text: "Adicionar à Tela de Início" }), " e toque em ", h("strong", { text: "Adicionar" }), "."),
    h("li", { text: "Abra o Nexus pelo ícone novo na tela de início." }),
  ];
  if (/Android/.test(navigator.userAgent)) return [
    h("li", {}, "No Chrome, toque no ", h("strong", { text: "⋮" }), " do canto de cima."),
    h("li", {}, "Escolha ", h("strong", { text: "Instalar app" }), " (ou ", h("strong", { text: "Adicionar à tela inicial" }), ")."),
  ];
  if (/Firefox/.test(navigator.userAgent)) return [
    h("li", { text: "O Firefox do computador não instala sites como app." }),
    h("li", { text: "Abra o Nexus no Chrome ou no Edge e use o ícone de instalar na barra de endereço." }),
  ];
  return [
    h("li", { text: "No Chrome ou no Edge, clique no ícone de instalar no fim da barra de endereço." }),
    h("li", {}, "Ou no menu do navegador: ", h("strong", { text: "Instalar Nexus Worklog" }), " (no Edge, em Apps)."),
  ];
}

function showSteps() {
  const dlg = modal(h("h2", { text: "Instalar o Nexus" }),
    h("p", { class: "dialog-note", text: "Vira um app: abre direto da tela de início ou do menu, numa janela própria, sem as abas do navegador." }),
    h("ol", { class: "install-steps" }, ...steps()),
    h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-primary", text: "Entendi", onClick: () => dlg.close() })));
}

// Ajuda › Começar: o botão só aparece fora do app instalado.
export const canOfferInstall = () => !installed();

// Convite no canto da tela, depois do tour e longe do primeiro segundo do app.
export function offerInstall(me) {
  if (installed() || dismissed() || !me.tour_done_at) return;
  setTimeout(() => {
    if (card || installed() || (!deferred && !ios())) return;  // computador sem o pedido: fica pela Ajuda
    const phone = matchMedia("(max-width: 860px)").matches;
    const text = ios() || phone
      ? "Fica na tela de início como um app e abre direto, sem passar pelo navegador."
      : "Abre numa janela própria, sem as abas do navegador, direto do menu Iniciar ou do Dock.";
    card = h("section", { class: "idle-card install-card", role: "dialog", "aria-label": "Instalar o Nexus" },
      h("div", { class: "idle-head" },
        h("img", { class: "install-icon", src: "/img/icon-192.png", alt: "", width: "40", height: "40" }),
        h("p", {}, h("strong", { text: "Instale o Nexus" }), " " + text),
        h("button", { type: "button", class: "icon", title: "Agora não", "aria-label": "Agora não", onClick: dismiss }, icon("close"))),
      h("div", { class: "assist-actions" },
        h("button", { type: "button", class: "btn btn-primary btn-sm", text: ios() ? "Como instalar" : "Instalar", onClick: () => (ios() ? (dismiss(), showSteps()) : install()) }),
        h("button", { type: "button", class: "btn btn-ghost btn-sm", text: "Agora não", onClick: dismiss })));
    document.body.append(card);
  }, 4000);
}

// ---------------------------------------------------------- número no ícone --
// Atrasadas (Hoje e Tarefas sem filtro) + rotinas na hora (lembretes.js).
const counts = {};
export function appBadge(kind, n) {
  counts[kind] = n;
  if (!("setAppBadge" in navigator)) return;
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  (total ? navigator.setAppBadge(total) : navigator.clearAppBadge()).catch(() => {});
}

// ------------------------------------------------- atalhos e compartilhar --
// Compartilhado de outro app (share_target: /?title=&text=&url=). Sem sessão, o
// login perde a busca do endereço: guarda na aba e retoma depois de entrar.
export function stashShare() {
  const q = new URLSearchParams(location.search);
  if (q.get("compartilhado")) { history.replaceState(null, "", "/" + location.hash); return; } // já no cache (sw.js)
  const data = { title: q.get("title") || "", text: q.get("text") || "", url: q.get("url") || "" };
  if (!data.title && !data.text && !data.url) return;
  try { sessionStorage.setItem(SHARE_KEY, JSON.stringify(data)); } catch { /* sem armazenamento */ }
  history.replaceState(null, "", "/" + location.hash);
}

// O que o sw.js guardou (texto e fotos); consome e apaga.
async function fromCache() {
  if (!("caches" in window)) return null;
  try {
    const cache = await caches.open("nexus-compartilhado");
    const res = await cache.match("/compartilhado/dados");
    if (!res) return null;
    const data = await res.json();
    const files = [];
    for (let i = 0; i < data.fotos; i++) {
      const r = await cache.match(`/compartilhado/foto-${i}`);
      if (r) { const b = await r.blob(); files.push(new File([b], `compartilhada-${i + 1}`, { type: b.type })); }
    }
    await caches.delete("nexus-compartilhado");
    return { ...data, files };
  } catch { return null; }
}

// Título: o assunto (ou a 1ª linha). Descrição: o resto, se couber nos 300
// caracteres do campo; se não couber, o texto inteiro vai como anotação.
export async function sharedTask() {
  let data = await fromCache();
  if (!data) {
    try { data = JSON.parse(sessionStorage.getItem(SHARE_KEY) || "null"); sessionStorage.removeItem(SHARE_KEY); } catch { data = null; }
  }
  if (!data) return null;
  const files = data.files || [];
  if (!data.title.trim() && !data.text.trim() && !data.url.trim() && files.length)
    data.title = files.length > 1 ? `${files.length} fotos compartilhadas` : "Foto compartilhada";
  const text = data.text.trim(), url = data.url.trim();
  const lines = text.split(/\r?\n/);
  const title = (data.title.trim() || lines[0] || url || "Compartilhado").slice(0, 200);
  const rest = (data.title.trim() ? text : lines.slice(1).join("\n")).trim();
  const extra = [rest, url && !text.includes(url) ? url : ""].filter(Boolean).join("\n");
  return extra.length <= 300
    ? { title, description: extra.replace(/\s*\n\s*/g, " · "), files }
    : { title, description: url && !text.includes(url) ? url.slice(0, 300) : "", note: extra.slice(0, 2000), files };
}

// Atalho do ícone: #/hoje?acao=nova|rapido. Tira o parâmetro do endereço e devolve a ação.
export function takeShortcut() {
  const [path, query] = location.hash.split("?");
  const q = new URLSearchParams(query || "");
  const acao = q.get("acao");
  if (!acao) return null;
  q.delete("acao");
  history.replaceState(null, "", "/" + path + (q.toString() ? "?" + q : ""));
  return acao;
}
