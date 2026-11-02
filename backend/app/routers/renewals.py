"""Vencimentos: certificados, licenças, domínios, garantias e contratos que
vencem numa data. Avisam com antecedência no Hoje, no e-mail da manhã e no
calendário — sem consultar nada de fora (a data é a que a pessoa informou).

Compartilhado com uma equipe (sql/044, opcional): quem criou escolhe UMA das
equipes dele; todo membro atual vê o vencimento (marcado com o nome da equipe),
pode "Renovei" (a nova data, registrada no histórico de quem criou com o nome de
quem fez) e "Virar tarefa" (na conta de cada um). Só quem criou (ou um admin que
o enxerga) edita o resto ou exclui. Sair da equipe = deixa de ver. O aviso vai a
cada membro uma vez (agenda.py grava por pessoa). As regras de "quem é da
equipe" ficam em teams.py.
"""
from fastapi import APIRouter, Depends, HTTPException

from .. import audit, db, teams
from ..deps import active_user, active_user_csrf
from ..people import profile
from ..schemas import RenewalIn, RenewalUpdate
from datetime import timedelta

from ..services import app_today, is_work_day, work_mask

router = APIRouter(prefix="/api/renewals", tags=["renewals"])

COLS = ("r.id, r.label, r.expires_on, r.warn_days, r.project_id, r.note, r.renew_months, p.name AS project_name,"
        " r.team_id, tm.name AS team_name, r.user_id")


def warn_start(expires_on, warn_days: int, mask: int):
    """Primeiro dia do aviso; caindo em dia não útil, antecipa para o último dia útil
    (um aviso curto não some no fim de semana)."""
    d = expires_on - timedelta(days=warn_days)
    for _ in range(7):
        if is_work_day(d, mask):
            return d
        d -= timedelta(days=1)
    return d


def _visible_sql(uid: int) -> str:
    """Os dele, mais os compartilhados com uma equipe ativa de que ele é membro."""
    return f"(r.user_id = {int(uid)} OR (r.team_id IS NOT NULL AND {teams.member_of_sql(int(uid), 'r.team_id')}))"


def _is_admin(user: dict) -> bool:
    return "admin" in (user.get("roles") or [])


def list_for(uid: int) -> list[dict]:
    """Todos os visíveis, do que vence primeiro ao último, com dias até vencer e se já está no aviso.
    Os de outra pessoa (da equipe) vêm sem projeto (é o projeto de quem criou) e com `mine` falso."""
    today = app_today()
    mask = work_mask(uid)
    rows = db.query_all(
        f"""SELECT {COLS} FROM renewals r LEFT JOIN projects p ON p.id = r.project_id
                 LEFT JOIN teams tm ON tm.id = r.team_id AND tm.archived_at IS NULL
             WHERE {_visible_sql(uid)} ORDER BY r.expires_on, r.id""")
    owners: dict[int, str] = {}
    for r in rows:
        r["mine"] = r["user_id"] == uid
        if not r["mine"]:
            r["project_id"] = r["project_name"] = None
            owners.setdefault(r["user_id"], profile(r["user_id"])["name"])
        r["owner_name"] = None if r["mine"] else owners[r["user_id"]]
        del r["user_id"]
        r["days_left"] = (r["expires_on"] - today).days
        r["warn_from"] = warn_start(r["expires_on"], r["warn_days"], mask)
        r["warning"] = today >= r["warn_from"]
    return rows


def _row(rid: int, user: dict) -> dict:
    """O vencimento, se a pessoa o enxerga (senão 404: nem confirma que existe).
    `can_edit`: quem criou, ou um admin que o enxerga."""
    r = db.query_one(
        f"""SELECT r.id, r.user_id, r.team_id FROM renewals r
             WHERE r.id = %s AND {_visible_sql(user['user_id'])}""", (rid,))
    if not r:
        raise HTTPException(status_code=404, detail="não encontrado")
    r["can_edit"] = r["user_id"] == user["user_id"] or _is_admin(user)
    return r


def _check_team(uid: int, team_id, keep=None) -> None:
    """Só as equipes dele (o admin master, qualquer uma); `keep` = a que já estava."""
    if team_id is None or team_id == keep:
        return
    if not any(t["id"] == team_id for t in teams.choosable(uid)):
        raise HTTPException(status_code=400, detail="equipe não encontrada")


def _check_project(uid: int, project_id) -> None:
    if project_id is not None and not db.query_one(
            "SELECT 1 FROM projects WHERE id = %s AND user_id = %s", (project_id, uid)):
        raise HTTPException(status_code=400, detail="projeto não encontrado")


def _snap(rid: int, owner: int):
    return db.query_one("SELECT id, label, expires_on, warn_days, project_id, note, renew_months, team_id FROM renewals WHERE id = %s AND user_id = %s",
                        (rid, owner))


@router.get("/teams")
def team_options(user=Depends(active_user)):
    """As equipes com que ele pode compartilhar um vencimento (vazio = o campo nem aparece)."""
    return {"teams": teams.choosable(user["user_id"])}


@router.get("")
def list_renewals(user=Depends(active_user)):
    return list_for(user["user_id"])


@router.post("", status_code=201)
def create(data: RenewalIn, user=Depends(active_user_csrf)):
    uid = user["user_id"]
    _check_project(uid, data.project_id)
    _check_team(uid, data.team_id)
    row = db.query_one(
        """INSERT INTO renewals (user_id, label, expires_on, warn_days, project_id, note, renew_months, team_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (uid, data.label.strip(), data.expires_on, data.warn_days, data.project_id, (data.note or "").strip() or None,
         data.renew_months, data.team_id))
    audit.record(user, "renewal.create", "renewal", row["id"], after=_snap(row["id"], uid))
    return {"id": row["id"]}


def _audit(user: dict, owner: int, action: str, rid: int, before=None, after=None) -> None:
    """No histórico de quem criou; se foi outro membro, com o nome de quem fez ("por")."""
    if owner == user["user_id"]:
        audit.record(user, action, "renewal", rid, before=before, after=after)
        return
    por = profile(user["user_id"])["name"]
    audit.record(user, action, "renewal", rid, before=before, after={**(after or before or {}), "por": por}, user_id=owner)


@router.patch("/{rid}")
def update(rid: int, data: RenewalUpdate, user=Depends(active_user_csrf)):
    """Editar ou renovar (nova data de vencimento). Outro membro da equipe só renova (expires_on)."""
    uid = user["user_id"]
    row = _row(rid, user)
    owner = row["user_id"]
    sent = data.model_fields_set
    if not row["can_edit"] and sent - {"expires_on"}:
        raise HTTPException(status_code=403, detail="só quem criou o vencimento altera isso; você pode informar a nova data (Renovei)")
    before = _snap(rid, owner)
    fields, values = [], []
    for col in ("label", "expires_on", "warn_days"):
        if getattr(data, col) is not None:
            fields.append(f"{col} = %s")
            values.append(getattr(data, col).strip() if col == "label" else getattr(data, col))
    if "project_id" in sent:
        _check_project(owner, data.project_id)
        fields.append("project_id = %s")
        values.append(data.project_id)
    if "team_id" in sent:
        _check_team(uid, data.team_id, keep=before["team_id"])
        fields.append("team_id = %s")
        values.append(data.team_id)
    if "renew_months" in sent:
        fields.append("renew_months = %s")
        values.append(data.renew_months)
    if "note" in sent:
        fields.append("note = %s")
        values.append((data.note or "").strip() or None)
    if not fields:
        raise HTTPException(status_code=400, detail="nada para atualizar")
    db.execute(f"UPDATE renewals SET {', '.join(fields)} WHERE id = %s AND user_id = %s", (*values, rid, owner))
    after = _snap(rid, owner)
    action = "renewal.renew" if after["expires_on"] != before["expires_on"] else "renewal.update"
    _audit(user, owner, action, rid, before, after)
    return {"ok": True}


@router.delete("/{rid}")
def delete(rid: int, user=Depends(active_user_csrf)):
    row = _row(rid, user)
    if not row["can_edit"]:
        raise HTTPException(status_code=403, detail="só quem criou o vencimento pode excluí-lo")
    owner = row["user_id"]
    before = _snap(rid, owner)
    db.execute("DELETE FROM renewals WHERE id = %s AND user_id = %s", (rid, owner))
    _audit(user, owner, "renewal.delete", rid, before)
    return {"ok": True}
