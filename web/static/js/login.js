// Tela de login. Contas são criadas pelo admin (convite); não há cadastro público.
// Com e-mail no servidor, a mesma tela também: pede o link de senha nova
// ("Esqueci a senha") e recebe os links do e-mail — #convite=… (criar a senha
// do convite) e #senha=… (senha nova). O token fica no # (não vai para logs).
import { api } from "./api.js";
import { loadBranding } from "./branding.js";
import { matchPasswords } from "./dom.js";

loadBranding();

const $ = (id) => document.getElementById(id);
const forms = ["form-login", "form-forgot", "form-link"];
function show(id) {
  for (const f of forms) $(f).classList.toggle("hidden", f !== id);
  const first = $(id).querySelector("input:not(.sr-only)");
  if (first) first.focus();
}

// Volta à tela que pediu o login (link de e-mail ou calendário): só rotas do app (#/...).
const next = new URLSearchParams(location.search).get("next") || "";
const destino = "/index.html" + (/^#\/[\w\-?=&%.]*$/.test(next) ? next : "");

$("form-login").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const err = $("login-error");
  const btn = ev.submitter;
  err.textContent = "";
  if (btn) btn.disabled = true; // clique repetido gasta tentativas do limite de login
  try {
    await api.post("/auth/login", {
      email: $("login-email").value,
      password: $("login-password").value,
    });
    location.href = destino;
  } catch (e) {
    err.textContent = e.message || "Falha no login.";
    if (btn) btn.disabled = false;
  }
});

// ---- Esqueci a senha: o link só aparece se o servidor manda e-mail.
api.get("/auth/options").then((o) => { if (o.email) $("go-forgot").classList.remove("hidden"); }).catch(() => {});
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
  if (btn) btn.disabled = true;
  try {
    await api.post("/auth/forgot", { email: $("forgot-email").value });
    // Mesma frase com ou sem conta: a tela não revela quem está cadastrado.
    ok.textContent = `Se ${$("forgot-email").value} tiver conta no Nexus, o link chega em instantes. Confira também o spam.`;
    ok.classList.remove("hidden");
  } catch (e) {
    err.textContent = e.message || "Não foi possível enviar.";
  } finally {
    if (btn) btn.disabled = false;
  }
});

// ---- Links do e-mail.
// Também quando o link abre numa aba que já estava no login (só o # muda).
function fromHash() {
  const m = location.hash.match(/^#(convite|senha)=([\w-]{20,100})$/);
  if (m) openLink(m[1] === "convite" ? "invite" : "reset", m[2]);
}
fromHash();
addEventListener("hashchange", fromHash);

async function openLink(kind, token) {
  history.replaceState(null, "", location.pathname); // o token sai da barra (e do histórico)
  const invite = kind === "invite";
  $("link-title").textContent = invite ? "Boas-vindas ao Nexus" : "Crie uma senha nova";
  $("link-submit").textContent = invite ? "Criar a senha e entrar" : "Salvar e entrar";
  $("link-name-wrap").classList.toggle("hidden", !invite);
  $("auth-foot").classList.add("hidden");
  show("form-link");
  const err = $("link-error");
  let info;
  try {
    info = await api.get(`/auth/link?kind=${kind}&token=${encodeURIComponent(token)}`);
  } catch (e) {
    $("link-sub").textContent = invite
      ? "Este convite venceu ou já foi usado. Peça um novo a quem administra o Nexus."
      : "Este link venceu ou já foi usado. Peça outro em “Esqueci a senha”.";
    $("form-link").querySelectorAll(".field, #link-submit").forEach((el) => el.classList.add("hidden"));
    $("link-back").classList.remove("hidden");
    return;
  }
  $("link-back").classList.add("hidden");
  $("link-submit").classList.remove("hidden");
  $("form-link").querySelectorAll(".field:not(#link-name-wrap)").forEach((el) => el.classList.remove("hidden"));
  $("link-sub").textContent = invite
    ? `Crie a senha da sua conta ${info.email}. Depois disso você já entra.`
    : `Conta ${info.email}. Ao salvar, as outras sessões e as chaves de API são encerradas.`;
  $("link-email").value = info.email; // o gerenciador de senhas guarda com o e-mail certo
  if (invite) $("link-name").value = info.display_name || "";
  matchPasswords($("link-pw"), $("link-pw2"));
  $("form-link").onsubmit = async (ev) => { // onsubmit: um link novo troca o anterior
    ev.preventDefault();
    err.textContent = "";
    const btn = ev.submitter;
    if (btn) btn.disabled = true;
    try {
      const body = { token, password: $("link-pw").value };
      if (invite) body.display_name = $("link-name").value.trim() || null;
      await api.post(invite ? "/auth/invite/accept" : "/auth/reset", body);
      location.href = "/index.html";
    } catch (e) {
      err.textContent = e.message || "Não foi possível salvar.";
      if (btn) btn.disabled = false;
    }
  };
}
