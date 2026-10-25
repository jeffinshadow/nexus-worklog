import { api } from "./api.js";
import { h, icon, clear, field } from "./dom.js";
import { codeBox, confirmDialog, errorToast, modal, toast } from "./ui.js";
import { applyBranding } from "./branding.js";
import { avatar } from "./profile.js";
import { consentsPanel } from "./atribuir.js";

const ROLES = [
  ["user", "Usuário", "tem o próprio registro (Hoje, Tarefas, Rotinas) e pode receber tarefas"],
  ["admin", "Admin", "contas, permissões e configurações gerais"],
  ["assigner", "Atribuidor de tarefas", "manda tarefas para quem aceitou receber"],
  ["viewer", "Visualizador de tarefas", "vê os registros e tira relatórios de todos"],
];

// Admin: contas (convite, senha), permissões, quem aceita tarefas, configurações
// gerais e identidade visual. Ver registros e relatórios é do Visualizador (Equipe).
export async function mount(root, ctx) {
  clear(root);
  const seg = h("div", { class: "seg", role: "tablist" });
  const body = h("div");
  const abas = [
    ["usuarios", "Usuários", (el) => mountUsers(el)],
    ["permissoes", "Permissões", (el) => mountRoles(el, ctx.me)],
    ["aceites", "Tarefas atribuídas", async (el) => { clear(el); el.append(h("div", { class: "settings-grid" }, consentsPanel(await api.get("/assign/people")))); }],
    ["geral", "Geral", (el) => mountGeneral(el, ctx.me)],
    ["identidade", "Identidade visual", (el) => mountBranding(el)],
  ];
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

const roleNames = (roles) => ROLES.filter(([k]) => roles.includes(k)).map(([, n]) => n).join(" · ") || "sem papel";

async function mountUsers(root) {
  clear(root);
  const users = await api.get("/admin/users");
  const emailById = new Map(users.map((u) => [String(u.id), u.email]));
  const inviteBtn = h("button", { type: "button", class: "btn btn-primary", onClick: onInvite }, icon("add"), "Novo usuário");
  const list = h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", { text: "Contas" }), h("div", { class: "spacer" }), inviteBtn),
    ...users.map((u) => h("div", { class: "list-row" }, avatar(u, "sm"),
      h("div", { class: "t" }, h("span", { text: u.display_name ? `${u.display_name} · ${u.email}` : u.email }),
        h("small", { text: roleNames(u.roles) })),
      h("button", { type: "button", class: "btn btn-text btn-sm", text: "Redefinir senha", onClick: () => onReset(String(u.id)) }),
      h("button", { type: "button", class: "icon", title: "Excluir conta", "aria-label": "Excluir a conta de " + u.email, onClick: () => onDelete(u) }, icon("trash")))));
  root.append(h("div", { class: "settings-grid" }, list));

  // ---- Excluir conta (LGPD): apaga a conta e todos os dados dela; confirma com o e-mail ----
  function onDelete(u) {
    const input = h("input", { type: "email", autocomplete: "off", required: "required" });
    const err = h("p", { class: "error-text" });
    const form = h("form", {},
      h("p", { class: "help", text: `Apaga a conta ${u.email} e tudo o que está nela: tarefas, rotinas, tempo, anotações, chaves de API e histórico. Não dá para desfazer. Tarefas que essa pessoa atribuiu a outras continuam com quem recebeu.` }),
      field("Digite o e-mail da conta para confirmar", input), err,
      h("div", { class: "dialog-actions" },
        h("button", { type: "button", class: "btn btn-text", text: "Cancelar", onClick: () => dlg.close() }),
        h("button", { type: "submit", class: "btn btn-danger", text: "Excluir para sempre" })));
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      err.textContent = "";
      try {
        const res = await api.post(`/admin/users/${u.id}/delete`, { confirm_email: input.value.trim() });
        dlg.close();
        toast(`Conta ${res.email} excluída (${res.tasks} tarefas, ${res.routines} rotinas).`);
        mountUsers(root);
      } catch (e) { err.textContent = e.message || "Não foi possível excluir."; }
    });
    const dlg = modal(h("h2", { text: "Excluir conta?" }), form);
    input.focus();
  }

  // ---- Redefinir senha (senha temporária, troca forçada no próximo login) ----
  async function onReset(uid) {
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
}


// ---- Permissões: papéis acumuláveis por conta ----
async function mountRoles(root, me) {
  clear(root);
  const users = await api.get("/admin/users");
  const sec = h("section", { class: "panel" },
    h("div", { class: "panel-head" }, icon("admin"), h("h2", { text: "Permissões" })),
    h("p", { class: "help", text: "Cada conta pode ter qualquer combinação de papéis. Marque e salve a linha." }),
    h("dl", { class: "roles-legend" }, ...ROLES.flatMap(([, n, d]) => [h("dt", { text: n }), h("dd", { text: d })])));
  for (const u of users) {
    const boxes = ROLES.map(([k, n]) => {
      const cb = h("input", { type: "checkbox", value: k, "aria-label": `${n} para ${u.email}` });
      cb.checked = u.roles.includes(k);
      if (k === "admin" && u.id === me.id) { cb.disabled = true; cb.title = "Você não pode tirar o seu próprio admin"; }
      return [cb, h("label", { class: "weekday-option" }, cb, h("span", { text: n }))];
    });
    const save = h("button", { type: "button", class: "btn btn-ghost btn-sm", text: "Salvar" });
    save.addEventListener("click", async () => {
      const roles = boxes.filter(([cb]) => cb.checked).map(([cb]) => cb.value);
      if (!roles.length) { toast("Marque pelo menos um papel.", { error: true }); return; }
      save.disabled = true;
      try {
        await api.put(`/admin/users/${u.id}/roles`, { roles });
        u.roles = roles;
        toast(`Permissões de ${u.display_name || u.email} salvas.`);
      } catch (e) { errorToast(e); }
      finally { save.disabled = false; }
    });
    sec.append(h("div", { class: "role-row" }, avatar(u, "sm"),
      h("div", { class: "t" }, h("span", { text: u.display_name || u.email }), u.display_name ? h("small", { text: u.email }) : null),
      h("div", { class: "role-boxes" }, ...boxes.map(([, l]) => l)), save));
  }
  root.append(h("div", { class: "settings-grid" }, sec));
}

// ---- Geral: limite de datas retroativas em tarefas ----
async function mountGeneral(root, me) {
  clear(root);
  const cfg = await api.get("/admin/settings");
  const days = h("input", { type: "number", min: "1", max: "366", value: String(cfg.retro_days), required: "required" });
  const contact = h("input", { type: "text", maxlength: "200", value: cfg.support_contact || "", placeholder: "ex.: suporte@empresa.com · ramal 2040" });
  const err = h("p", { class: "error-text" });
  const form = h("form", {},
    field("Dias para trás", days),
    h("p", { class: "dialog-note", text: "Vale para criar ou concluir tarefas com data passada, pelo app, pela API e pela IA. As rotinas seguem com 7 dias." }),
    field("Contato de suporte (aparece em Ajuda)", contact),
    err, h("button", { type: "submit", class: "btn btn-primary", text: "Salvar" }));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    err.textContent = "";
    try {
      const res = await api.put("/admin/settings", { retro_days: Number(days.value), support_contact: contact.value.trim() || null });
      me.retro_days = res.retro_days;
      me.support_contact = res.support_contact;
      toast("Configurações salvas.");
    } catch (e) { err.textContent = e.message || "Falha ao salvar."; }
  });
  root.append(h("div", { class: "settings-grid" }, h("section", { class: "panel" },
    h("div", { class: "panel-head" }, icon("calendar"), h("h2", { text: "Geral" })), form)));
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
