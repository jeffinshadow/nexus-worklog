"""Atribuição de tarefas: o Atribuidor manda uma tarefa para quem consentiu.

A tarefa nasce na conta de quem recebe (ele é o dono: edita, conclui, exclui)
com "atribuída por". Quem atribuiu acompanha o status em "Tarefas que
atribuí" e, enquanto ela está "a fazer" e sem nada registrado, ainda pode
corrigir título, prazo e prioridade ou cancelar o envio (engano). Depois disso
é só de quem recebeu. Excluída ou cancelada, a linha continua na lista com o
que aconteceu (vem do histórico, 60 dias). Cada atribuição manda um e-mail.
Pelo app ou por chave de API/MCP (escopo de escrita), só com o papel.
"""
import logging
import threading

from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db, mailer, people, push
from ..config import config
from ..deps import require_assigner, require_assigner_csrf, require_people_list
from ..labels import PRIO_PT
from ..schemas import AssignEditIn, AssignIn
from ..services import app_today, app_tz, default_project

router = APIRouter(prefix="/api/assign", tags=["assign"])
log = logging.getLogger("uvicorn.error")


@router.get("/people")
def list_people(user=Depends(require_people_list)):
    """Contas com registro próprio e se aceitam receber tarefas (desde quando)."""
    rows = db.query_all(
        """SELECT u.id, u.email, u.accepts_assignments_at
             FROM users u
            WHERE EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'user')
            ORDER BY u.accepts_assignments_at IS NULL, lower(u.email)""")
    return [{**r, "accepts": r["accepts_assignments_at"] is not None, **people.profile(r["id"])} for r in rows]


def _assignment_mail(task: dict, by_name: str):
    from ..notify import Mail  # import tardio: notify importa rotas
    m = Mail(f"Nova tarefa para você: {task['title']}", f"{by_name} atribuiu uma tarefa a você",
             "Ela já está nas suas tarefas no Nexus.")
    m.reason = "Você recebe este e-mail porque aceitou receber tarefas atribuídas (Configurações > Conta)."
    m.settings_tab = "conta"
    m.link = f"/#/tarefas?id={task['id']}"
    itens = [task["title"]]
    if task.get("description"):
        itens.append(task["description"])
    if task.get("due_date"):
        itens.append(f"Prazo: {task['due_date'].strftime('%d/%m/%Y')}")
    if task.get("priority") != 2:
        itens.append(f"Prioridade {PRIO_PT[task['priority']]}")
    if task.get("ticket"):
        itens.append(f"Chamado {task['ticket']}")
    m.blocks = [("Tarefa", itens)]
    return m


def _send(to: str, mail) -> None:
    try:
        mailer.send(to, mail.subject, mail.text(), mail.html())
    except Exception as e:  # noqa: BLE001 — a tarefa já foi atribuída; o e-mail é aviso
        log.warning("e-mail de atribuição para %s falhou: %s", to, e)


def _spawn(to: str, mail) -> None:
    """Envio fora da requisição (o SMTP pode levar segundos)."""
    threading.Thread(target=_send, args=(to, mail), daemon=True).start()


@router.post("", status_code=201)
def assign(data: AssignIn, user=Depends(require_assigner_csrf)):
    if data.user_id == user["user_id"]:
        raise HTTPException(status_code=400, detail="para você mesmo, crie a tarefa normalmente")
    target = db.query_one(
        """SELECT u.id, u.email, u.accepts_assignments_at FROM users u
            WHERE u.id = %s AND EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'user')""",
        (data.user_id,),
    )
    if not target:
        raise HTTPException(status_code=404, detail="usuário não encontrado")
    if target["accepts_assignments_at"] is None:
        raise HTTPException(status_code=403, detail="essa pessoa não aceitou receber tarefas atribuídas")
    row = db.query_one(
        """INSERT INTO worklog_tasks (user_id, title, description, due_date, priority, ticket, after_hours,
                                      assigned_by, assigned_at, project_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), %s) RETURNING id""",
        (target["id"], data.title, data.description, data.due_date, data.priority, data.ticket,
         data.after_hours, user["user_id"], default_project(target["id"])),  # o projeto padrão de quem recebe
    )
    tid = row["id"]
    by_name = people.profile(user["user_id"])["name"]
    to_name = people.profile(target["id"])["name"]
    snap = audit.worklog_snapshot(tid, target["id"])
    audit.record(user, "worklog.assign", "worklog", tid, after={**snap, "by": by_name}, user_id=target["id"])
    audit.record(user, "assign.send", "assignment", tid,
                 after={"title": data.title, "to": to_name, "to_email": target["email"], "to_id": target["id"]})
    emailed = mailer.configured()
    if emailed:
        _spawn(target["email"], _assignment_mail({**snap, "due_date": data.due_date}, by_name))
    threading.Thread(target=push.notify_assigned, args=(target["id"], {"id": tid, "title": data.title}, by_name), daemon=True).start()
    return {"id": tid, "to": to_name, "emailed": emailed}


def notify_assigner(task_id: int) -> None:
    """Tarefa atribuída acabou de ser concluída: avisa quem atribuiu, uma vez só
    (assigner_notified_at). Sem SMTP, só marca. Quem atribuiu também vê na lista."""
    row = db.query_one(
        """UPDATE worklog_tasks SET assigner_notified_at = now()
            WHERE id = %s AND status = 'done' AND assigned_by IS NOT NULL AND assigner_notified_at IS NULL
        RETURNING title, user_id, assigned_by, completed_at""",
        (task_id,),
    )
    if not row or not mailer.configured():
        return
    to = db.query_one("SELECT email FROM users WHERE id = %s", (row["assigned_by"],))
    if not to:
        return
    from ..notify import Mail
    quem = people.profile(row["user_id"])["name"]
    m = Mail(f"Concluída: {row['title']}", f"{quem} concluiu a tarefa que você atribuiu",
             "Ela aparece como concluída em Atribuir tarefas, no Nexus.")
    m.reason = "Você recebe este e-mail porque atribuiu esta tarefa pelo Nexus (um aviso por tarefa)."
    m.settings_tab = None
    m.link = "/#/atribuir"
    m.blocks = [("Tarefa", [row["title"], f"Concluída em {row['completed_at'].astimezone(app_tz()).strftime('%d/%m/%Y %H:%M')}"])]
    _spawn(to["email"], m)


@router.get("/sent")
def sent(user=Depends(require_assigner)):
    """Tarefas que esta pessoa atribuiu, com o status atual (as mais recentes).
    `editable`: ainda dá para corrigir ou cancelar. As que saíram da conta de
    quem recebeu continuam aqui (status "removed", com `ended`)."""
    rows = db.query_all(
        f"""SELECT w.id, w.title, w.status, w.due_date, w.assigned_at, w.completed_at, w.priority, w.blocked_reason,
                   w.user_id AS to_id, u.email AS to_email,
                   (w.status = 'todo' AND NOT EXISTS ({_STARTED.format(t="w.id")})) AS editable
              FROM worklog_tasks w JOIN users u ON u.id = w.user_id
             WHERE w.assigned_by = %s
             ORDER BY w.assigned_at DESC NULLS LAST, w.id DESC
             LIMIT 200""",
        (user["user_id"],),
    )
    today = app_today()
    for r in rows:
        r["to_name"] = people.profile(r.pop("to_id"))["name"]
        r["late"] = bool(r["due_date"] and r["status"] != "done" and r["due_date"] < today)
        r["ended"] = None
    rows += _removed(user["user_id"])
    rows.sort(key=lambda r: (r["assigned_at"] is not None, r["assigned_at"] or 0, r["id"]), reverse=True)
    return rows[:200]


# Quem recebeu já registrou algo na tarefa: tempo, anotação, checklist, foto, cronômetro.
_STARTED = """SELECT 1 FROM time_entries WHERE task_id = {t} UNION ALL
              SELECT 1 FROM task_notes WHERE task_id = {t} UNION ALL
              SELECT 1 FROM task_checklist WHERE task_id = {t} UNION ALL
              SELECT 1 FROM task_timers WHERE task_id = {t} UNION ALL
              SELECT 1 FROM photos WHERE task_id = {t} AND deleted_at IS NULL"""


def _removed(uid: int) -> list[dict]:
    """Atribuições (histórico de quem atribuiu, 60 dias) cuja tarefa não existe
    mais, com o que houve: excluída no histórico de quem recebeu, ou cancelada
    no de quem atribuiu. Sem registro (desfez o recebimento, conta excluída):
    "removed" sem data."""
    rows = db.query_all(
        """SELECT a.entity_id AS id, a.after->>'title' AS title, a.after->>'to' AS to_name,
                  a.after->>'to_email' AS to_email, a.created_at AS assigned_at, f.action AS end_action, f.at AS ended_at
             FROM audit_log a
             LEFT JOIN LATERAL (
                  SELECT d.action, d.created_at AS at, d.id FROM audit_log d
                   WHERE d.user_id = COALESCE((a.after->>'to_id')::bigint,
                                              (SELECT x.id FROM users x WHERE x.email = a.after->>'to_email'))
                     AND d.entity = 'worklog' AND d.entity_id = a.entity_id AND d.action = 'worklog.delete'
                  UNION ALL
                  SELECT d.action, d.created_at, d.id FROM audit_log d
                   WHERE d.user_id = a.user_id AND d.entity = 'assignment' AND d.entity_id = a.entity_id
                     AND d.action = 'assign.cancel'
                  ORDER BY id DESC LIMIT 1) f ON true
            WHERE a.user_id = %s AND a.action = 'assign.send' AND a.created_at > now() - interval '60 days'
              AND NOT EXISTS (SELECT 1 FROM worklog_tasks w WHERE w.id = a.entity_id)
            ORDER BY a.id DESC LIMIT 100""",
        (uid,),
    )
    kinds = {"worklog.delete": "deleted", "assign.cancel": "canceled"}
    return [{**r, "status": "removed", "due_date": None, "completed_at": None, "priority": 2,
             "blocked_reason": None, "late": False, "editable": False,
             "ended": {"kind": kinds.get(r.pop("end_action"), "removed"), "at": r.pop("ended_at")}}
            for r in rows]


def _own_sent(task_id: int, uid: int) -> dict:
    """A tarefa que esta pessoa atribuiu, se ainda dá para mexer: "a fazer" e
    sem nada registrado por quem recebeu. Depois disso é só de quem recebeu."""
    row = db.query_one(
        """SELECT w.id, w.user_id, w.status, w.title, u.email FROM worklog_tasks w JOIN users u ON u.id = w.user_id
            WHERE w.id = %s AND w.assigned_by = %s""", (task_id, uid))
    if not row:
        raise HTTPException(status_code=404, detail="tarefa não encontrada")
    if row["status"] != "todo" or db.query_one(_STARTED.format(t="%(t)s") + " LIMIT 1", {"t": task_id}):
        raise HTTPException(status_code=409, detail=STARTED_MSG)
    return row


STARTED_MSG = "a pessoa já começou esta tarefa e agora só ela pode alterá-la; combine direto com quem recebeu"


def _change_mail(title: str, by_name: str, verb: str, lines: list[str], link: str):
    from ..notify import Mail  # import tardio: notify importa rotas
    m = Mail(f"Tarefa {verb[:-2].lower()}ada: {title}", f"{by_name} {verb.lower()} uma tarefa que tinha atribuído a você",
             "Era uma das suas tarefas a fazer no Nexus.")
    m.reason = "Você recebe este e-mail porque aceitou receber tarefas atribuídas (Configurações > Conta)."
    m.settings_tab = "conta"
    m.link = link
    m.blocks = [("Tarefa", lines)]
    return m


@router.patch("/{task_id}")
def update_sent(task_id: int, data: AssignEditIn, user=Depends(require_assigner_csrf)):
    """Corrige título, prazo ou prioridade de uma tarefa atribuída que ainda não começou."""
    row = _own_sent(task_id, user["user_id"])
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None or k == "due_date"}
    if not changes:
        raise HTTPException(status_code=400, detail="nada para mudar")
    before = audit.worklog_snapshot(task_id, row["user_id"])
    sets = ", ".join(f"{k} = %({k})s" for k in changes)  # chaves fixas do schema
    if not db.execute(f"UPDATE worklog_tasks SET {sets} WHERE id = %(id)s AND assigned_by = %(by)s AND status = 'todo'",
                      {**changes, "id": task_id, "by": user["user_id"]}):
        raise HTTPException(status_code=409, detail=STARTED_MSG)
    after = audit.worklog_snapshot(task_id, row["user_id"])
    by_name = people.profile(user["user_id"])["name"]
    # No histórico de quem recebe (pode desfazer: a tarefa é dela) e no de quem atribuiu.
    audit.record(user, "worklog.assign_update", "worklog", task_id, before=before, after={**after, "by": by_name},
                 user_id=row["user_id"])
    audit.record(user, "assign.update", "assignment", task_id,
                 before={k: before[k] for k in ("title", "due_date", "priority")},
                 after={"title": after["title"], "due_date": after["due_date"], "priority": after["priority"],
                        "to": people.profile(row["user_id"])["name"]})
    if mailer.configured():
        lines = [after["title"]]
        if after["due_date"]:
            lines.append(f"Prazo: {after['due_date'].strftime('%d/%m/%Y')}")
        lines.append(f"Prioridade {PRIO_PT[after['priority']]}")
        _spawn(row["email"], _change_mail(after["title"], by_name, "Alterou", lines, f"/#/tarefas?id={task_id}"))
    return {"id": task_id, "title": after["title"], "due_date": after["due_date"], "priority": after["priority"]}


@router.post("/{task_id}/cancel")
def cancel_sent(task_id: int, user=Depends(require_assigner_csrf)):
    """Cancela uma atribuição feita por engano: a tarefa (ainda não começada)
    sai da conta de quem recebeu, que é avisada por e-mail."""
    row = _own_sent(task_id, user["user_id"])
    before = audit.worklog_snapshot(task_id, row["user_id"])
    if not db.execute("DELETE FROM worklog_tasks WHERE id = %s AND assigned_by = %s AND status = 'todo'",
                      (task_id, user["user_id"])):
        raise HTTPException(status_code=409, detail=STARTED_MSG)
    by_name = people.profile(user["user_id"])["name"]
    audit.record(user, "worklog.assign_cancel", "worklog", task_id, before={**before, "by": by_name},
                 user_id=row["user_id"])
    audit.record(user, "assign.cancel", "assignment", task_id,
                 before={"title": row["title"], "to": people.profile(row["user_id"])["name"]})
    if mailer.configured():
        _spawn(row["email"], _change_mail(row["title"], by_name, "Cancelou", [row["title"], "A tarefa saiu da sua lista; não precisa fazer nada."], "/#/tarefas"))
    return {"ok": True}
