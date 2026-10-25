// Tela de login. Contas são criadas pelo admin (convite); não há cadastro público.
import { api } from "./api.js";
import { loadBranding } from "./branding.js";

loadBranding();

// Volta à tela que pediu o login (link de e-mail ou calendário): só rotas do app (#/...).
const next = new URLSearchParams(location.search).get("next") || "";
const destino = "/index.html" + (/^#\/[\w\-?=&%.]*$/.test(next) ? next : "");

document.getElementById("form-login").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const err = document.getElementById("login-error");
  const btn = ev.submitter;
  err.textContent = "";
  if (btn) btn.disabled = true; // clique repetido gasta tentativas do limite de login
  try {
    await api.post("/auth/login", {
      email: document.getElementById("login-email").value,
      password: document.getElementById("login-password").value,
    });
    location.href = destino;
  } catch (e) {
    err.textContent = e.message || "Falha no login.";
    if (btn) btn.disabled = false;
  }
});
