// Registro rápido: "Troca de toner — 15min" já entra concluída e com o tempo
// apontado; "@Projeto #chamado !plantão" no fim preenchem esses campos.
// Usado no Hoje e no lembrete de inatividade.
import { api } from "./api.js";
import { parseDuration } from "./task.js";
import { listProjects } from "./projects.js";

// Marcadores no fim do registro, em qualquer ordem: "@Projeto", "#chamado",
// "!plantão". Ex.: "Troca de switch @Matriz #4821 !plantão — 45min".
const FOLD = (s) => s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim();
async function parseMarks(text) {
  let title = text, ticket = null, afterHours = false, project = null;
  for (;;) {
    let m;
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
  return { title: title.trim(), ticket, afterHours, project };
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
    ticket: marks.ticket, after_hours: marks.afterHours, status: comTempo ? "done" : "todo",
  });
  const extras = [marks.project && marks.project.name, marks.ticket && "#" + marks.ticket, marks.afterHours && "plantão"].filter(Boolean);
  const com = extras.length ? ` (${extras.join(", ")})` : "";
  if (!comTempo) return `Tarefa registrada${com}.`;
  try {
    await api.post(`/worklog/${created.id}/time`, { minutes });
    return `Registrada e concluída com ${m[1].trim()}${com}.`;
  } catch {
    return "Tarefa registrada, mas o tempo não foi apontado.";
  }
}
