// Tela de login. Contas são criadas pelo admin (convite); não há cadastro público.
// Com e-mail no servidor, a mesma tela também: pede o link de senha nova
// ("Esqueci a senha") e recebe os links do e-mail — #convite=… (criar a senha
// do convite), #senha=… (senha nova) e #email=… (confirmar o e-mail novo da
// conta). O token fica no # (não vai para logs).
import { api } from "./api.js";
import { loadBranding } from "./branding.js";
import { markInvalid, matchPasswords } from "./dom.js";
import { cancelled, conditionalAvailable, login as passkeyLogin, supported as passkeySupported } from "./passkey.js";

loadBranding();

const $ = (id) => document.getElementById(id);
const forms = ["form-login", "form-forgot", "form-link", "form-request"];
function show(id) {
  for (const f of forms) $(f).classList.toggle("hidden", f !== id);
  if (id === "form-login") document.title = "Entrar · Nexus Worklog"; // volta de um link do e-mail
  const first = $(id).querySelector("input:not(.sr-only)");
  if (first) first.focus();
}

// Erro de envio: marca os campos culpados (aria-invalid) e liga a mensagem a
// eles; a mensagem em si tem role="alert" e é lida na hora.
function invalid(ids, errId, on) {
  markInvalid(ids.map($), $(errId), on);
}

// Volta à tela que pediu o login (link de e-mail ou calendário): só rotas do app (#/...).
const next = new URLSearchParams(location.search).get("next") || "";
const destino = "/" + (/^#\/[\w\-?=&%.]*$/.test(next) ? next : "");

$("form-login").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const err = $("login-error");
  const btn = ev.submitter;
  err.textContent = "";
  invalid(["login-email", "login-password"], "login-error", false);
  if (btn) btn.disabled = true; // clique repetido gasta tentativas do limite de login
  try {
    await api.post("/auth/login", {
      email: $("login-email").value,
      password: $("login-password").value,
    });
    location.href = destino;
  } catch (e) {
    err.textContent = e.message || "Não foi possível entrar.";
    invalid(["login-email", "login-password"], "login-error", true);
    if (btn) btn.disabled = false;
  }
});

// ---- Passkey: o botão (digital, rosto, Windows Hello) e, onde o navegador
// permite, a sugestão no próprio campo de e-mail, sem janela.
let conditional = null;
async function withPasskey(opts) {
  const err = $("login-error");
  try {
    await passkeyLogin(opts);
    location.href = destino;
  } catch (e) {
    // A consulta silenciosa (sugestão no campo) nunca mostra erro: só o botão.
    if (!cancelled(e) && !opts.conditional) err.textContent = e.message || "Não foi possível entrar com a digital ou o rosto.";
  }
}
if (passkeySupported()) {
  $("login-passkey").classList.remove("hidden");
  $("login-passkey").addEventListener("click", () => {
    if (conditional) conditional.abort(); // uma consulta por vez ao aparelho
    $("login-error").textContent = "";
    withPasskey({});
  });
  conditionalAvailable().then((ok) => {
    if (!ok || !$("form-link").classList.contains("hidden")) return; // nos links do e-mail, não
    conditional = new AbortController();
    withPasskey({ conditional: true, signal: conditional.signal });
  });
}

// ---- Esqueci a senha: o link só aparece se o servidor manda e-mail.
api.get("/auth/options").then((o) => {
  if (o.email) $("go-forgot").classList.remove("hidden");
  if (o.invite_request) { $("go-request").classList.remove("hidden"); $("foot-ask").classList.add("hidden"); }
  // Política de privacidade da instância (Admin › Para empresas), quando definida.
  if (o.privacy_url && /^https:\/\//.test(o.privacy_url)) { $("privacy-link").href = o.privacy_url; $("privacy-foot").classList.remove("hidden"); }
}).catch(() => {});

// ---- Pedido de convite: vai para o administrador (e-mail e Admin).
$("go-request").addEventListener("click", () => {
  $("req-email").value = $("req-email").value || $("login-email").value;
  $("request-ok").classList.add("hidden");
  $("auth-foot").classList.add("hidden");
  show("form-request");
});
$("request-back").addEventListener("click", () => { $("auth-foot").classList.remove("hidden"); show("form-login"); });
$("req-source").addEventListener("change", () => $("req-note-wrap").classList.toggle("hidden", !["colega", "internet", "outro"].includes($("req-source").value)));
$("form-request").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const err = $("request-error"), ok = $("request-ok"), btn = $("request-submit");
  err.textContent = "";
  btn.disabled = true;
  try {
    await api.post("/auth/invite-request", {
      name: $("req-name").value.trim(), email: $("req-email").value.trim(), source: $("req-source").value,
      source_note: $("req-note").value.trim() || null, reason: $("req-reason").value.trim(), website: $("req-website").value || null,
    });
    // Mesma frase em qualquer caso: a tela não revela se o e-mail já tem conta.
    ok.textContent = "Pedido enviado. Com a aprovação, o convite chega no seu e-mail; confira também o spam.";
    ok.classList.remove("hidden");
    $("form-request").querySelectorAll(".field, #request-submit").forEach((el) => el.classList.add("hidden"));
  } catch (e) {
    err.textContent = e.message || "Não foi possível enviar.";
    btn.disabled = false;
  }
});
$("go-forgot").addEventListener("click", () => {
  $("forgot-email").value = $("login-email").value;
  $("forgot-ok").classList.add("hidden");
  show("form-forgot");
});
$("back-login").addEventListener("click", () => show("form-login"));
$("link-back").addEventListener("click", () => { $("auth-foot").classList.remove("hidden"); show("form-login"); });
$("form-forgot").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const err = $("forgot-error"), ok = $("forgot-ok"), btn = ev.submitter;
  err.textContent = "";
  invalid(["forgot-email"], "forgot-error", false);
  if (btn) btn.disabled = true;
  try {
    await api.post("/auth/forgot", { email: $("forgot-email").value });
    // Mesma frase com ou sem conta: a tela não revela quem está cadastrado.
    ok.textContent = `Se ${$("forgot-email").value} tiver conta no Nexus, o link chega em instantes. Confira também o spam.`;
    ok.classList.remove("hidden");
  } catch (e) {
    err.textContent = e.message || "Não foi possível enviar.";
    invalid(["forgot-email"], "forgot-error", true);
  } finally {
    if (btn) btn.disabled = false;
  }
});

// ---- Links do e-mail.
// Também quando o link abre numa aba que já estava no login (só o # muda).
function fromHash() {
  const m = location.hash.match(/^#(convite|senha|email)=([\w-]{20,100})$/);
  if (m && m[1] === "email") confirmEmail(m[2]);
  else if (m) openLink(m[1] === "convite" ? "invite" : "reset", m[2]);
}
fromHash();
addEventListener("hashchange", fromHash);

// Confirmação do e-mail novo (Configurações > Conta > E-mail): troca na hora e
// avisa o endereço antigo. Mostra o resultado na mesma caixa dos outros links.
async function confirmEmail(token) {
  history.replaceState(null, "", location.pathname);
  $("auth-foot").classList.add("hidden");
  show("form-link");
  $("link-name-wrap").classList.add("hidden");
  $("form-link").querySelectorAll(".field, #link-submit").forEach((el) => el.classList.add("hidden"));
  $("link-back").classList.remove("hidden");
  $("link-title").textContent = "Confirmando o e-mail…";
  $("link-sub").textContent = "";
  document.title = "Confirmar e-mail · Nexus Worklog";
  $("link-title").focus();
  try {
    const res = await api.post("/auth/email/confirm", { token });
    $("link-title").textContent = "E-mail confirmado";
    $("link-sub").textContent = `Pronto: a sua conta agora usa ${res.email}. Entre com ele daqui em diante.`;
    $("login-email").value = res.email;
  } catch (e) {
    $("link-title").textContent = "Não foi possível confirmar";
    $("link-sub").textContent = e.status === 429 ? "Muitas tentativas agora. Espere um minuto e abra o link de novo."
      : e.message ? e.message.charAt(0).toUpperCase() + e.message.slice(1) + "." : "Este link venceu ou já foi usado. Peça a troca de novo em Configurações > Conta.";
  }
  $("link-title").focus();
}

async function openLink(kind, token) {
  history.replaceState(null, "", location.pathname); // o token sai da barra (e do histórico)
  const invite = kind === "invite";
  $("link-title").textContent = invite ? "Boas-vindas ao Nexus" : "Crie uma senha nova";
  $("link-submit").textContent = invite ? "Criar a senha e entrar" : "Salvar e entrar";
  $("link-name-wrap").classList.toggle("hidden", !invite);
  $("auth-foot").classList.add("hidden");
  show("form-link");
  // Tela própria: título da aba e foco no título (o leitor anuncia onde está).
  document.title = (invite ? "Criar senha" : "Senha nova") + " · Nexus Worklog";
  $("link-title").focus();
  const err = $("link-error");
  let info;
  try {
    info = await api.post("/auth/link", { kind, token });  // token no corpo: fora do log de acesso
  } catch (e) {
    $("link-sub").textContent = e.status === 429  // limite de tentativas: o link pode estar bom
      ? "Muitas tentativas agora. Espere um minuto e abra o link de novo."
      : invite
      ? "Este convite venceu ou já foi usado. Peça um novo a quem administra o Nexus."
      : "Este link venceu ou já foi usado. Peça outro em “Esqueci a senha”.";
    $("form-link").querySelectorAll(".field, #link-submit").forEach((el) => el.classList.add("hidden"));
    $("link-back").classList.remove("hidden");
    return;
  }
  $("link-back").classList.add("hidden");
  $("link-submit").classList.remove("hidden");
  $("form-link").querySelectorAll(".field:not(#link-name-wrap)").forEach((el) => el.classList.remove("hidden"));
  // Quem convidou já pôs o nome (a pessoa confere no tour) ou a administração o
  // define: o convite não pergunta de novo.
  $("link-name-wrap").classList.toggle("hidden", !invite || !!info.display_name || !!info.name_locked);
  $("link-sub").textContent = invite
    ? `Crie a senha da sua conta ${info.email}. Depois disso você já entra.`
    : `Conta ${info.email}. Ao salvar, as outras sessões e as chaves de API são encerradas.`;
  $("link-email").value = info.email; // o gerenciador de senhas guarda com o e-mail certo
  if (invite) $("link-name").value = info.display_name || "";
  matchPasswords($("link-pw"), $("link-pw2"));
  $("form-link").onsubmit = async (ev) => { // onsubmit: um link novo troca o anterior
    ev.preventDefault();
    err.textContent = "";
    invalid(["link-pw"], "link-error", false);
    const btn = ev.submitter;
    if (btn) btn.disabled = true;
    try {
      const body = { token, password: $("link-pw").value };
      if (invite && !$("link-name-wrap").classList.contains("hidden")) body.display_name = $("link-name").value.trim() || null;
      await api.post(invite ? "/auth/invite/accept" : "/auth/reset", body);
      location.href = "/";
    } catch (e) {
      err.textContent = e.message || "Não foi possível salvar.";
      invalid(["link-pw"], "link-error", true);
      if (btn) btn.disabled = false;
    }
  };
}
