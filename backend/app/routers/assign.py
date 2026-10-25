"""Atribuição de tarefas: o Atribuidor manda uma tarefa para quem consentiu.

A tarefa nasce na conta de quem recebe (ele é o dono: edita, conclui, exclui)
com "atribuída por". Quem atribuiu acompanha o status em "Tarefas que
atribuí", sem editar. Cada atribuição manda um e-mail para quem recebe.
Pelo app ou por chave de API/MCP (escopo de escrita), só com o papel.
"""
import logging
import threading

from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db, mailer, people
from ..config import config
from ..deps import require_assigner, require_assigner_csrf, require_people_list
from ..labels import PRIO_PT
from ..schemas import AssignIn
from ..services import app_today

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
    m.link = "/index.html#/tarefas"
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
                                      assigned_by, assigned_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now()) RETURNING id""",
        (target["id"], data.title, data.description, data.due_date, data.priority, data.ticket,
         data.after_hours, user["user_id"]),
    )
    tid = row["id"]
    by_name = people.profile(user["user_id"])["name"]
    to_name = people.profile(target["id"])["name"]
    snap = audit.worklog_snapshot(tid, target["id"])
    audit.record(user, "worklog.assign", "worklog", tid, after={**snap, "by": by_name}, user_id=target["id"])
    audit.record(user, "assign.send", "assignment", tid,
                 after={"title": data.title, "to": to_name, "to_email": target["email"]})
    emailed = mailer.configured()
    if emailed:
        _spawn(target["email"], _assignment_mail({**snap, "due_date": data.due_date}, by_name))
    return {"id": tid, "to": to_name, "emailed": emailed}


@router.get("/sent")
def sent(user=Depends(require_assigner)):
    """Tarefas que esta pessoa atribuiu, com o status atual (as mais recentes)."""
    rows = db.query_all(
        """SELECT w.id, w.title, w.status, w.due_date, w.assigned_at, w.completed_at, w.priority,
                  w.user_id AS to_id, u.email AS to_email
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
    return rows
