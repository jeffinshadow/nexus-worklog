from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db, push
from ..config import config
from ..deps import active_user, active_user_csrf, deny_append
from ..schemas import OrderIn, PauseIn, RecurringIn, RecurringUpdate, SnoozeIn, ToggleIn
from ..services import app_today, app_tz, is_pending, recurring_vigente, rotinas, work_mask
from .board import check_board_day
from .worklog import task_reminders

router = APIRouter(prefix="/api/recurring", tags=["recurring"])


@router.get("/reminders")
def reminders(user=Depends(active_user)):
    """Rotinas com horário devidas hoje (para o lembrete da interface tocar
    perto do horário até a rotina ser marcada). Pausada não lembra. `tasks`:
    os lembretes com hora das tarefas abertas (de 24 h atrás a 12 h à frente,
    sem os já vistos), com até quando estão adiados."""
    uid, today = user["user_id"], app_today()
    mask = work_mask(uid)
    feitas = {r["task_id"] for r in db.query_all(
        "SELECT task_id FROM recurring_completions WHERE user_id = %s AND completed_date = %s", (uid, today))}
    return {"today": today, "items": [
        {"id": r["id"], "label": r["label"], "remind_at": r["remind_at"].strftime("%H:%M"),
         "require_note": r["require_note"], "steps": r["steps"] or [], "done": r["id"] in feitas}
        for r in rotinas(uid)
        if r["remind_at"] and r["start_d"] <= today <= r["end_d"] and is_pending(r, today, mask)],
        "tasks": task_reminders(uid)}


@router.post("", status_code=201)
def create(data: RecurringIn, user=Depends(active_user_csrf)):
    row = db.query_one(
        """
        INSERT INTO recurring_tasks (user_id, label, position, freq, weekdays, month_day, interval_days, require_note, remind_at,
                                     steps)
        VALUES (%(uid)s, %(label)s,
                (SELECT COALESCE(MAX(position), 0) + 1
                   FROM recurring_tasks WHERE user_id = %(uid)s),
                %(freq)s, %(weekdays)s, %(month_day)s, %(interval_days)s, %(require_note)s, %(remind_at)s, %(steps)s)
        RETURNING id, label, position, active, freq, weekdays, month_day, interval_days, require_note, remind_at, steps
        """,
        {"uid": user["user_id"], "label": data.label, "require_note": data.require_note, "remind_at": data.remind_at,
         "steps": data.steps,
         **(data.agenda() if data.freq else {"freq": "daily", "weekdays": None, "month_day": None, "interval_days": None})},
    )
    audit.record(user, "recurring.create", "recurring", row["id"],
                 after=audit.recurring_snapshot(row["id"], user["user_id"]))
    return row


def active_order(uid: int) -> list[int]:
    return [r["id"] for r in db.query_all(
        "SELECT id FROM recurring_tasks WHERE user_id = %s AND active ORDER BY position, id", (uid,))]


def renumber(uid: int, ids: list[int]) -> None:
    for i, rid in enumerate(ids, start=1):
        db.execute("UPDATE recurring_tasks SET position = %s WHERE id = %s AND user_id = %s", (i, rid, uid))


@router.post("/order")
def order(data: OrderIn, user=Depends(active_user_csrf)):
    """Ordem das rotinas no Hoje: as ativas, na ordem nova. Uma que não veio na
    lista (criada em outro aparelho) fica depois, na ordem que tinha. A anterior
    fica no histórico, com desfazer. Rotina nova entra no fim."""
    uid = user["user_id"]
    ids = active_order(uid)
    if len(set(data.ids)) != len(data.ids):
        raise HTTPException(status_code=400, detail="rotina repetida na lista")
    if not set(data.ids) <= set(ids):
        raise HTTPException(status_code=400, detail="rotina não encontrada (pode ter sido excluída)")
    new = data.ids + [i for i in ids if i not in data.ids]
    if new == ids:
        return {"ok": True}
    renumber(uid, new)
    audit.record(user, "recurring.order", "recurring_order", uid, before={"ids": ids}, after={"ids": new})
    return {"ok": True}


def _last_time(uid: int, old: dict, until=None):
    """"Depois da última vez": a última marcação da rotina antiga (antes de hoje,
    ou de `until`, o dia da troca; a desse dia passa para a nova). Sem marcação,
    se a antiga já era 'after', o ponto de onde ela contava. A nova segue
    contando dali (última + N novo)."""
    r = db.query_one(
        """SELECT (SELECT max(completed_date) FROM recurring_completions
                    WHERE task_id = t.id AND user_id = t.user_id AND completed_date < %s) AS last,
                  t.freq, t.after_from, (t.created_at AT TIME ZONE %s)::date AS start_d
             FROM recurring_tasks t WHERE t.id = %s AND t.user_id = %s""",
        (until or app_today(), config.APP_TZ, old["id"], uid))
    if not r:
        return None
    if r["last"]:
        return max(r["last"], r["after_from"]) if r["after_from"] else r["last"]
    return (r["after_from"] or r["start_d"]) if r["freq"] == "after" else None


def refresh_after_from(uid: int, rid: int) -> None:
    """Marcar ou desmarcar um dia passado numa rotina já substituída (troca de
    agenda) move a "última vez" de onde a sucessora 'after' conta."""
    for _ in range(50):
        nxt = db.query_one(
            """SELECT r.id, r.freq, (r.created_at AT TIME ZONE %s)::date AS start_d
                 FROM audit_log a JOIN recurring_tasks r ON r.id = a.entity_id AND r.user_id = a.user_id
                WHERE a.user_id = %s AND a.action = 'recurring.replace' AND a.undone_at IS NULL
                  AND (a.after->>'replaced')::bigint = %s
                ORDER BY a.id DESC LIMIT 1""", (config.APP_TZ, uid, rid))
        if not nxt:
            return
        if nxt["freq"] == "after":
            db.execute("UPDATE recurring_tasks SET after_from = %s WHERE id = %s AND user_id = %s",
                       (_last_time(uid, {"id": rid}, nxt["start_d"]), nxt["id"], uid))
        rid = nxt["id"]


def replace_routine(user: dict, before: dict, new: dict, freeze: dict | None = None) -> int:
    """Encerra a rotina `before` hoje e cria outra (mesma posição) a partir de
    hoje com `new` (label + agenda): o passado da antiga não muda. `freeze`
    regrava a agenda da antiga (ex.: dias úteis antigos, congelados como
    semanal). A marcação de hoje passa para a nova. UMA ação no histórico
    ("recurring.replace", na nova), desfeita por inteiro."""
    uid, old_id = user["user_id"], before["id"]
    sets = ["active = false", "deactivated_at = now()"] + [f"{k} = %s" for k in (freeze or {})]
    db.execute(f"UPDATE recurring_tasks SET {', '.join(sets)} WHERE id = %s AND user_id = %s",
               tuple((freeze or {}).values()) + (old_id, uid))
    freq = new.get("freq") or before.get("freq")
    row = db.query_one(
        """INSERT INTO recurring_tasks (user_id, label, position, freq, weekdays, month_day, interval_days, require_note,
                                        remind_at, steps, after_from)
           VALUES (%(uid)s, %(label)s, %(position)s, %(freq)s, %(weekdays)s, %(month_day)s, %(interval_days)s, %(require_note)s,
                   %(remind_at)s, %(steps)s, %(after_from)s)
           RETURNING id""",
        {"uid": uid, "position": before["position"], "weekdays": None, "month_day": None, "interval_days": None,
         "require_note": bool(before.get("require_note")), "remind_at": before.get("remind_at"), "steps": before.get("steps"),
         "after_from": _last_time(uid, before) if freq == "after" else None, **new})
    db.execute("UPDATE recurring_completions SET task_id = %s WHERE task_id = %s AND user_id = %s AND completed_date = %s",
               (row["id"], old_id, uid, app_today()))
    db.execute("UPDATE photos SET recurring_id = %s WHERE recurring_id = %s AND user_id = %s AND day = %s",
               (row["id"], old_id, uid, app_today()))  # as fotos de hoje vão junto com a marcação
    # A pausa em curso continua na nova (de hoje até o mesmo fim).
    db.execute("""INSERT INTO recurring_pauses (recurring_id, start_d, end_d)
                  SELECT %s, %s, end_d FROM recurring_pauses
                   WHERE recurring_id = %s AND start_d <= %s AND end_d >= %s""",
               (row["id"], app_today(), old_id, app_today(), app_today()))
    audit.record(user, "recurring.replace", "recurring", row["id"], before=before,
                 after={"replaced": old_id, **audit.recurring_snapshot(row["id"], uid)})
    return row["id"]


@router.patch("/{task_id}")
def update(task_id: int, data: RecurringUpdate, user=Depends(active_user_csrf)):
    """Nome e agenda. Trocar a agenda de uma rotina que já tem passado NÃO
    reescreve o passado: a atual é encerrada hoje e uma nova (mesmo nome e
    posição) começa hoje. A marcação de hoje, se houver, passa para a nova."""
    uid = user["user_id"]
    before = audit.recurring_snapshot(task_id, uid)
    if not before or not before["active"]:
        raise HTTPException(status_code=404, detail="rotina não encontrada (pode ter sido excluída)")
    agenda = data.agenda() if data.freq is not None else {}
    horario = "remind_at" in data.model_fields_set  # null tira o horário
    passos = "steps" in data.model_fields_set  # null ou [] tira os passos
    if data.label is None and not agenda and data.require_note is None and not horario and not passos:
        raise HTTPException(status_code=400, detail="nada mudou na rotina")
    today = app_today()
    muda_agenda = any(before[k] != v for k, v in agenda.items())
    tem_passado = before["created_at"].astimezone(app_tz()).date() < today

    if muda_agenda and tem_passado:
        new_id = replace_routine(user, before, {"label": data.label or before["label"], **agenda,
                                                **({"require_note": data.require_note} if data.require_note is not None else {}),
                                                **({"remind_at": data.remind_at} if horario else {}),
                                                **({"steps": data.steps} if passos else {})})
        return {"ok": True, "id": new_id, "replaced": task_id}

    fields, values = [], []
    if data.label is not None:
        fields.append("label = %s")
        values.append(data.label)
    if data.require_note is not None:
        fields.append("require_note = %s")
        values.append(data.require_note)
    if horario:
        fields.append("remind_at = %s")
        values.append(data.remind_at)
    if passos:
        fields.append("steps = %s")
        values.append(data.steps)
    for col, val in agenda.items():  # rotina criada hoje: ainda sem passado
        fields.append(f"{col} = %s")
        values.append(val)
    db.execute(f"UPDATE recurring_tasks SET {', '.join(fields)} WHERE id = %s AND user_id = %s",
               tuple(values) + (task_id, uid))
    audit.record(user, "recurring.update", "recurring", task_id, before=before,
                 after=audit.recurring_snapshot(task_id, uid))
    return {"ok": True, "id": task_id}


@router.delete("/{task_id}")
def deactivate(task_id: int, user=Depends(active_user_csrf)):
    # Soft-delete = desativar: preserva o historico em recurring_completions e
    # marca deactivated_at (so na transicao ativa->inativa).
    before = audit.recurring_snapshot(task_id, user["user_id"])
    updated = db.execute(
        """UPDATE recurring_tasks
              SET active = false,
                  deactivated_at = CASE WHEN active THEN now() ELSE deactivated_at END
            WHERE id = %s AND user_id = %s""",
        (task_id, user["user_id"]),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="rotina não encontrada (pode ter sido excluída)")
    audit.record(user, "recurring.deactivate", "recurring", task_id, before=before,
                 after=audit.recurring_snapshot(task_id, user["user_id"]))
    return {"ok": True}


@router.post("/{task_id}/toggle")
def toggle(task_id: int, data: ToggleIn, user=Depends(active_user_csrf)):
    owns = db.query_one(
        "SELECT 1 FROM recurring_tasks WHERE id = %s AND user_id = %s",
        (task_id, user["user_id"]),
    )
    if not owns:
        raise HTTPException(status_code=404, detail="rotina não encontrada (pode ter sido excluída)")

    # Marcação retroativa: hoje ou até RETRO_DAYS dias atrás (mesma janela do
    # quadro), e só em dia em que a rotina estava vigente.
    today = check_board_day(data.day) or app_today()
    if not recurring_vigente(task_id, user["user_id"], today):
        raise HTTPException(status_code=400, detail="a rotina não existia nesse dia")
    prev = db.query_one(
        "SELECT note FROM recurring_completions WHERE task_id = %s AND user_id = %s AND completed_date = %s",
        (task_id, user["user_id"], today),
    )
    was, old_note = prev is not None, (prev or {}).get("note")
    note = " ".join((data.note or "").split()) or None
    keep = "note" not in data.model_fields_set  # sem o campo: mantém; vazio ou null: apaga
    # Chave "só registrar": marca, mas não desmarca nem troca a evidência que já havia.
    deny_append(user, not data.done or (was and not keep and note != old_note))
    if data.done and not (note or (keep and old_note)) and db.query_one(
            "SELECT 1 FROM recurring_tasks WHERE id = %s AND require_note", (task_id,)):
        raise HTTPException(status_code=400, detail="esta rotina exige a evidência do que foi conferido")
    if data.done:
        db.execute(
            """INSERT INTO recurring_completions (task_id, user_id, completed_date, note)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (task_id, completed_date) DO UPDATE
                  SET note = CASE WHEN %s THEN recurring_completions.note ELSE EXCLUDED.note END""",
            (task_id, user["user_id"], today, note, keep),
        )
    else:
        db.execute(
            "DELETE FROM recurring_completions WHERE task_id = %s AND user_id = %s AND completed_date = %s",
            (task_id, user["user_id"], today),
        )
    new_note = (old_note if keep else note) if data.done else None
    if was != data.done:
        refresh_after_from(user["user_id"], task_id)
    if was != data.done or (data.done and new_note != old_note):
        audit.record(user, "recurring.toggle", "recurring", task_id,
                     before={"day": today, "done": was, "note": old_note},
                     after={"day": today, "done": data.done, "note": new_note})
    return {"ok": True, "done": data.done, "day": today, "note": new_note}


@router.post("/{task_id}/snooze")
def snooze(task_id: int, data: SnoozeIn, user=Depends(active_user_csrf)):
    """Adia o lembrete da rotina hoje (as notificações do aparelho esperam)."""
    if not db.query_one("SELECT 1 FROM recurring_tasks WHERE id = %s AND user_id = %s AND active", (task_id, user["user_id"])):
        raise HTTPException(status_code=404, detail="rotina não encontrada (pode ter sido excluída)")
    return {"until": push.snooze(user["user_id"], task_id, data.minutes)}


# ------------------------------------------------------------------ pausa --
# Férias, folga, prédio fechado: nos dias pausados a rotina não é devida (não
# é falta, não lembra, não entra em aviso); marcar conta como extra. A pausa
# vale de HOJE até `until` (inclusive) e volta sozinha no dia seguinte; nunca
# começa no passado, então os números já fechados não mudam.
PAUSE_MAX_DAYS = 366


def current_pause(task_id: int, today):
    """O período que cobre hoje (no máximo um), ou None."""
    return db.query_one(
        """SELECT id, start_d, end_d FROM recurring_pauses
            WHERE recurring_id = %s AND start_d <= %s AND end_d >= %s ORDER BY id DESC LIMIT 1""",
        (task_id, today, today))


def _active_routine(task_id: int, uid: int) -> dict:
    row = db.query_one("SELECT id, label FROM recurring_tasks WHERE id = %s AND user_id = %s AND active", (task_id, uid))
    if not row:
        raise HTTPException(status_code=404, detail="rotina não encontrada (pode ter sido excluída)")
    return row


@router.post("/{task_id}/pause")
def pause(task_id: int, data: PauseIn, user=Depends(active_user_csrf)):
    """Pausa a rotina de hoje até `until` (inclusive). Já pausada: muda o fim."""
    uid, today = user["user_id"], app_today()
    r = _active_routine(task_id, uid)
    if data.until < today:
        raise HTTPException(status_code=400, detail="a pausa começa hoje: escolha hoje ou um dia depois")
    if (data.until - today).days > PAUSE_MAX_DAYS:
        raise HTTPException(status_code=400, detail="a pausa pode ir até um ano a partir de hoje; escolha uma data mais próxima")
    cur = current_pause(task_id, today)
    if cur:
        db.execute("UPDATE recurring_pauses SET end_d = %s WHERE id = %s", (data.until, cur["id"]))
        new = {**cur, "end_d": data.until}
    else:
        new = db.query_one("""INSERT INTO recurring_pauses (recurring_id, start_d, end_d) VALUES (%s, %s, %s)
                              RETURNING id, start_d, end_d""", (task_id, today, data.until))
    audit.record(user, "recurring.pause", "recurring", task_id,
                 before={"label": r["label"], "pause": cur}, after={"label": r["label"], "pause": new})
    return {"ok": True, "paused_until": data.until}


@router.delete("/{task_id}/pause")
def resume(task_id: int, user=Depends(active_user_csrf)):
    """Retomar agora: a pausa termina ontem e hoje a rotina já é devida."""
    uid, today = user["user_id"], app_today()
    r = _active_routine(task_id, uid)
    cur = current_pause(task_id, today)
    if not cur:
        raise HTTPException(status_code=400, detail="a rotina não está pausada")
    db.execute("UPDATE recurring_pauses SET end_d = %s WHERE id = %s", (today - timedelta(days=1), cur["id"]))
    audit.record(user, "recurring.resume", "recurring", task_id,
                 before={"label": r["label"], "pause": cur},
                 after={"label": r["label"], "pause": {**cur, "end_d": today - timedelta(days=1)}})
    return {"ok": True, "paused_until": None}
