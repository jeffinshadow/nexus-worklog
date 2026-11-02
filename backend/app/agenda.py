"""Avisos de agenda no feed e nos webhooks: o tempo chegou, não uma mudança.

  followup.due     uma tarefa aguardando chegou no dia de cobrar (follow_up_on = hoje)
  recurring.due    a hora de uma rotina com horário chegou e ela não foi marcada
  renewal.warning  um vencimento entrou no aviso (antecedência que a pessoa definiu)

São os mesmos cálculos do e-mail e das notificações da manhã (dia de cobrar,
rotina devida com pausa e agenda, vencimento no aviso). Cada aviso vira uma
linha no histórico da pessoa com actor "system" e entity "agenda" (entity_id =
id da tarefa, rotina ou vencimento): o feed (GET /api/history?after=) e os
webhooks entregam sem código novo, e o filtro de eventos funciona
("followup.*", "recurring.*"...). A tela de Histórico não mostra (não é algo
que alguém fez), e nada disso é desfazível.

Uma vez por ocorrência: `after.occurrence` (o dia de cobrar, o dia da rotina ou
a data do vencimento) entra num índice único (sql/037): reiniciar o processo
ou rodar duas vezes não repete. Só para quem tem um webhook ligado ou uma chave
de API ativa (quem pode ler o feed); os outros não ganham linhas à toa.
"""
import logging
from datetime import datetime

from psycopg.types.json import Jsonb

from . import audit, db
from .services import is_pending, rotinas, work_mask

log = logging.getLogger("uvicorn.error")

EVENTS = ("followup.due", "recurring.due", "renewal.warning")
WARN_GRACE_DAYS = 7
DEFAULT_MORNING_HOUR = 8  # a mesma hora padrão das notificações da manhã (push.DEFAULT_PREFS)


def _users() -> list[int]:
    return [r["id"] for r in db.query_all(
        """SELECT u.id FROM users u
            WHERE NOT u.must_change_password
              AND (EXISTS (SELECT 1 FROM webhooks w WHERE w.user_id = u.id AND w.disabled_at IS NULL)
                   OR EXISTS (SELECT 1 FROM api_tokens t WHERE t.user_id = u.id AND t.revoked_at IS NULL
                                AND (t.expires_at IS NULL OR t.expires_at > now())))
            ORDER BY u.id""")]


def _emit(uid: int, action: str, item_id: int, occurrence, data: dict) -> bool:
    """Grava o aviso (uma vez por item e ocorrência). True = era novo."""
    after = audit._jsonable({**data, "occurrence": occurrence})
    return bool(db.query_one(
        """INSERT INTO audit_log (user_id, actor, action, entity, entity_id, after)
           VALUES (%s, 'system', %s, 'agenda', %s, %s)
           ON CONFLICT (user_id, action, entity_id, (after->>'occurrence')) WHERE actor = 'system' DO NOTHING
           RETURNING id""",
        (uid, action, item_id, Jsonb(after))))


def _morning_hour(uid: int) -> int:
    row = db.query_one("SELECT morning_hour FROM push_prefs WHERE user_id = %s", (uid,))
    return row["morning_hour"] if row else DEFAULT_MORNING_HOUR


def _followups(uid: int, today) -> list[str]:
    out = []
    for t in db.query_all(
            """SELECT id FROM worklog_tasks
                WHERE user_id = %s AND status = 'blocked' AND follow_up_on = %s ORDER BY id""", (uid, today)):
        snap = audit.worklog_snapshot(t["id"], uid)
        if snap and _emit(uid, "followup.due", t["id"], today, snap):
            out.append(f"followup:{t['id']}")
    return out


def _renewals(uid: int, today) -> list[str]:
    from .routers.renewals import list_for  # import tardio: o router importa services
    out = []
    for r in list_for(uid):
        # No dia em que entra no aviso (até WARN_GRACE_DAYS depois, se o servidor
        # estava fora): um vencimento antigo não dispara ao criar a 1ª chave.
        if not r["warning"] or (today - r["warn_from"]).days > WARN_GRACE_DAYS:
            continue
        data = {k: r[k] for k in ("id", "label", "expires_on", "warn_days", "project_id", "note", "renew_months", "days_left")}
        if _emit(uid, "renewal.warning", r["id"], r["expires_on"], data):
            out.append(f"renewal:{r['id']}")
    return out


def _routines(uid: int, now: datetime) -> list[str]:
    today, out = now.date(), []
    mask = work_mask(uid)
    feitas = {r["task_id"] for r in db.query_all(
        "SELECT task_id FROM recurring_completions WHERE user_id = %s AND completed_date = %s", (uid, today))}
    for r in rotinas(uid):
        if (not r["remind_at"] or r["id"] in feitas or not (r["start_d"] <= today <= r["end_d"])
                or not is_pending(r, today, mask)):
            continue
        if now < datetime.combine(today, r["remind_at"], tzinfo=now.tzinfo):
            continue
        snap = audit.recurring_snapshot(r["id"], uid)
        if snap and _emit(uid, "recurring.due", r["id"], today, {**snap, "day": today}):
            out.append(f"recurring:{r['id']}")
    return out


def run_once(now: datetime) -> list[tuple[int, str]]:
    """Uma passada no horário local `now` (com fuso). Devolve o que gravou."""
    done = []
    for uid in _users():
        try:
            done += [(uid, x) for x in _routines(uid, now)]
            if now.hour >= _morning_hour(uid):  # cobrar e vencimentos: de manhã, como o e-mail e o push
                done += [(uid, x) for x in _followups(uid, now.date())]
                done += [(uid, x) for x in _renewals(uid, now.date())]
        except Exception:  # noqa: BLE001 — uma pessoa com erro não para as outras
            log.exception("avisos de agenda do usuário %s falharam nesta passada", uid)
    return done
