// Tema antes da página aparecer (script comum, não módulo: roda já no <head>,
// sem piscar escuro e depois claro). "auto" segue o aparelho; "light" e "dark"
// forçam (Configurações › Conta). A conta guarda a escolha; aqui vale a última
// conhecida neste aparelho, até o app confirmar com a do servidor.
(function () {
  var KEY = "nexus.tema";
  var dark = matchMedia("(prefers-color-scheme: dark)");
  function apply(pref) {
    var root = document.documentElement;
    if (pref === "light" || pref === "dark") root.setAttribute("data-theme", pref);
    else root.removeAttribute("data-theme");
    var isDark = pref === "dark" || (pref !== "light" && dark.matches);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", isDark ? "#121213" : "#F6F7FA");  // a barra do sistema no celular
  }
  var pref = "auto";
  try { pref = localStorage.getItem(KEY) || "auto"; } catch (e) { /* sem armazenamento */ }
  apply(pref);
  dark.addEventListener("change", function () { apply(window.nexusTheme.get()); });
  window.nexusTheme = {
    get: function () { try { return localStorage.getItem(KEY) || "auto"; } catch (e) { return "auto"; } },
    set: function (p) { try { localStorage.setItem(KEY, p); } catch (e) { /* só agora */ } apply(p); },
  };
})();
