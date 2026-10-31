// Peças de interface reutilizáveis: diálogos, avisos (toasts) e cópia.
// Substituem alert()/confirm() do navegador. Tudo criado via DOM (CSP).
import { api } from "./api.js";
import { h, icon } from "./dom.js";

// Diálogo modal criado na hora; some do DOM ao fechar.
export function modal(...children) {
  const dlg = h("dialog", {}, ...children);
  document.body.appendChild(dlg);
  dlg.addEventListener("close", () => dlg.remove());
  dlg.showModal();
  return dlg;
}

// Celular: menu que sobe de baixo (bottom sheet). items: [rótulo, ícone, fn];
// null é ignorado. Toque fora ou Esc fecha.
export function sheet(title, items) {
  const dlg = modal(
    h("span", { class: "sheet-handle", "aria-hidden": "true" }),
    title ? h("p", { class: "sheet-title", text: title }) : null,
    h("div", { class: "menu-list" }, ...items.filter(Boolean).map(([label, ic, fn]) =>
      h("button", { type: "button", class: "nav-btn", onClick: () => { dlg.close(); fn(); } }, icon(ic), h("span", { text: label })))));
  dlg.classList.add("sheet");
  dlg.addEventListener("click", (ev) => { if (ev.target === dlg) dlg.close(); });
  return dlg;
}

// Menu flutuante (Material 3) aberto num ponto da tela, como o clique direito
// num cartão. items: [rótulo, ícone, fn]; fecha com clique fora, Esc, rolagem
// ou Tab; setas andam entre os itens. Fica fora do zoom do <body>, então a
// posição é a do ponteiro em px da tela.
let menuClose = null;
export function popupMenu(x, y, items) {
  if (menuClose) menuClose();
  const back = document.activeElement;
  const menu = h("div", { class: "pop-menu", role: "menu" }, ...items.filter(Boolean).map(([label, ic, fn]) =>
    h("button", { type: "button", role: "menuitem", onClick: () => { close(); fn(); } }, icon(ic), h("span", { text: label }))));
  document.documentElement.append(menu);
  const r = menu.getBoundingClientRect();
  menu.style.left = Math.max(8, Math.min(x, innerWidth - r.width - 8)) + "px";
  menu.style.top = Math.max(8, Math.min(y, innerHeight - r.height - 8)) + "px";
  const btns = [...menu.querySelectorAll("button")];
  btns[0].focus();
  const onDown = (ev) => { if (!menu.contains(ev.target)) close(); };
  const onKey = (ev) => {
    const i = btns.indexOf(document.activeElement);
    if (ev.key === "Escape" || ev.key === "Tab") { ev.preventDefault(); ev.stopPropagation(); close(); if (back && back.focus) back.focus(); }
    else if (ev.key === "ArrowDown") { ev.preventDefault(); btns[(i + 1) % btns.length].focus(); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); btns[(i - 1 + btns.length) % btns.length].focus(); }
  };
  function close() {
    menu.remove(); menuClose = null;
    document.removeEventListener("pointerdown", onDown, true);
    document.removeEventListener("keydown", onKey, true);
    removeEventListener("scroll", close, true);
    removeEventListener("resize", close);
  }
  document.addEventListener("pointerdown", onDown, true);
  document.addEventListener("keydown", onKey, true);
  addEventListener("scroll", close, true);
  addEventListener("resize", close);
  menuClose = close;
}

// Quem pediu ao sistema menos movimento (as animações em JS também respeitam).
const calm = matchMedia("(prefers-reduced-motion: reduce)");
export const calmMotion = () => calm.matches;

// Último cartão ou linha tocado: de onde o detalhe da tarefa cresce no celular.
let pressed = null, pressedAt = 0;
document.addEventListener("pointerdown", (ev) => {
  pressed = ev.target.closest ? ev.target.closest(".card, .list-row, .search-row, .sum-row, .sugg-item") : null;
  pressedAt = Date.now();
}, true);

// Material 3, "container transform": a tela inteira nasce do retângulo do
// cartão tocado e cresce até ocupar a tela. Sem cartão de origem, sobe de leve.
export function growFrom(el) {
  if (calmMotion()) return;
  const from = pressed && pressed.isConnected && Date.now() - pressedAt < 4000 ? pressed : null;
  pressed = null;
  if (!from) {
    el.animate([{ opacity: 0, transform: "translateY(16px)" }, { opacity: 1, transform: "none" }], { duration: 250, easing: "cubic-bezier(.05, .7, .1, 1)" });
    return;
  }
  const r = from.getBoundingClientRect();
  const clip = `inset(${r.top}px ${innerWidth - r.right}px ${innerHeight - r.bottom}px ${r.left}px round 14px)`;
  el.animate([{ clipPath: clip }, { clipPath: "inset(0 round 0)" }], { duration: 320, easing: "cubic-bezier(.05, .7, .1, 1)" });
  el.firstElementChild?.animate([{ opacity: 0 }, { opacity: 0, offset: .25 }, { opacity: 1 }], { duration: 320 });
}

// Menu compacto (só ícones): em 861–1199 px sempre; em 1200–1739 px só
// enquanto o detalhe da tarefa está aberto ao lado (body.has-side).
const railAlways = matchMedia("(min-width: 861px) and (max-width: 1199px)");
const railWithSide = matchMedia("(min-width: 1200px) and (max-width: 1739px)");
let peek = false; // mouse sobre o menu compacto: abre por cima do conteúdo
export function syncRail() {
  const b = document.body;
  const rail = railAlways.matches || (railWithSide.matches && b.classList.contains("has-side"));
  b.classList.toggle("rail", rail && !peek);
  b.classList.toggle("rail-peek", rail && peek);
}
railAlways.addEventListener("change", syncRail);
railWithSide.addEventListener("change", syncRail);

// Menu compacto com mouse: parar sobre ele abre o menu inteiro por cima da
// tela (o conteúdo não se mexe); tirar o mouse volta aos ícones.
export function initRailPeek() {
  if (!matchMedia("(hover: hover)").matches) return;
  const side = document.querySelector(".sidebar");
  let timer = null;
  const set = (on) => { clearTimeout(timer); if (peek !== on) { peek = on; syncRail(); } };
  side.addEventListener("mouseenter", () => {
    if (!document.body.matches(".rail, .rail-peek")) return;
    clearTimeout(timer);
    timer = setTimeout(() => set(true), 150); // passar de raspão não abre
  });
  side.addEventListener("mouseleave", () => set(false));
  side.addEventListener("click", (ev) => { if (ev.target.closest("a[href]")) set(false); }); // escolheu: fecha
}

// Dicas dos botões só com ícone (Material 3, "plain tooltip"): no lugar da
// dica nativa do navegador, que demora e é pequena. Aparece ao passar o mouse
// ou ao chegar pelo teclado. Só em aparelhos com mouse.
export function initTooltips() {
  if (!matchMedia("(hover: hover)").matches) return;
  const SEL = "button.icon, .icon-btn, button.column-toggle, body.rail .sidebar .nav a, body.rail .sidebar .nav-link, body.rail .who-me";
  const tip = h("div", { class: "tooltip", "aria-hidden": "true" });
  document.documentElement.append(tip);
  let cur = null, timer = null;
  const hide = () => { clearTimeout(timer); cur = null; tip.classList.remove("show"); };
  const place = (el) => {
    if (cur !== el || !el.isConnected) return;
    tip.textContent = el.dataset.tip;
    tip.classList.add("show");
    const r = el.getBoundingClientRect(), t = tip.getBoundingClientRect();
    if (el.closest(".sidebar")) { // menu compacto: a dica sai à direita do ícone
      tip.style.left = r.right + 8 + "px";
      tip.style.top = r.top + r.height / 2 - t.height / 2 + "px";
      return;
    }
    const below = r.bottom + 6 + t.height <= innerHeight - 4;
    tip.style.left = Math.max(4, Math.min(r.left + r.width / 2 - t.width / 2, innerWidth - t.width - 4)) + "px";
    tip.style.top = (below ? r.bottom + 6 : r.top - 6 - t.height) + "px";
  };
  const target = (node) => {
    const el = node && node.closest ? node.closest(SEL) : null;
    if (!el) return null;
    if (el.hasAttribute("title")) { // a nativa sairia junto; o texto vai para o leitor de tela também
      el.dataset.tip = el.getAttribute("title");
      if (!el.hasAttribute("aria-label")) el.setAttribute("aria-label", el.dataset.tip);
      el.removeAttribute("title");
    }
    if (!el.dataset.tip && el.closest(".sidebar")) el.dataset.tip = el.querySelector("span:not(.nav-badge)")?.textContent || "";
    return el.dataset.tip ? el : null;
  };
  document.addEventListener("mouseover", (ev) => {
    const el = target(ev.target);
    if (el === cur) return;
    hide();
    if (!el) return;
    cur = el;
    timer = setTimeout(() => place(el), 350);
  });
  document.addEventListener("focusin", (ev) => {
    const el = target(ev.target);
    if (!el || !el.matches(":focus-visible")) return;
    hide(); cur = el; place(el);
  });
  document.addEventListener("focusout", hide);
  document.addEventListener("pointerdown", hide, true);
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") hide(); });
  addEventListener("scroll", hide, true);
}

// Número no item do menu (ex.: tarefas atrasadas); 0 apaga.
export function navBadge(view, n, label) {
  for (const a of document.querySelectorAll(`#tabbar [data-view="${view}"], #nav [data-view="${view}"]`)) {
    let b = a.querySelector(".nav-badge");
    if (!n) { if (b) b.remove(); continue; }
    if (!b) { b = h("span", { class: "nav-badge" }); (a.querySelector(".tab-ind") || a).append(b); }
    b.textContent = n > 99 ? "99+" : String(n);
    b.setAttribute("aria-label", label || String(n));
  }
}

// Confirmação com botões próprios. Resolve true/false.
export function confirmDialog({ title, text, confirm = "Confirmar", danger = false }) {
  return new Promise((resolve) => {
    let ok = false;
    const dlg = modal(
      h("h2", { text: title }),
      text ? h("p", { text }) : null,
      h("div", { class: "dialog-actions" },
        h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
        h("button", {
          type: "button", class: "btn " + (danger ? "btn-danger" : "btn-primary"), text: confirm,
          onClick: () => { ok = true; dlg.close(); },
        }))
    );
    dlg.addEventListener("close", () => resolve(ok));
  });
}

// Aviso curto no rodapé. opts: { error, action: "Desfazer", onAction }
export function toast(message, opts = {}) {
  const box = document.getElementById("toasts");
  if (!box) return;
  // Uma ação (action/onAction) ou várias (actions: [[rótulo, fn], ...]).
  const actions = opts.actions || (opts.action ? [[opts.action, opts.onAction]] : []);
  const long = String(message).length > 48; // não cabe numa linha de pílula
  const el = h("div", { class: "toast" + (opts.error ? " error" : "") + (long ? " long" : "") + (actions.length ? " has-actions" : ""), role: "status",
    title: long ? message : null }, h("span", { text: message }));
  for (const [label, fn] of actions) {
    el.append(h("button", {
      type: "button", class: "btn btn-ghost btn-sm", text: label,
      onClick: async () => { el.remove(); await fn?.(); },
    }));
  }
  box.append(el);
  setTimeout(() => el.remove(), actions.length ? 9000 : 3500);
}

// Formulário: o botão de envio fica desabilitado até o handler terminar
// (duplo clique não manda duas vezes). Uso: addEventListener("submit", busy(async (ev) => {...})).
export function busy(fn) {
  return async (ev) => {
    if (ev) ev.preventDefault(); // nunca o envio nativo do formulário
    const form = ev && ev.target;
    if (form && form.dataset) {
      if (form.dataset.busy) return;
      form.dataset.busy = "1";
    }
    const btns = form && form.querySelectorAll ? [...form.querySelectorAll("[type=submit]")] : [];
    btns.forEach((b) => { b.disabled = true; });
    try { return await fn(ev); } finally {
      if (form && form.dataset) delete form.dataset.busy;
      btns.forEach((b) => { b.disabled = false; });
    }
  };
}

// Só mensagens da API (que têm status) vão para a tela; erro de JavaScript
// (em inglês, técnico) vira a mensagem genérica.
export function errorToast(e, fallback = "Algo deu errado.") {
  toast((e && "status" in e && e.message) || fallback, { error: true });
}

// Desfaz a ação mais recente de um item (usa o histórico do backend).
export async function undoLatest(entity, entityId, onDone) {
  try {
    const rows = await api.get(`/history?limit=1&entity=${entity}&entity_id=${entityId}`);
    if (!rows.length || !rows[0].can_undo) throw new Error("Nada para desfazer.");
    await api.post(`/history/${rows[0].id}/undo`);
    toast("Desfeito.");
    onDone && onDone();
  } catch (e) {
    errorToast(e, "Não foi possível desfazer.");
  }
}

// Bloco de código/valor com botão de copiar.
export function codeBox(text) {
  const btn = h("button", { type: "button", class: "icon-btn copy", title: "Copiar", "aria-label": "Copiar" }, icon("copy"));
  btn.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(text); toast("Copiado."); }
    catch { toast("Selecione e copie manualmente.", { error: true }); }
  });
  return h("div", { class: "codebox" }, text, btn);
}

export function warnBox(text) {
  return h("div", { class: "warnbox" }, icon("alert"), h("span", { text }));
}
