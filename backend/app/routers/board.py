from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import db
from ..deps import active_user, active_user_csrf
from ..services import BOARD_DONE_LIMIT, RETRO_DAYS, app_today, board_day_range, get_board, next_work_day, work_mask

router = APIRouter(prefix="/api/board", tags=["board"])


def check_board_day(day: Optional[date]) -> Optional[date]:
    """Dia pedido para as recorrentes: hoje ou até RETRO_DAYS dias atrás."""
    if day is None:
        return None
    min_day, today = board_day_range(app_today())
    if not (min_day <= day <= today):
        raise HTTPException(status_code=400, detail=f"só dá para marcar rotinas dos últimos {RETRO_DAYS} dias")
    return day


@router.get("")
def board(
    day: Optional[date] = Query(default=None),
    project: Optional[int] = Query(default=None, ge=0, description="0 = sem projeto"),
    done_offset: int = Query(default=0, ge=0, le=1000000, description="Concluídas: pula as N mais recentes (páginas)"),
    done_limit: int = Query(default=BOARD_DONE_LIMIT, ge=1, le=BOARD_DONE_LIMIT, description="Concluídas por resposta; o total vem em done_total"),
    user=Depends(active_user),
):
    return get_board(user["user_id"], check_board_day(day), project, done_offset, done_limit)


# ------------------------------------------------------- primeiro amanhã --

FIRST_MAX = 3


class FirstIn(BaseModel):
    # Até 3 tarefas abertas da pessoa; lista vazia = nenhuma (desfaz a escolha do dia).
    ids: list[int] = Field(default_factory=list, max_length=FIRST_MAX)
    day: Optional[date] = None  # padrão: o próximo dia útil (first_day de GET /api/board)


def first_day(user_id: int) -> date:
    return next_work_day(app_today(), work_mask(user_id))


def set_first(user_id: int, day: date, ids: list[int], strict: bool = True) -> list[int]:
    """A escolha do dia `day` passa a ser exatamente `ids` (as tarefas abertas da
    pessoa, na ordem dada; repetidas contam uma vez). strict: id que não é uma
    tarefa aberta da pessoa = 400 (a revisão da semana só ignora)."""
    ids = list(dict.fromkeys(ids))[:FIRST_MAX]
    ok = {r["id"] for r in db.query_all(
        "SELECT id FROM worklog_tasks WHERE user_id = %s AND status <> 'done' AND id = ANY(%s)", (user_id, ids))} if ids else set()
    if strict and len(ok) != len(ids):
        raise HTTPException(status_code=400, detail="só tarefas suas em aberto (concluída ou de outra pessoa não entra); atualize a tela")
    ids = [i for i in ids if i in ok]
    db.execute("UPDATE worklog_tasks SET first_on = NULL WHERE user_id = %s AND first_on = %s AND NOT (id = ANY(%s))",
               (user_id, day, ids))
    if ids:
        db.execute("UPDATE worklog_tasks SET first_on = %s WHERE user_id = %s AND id = ANY(%s)", (day, user_id, ids))
    return ids


@router.put("/first")
def put_first(data: FirstIn, user=Depends(active_user_csrf)):
    """"Primeiro amanhã": até 3 tarefas para começar o próximo dia útil. Nesse
    dia elas abrem as abertas do Hoje (e de Tarefas) com um selo; passado o dia,
    ou concluídas, saem sozinhas. Vale em todos os aparelhos. `day` (opcional)
    entre amanhã e daqui a 7 dias."""
    uid = user["user_id"]
    today = app_today()
    day = data.day or first_day(uid)
    if not (today < day <= today + timedelta(days=7)):
        raise HTTPException(status_code=400, detail="o dia do “Primeiro amanhã” vai de amanhã a daqui a 7 dias")
    return {"day": day, "ids": set_first(uid, day, data.ids)}
