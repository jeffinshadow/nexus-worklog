// Abertura que não completa: se um módulo do app não chega (o app.js ou um dos
// que ele importa), o "Abrindo o Nexus…" não fica para sempre: vira "Não abriu" com "Tentar de novo".
// Script comum, antes dos módulos (o erro de carga não sobe até a janela: só se vê
// na captura). Sem prazo: em sinal fraco a abertura demora e não é falha.
(function () {
  var falhou = false;
  function mostrar() {
    var splash = document.getElementById("boot-splash");
    var card = splash && splash.querySelector(".auth-card");
    if (!card || card.classList.contains("boot-error")) return;
    var msg = card.querySelector(".boot-msg"), bar = card.querySelector(".boot-progress");
    if (msg) msg.remove();
    if (bar) bar.remove();
    card.classList.add("boot-error");
    card.setAttribute("role", "alert");
    var p = document.createElement("p");
    p.className = "sub";
    p.textContent = "Não abriu: uma parte do Nexus não chegou. Confira a internet e tente de novo.";
    var b = document.createElement("button");
    b.type = "button";
    b.className = "btn btn-primary full";
    b.textContent = "Tentar de novo";
    b.addEventListener("click", function () { location.reload(); });
    card.append(p, b);
    b.focus();
  }
  document.addEventListener("error", function (ev) {
    var t = ev.target;
    if (!t || !t.tagName) return;
    var arquivo = (t.tagName === "SCRIPT" && /\/js\/app\.js/.test(t.src || "")) || (t.tagName === "LINK" && t.rel === "modulepreload");
    if (!arquivo) return;
    falhou = true;
    mostrar();
  }, true);
  // A falha veio antes de a marca estar na página: mostra quando ela chegar.
  document.addEventListener("DOMContentLoaded", function () { if (falhou) mostrar(); });
})();
