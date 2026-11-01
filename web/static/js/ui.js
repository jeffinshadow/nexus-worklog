// Peças de interface reutilizáveis: diálogos, avisos (toasts) e cópia.
// Substituem alert()/confirm() do navegador. Tudo criado via DOM (CSP).
import { api } from "./api.js";
import { h, icon } from "./dom.js";

// Diálogo modal criado na hora; some do DOM ao fechar. O primeiro título (h2)
// vira o nome do diálogo para o leitor de tela.
let dlgSeq = 0;
export function modal(...children) {
  const dlg = h("dialog", {}, ...children);
  const title = dlg.querySelector("h2");
  if (title) {
    if (!title.id) title.id = "dlg-t" + ++dlgSeq;
    dlg.setAttribute("aria-labelledby", title.id);
  }
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
  if (title) dlg.setAttribute("aria-label", title);
  dlg.addEventListener("click", (ev) => { if (ev.target === dlg) dlg.close(); });
  return dlg;
}

// Menu flutuante (Material 3) aberto num ponto da tela, como o clique direito
// num cartão. items: [rótulo, ícone, fn]; fecha com clique fora, Esc, rolagem
// ou Tab; setas andam entre os itens. Fica fora do zoom do <body>, então a
// posição é a do ponteiro em px da tela.
let menuClose = null;
// anchorTop: o topo do botão que abriu; sem espaço embaixo, o menu abre acima dele (não o cobre).
export function popupMenu(x, y, items, anchorTop = null) {
  if (menuClose) menuClose();
  const back = document.activeElement;
  const menu = h("div", { class: "pop-menu", role: "menu" }, ...items.filter(Boolean).map(([label, ic, fn]) =>
    h("button", { type: "button", role: "menuitem", onClick: () => { close(); if (back && back.isConnected && back.focus) back.focus(); fn(); } }, icon(ic), h("span", { text: label }))));
  document.documentElement.append(menu);
  const r = menu.getBoundingClientRect();
  menu.style.left = Math.max(8, Math.min(x, innerWidth - r.width - 8)) + "px";
  const top = anchorTop !== null && y + r.height + 8 > innerHeight ? anchorTop - r.height - 4 : y;
  menu.style.top = Math.max(8, Math.min(top, innerHeight - r.height - 8)) + "px";
  const btns = [...menu.querySelectorAll("button")];
  btns[0].focus();
  const onDown = (ev) => { if (!menu.contains(ev.target)) close(); };
  const onKey = (ev) => {
    const i = btns.indexOf(document.activeElement);
    if (ev.key === "Escape" || ev.key === "Tab") { ev.preventDefault(); ev.stopPropagation(); close(); if (back && back.focus) back.focus(); }
    else if (ev.key === "ArrowDown") { ev.preventDefault(); btns[(i + 1) % btns.length].focus(); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); btns[(i - 1 + btns.length) % btns.length].focus(); }
  };
  // Fechou sozinho (rolagem, outra janela) com o foco nele: volta para quem abriu.
  const opened = Date.now();
  const closeBack = (ev) => {
    if (ev && ev.type === "scroll" && Date.now() - opened < 400) return; // a rolagem que trouxe o cartão para a vista
    const had = menu.contains(document.activeElement); close(); if (had && back && back.isConnected && back.focus) back.focus({ preventScroll: true });
  };
  function close() {
    menu.remove(); menuClose = null;
    document.removeEventListener("pointerdown", onDown, true);
    document.removeEventListener("keydown", onKey, true);
    removeEventListener("scroll", closeBack, true);
    removeEventListener("resize", closeBack);
  }
  document.addEventListener("pointerdown", onDown, true);
  document.addEventListener("keydown", onKey, true);
  addEventListener("scroll", closeBack, true);
  addEventListener("resize", closeBack);
  menuClose = close;
}

// Botão ⋮: no celular, a folha de baixo; no computador, o menu junto do botão.
export function actionMenu(btn, title, items) {
  if (matchMedia("(max-width: 860px)").matches) { sheet(title, items); return; }
  const r = btn.getBoundingClientRect();
  popupMenu(r.right - 220, r.bottom + 4, items, r.top);
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
    if (cur !== el || !el.isConnected || !el.matches(SEL)) return; // ex.: o menu compacto abriu inteiro
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

// Número no item do menu (ex.: tarefas atrasadas); 0 apaga. No celular, o que
// não está na barra de baixo (Admin, por exemplo) acende o número também em
// "Mais" e no item dentro dela.
const badges = new Map();
export function navBadge(view, n, label) {
  badges.set(view, [n, label]);
  for (const a of document.querySelectorAll(`#tabbar [data-view="${view}"], #nav [data-view="${view}"], #view-mais [data-view="${view}"]`)) paintBadge(a, n, label);
  let more = 0;
  for (const [v, [k]] of badges) {
    const tab = document.querySelector(`#tabbar [data-view="${v}"]`);
    if (k && (!tab || tab.classList.contains("hidden"))) more += k;
  }
  const tab = document.querySelector('#tabbar [data-view="mais"]');
  if (tab) paintBadge(tab, more, more === 1 ? "1 aviso em Mais" : `${more} avisos em Mais`);
}

// A tela "Mais" é montada de novo a cada visita: repõe os números.
export function repaintBadges() {
  for (const [v, [n, label]] of badges) navBadge(v, n, label);
}

function paintBadge(a, n, label) {
  let b = a.querySelector(".nav-badge");
  if (!n) { if (b) b.remove(); return; }
  if (!b) { b = h("span", { class: "nav-badge" }); (a.querySelector(".tab-ind") || a).append(b); }
  b.textContent = n > 99 ? "99+" : String(n);
  b.setAttribute("aria-label", label || String(n));
}

// Confirmação com botões próprios. Resolve true/false. `dismiss`: o botão de sair
// (ex.: "Voltar" quando a ação já é "Cancelar tarefa", para não ter dois "Cancelar").
export function confirmDialog({ title, text, confirm = "Confirmar", danger = false, dismiss = "Cancelar" }) {
  return new Promise((resolve) => {
    let ok = false;
    const dlg = modal(
      h("h2", { text: title }),
      text ? h("p", { text }) : null,
      h("div", { class: "dialog-actions" },
        h("button", { type: "button", class: "btn btn-text", text: dismiss, onClick: () => dlg.close() }),
        h("button", {
          type: "button", class: "btn " + (danger ? "btn-danger" : "btn-primary"), text: confirm,
          onClick: () => { ok = true; dlg.close(); },
        }))
    );
    dlg.addEventListener("close", () => resolve(ok));
  });
}

// Aviso curto no rodapé. opts: { error, action: "Desfazer", onAction }
// Com ação, fica 12 s e pausa enquanto o mouse ou o foco estão nele (só some
// depois que o foco sai). Não puxa o foco: "Desfazer" também vai pelo Ctrl+Z.
let undoAction = null;
export function toast(message, opts = {}) {
  const box = document.getElementById("toasts");
  if (!box) return;
  // Uma ação (action/onAction) ou várias (actions: [[rótulo, fn], ...]).
  const actions = opts.actions || (opts.action ? [[opts.action, opts.onAction]] : []);
  const long = String(message).length > 48; // não cabe numa linha de pílula
  const el = h("div", { class: "toast" + (opts.error ? " error" : "") + (long ? " long" : "") + (actions.length ? " has-actions" : ""), role: "status",
    title: long ? message : null }, h("span", { text: message }));
  let undo = null;
  const remove = () => {
    // O foco estava num botão do aviso: volta para o conteúdo, não para o <body>.
    if (el.contains(document.activeElement)) document.getElementById("main")?.focus({ preventScroll: true });
    el.remove();
    if (undoAction === undo) undoAction = null;
  };
  for (const [label, fn] of actions) {
    const run = async () => { remove(); await fn?.(); };
    const isUndo = /^Desfazer/.test(label);
    if (isUndo) undo = run;
    el.append(h("button", {
      type: "button", class: "btn btn-ghost btn-sm", text: label,
      "aria-keyshortcuts": isUndo ? "Control+Z" : null, onClick: run,
    }));
  }
  if (undo) { undoAction = undo; el.append(h("span", { class: "sr-only", text: "Ctrl+Z desfaz." })); }
  box.append(el);
  const ms = actions.length ? 12000 : 3500;
  let timer = setTimeout(remove, ms), hover = false;
  const hold = () => { clearTimeout(timer); timer = null; };
  const resume = () => { if (!timer && !hover && !el.contains(document.activeElement)) timer = setTimeout(remove, 4000); };
  el.addEventListener("pointerenter", () => { hover = true; hold(); });
  el.addEventListener("pointerleave", () => { hover = false; resume(); });
  el.addEventListener("focusin", hold);
  el.addEventListener("focusout", (ev) => { if (!el.contains(ev.relatedTarget)) setTimeout(resume); });
}
// Ctrl+Z (fora de campos de texto) aperta o "Desfazer" do aviso que está na tela.
document.addEventListener("keydown", (ev) => {
  if (!undoAction || ev.key.toLowerCase() !== "z" || !(ev.ctrlKey || ev.metaKey) || ev.shiftKey || ev.altKey) return;
  const a = document.activeElement;
  if (a && (/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) || a.isContentEditable)) return; // o Ctrl+Z do próprio campo
  if (document.querySelector("dialog[open]:not(.side)")) return;
  ev.preventDefault();
  const back = keepFocus(); // a lista é redesenhada: o foco volta para onde estava
  Promise.resolve(undoAction()).then(back);
});

// Abas (role="tab"): as setas, Home e End andam entre elas e já abrem a escolhida,
// como o leitor de tela anuncia. Vale para todas as telas com abas.
document.addEventListener("keydown", (ev) => {
  if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(ev.key) || ev.altKey || ev.ctrlKey || ev.metaKey) return;
  const tab = ev.target.closest ? ev.target.closest('[role="tab"]') : null;
  const list = tab && tab.closest('[role="tablist"]');
  if (!list) return;
  const tabs = [...list.querySelectorAll('[role="tab"]')].filter((t) => !t.disabled && t.offsetParent);
  const i = tabs.indexOf(tab), n = tabs.length;
  const j = ev.key === "Home" ? 0 : ev.key === "End" ? n - 1 : (i + (ev.key === "ArrowRight" ? 1 : -1) + n) % n;
  ev.preventDefault();
  tabs[j].focus();
  tabs[j].click();
});

// Atalhos de uma tecla (n, h, t, s...): ligados por padrão; dá para desligar
// em Configurações (vale para este aparelho).
const KEYS_KEY = "nexus.atalhos";
export const singleKeysOn = () => { try { return localStorage.getItem(KEYS_KEY) !== "off"; } catch { return true; } };
export function setSingleKeys(on) {
  try { localStorage.setItem(KEYS_KEY, on ? "on" : "off"); } catch { /* sem armazenamento: vale só agora */ }
}

// Foco que não se perde quando a lista é redesenhada: depois de render(),
// volta ao controle de mesmo nome (aria-label) dentro de scope.
// Anúncio para o leitor de tela numa região viva que não é recriada com a tela.
let liveRegion = null;
export function announce(text) {
  if (!liveRegion) { liveRegion = h("div", { class: "sr-only", role: "status", "aria-live": "polite" }); document.body.append(liveRegion); }
  liveRegion.textContent = "";
  setTimeout(() => { liveRegion.textContent = text; }, 60);
}

// Setas de período (dia no Hoje, semana, mês, Equipe): a tela se redesenha e o
// botão focado some. Espera o rótulo mudar, devolve o foco à mesma seta (ou à
// outra, se esta ficou desabilitada no limite) e anuncia o período novo.
document.addEventListener("click", (ev) => {
  const btn = ev.target.closest && ev.target.closest(".day-nav button[aria-label]");
  if (!btn) return;
  const label = btn.getAttribute("aria-label");
  const oldNav = btn.closest(".day-nav"), oldLab = oldNav.querySelector(".day-nav-label"), oldText = oldLab?.textContent;
  const index = [...document.querySelectorAll(".day-nav")].indexOf(oldNav);
  const t0 = performance.now();
  const tick = () => {
    if (performance.now() - t0 > 4000) return;
    const navs = [...document.querySelectorAll(".day-nav")];
    const nav = oldNav.isConnected ? oldNav : navs.filter((n) => n.querySelector(`button[aria-label="${CSS.escape(label)}"]`))[0] || navs[index];
    const lab = nav && nav.querySelector(".day-nav-label");
    if (!lab || lab.textContent === oldText) { requestAnimationFrame(tick); return; }
    const a = document.activeElement;
    if (!a || a === document.body || !a.isConnected || a === btn) {
      const same = nav.querySelector(`button[aria-label="${CSS.escape(label)}"]`);
      const el = same && !same.disabled ? same : nav.querySelector("button:not([disabled])");
      if (el) el.focus();
    }
    if (lab !== oldLab || !lab.hasAttribute("aria-live")) announce(lab.textContent);  // rótulo recriado: a região viva nova não fala
  };
  requestAnimationFrame(tick);
});

export function refocusBy(scope, label) {
  if (!scope || !label) return;
  const el = scope.querySelector(`[aria-label="${CSS.escape(label)}"]`);
  if (el) el.focus();
}

// Ação que redesenha a tarefa sem tirá-la da lista (Aguardando, cronômetro,
// desfazer): guarda o controle focado e, depois do redesenho, volta para ele
// (mesmo nome; o par Iniciar/Parar do cronômetro; ou o cartão da mesma tarefa).
// Se a tarefa saiu, cai na que ficou no lugar (focusAfterRemoval).
const TIMER_SWAP = [[/^Iniciar o cronômetro em /, "Parar o cronômetro de "], [/^Parar o cronômetro de /, "Iniciar o cronômetro em "]];
export function keepFocus() {
  const a = document.activeElement;
  // Foco no painel/janela da tarefa (ex.: "Mais ações" > Aguardando): volta para o mesmo controle lá.
  const dlg = a && a.closest ? a.closest("dialog.task-dialog") : null;
  const item = a && a.closest ? a.closest("#main [data-task-id]") : null;
  const id = item && item.dataset.taskId;
  const label = a && a.getAttribute ? a.getAttribute("aria-label") : null;
  const removed = focusAfterRemoval();
  return () => {
    const cur = document.activeElement;
    if (cur && cur !== document.body && cur !== document.getElementById("main") && cur.isConnected) return; // já tem lugar (ex.: um diálogo)
    if (dlg && dlg.isConnected && dlg.open) {
      const el = (label && dlg.querySelector(`[aria-label="${CSS.escape(label)}"]`)) || dlg.querySelector(".task-appbar button");
      if (el) { el.focus(); return; }
    }
    const box = id && document.querySelector(`#main [data-task-id="${CSS.escape(id)}"]`);
    if (!box) { removed(); return; }
    const names = label ? [label, ...TIMER_SWAP.filter(([re]) => re.test(label)).map(([re, to]) => label.replace(re, to))] : [];
    const el = names.map((n) => box.querySelector(`[aria-label="${CSS.escape(n)}"]`)).find(Boolean)
      || box.querySelector(".card-open, button") || box;
    el.focus();
  };
}

// Tarefa que sai da lista (concluir, excluir) com o foco nela: guarda a posição
// e, depois do redesenho, foca a que ficou no lugar (ou a anterior, ou o título).
export function focusAfterRemoval() {
  const a = document.activeElement;
  const item = a && a.closest ? a.closest("#main [data-task-id]") : null;
  if (!item) return () => {};
  const i = [...document.querySelectorAll("#main [data-task-id]")].indexOf(item);
  return () => {
    if (document.activeElement && document.activeElement !== document.body && document.activeElement.isConnected) return; // já foi para outro lugar (ex.: um diálogo)
    const items = [...document.querySelectorAll("#main [data-task-id]")].filter((el) => el.offsetParent);
    const next = items[Math.min(i, items.length - 1)];
    const target = next ? next.querySelector(".card-open, button") || next : document.getElementById("page-title");
    if (target) target.focus();
  };
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
export function errorToast(e, fallback = "Não foi possível concluir.") {
  toast((e && "status" in e && e.message) || fallback, { error: true });
}

// Desfaz a ação mais recente de um item (usa o histórico do backend).
export async function undoLatest(entity, entityId, onDone) {
  try {
    const rows = await api.get(`/history?limit=1&entity=${entity}&entity_id=${entityId}`);
    if (!rows.length || !rows[0].can_undo) throw new Error("Nada para desfazer.");
    await api.post(`/history/${rows[0].id}/undo`);
    toast("Desfeito.");
    if (onDone) await onDone();
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
