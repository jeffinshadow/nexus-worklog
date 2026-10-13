// Registro rápido: "Troca de toner — 15min" já entra concluída e com o tempo
// apontado. Usado no Hoje e no lembrete de inatividade.
import { api } from "./api.js";
import { parseDuration } from "./task.js";

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
  const created = await api.post("/worklog", { title, project_id, status: comTempo ? "done" : "todo" });
  if (!comTempo) return "Tarefa registrada.";
  try {
    await api.post(`/worklog/${created.id}/time`, { minutes });
    return `Registrada e concluída com ${m[1].trim()}.`;
  } catch {
    return "Tarefa registrada, mas o tempo não foi apontado.";
  }
}
