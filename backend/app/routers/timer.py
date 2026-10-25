"""Cronômetro: um por pessoa, guardado no servidor (vale em qualquer aparelho).

Ao parar, o tempo vira um apontamento comum (mesmas regras do apontamento à
mão: no dia em que começou, até 24h no dia). Concluir a tarefa com o
cronômetro rodando nela também para e aponta.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db
from ..deps import active_user, active_user_csrf
from ..schemas import TimeIn, TimerIn
from ..services import app_tz, running_timer
from .worklog import log_time

router = APIRouter(prefix="/api/timer", tags=["timer"])


def stop_running(user: dict, only_task: int | None = None):
    """Para o cronômetro e aponta o tempo. Devolve o apontamento ou None.
    only_task: só para se estiver rodando nessa tarefa."""
    t = db.query_one("SELECT task_id, started_at FROM task_timers WHERE user_id = %s", (user["user_id"],))
    if not t or (only_task is not None and t["task_id"] != only_task):
        return None
    minutes = max(1, round((datetime.now(timezone.utc) - t["started_at"]).total_seconds() / 60))
    day = t["started_at"].astimezone(app_tz()).date()
    # Cronômetro esquecido por dias não pode travar concluir/parar/trocar: aponta só
    # o que ainda cabe nas 24h daquele dia (dia cheio = descarta, sem erro).
    used = db.query_one("SELECT COALESCE(sum(minutes), 0)::int AS m FROM time_entries WHERE user_id = %s AND day = %s",
                        (user["user_id"], day))["m"]
    minutes = min(minutes, 1440 - used)
    db.execute("DELETE FROM task_timers WHERE user_id = %s", (user["user_id"],))
    if minutes < 1:
        return None
    entry = log_time(t["task_id"], TimeIn(minutes=minutes, day=day, note="cronômetro"), user=user)
    return {**entry, "task_id": t["task_id"]}


@router.get("")
def get_timer(user=Depends(active_user)):
    return {"timer": running_timer(user["user_id"])}


@router.post("/start")
def start(data: TimerIn, user=Depends(active_user_csrf)):
    task = audit.worklog_snapshot(data.task_id, user["user_id"])
    if not task:
        raise HTTPException(status_code=404, detail="tarefa não encontrada")
    if task["status"] == "done":
        raise HTTPException(status_code=400, detail="a tarefa já está concluída")
    current = running_timer(user["user_id"])
    if current and current["task_id"] == data.task_id:
        return {"timer": current, "stopped": None}
    stopped = stop_running(user)  # trocar de tarefa aponta o tempo da anterior
    db.execute("INSERT INTO task_timers (user_id, task_id) VALUES (%s, %s)", (user["user_id"], data.task_id))
    if task["status"] == "todo":  # quem começa a cronometrar está fazendo (edição comum, desfazível)
        db.execute("UPDATE worklog_tasks SET status = 'in_progress' WHERE id = %s AND user_id = %s",
                   (data.task_id, user["user_id"]))
        audit.record(user, "worklog.update", "worklog", data.task_id, before=task,
                     after=audit.worklog_snapshot(data.task_id, user["user_id"]))
    # Entidade própria: não conta como "última ação da tarefa" para o desfazer.
    audit.record(user, "timer.start", "timer", data.task_id, after={"task_id": data.task_id, "title": task["title"]})
    return {"timer": running_timer(user["user_id"]), "stopped": stopped}


@router.post("/stop")
def stop(user=Depends(active_user_csrf)):
    if not running_timer(user["user_id"]):
        raise HTTPException(status_code=409, detail="nenhum cronômetro rodando")
    # stopped = None: o dia daquele cronômetro já tinha 24h apontadas (nada a somar).
    return {"timer": None, "stopped": stop_running(user)}


@router.delete("")
def discard(user=Depends(active_user_csrf)):
    t = running_timer(user["user_id"])
    if not t:
        raise HTTPException(status_code=409, detail="nenhum cronômetro rodando")
    db.execute("DELETE FROM task_timers WHERE user_id = %s", (user["user_id"],))
    audit.record(user, "timer.discard", "timer", t["task_id"], after={"task_id": t["task_id"], "title": t["title"]})
    return {"timer": None}
