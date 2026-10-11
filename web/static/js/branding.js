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
  return brand;
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
