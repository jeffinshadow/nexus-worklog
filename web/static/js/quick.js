// Registro rápido: "Troca de toner — 15min" já entra concluída e com o tempo
// apontado; "@Projeto #chamado !plantão" no fim preenchem esses campos.
// Usado no Hoje e no lembrete de inatividade.
import { api } from "./api.js";
import { parseDuration } from "./task.js";
import { listProjects } from "./projects.js";
import { addDays, localDay } from "./dom.js";

// "^sex" = próxima sexta (hoje, se for sexta); "^25/10" = esse dia (ano que vem, se já passou).
const WD = { dom: 0, seg: 1, ter: 2, qua: 3, qui: 4, sex: 5, sab: 6, "sáb": 6 };
function dueFrom(token) {
  const today = localDay(Date.now());
  const k = token.toLowerCase();
  if (k === "hoje") return today;
  if (k === "amanha" || k === "amanhã") return addDays(today, 1);
  if (k in WD) {
    const now = new Date(today + "T12:00:00Z").getUTCDay();
    return addDays(today, (WD[k] - now + 7) % 7);
  }
  const [d, m] = k.split("/").map(Number);
  if (!d || !m || m > 12 || d > 31) return null;
  let y = Number(today.slice(0, 4));
  let iso = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  if (iso < today) iso = `${y + 1}${iso.slice(4)}`;
  const ok = new Date(iso + "T12:00:00Z").toISOString().slice(0, 10) === iso; // 31/02 não existe: fica no título
  return ok ? iso : null;
}

// Marcadores no fim do registro, em qualquer ordem: "@Projeto", "#chamado",
// "!plantão", "^sex" ou "^25/10" (prazo) e "!bloq motivo" (por último: o motivo vai até o fim).
// Ex.: "Troca de switch @Matriz #4821 !plantão — 45min"; "Trocar HD ^qui !bloq peça da Dell".
const FOLD = (s) => s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim();
async function parseMarks(text) {
  let title = text, ticket = null, afterHours = false, project = null, due = null, blocked = null, high = false;
  for (;;) {
    let m;
    const bm = blocked === null && title.match(/\s!bloq(?:\s+(.*))?$/i); // "!bloq" sozinho ou "!bloq motivo" (não "!bloqueio")
    if (bm) { blocked = (bm[1] || "").trim().slice(0, 120); title = title.slice(0, bm.index); continue; }
    if ((m = title.match(/\s+\^(hoje|amanh[aã]|seg|ter|qua|qui|sex|s[aá]b|dom|\d{1,2}\/\d{1,2})$/i)) && !due && (due = dueFrom(m[1]))) { title = title.slice(0, m.index); continue; }
    if ((m = title.match(/\s+!alta$/i)) && !high) { high = true; title = title.slice(0, m.index); continue; }
    if ((m = title.match(/\s+!plant[aã]o$/i))) { afterHours = true; title = title.slice(0, m.index); continue; }
    if ((m = title.match(/\s+#([\w./-]{1,40})$/))) { ticket = m[1]; title = title.slice(0, m.index); continue; }
    // "@Projeto" só vale se for um projeto seu; "Ligar para @Fulano" fica no título.
    const at = title.lastIndexOf(" @");
    if (at > 0 && !project) {
      const name = title.slice(at + 2);
      const found = (await listProjects()).find((p) => !p.archived && FOLD(p.name) === FOLD(name));
      if (found) { project = found; title = title.slice(0, at); continue; }
    }
    break;
  }
  return { title: title.trim(), ticket, afterHours, project, due, blocked, high };
}

// Duração no fim do registro rápido, depois de um traço: "Troca de toner — 15min",
// "Loja X - 2h", "Backup — 1:30". Sem o traço, "Reunião 14h" e "Ligar 15:30"
// ficam como título (hora do dia não vira tempo gasto).
const QUICK_DUR = /\s+[-–—]\s*(\d+(?:[.,]\d+)?\s*h(?:\s*\d{1,2})?(?:\s*min)?|\d+\s*min|\d+:\d{2})$/i;

// Cria a tarefa e devolve a frase de confirmação. Erro na criação = exceção;
// erro só no tempo = a tarefa fica e a frase avisa.
export async function quickRegister(text, project_id = null) {
  let title = text.trim();
  const m = title.match(QUICK_DUR);
  const minutes = m ? parseDuration(m[1].replace(/\s+/g, "").replace(",", ".")) : null;
  const comTempo = minutes && minutes <= 1440;
  if (comTempo) title = title.slice(0, m.index).trim();
  const marks = await parseMarks(title);
  const created = await api.post("/worklog", {
    title: marks.title || title, project_id: marks.project ? marks.project.id : project_id,
    ticket: marks.ticket, after_hours: marks.afterHours, due_date: marks.due, priority: marks.high ? 1 : 2,
    // !bloq vence o "— 30min": fica bloqueada com o motivo e o tempo apontado, sem concluir.
    status: marks.blocked !== null ? "blocked" : comTempo ? "done" : "todo",
    blocked_reason: marks.blocked || null,
  });
  const extras = [marks.project && marks.project.name, marks.ticket && "#" + marks.ticket, marks.afterHours && "plantão", marks.high && "alta",
    marks.due && "prazo " + marks.due.split("-").reverse().slice(0, 2).join("/"),
    marks.blocked !== null && (marks.blocked ? "bloqueada: " + marks.blocked : "bloqueada")].filter(Boolean);
  const com = extras.length ? ` (${extras.join(", ")})` : "";
  if (!comTempo) return `Tarefa registrada${com}.`;
  try {
    await api.post(`/worklog/${created.id}/time`, { minutes });
    return `${marks.blocked !== null ? "Registrada" : "Registrada e concluída"} com ${m[1].trim()}${com}.`;
  } catch {
    return "Tarefa registrada, mas o tempo não foi apontado.";
  }
}
