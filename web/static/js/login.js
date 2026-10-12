// Tela de login. Contas são criadas pelo admin (convite); não há cadastro público.
import { api } from "./api.js";
import { loadBranding } from "./branding.js";

loadBranding();

document.getElementById("form-login").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const err = document.getElementById("login-error");
  err.textContent = "";
  try {
    await api.post("/auth/login", {
      email: document.getElementById("login-email").value,
      password: document.getElementById("login-password").value,
    });
    location.href = "/index.html";
  } catch (e) {
    err.textContent = e.message || "Falha no login.";
  }
});
