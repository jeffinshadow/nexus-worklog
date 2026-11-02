// Pacotes de rotina por área: um ponto de partida pronto (manutenção predial,
// suporte de TI, atendimento...). A pessoa escolhe a área, marca os itens e o
// Nexus cria o projeto (com ícone) e as rotinas com agenda e horário. Depois,
// tudo se edita como qualquer rotina ou projeto. Usado no tour, no + das
// rotinas e nas telas vazias de Rotinas e Projetos.
import { api } from "./api.js";
import { h, icon, clear } from "./dom.js";
import { busy, errorToast, modal, toast } from "./ui.js";
import { PALETA, invalidateProjects, projTile } from "./projects.js";
import { refreshReminders } from "./lembretes.js";

const DIAS = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const ORDEM = [1, 2, 3, 4, 5, 6, 0];

// "Dias úteis · 08:00", "Toda seg, qui · 09:00", "Todo mês, dia 1 · 10:00".
function packAgenda(i) {
  let txt = "Dias úteis";
  if (i.freq === "weekly") txt = "Toda " + ORDEM.filter((b) => (i.weekdays >> b) & 1).map((b) => DIAS[b]).join(", ");
  else if (i.freq === "monthly") txt = i.month_day >= 31 ? "Todo mês, no último dia" : `Todo mês, dia ${i.month_day}`;
  else if (i.freq === "interval") txt = `A cada ${i.interval_days} dias`;
  return txt + (i.remind_at ? ` · ${i.remind_at.slice(0, 5)}` : "");
}

export const loadPacks = () => api.get("/routine-packs");

// O ícone da área num quadradinho (a mesma peça dos projetos).
const tile = (p, extra = "proj-tile-sm") => projTile({ icon: p.icon, color: PALETA[0] }, extra);

// Botões das áreas. onPick(pack); selected: id da área marcada (aria-pressed).
export function packAreas(packs, onPick, selected = null) {
  return h("div", { class: "pack-areas" }, ...packs.map((p) =>
    h("button", { type: "button", class: "proj-ex-btn pack-area", "aria-pressed": String(p.id === selected), onClick: () => onPick(p) },
      tile(p), p.name)));
}

// Itens do pacote para marcar: o projeto e cada rotina (com agenda e horário).
// As que a pessoa já tem (mesmo nome) aparecem marcadas como "você já tem".
// onChange(n): quantas rotinas novas estão marcadas.
export function packPicker(pack, onChange = () => {}) {
  const proj = h("input", { type: "checkbox", checked: "" });
  const rows = pack.items.map((i) => {
    const cb = h("input", { type: "checkbox" });
    cb.checked = !i.exists;
    cb.addEventListener("change", () => onChange(count()));
    const sub = packAgenda(i) + (i.require_note ? " · pede evidência" : "") + (i.exists ? " · você já tem" : "");
    const text = h("span", { class: "label" }, i.label, h("small", { text: sub }));
    // Já existe (mesmo nome): um ✓ no lugar da caixa; aplicar pula essa.
    const el = i.exists ? h("div", { class: "check-row pack-item pack-have" }, icon("check"), text) : h("label", { class: "check-row pack-item" }, cb, text);
    return { i, cb, el };
  });
  const count = () => rows.filter((r) => r.cb.checked && !r.i.exists).length;
  const el = h("div", { class: "pack-picker" },
    h("label", { class: "check-row pack-proj" }, proj, tile(pack),
      h("span", { class: "label" }, `Projeto “${pack.project.name}”`, h("small", { text: "Para agrupar as tarefas desta área (se já existir, aproveita)" }))),
    h("p", { class: "pack-sub", text: "Rotinas" }),
    ...rows.map((r) => r.el));
  return {
    el,
    count,
    value: () => ({ items: rows.filter((r) => r.cb.checked && !r.i.exists).map((r) => r.i.key), project: proj.checked }),
  };
}

// Aplica e avisa ("3 rotinas e o projeto X criados"). Devolve a resposta.
export async function applyPack(pack, sel) {
  const res = await api.post(`/routine-packs/${pack.id}/apply`, sel);
  invalidateProjects();
  refreshReminders();
  const n = res.created.length;
  const partes = [n ? `${n} rotina${n === 1 ? "" : "s"}` : null, res.project && res.project.created ? `o projeto ${res.project.name}` : null].filter(Boolean);
  toast(partes.length ? `Criado${partes.length > 1 || n > 1 ? "s" : ""}: ${partes.join(" e ")}. Tudo se edita depois.` : "Nada novo: você já tinha esses itens.");
  return res;
}

// Diálogo "Usar um pacote": escolher a área e, depois, os itens.
// onDone(res) depois de criar.
export function openPacks(onDone) {
  const body = h("div", { class: "pack-body" });
  const dlg = modal(h("h2", { text: "Usar um pacote" }), body);
  dlg.classList.add("pack-dialog");
  const close = h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() });

  function areas(packs) {
    clear(body);
    body.append(
      h("p", { class: "dialog-note pack-intro", text: "Escolha a sua área. Você marca o que quer e o Nexus cria o projeto e as rotinas, com agenda e horário. Depois, tudo se edita." }),
      h("div", { class: "pack-list" }, ...packs.map((p) =>
        h("button", { type: "button", class: "pack-card", onClick: () => items(packs, p) }, tile(p, ""),
          h("span", { class: "pack-card-text" }, h("strong", { text: p.name }), h("small", { text: p.description }))))),
      h("div", { class: "dialog-actions" }, close));
    dlg.querySelector("h2").textContent = "Usar um pacote";
    body.querySelector(".pack-card")?.focus();
  }

  function items(packs, pack) {
    clear(body);
    dlg.querySelector("h2").textContent = pack.name;
    const ok = h("button", { type: "submit", class: "btn btn-primary" });
    const label = (n) => { ok.textContent = n ? `Criar ${n} rotina${n === 1 ? "" : "s"}` : "Criar"; };
    const picker = packPicker(pack, label);
    label(picker.count());
    const form = h("form", {}, h("p", { class: "dialog-note pack-intro", text: pack.description }), picker.el,
      h("div", { class: "dialog-actions" },
        h("button", { type: "button", class: "btn btn-text", text: "Voltar", onClick: () => areas(packs) }),
        h("div", { class: "spacer" }), close, ok));
    form.classList.add("pack-items"); // no celular estreito, só Voltar e Criar (cabem numa linha)
    form.addEventListener("submit", busy(async () => {
      const sel = picker.value();
      if (!sel.items.length && !sel.project) { toast("Marque pelo menos um item.", { error: true }); return; }
      try {
        const res = await applyPack(pack, sel);
        dlg.close();
        onDone && onDone(res);
      } catch (e) { errorToast(e, "Não foi possível criar."); }
    }));
    body.append(form);
    ok.focus();
  }

  body.append(h("p", { class: "dialog-note", text: "Carregando…" }));
  loadPacks().then(areas).catch((e) => { dlg.close(); errorToast(e, "Não foi possível carregar os pacotes."); });
  return dlg;
}

// Atalho para as telas vazias: um botão que abre o diálogo.
export function packButton(onDone, text = "Usar um pacote da sua área") {
  return h("button", { type: "button", class: "btn btn-ghost pack-btn", onClick: () => openPacks(onDone) }, icon("add"), text);
}
