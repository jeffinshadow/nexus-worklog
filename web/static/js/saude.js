// Saúde do Nexus (Admin > Geral): versão, último backup, e-mail, notificações,
// fotos e webhooks, só leitura. "Copiar diagnóstico" monta um texto sem dados
// de pessoas nem segredos (o servidor já não manda nada disso) para um chamado.
import { api } from "./api.js";
import { h, icon, dateTime } from "./dom.js";
import { codeBox, modal, toast } from "./ui.js";

const BACKUP_OLD_DAYS = 14; // backup é feito a cada deploy: passou disso, vale conferir

const mb = (bytes) => {
  const n = Number(bytes) || 0;
  if (n >= 1024 ** 3) return (n / 1024 ** 3).toFixed(1).replace(".", ",") + " GB";
  if (n >= 1024 ** 2) return (n / 1024 ** 2).toFixed(n >= 10 * 1024 ** 2 ? 0 : 1).replace(".", ",") + " MB";
  return Math.max(1, Math.round(n / 1024)) + " KB";
};
const when = (iso) => (iso ? dateTime(iso) : null);
const daysAgo = (iso) => Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
const ago = (iso) => { const d = daysAgo(iso); return d <= 0 ? "hoje" : d === 1 ? "ontem" : `há ${d} dias`; };

// Cada linha: [título, texto, tom] — tom "ok", "warn" ou "" (neutro).
function rows(s) {
  const v = s.version, b = s.backup, e = s.email, p = s.push, f = s.photos, w = s.webhooks;
  const out = [];
  out.push(["Versão", v.commit
    ? `${v.commit}` + (v.deployed_at ? ` · deploy ${when(v.deployed_at)}` : "") + ` · migração ${v.migration}`
    : `sem informação do deploy · migração ${v.migration}`, v.commit ? "ok" : ""]);
  out.push(["No ar desde", when(v.started_at), ""]);
  if (b && b.at) {
    const old = daysAgo(b.at) > BACKUP_OLD_DAYS;
    out.push(["Último backup", `${when(b.at)} (${ago(b.at)})` + (b.size_bytes ? ` · ${mb(b.size_bytes)}` : "") + (b.tables ? ` · ${b.tables} tabelas` : "")
      + (old ? " · antigo: confira" : ""), old ? "warn" : "ok"]);
  } else {
    out.push(["Último backup", "sem informação (o deploy.sh grava a data a cada backup)", "warn"]);
  }
  if (!e.configured) out.push(["E-mail", "desligado (sem SMTP no servidor): convites e avisos não saem por e-mail", "warn"]);
  else {
    const fail = e.last_error_at && (!e.last_ok_at || new Date(e.last_error_at) > new Date(e.last_ok_at));
    out.push(["E-mail", "configurado" + (e.last_ok_at ? ` · último envio ${when(e.last_ok_at)}` : " · nada enviado ainda")
      + (e.last_error_at ? ` · último erro ${when(e.last_error_at)}: ${e.last_error}` : " · sem erros"), fail ? "warn" : "ok"]);
  }
  out.push(["Notificações", (p.keys_ok ? "chaves prontas" : "chaves geradas no primeiro aparelho")
    + ` · ${p.devices} ${p.devices === 1 ? "aparelho" : "aparelhos"}`
    + (p.failing ? ` · ${p.failing} com falha` : "") + (p.last_ok_at ? ` · última entrega ${when(p.last_ok_at)}` : ""), p.failing ? "warn" : ""]);
  const near = f.near_quota ? ` · ${f.near_quota} ${f.near_quota === 1 ? "pessoa perto" : "pessoas perto"} do limite` : "";
  out.push(["Fotos", `${mb(f.used_bytes)} usados · limite de ${f.quota_mb} MB por pessoa` + (f.top_bytes ? ` (quem mais usa: ${mb(f.top_bytes)})` : "") + near,
    f.near_quota ? "warn" : ""]);
  out.push(["Webhooks", w.total ? `${w.total} ${w.total === 1 ? "cadastrado" : "cadastrados"}` + (w.disabled ? ` · ${w.disabled} ${w.disabled === 1 ? "desligado" : "desligados"} por falha` : " · todos ligados") : "nenhum",
    w.disabled ? "warn" : ""]);
  out.push(["Contas", `${s.accounts} · ${s.api_tokens} ${s.api_tokens === 1 ? "chave de API ativa" : "chaves de API ativas"}`
    + (s.invite_requests ? ` · ${s.invite_requests} ${s.invite_requests === 1 ? "pedido de convite" : "pedidos de convite"}` : ""), ""]);
  out.push(["Banco de dados", mb(s.db_bytes), ""]);
  return out;
}

function diagnostico(s) {
  return ["Diagnóstico do Nexus Worklog", `Gerado em ${dateTime(s.now)}`, "",
    ...rows(s).map(([t, txt, tone]) => `${tone === "warn" ? "[!] " : ""}${t}: ${txt}`)].join("\n");
}

// Painel pronto para ir ao lado do "Geral". Erro ao ler: o painel avisa, o resto da tela segue.
export async function healthPanel() {
  const panel = h("section", { class: "panel health", "aria-labelledby": "health-title" },
    h("div", { class: "panel-head" }, h("h2", { id: "health-title", text: "Saúde do Nexus" })));
  let s;
  try { s = await api.get("/admin/health"); }
  catch (e) { panel.append(h("p", { class: "error-text", text: "Não foi possível ler a saúde do servidor: " + (e.message || "erro") })); return panel; }
  const list = rows(s);
  const warns = list.filter((r) => r[2] === "warn").length;
  panel.append(h("p", { class: "help", text: warns
    ? `${warns} ${warns === 1 ? "ponto pede" : "pontos pedem"} atenção (marcados abaixo). Só leitura: nada aqui muda o servidor.`
    : "Tudo em ordem. Só leitura: nada aqui muda o servidor." }));
  panel.append(h("dl", { class: "health-list" }, ...list.flatMap(([t, txt, tone]) => [
    h("dt", {}, tone === "warn" ? icon("alert") : tone === "ok" ? icon("check") : null, t),
    h("dd", { class: tone, text: txt }),
  ])));
  const copy = h("button", { type: "button", class: "btn btn-ghost", onClick: async () => {
    try { await navigator.clipboard.writeText(diagnostico(s)); toast("Diagnóstico copiado: cole no chamado ou na conversa."); }
    catch { // sem acesso à área de transferência (http, permissão): mostra para copiar à mão
      const dlg = modal(h("h2", { text: "Diagnóstico" }), codeBox(diagnostico(s)),
        h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "btn btn-text", text: "Fechar", onClick: () => dlg.close() })));
    }
  } }, icon("copy"), "Copiar diagnóstico");
  panel.append(h("div", { class: "dialog-actions health-actions" }, copy),
    h("p", { class: "dialog-note", text: "O diagnóstico leva só versões, datas e contagens: nenhum nome, e-mail, endereço de webhook ou senha." }));
  return panel;
}
