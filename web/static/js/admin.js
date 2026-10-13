import { api } from "./api.js";
import { h, icon, clear, field } from "./dom.js";
import { codeBox, confirmDialog, errorToast, modal, toast } from "./ui.js";
import { applyBranding } from "./branding.js";
import * as board from "./board.js";
import * as dashboard from "./dashboard.js";
import * as reports from "./reports.js";

const SUBVIEWS = [
  { key: "board", label: "Tarefas" },
  { key: "dashboard", label: "Dashboard" },
  { key: "reports", label: "Relatórios" },
];

// Admin: usuários (visão somente leitura + convite/reset) e identidade visual.
export async function mount(root) {
  clear(root);
  const seg = h("div", { class: "seg", role: "tablist" });
  const body = h("div");
  const abas = [["usuarios", "Usuários", mountUsers], ["identidade", "Identidade visual", mountBranding]];
  for (const [key, label, fn] of abas) {
    seg.append(h("button", {
      type: "button", class: "chip-btn", role: "tab", "aria-selected": key === "usuarios" ? "true" : "false", text: label,
      onClick: () => {
        for (const b of seg.children) b.setAttribute("aria-selected", b.textContent === label ? "true" : "false");
        fn(body);
      },
    }));
  }
  root.append(seg, body);
  await mountUsers(body);
}

async function mountUsers(root) {
  clear(root);
  const users = await api.get("/admin/users");
  if (!users.length) {
    root.append(h("p", { class: "empty", text: "Nenhum usuário." }));
    return;
  }
  const emailById = new Map(users.map((u) => [String(u.id), u.email]));

  const select = h(
    "select",
    {},
    ...users.map((u) => h("option", { value: u.id }, `${u.display_name ? u.display_name + " · " : ""}${u.email}${u.role === "admin" ? " (admin)" : ""}`))
  );

  const resetBtn = h("button", { type: "button", class: "btn btn-danger", text: "Redefinir senha", onClick: onReset });
  const inviteBtn = h("button", { type: "button", class: "btn btn-primary", onClick: onInvite }, icon("add"), "Novo usuário");

  let active = "board";
  const subtabs = h(
    "div",
    { class: "seg seg-sm", role: "tablist" },
    ...SUBVIEWS.map((s) =>
      h("button", {
        type: "button", class: "chip-btn", role: "tab",
        text: s.label,
        "aria-selected": s.key === active ? "true" : "false",
        onClick: () => {
          active = s.key;
          for (const b of subtabs.children)
            b.setAttribute("aria-selected", b.textContent === s.label ? "true" : "false");
          renderCurrent();
        },
      })
    )
  );

  const content = h("div", {});
  root.append(
    h(
      "div",
      { class: "admin-bar" },
      field("Usuário", select),
      resetBtn,
      inviteBtn,
      h("button", { type: "button", class: "btn btn-ghost", title: "Horas de todos, com usuário e projeto (some por cliente na planilha)", onClick: async (ev) => {
        const b = ev.currentTarget;
        b.disabled = true;
        try { await api.download("/admin/export/apontamentos.csv"); } catch (e) { errorToast(e, "Falha ao exportar."); } finally { b.disabled = false; }
      } }, icon("download"), "Horas da equipe (CSV)")
    ),
    subtabs,
    h("p", { class: "readonly-note", text: "visão somente leitura do usuário selecionado" }),
    content
  );

  function renderCurrent() {
    const uid = select.value;
    if (active === "board")
      board.mount(content, { readOnly: true, boardUrl: `/admin/users/${uid}/board` });
    else if (active === "dashboard")
      dashboard.mount(content, { dashUrl: `/admin/users/${uid}/dashboard` });
    else reports.mount(content, { exportBase: `/admin/users/${uid}/reports/export`, projectsUrl: `/admin/users/${uid}/projects` });
  }

  // ---- Redefinir senha (senha temporária, troca forçada no próximo login) ----
  async function onReset() {
    const uid = select.value;
    const email = emailById.get(uid) || "";
    const ok = await confirmDialog({
      title: "Redefinir senha?",
      text: `Gera uma senha temporária para ${email}. As sessões, as chaves de API e o link do calendário dele são revogados; no próximo login ele define uma senha nova.`,
      confirm: "Redefinir", danger: true,
    });
    if (!ok) return;
    try {
      const res = await api.post(`/admin/users/${uid}/reset-password`);
      showPassword(res.email, res.temp_password);
    } catch (e) {
      errorToast(e, "Falha ao redefinir a senha.");
    }
  }

  // ---- Novo usuário (convite): conta com senha temporária, troca no 1º login ----
  function onInvite() {
    const input = h("input", { type: "email", required: "required", autocomplete: "off" });
    const err = h("p", { class: "error-text" });
    const submit = h("button", { type: "submit", class: "btn btn-primary", text: "Criar conta" });
    const form = h(
      "form",
      {},
      h("label", { class: "field" }, "E-mail do convidado", input),
      h("p", {
        class: "dialog-note",
        text: "A conta nasce com uma senha temporária, que o convidado troca no primeiro acesso.",
      }),
      err,
      h(
        "div",
        { class: "dialog-actions" },
        h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
        submit
      )
    );
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      err.textContent = "";
      submit.disabled = true;
      try {
        const res = await api.post("/admin/users", { email: input.value.trim() });
        dlg.close();
        showPassword(res.email, res.temp_password);
        mountUsers(root); // recarrega a lista com o novo usuário
      } catch (e) {
        err.textContent =
          e.status === 409 ? "Esse e-mail já tem conta." :
          e.status === 422 ? "E-mail inválido." :
          e.message || "Falha ao criar a conta.";
        submit.disabled = false;
      }
    });
    const dlg = modal(h("h2", { text: "Novo usuário" }), form);
    input.focus();
  }

  function showPassword(email, pw) {
    const dlg = modal(
      h("h2", { text: "Senha temporária" }),
      h("p", {}, "Usuário: ", h("strong", { text: email })),
      codeBox(pw),
      h("p", { class: "dialog-note", text: "Repasse agora — não será exibida novamente. O usuário deverá trocá-la no próximo login." }),
      h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-primary", text: "Pronto", onClick: () => dlg.close() })));
  }


  select.addEventListener("change", renderCurrent);
  renderCurrent();
}


// ---- Identidade visual: logo + duas linhas do lockup (menu e login) ----
async function mountBranding(root) {
  clear(root);
  let brand = await api.get("/branding");

  const preview = h("div", { class: "lockup lockup--preview" },
    h("img", { class: "lockup-mark", alt: "", src: brand.logo || "/img/dragon-mark.svg" }),
    h("span", { class: "lockup-type" }, h("span", { text: brand.line1 }), h("span", { text: brand.line2 })));
  const l1 = h("input", { type: "text", maxlength: "24", value: brand.line1 });
  const l2 = h("input", { type: "text", maxlength: "24", value: brand.line2 });
  const sync = () => {
    preview.querySelectorAll(".lockup-type span")[0].textContent = l1.value || "—";
    preview.querySelectorAll(".lockup-type span")[1].textContent = l2.value;
  };
  l1.addEventListener("input", sync);
  l2.addEventListener("input", sync);

  const file = h("input", { type: "file", accept: "image/svg+xml,image/png,image/webp" });
  const err = h("p", { class: "error-text" });

  const apply = (b) => {
    brand = b;
    preview.querySelector(".lockup-mark").src = b.logo || "/img/dragon-mark.svg";
    applyBranding(b); // atualiza o menu na hora
  };

  const saveText = h("button", { type: "button", class: "btn btn-primary", text: "Salvar textos", onClick: async () => {
    err.textContent = "";
    try {
      apply(await api.put("/admin/branding", { line1: l1.value.trim(), line2: l2.value.trim() }));
      toast("Textos salvos.");
    } catch (e) { err.textContent = e.message || "Falha ao salvar."; }
  } });

  const upload = h("button", { type: "button", class: "btn btn-ghost", onClick: async () => {
    err.textContent = "";
    const f = file.files && file.files[0];
    if (!f) { err.textContent = "Escolha um arquivo SVG, PNG ou WebP."; return; }
    if (f.size > 256 * 1024) { err.textContent = "O arquivo passa de 256 KB."; return; }
    try {
      apply(await api.upload("/admin/branding/logo", f));
      file.value = "";
      toast("Logo atualizado.");
    } catch (e) { err.textContent = e.message || "Falha ao enviar."; }
  } }, icon("add"), "Enviar logo");

  const reset = h("button", { type: "button", class: "btn btn-text", text: "Restaurar dragão padrão", onClick: async () => {
    try { apply(await api.del("/admin/branding/logo")); toast("Logo padrão restaurado."); }
    catch (e) { errorToast(e); }
  } });

  root.append(
    h("div", { class: "settings-grid" },
      h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", { text: "Prévia" })),
        h("div", { class: "brand-preview" }, preview),
        h("p", { class: "help", text: "Aparece no menu lateral, no login e na troca de senha. O logo fica com a altura das duas linhas de texto." })),
      h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", { text: "Textos" })),
        h("div", { class: "field-row" },
          field("Linha 1 (destaque)", l1),
          field("Linha 2 (opcional)", l2)),
        saveText),
      h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", { text: "Logo" })),
        h("p", { class: "help", text: "SVG, PNG ou WebP, até 256 KB. Prefira SVG ou PNG com fundo transparente. SVG com script, eventos ou links externos é recusado." }),
        h("div", { class: "field" }, file),
        err,
        h("div", { class: "dialog-actions" }, reset, h("div", { class: "spacer" }), upload))));
}
