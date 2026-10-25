from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from .. import people
from ..deps import active_user
from ..services import app_today, app_tz, get_board, get_summary, next_work_day, work_mask

router = APIRouter(prefix="/api/summary", tags=["summary"])


@router.get("")
def summary(user=Depends(active_user)):
    return get_summary(user["user_id"])


def _dias(ts) -> int:
    """Dias de calendário no fuso da app (bloqueada ontem às 18h = 1 dia hoje)."""
    return max(0, (app_today() - ts.astimezone(app_tz()).date()).days) if ts else 0


def handoff_text(user_id: int) -> str:
    """Passagem de turno/plantão: o que fica aberto, o que está travado e por quê,
    o que vence até amanhã e o que saiu hoje. Texto puro, pronto pra colar no
    chat da equipe. Calculado do quadro, sem IA."""
    b = get_board(user_id)
    hoje = b["today"]
    amanha = next_work_day(hoje, work_mask(user_id))  # na sexta, a segunda
    agora = datetime.now(app_tz()).strftime("%d/%m %H:%M")
    linhas = [f"Passagem de turno — {people.profile(user_id)['name']}, {agora}", ""]

    def item(t):
        extra = []
        if t.get("ticket"):
            extra.append(f"chamado {t['ticket']}")
        if t.get("project_name"):
            extra.append(t["project_name"])
        if t.get("due_date") and t["due_date"] <= amanha:
            extra.append("ATRASADA" if t["due_date"] < hoje else ("vence hoje" if t["due_date"] == hoje
                         else f"vence {t['due_date'].strftime('%d/%m')}"))
        return f"- {t['title']}" + (f" ({', '.join(extra)})" if extra else "")

    abertas = [t for t in b["in_progress"] if t["status"] != "blocked"]
    travadas = [t for t in b["in_progress"] if t["status"] == "blocked"]
    linhas.append(f"Em aberto ({len(abertas)}):")
    linhas += [item(t) for t in abertas[:15]] or ["- nada"]
    if len(abertas) > 15:
        linhas.append(f"- e mais {len(abertas) - 15}")
    linhas += ["", f"Bloqueadas ({len(travadas)}):"]
    for t in travadas:
        motivo = f" — aguardando {t['blocked_reason']}" if t.get("blocked_reason") else ""
        dias = _dias(t.get("blocked_at"))
        info = [f"há {dias} d"] if dias else []
        if t.get("follow_up_on"):
            info.append(f"cobrar dia {t['follow_up_on'].strftime('%d/%m')}")
        linhas.append(item(t) + motivo + (f" ({', '.join(info)})" if info else ""))
    if not travadas:
        linhas.append("- nenhuma")
    feitas = [t for t in b["done"] if t["completed_at"] and t["completed_at"].astimezone(app_tz()).date() == hoje]
    plantao = [t for t in feitas if t.get("after_hours")]
    linhas += ["", f"Concluídas hoje ({len(feitas)}):"]
    linhas += [f"- {t['title']}" + (" (plantão)" if t.get("after_hours") else "") for t in feitas[:15]] or ["- nada"]
    if len(feitas) > 15:
        linhas.append(f"- e mais {len(feitas) - 15}")
    pend = [r for r in b["recurring"] if r.get("due") and not r["done_today"]]
    if pend:
        linhas += ["", "Rotinas de hoje ainda não feitas:"] + [f"- {r['label']}" for r in pend]
    if plantao:
        linhas += ["", f"Plantão: {len(plantao)} atendimento(s) fora do horário hoje."]
    return "\n".join(linhas)


@router.get("/handoff")
def handoff(user=Depends(active_user)):
    return {"text": handoff_text(user["user_id"])}
