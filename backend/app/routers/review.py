"""Revisão semanal guiada (Hoje > Esta semana, ou o convite do assistente no
último dia útil). As mudanças nas tarefas (prazo, aguardando, concluir, como
resolveu, prioridade) usam as rotas de sempre (/api/worklog); aqui só a leitura,
o texto final e o registro de que a revisão foi feita ou dispensada."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import review
from ..deps import active_user, active_user_csrf

router = APIRouter(prefix="/api/review", tags=["review"])


class WeekDoneIn(BaseModel):
    # Prioridades da próxima semana (ids de tarefas abertas da pessoa; até 3).
    next: list[int] = Field(default_factory=list, max_length=review.NEXT_MAX)


@router.get("/week")
def week(user=Depends(active_user)):
    """O que fechou, o que ficou (aberto e aguardando), sugestões para a próxima
    semana, tarefas paradas e se a revisão desta semana já foi feita."""
    return review.week_review(user["user_id"])


@router.post("/week/done")
def week_done(data: WeekDoneIn | None = None, user=Depends(active_user_csrf)):
    """Registra a revisão da semana (o assistente para de convidar) e devolve o
    texto da semana pronto para copiar."""
    uid = user["user_id"]
    st = review.mark(uid, "done_at")
    return {"done_at": st["done_at"], "text": review.week_text(uid, (data.next if data else []))}


@router.post("/week/dismiss")
def week_dismiss(user=Depends(active_user_csrf)):
    """"Agora não" no convite do assistente: não volta nesta semana."""
    return review.mark(user["user_id"], "dismissed_at")
