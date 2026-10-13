// Identidade visual configurável pelo admin: logo + duas linhas do lockup.
// Aplica em todo .lockup da página (menu, login, troca de senha).
const PADRAO = { line1: "nexus", line2: "worklog", logo: null };
const DRAGAO = "/img/dragon-mark.svg";

export function applyBranding(b) {
  const brand = { ...PADRAO, ...(b || {}) };
  for (const el of document.querySelectorAll(".lockup")) {
    const img = el.querySelector(".lockup-mark");
    if (img) img.src = brand.logo || DRAGAO;
    const spans = el.querySelectorAll(".lockup-type span");
    if (spans[0]) spans[0].textContent = brand.line1;
    if (spans[1]) spans[1].textContent = brand.line2 || "";
    const nome = [brand.line1, brand.line2].filter(Boolean).join(" ");
    if (el.tagName === "A") el.setAttribute("aria-label", `${nome} — Hoje`);
  }
  fitSidebarLockup();
  return brand;
}

// No menu, o lockup inteiro (símbolo + texto) cresce até ocupar a largura
// útil, qualquer que seja o texto escolhido pelo admin. Refaz quando o menu
// aparece (o app nasce oculto até confirmar a sessão) e quando a imagem ou a
// fonte terminam de carregar (mudam a largura medida).
let lockupObserver = null;
function fitSidebarLockup() {
  const el = document.querySelector(".sidebar > .lockup");
  if (!el) return;
  const fit = () => {
    el.style.removeProperty("--lock-fs");
    const box = el.parentElement, cb = getComputedStyle(box), ce = getComputedStyle(el);
    const avail = box.clientWidth - parseFloat(cb.paddingLeft) - parseFloat(cb.paddingRight)
      - parseFloat(ce.paddingLeft) - parseFloat(ce.paddingRight);
    const kids = [...el.children];
    const used = kids.reduce((sum, k) => sum + k.offsetWidth, 0) + parseFloat(ce.columnGap || 0) * (kids.length - 1);
    if (avail > 0 && used > 0) el.style.setProperty("--lock-fs", `${Math.min(avail / used, 3).toFixed(3)}rem`);
  };
  fit();
  if (!lockupObserver && window.ResizeObserver) {
    lockupObserver = new ResizeObserver(fit);
    lockupObserver.observe(el.parentElement);
  }
  const img = el.querySelector(".lockup-mark");
  if (img && !img.complete) img.addEventListener("load", fit, { once: true });
  if (document.fonts) document.fonts.ready.then(fit);
}

export async function loadBranding() {
  try {
    const r = await fetch("/api/branding", { credentials: "same-origin" });
    if (!r.ok) return applyBranding(PADRAO);
    return applyBranding(await r.json());
  } catch {
    return applyBranding(PADRAO);
  }
}
