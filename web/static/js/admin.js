import { api } from "./api.js";
import { h, icon, clear } from "./dom.js";
import { modal } from "./ui.js";
import * as board from "./board.js";
import * as dashboard from "./dashboard.js";
import * as reports from "./reports.js";

const SUBVIEWS = [
  { key: "board", label: "Board" },
  { key: "dashboard", label: "Dashboard" },
  { key: "reports", label: "Relatórios" },
];

export async function mount(root) {
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
    ...users.map((u) => h("option", { value: u.id }, `${u.email}${u.role === "admin" ? " (admin)" : ""}`))
  );

  const resetBtn = h("button", { type: "button", class: "btn btn-danger", text: "Redefinir senha", onClick: onReset });
  const inviteBtn = h("button", { type: "button", class: "btn btn-primary", onClick: onInvite }, icon("add"), "Novo usuário");

  let active = "board";
  const subtabs = h(
    "div",
    { class: "auth-tabs" },
    ...SUBVIEWS.map((s) =>
      h("button", {
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
      h("div", { class: "field" }, h("label", { text: "Usuário" }), select),
      resetBtn,
      inviteBtn
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
    else reports.mount(content, { exportBase: `/admin/users/${uid}/reports/export` });
  }

  // ---- Redefinir senha (senha temporária, troca forçada no próximo login) ----
  function onReset() {
    const uid = select.value;
    const email = emailById.get(uid) || "";

    const dlg = modal(
      h("h2", { text: "Redefinir senha" }),
      h("p", {}, "Gerar uma senha temporária para ", h("strong", { text: email }), "?"),
      h("p", {
        class: "dialog-note",
        text: "As sessões ativas do usuário serão encerradas e ele precisará definir uma nova senha no próximo login.",
      }),
      h(
        "div",
        { class: "dialog-actions" },
        h("button", { class: "text", text: "Cancelar", onClick: () => dlg.close() }),
        h("button", {
          class: "danger",
          text: "Redefinir",
          onClick: async (ev) => {
            const b = ev.currentTarget;
            b.disabled = true;
            b.textContent = "Gerando...";
            try {
              const res = await api.post(`/admin/users/${uid}/reset-password`);
              dlg.close();
              showPassword(res.email, res.temp_password);
            } catch (e) {
              dlg.close();
              modal(
                h("h2", { text: "Erro" }),
                h("p", { text: e.message || "Falha ao redefinir a senha." }),
                h("div", { class: "dialog-actions" },
                  h("button", { text: "Fechar", onClick: (x) => x.currentTarget.closest("dialog").close() })
                )
              );
            }
          },
        })
      )
    );
  }

  // ---- Novo usuário (convite): conta com senha temporária, troca no 1º login ----
  function onInvite() {
    const input = h("input", { type: "email", required: "required", autocomplete: "off" });
    const err = h("p", { class: "error-text" });
    const submit = h("button", { type: "submit", text: "Criar conta" });
    const form = h(
      "form",
      {},
      h("div", { class: "field" }, h("label", { text: "E-mail do convidado" }), input),
      h("p", {
        class: "dialog-note",
        text: "A conta nasce com uma senha temporária, que o convidado troca no primeiro acesso.",
      }),
      err,
      h(
        "div",
        { class: "dialog-actions" },
        h("button", { type: "button", class: "text", text: "Cancelar", onClick: () => dlg.close() }),
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
        mount(root); // recarrega a lista com o novo usuário
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
    const box = h("div", { class: "token-box", text: pw });
    const copyBtn = h("button", {
      class: "tonal",
      text: "Copiar",
      onClick: async () => {
        try {
          await navigator.clipboard.writeText(pw);
          copyBtn.textContent = "Copiado!";
        } catch {
          const range = document.createRange();
          range.selectNodeContents(box);
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
          copyBtn.textContent = "Selecione e copie";
        }
      },
    });

    const dlg = modal(
      h("h2", { text: "Senha temporária" }),
      h("p", {}, "Usuário: ", h("strong", { text: email })),
      box,
      h("p", {
        class: "dialog-note",
        text: "Repasse agora — não será exibida novamente. O usuário deverá trocá-la no próximo login.",
      }),
      h(
        "div",
        { class: "dialog-actions" },
        copyBtn,
        h("button", { text: "Fechar", onClick: () => dlg.close() })
      )
    );
  }

  select.addEventListener("change", renderCurrent);
  renderCurrent();
}
