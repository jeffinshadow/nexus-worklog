"""Admin › Equipes (sql/043): cadastro das equipes, quem está em cada uma e o
admin master.

Equipes: criar, renomear, arquivar (não conta para nada, guarda os membros) e
excluir; membros em lote (a lista inteira) ou por pessoa (Admin › Contas ›
pessoa › Equipes…). Só o admin mexe; cada mudança fica no log de admin.
Quem vê e quem atribui para quem: visibility.py e assignable.py (com teams.py).

Admin master: o primeiro admin da instância, sempre exatamente um
(app_settings.master_user_id). Liga/desliga os próprios papéis "Vê a equipe" e
"Manda tarefas" aqui (desligados, nada de equipe aparece para ele). Transferir o
papel só pelo próprio master: senha + código de 6 dígitos mandado ao e-mail dele
(uso único, 10 minutos, 5 tentativas); quem recebe é avisado; log de admin.
"""
import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from psycopg.errors import UniqueViolation

from .. import audit, db, mailer, people, roles, teams
from ..deps import require_admin, require_admin_csrf
from ..schemas import MasterConfirmIn, MasterRolesIn, MasterTransferIn, TeamEditIn, TeamIn, UserTeamsIn
from ..security import login_limiter, token_hash, verify_password

router = APIRouter(prefix="/api/admin", tags=["admin"])
log = logging.getLogger("uvicorn.error")

CODE_TTL = timedelta(minutes=10)
CODE_ATTEMPTS = 5
NAME_TAKEN = "já existe uma equipe com esse nome"


def _ctx(admin: dict) -> dict:
    return {**admin, "actor": "admin"}


def _clean(name: str) -> str:
    n = " ".join((name or "").split())
    if not n:
        raise HTTPException(status_code=400, detail="dê um nome para a equipe")
    return n


def _team(team_id: int) -> dict:
    row = db.query_one("SELECT id, name, archived_at FROM teams WHERE id = %s", (team_id,))
    if not row:
        raise HTTPException(status_code=404, detail="equipe não encontrada")
    return row


def _members(team_id: int) -> list[dict]:
    rows = db.query_all("""SELECT u.id, u.email FROM team_members m JOIN users u ON u.id = m.user_id
                            WHERE m.team_id = %s""", (team_id,))
    out = [{"id": r["id"], "email": r["email"], "name": people.profile(r["id"])["name"]} for r in rows]
    return sorted(out, key=lambda r: (r["name"].lower(), r["email"]))


def _check_users(ids: list[int]) -> list[int]:
    ids = sorted(set(ids))
    if ids:
        n = db.query_one("SELECT count(*)::int AS n FROM users WHERE id = ANY(%s)", (ids,))["n"]
        if n != len(ids):
            raise HTTPException(status_code=400, detail="pessoa não encontrada")
    return ids


def check_teams(ids: list[int], archived_ok: bool = False) -> list[int]:
    """Valida ids de equipes (o convite e Equipes… da pessoa só vinculam a equipes ativas)."""
    ids = sorted(set(ids))
    if ids:
        rows = db.query_all(f"""SELECT id FROM teams WHERE id = ANY(%s) {'' if archived_ok else 'AND archived_at IS NULL'}""",
                            (ids,))
        if len(rows) != len(ids):
            raise HTTPException(status_code=400, detail="equipe não encontrada (ou arquivada)")
    return ids


def _names(ids: list[int]) -> list[str]:
    return [r["name"] for r in db.query_all("SELECT name FROM teams WHERE id = ANY(%s) ORDER BY lower(name)", (ids,))]


def set_user_teams(user_id: int, team_ids: list[int]) -> tuple[list[int], list[int]]:
    """Troca as equipes ativas da pessoa pela lista (as arquivadas ficam como estão).
    Devolve (antes, depois) só das ativas."""
    before = [t["id"] for t in teams.of_user(user_id)]
    db.execute("""DELETE FROM team_members m USING teams t
                   WHERE m.team_id = t.id AND t.archived_at IS NULL AND m.user_id = %s AND NOT (m.team_id = ANY(%s))""",
               (user_id, team_ids))
    for tid in team_ids:
        db.execute("INSERT INTO team_members (team_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (tid, user_id))
    return before, [t["id"] for t in teams.of_user(user_id)]


# ------------------------------------------------------------------ equipes --

@router.get("/teams")
def list_teams(admin=Depends(require_admin)):
    """Equipes (ativas primeiro, por nome) com os membros, e o master da instância."""
    rows = db.query_all("SELECT id, name, created_at, archived_at FROM teams ORDER BY archived_at IS NOT NULL, lower(name)")
    return [{**r, "members": _members(r["id"])} for r in rows]


@router.post("/teams", status_code=201)
def create_team(data: TeamIn, admin=Depends(require_admin_csrf)):
    name = _clean(data.name)
    ids = _check_users(data.member_ids)
    first = not teams.any_active()
    try:
        row = db.query_one("INSERT INTO teams (name) VALUES (%s) RETURNING id", (name,))
    except UniqueViolation as e:
        raise HTTPException(status_code=409, detail=NAME_TAKEN) from e
    for uid in ids:
        db.execute("INSERT INTO team_members (team_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (row["id"], uid))
    audit.record(_ctx(admin), "team.create", "team", row["id"],
                 after={"name": name, "members": len(ids), "by": admin["email"], "first": first})
    return {"id": row["id"], "name": name, "archived_at": None, "members": _members(row["id"]), "first": first}


@router.patch("/teams/{team_id}")
def edit_team(team_id: int, data: TeamEditIn, admin=Depends(require_admin_csrf)):
    """Renomear, arquivar/desarquivar e trocar os membros em lote (a lista inteira)."""
    t = _team(team_id)
    ctx = _ctx(admin)
    if data.name is not None:
        name = _clean(data.name)
        if name != t["name"]:
            try:
                db.execute("UPDATE teams SET name = %s WHERE id = %s", (name, team_id))
            except UniqueViolation as e:
                raise HTTPException(status_code=409, detail=NAME_TAKEN) from e
            audit.record(ctx, "team.update", "team", team_id, before={"name": t["name"]},
                         after={"name": name, "by": admin["email"]})
    if data.archived is not None and data.archived != (t["archived_at"] is not None):
        db.execute("UPDATE teams SET archived_at = CASE WHEN %s THEN now() END WHERE id = %s", (data.archived, team_id))
        audit.record(ctx, "team.archive" if data.archived else "team.unarchive", "team", team_id,
                     after={"name": data.name or t["name"], "by": admin["email"]})
    if data.member_ids is not None:
        ids = _check_users(data.member_ids)
        before = [m["id"] for m in _members(team_id)]
        db.execute("DELETE FROM team_members WHERE team_id = %s AND NOT (user_id = ANY(%s))", (team_id, ids))
        for uid in ids:
            db.execute("INSERT INTO team_members (team_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (team_id, uid))
        if set(before) != set(ids):
            audit.record(ctx, "team.members", "team", team_id,
                         before={"members": before},
                         after={"members": ids, "name": data.name or t["name"], "by": admin["email"],
                                "added": len(set(ids) - set(before)), "removed": len(set(before) - set(ids))})
    row = _team(team_id)
    return {**row, "members": _members(team_id)}


@router.delete("/teams/{team_id}")
def delete_team(team_id: int, admin=Depends(require_admin_csrf)):
    """Exclui a equipe (os membros só saem dela; nada das pessoas é apagado)."""
    t = _team(team_id)
    members = [m["id"] for m in _members(team_id)]
    db.execute("DELETE FROM teams WHERE id = %s", (team_id,))
    audit.record(_ctx(admin), "team.delete", "team", team_id,
                 before={"name": t["name"], "members": members, "by": admin["email"]})
    return {"ok": True, "name": t["name"]}


@router.put("/users/{user_id}/teams")
def put_user_teams(user_id: int, data: UserTeamsIn, admin=Depends(require_admin_csrf)):
    """As equipes ativas da pessoa (a lista inteira; vazia = sem equipe)."""
    target = db.query_one("SELECT id, email FROM users WHERE id = %s", (user_id,))
    if not target:
        raise HTTPException(status_code=404, detail="usuário não encontrado")
    ids = check_teams(data.team_ids)
    before, after = set_user_teams(user_id, ids)
    if set(before) != set(after):
        audit.record(_ctx(admin), "user.teams", "user", user_id, before={"teams": _names(before)},
                     after={"teams": _names(after), "by": admin["email"], "email": target["email"]})
    return {"id": user_id, "teams": teams.of_user(user_id)}


# -------------------------------------------------------------- admin master --

def _require_master(admin: dict) -> None:
    if not teams.is_master(admin["user_id"]):
        raise HTTPException(status_code=403, detail="só o admin master pode fazer isto")


@router.get("/master")
def get_master(admin=Depends(require_admin)):
    """Quem é o master, se é quem pede, os papéis dele e um código pendente."""
    mid = teams.master_id()
    m = db.query_one("SELECT id, email FROM users WHERE id = %s", (mid,)) if mid else None
    me_master = mid == admin["user_id"]
    pending = None
    if me_master:
        pending = db.query_one(
            """SELECT l.expires_at, l.target_user_id FROM auth_links l
                WHERE l.user_id = %s AND l.kind = 'master' AND l.used_at IS NULL AND l.expires_at > now()
                ORDER BY l.id DESC LIMIT 1""", (admin["user_id"],))
    r = roles.of(mid) if mid else []
    return {"master": {**m, "name": people.profile(m["id"])["name"]} if m else None,
            "me": me_master,
            "viewer": "viewer" in r, "assigner": "assigner" in r,
            "pending": ({"expires_at": pending["expires_at"], "to_user_id": pending["target_user_id"],
                         "to": people.profile(pending["target_user_id"])["name"]} if pending else None),
            "mail_configured": mailer.configured()}


@router.put("/master/roles")
def master_roles(data: MasterRolesIn, admin=Depends(require_admin_csrf)):
    """O master liga/desliga os próprios "Vê a equipe" e "Manda tarefas" (um toque)."""
    _require_master(admin)
    uid = admin["user_id"]
    before = roles.of(uid)
    novos = set(before)
    for key in ("viewer", "assigner"):
        val = getattr(data, key)
        if val is True:
            novos.add(key)
        elif val is False:
            novos.discard(key)
    novos = sorted(novos)
    if set(novos) != set(before):
        roles.replace(uid, novos)
        audit.record(_ctx(admin), "user.roles", "user", uid, before={"roles": before},
                     after={"roles": novos, "by": admin["email"], "email": admin["email"], "master": True})
    return get_master(admin)


def _code_mail(code: str, to_name: str):
    from ..notify import Mail  # import tardio: notify importa rotas
    m = Mail("Código para transferir o papel de admin master", "Confirme a transferência do papel de master",
             f"Você pediu para passar o papel de admin master do Nexus para {to_name}. Digite o código abaixo no Nexus "
             f"para confirmar. Ele vale por {int(CODE_TTL.total_seconds() // 60)} minutos e funciona uma vez só.")
    m.blocks = [("Código", [code]), ("Não foi você?", ["Não digite o código e troque a sua senha agora."])]
    m.reason, m.settings_tab = "Aviso de segurança: você é o admin master desta instância do Nexus.", None
    return m


def _received_mail(from_name: str):
    from ..notify import Mail
    m = Mail("Você agora é o admin master do Nexus", f"{from_name} passou para você o papel de admin master",
             "Como admin master, você é quem pode ver e mandar tarefas para todos, com ou sem equipe, quando ligar os "
             "seus papéis “Vê a equipe” e “Manda tarefas” (Admin › Equipes). As suas visualizações dos registros de "
             "outras pessoas ficam no log de admin. Só você pode passar este papel adiante.")
    m.reason, m.settings_tab = "Você recebe este e-mail porque recebeu o papel de admin master do Nexus.", None
    return m


def _send_quiet(to: str, mail) -> None:
    try:
        mailer.send(to, mail.subject, mail.text(), mail.html())
    except Exception as e:  # noqa: BLE001 — a transferência já foi feita; o e-mail é aviso
        log.warning("aviso por e-mail para %s falhou: %s", to, e)


def _receiver(admin: dict, to_id: int) -> dict:
    if to_id == admin["user_id"]:
        raise HTTPException(status_code=400, detail="escolha outro admin para receber o papel")
    row = db.query_one(
        """SELECT u.id, u.email FROM users u
            WHERE u.id = %s AND u.blocked_at IS NULL AND NOT u.invite_pending
              AND EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'admin')""", (to_id,))
    if not row:
        raise HTTPException(status_code=400, detail="quem recebe precisa ser admin, ter o acesso liberado e já ter entrado no Nexus")
    return row


@router.post("/master/transfer")
def transfer_start(data: MasterTransferIn, admin=Depends(require_admin_csrf)):
    """1º passo: senha do master e para quem. Manda um código de 6 dígitos ao
    e-mail do master (vale 10 minutos, uso único; um pedido novo invalida o anterior)."""
    _require_master(admin)
    uid = admin["user_id"]
    if not login_limiter.allow(f"pw:{uid}"):  # sessão roubada não testa senhas à vontade
        raise HTTPException(status_code=429, detail="muitas tentativas, tente mais tarde")
    row = db.query_one("SELECT password_hash, email FROM users WHERE id = %s", (uid,))
    if not row or not verify_password(row["password_hash"], data.password):
        raise HTTPException(status_code=400, detail="senha incorreta")
    if not mailer.configured():
        raise HTTPException(status_code=409, detail="o código de confirmação vai por e-mail: configure o e-mail do servidor antes")
    dest = _receiver(admin, data.to_user_id)
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.execute("UPDATE auth_links SET used_at = now() WHERE user_id = %s AND kind = 'master' AND used_at IS NULL", (uid,))
    db.execute("""INSERT INTO auth_links (user_id, kind, token_hash, expires_at, target_user_id)
                  VALUES (%s, 'master', %s, %s, %s)""",
               (uid, token_hash(f"master:{uid}:{code}"), datetime.now(timezone.utc) + CODE_TTL, dest["id"]))
    to_name = people.profile(dest["id"])["name"]
    try:
        m = _code_mail(code, to_name)
        mailer.send(row["email"], m.subject, m.text(), m.html())
    except mailer.MailError as e:
        db.execute("UPDATE auth_links SET used_at = now() WHERE user_id = %s AND kind = 'master' AND used_at IS NULL", (uid,))
        log.warning("código de transferência de master não foi por e-mail: %s", e)
        raise HTTPException(status_code=502, detail="não foi possível mandar o código por e-mail; tente de novo") from None
    audit.record(_ctx(admin), "master.transfer_code", "user", dest["id"],
                 after={"to": to_name, "to_email": dest["email"], "by": admin["email"]})
    return {"sent": True, "to": to_name, "minutes": int(CODE_TTL.total_seconds() // 60)}


@router.post("/master/transfer/confirm")
def transfer_confirm(data: MasterConfirmIn, admin=Depends(require_admin_csrf)):
    """2º passo: o código do e-mail. Errado conta tentativa (5 e o código morre);
    vencido ou já usado pede outro. Certo: o papel passa numa gravação só, quem
    recebe é avisado (no app e por e-mail) e fica no log de admin."""
    _require_master(admin)
    uid = admin["user_id"]
    link = db.query_one(
        """SELECT id, token_hash, attempts, target_user_id FROM auth_links
            WHERE user_id = %s AND kind = 'master' AND used_at IS NULL AND expires_at > now()
            ORDER BY id DESC LIMIT 1""", (uid,))
    if not link:
        raise HTTPException(status_code=400, detail="código vencido ou já usado: peça outro")
    code = data.code.strip()
    if link["token_hash"] != token_hash(f"master:{uid}:{code}"):
        row = db.query_one(
            """UPDATE auth_links SET attempts = attempts + 1,
                                     used_at = CASE WHEN attempts + 1 >= %s THEN now() END
                WHERE id = %s AND used_at IS NULL RETURNING attempts""", (CODE_ATTEMPTS, link["id"]))
        left = CODE_ATTEMPTS - (row["attempts"] if row else CODE_ATTEMPTS)
        audit.record(_ctx(admin), "master.transfer_fail", "user", link["target_user_id"],
                     after={"attempt": CODE_ATTEMPTS - left, "by": admin["email"]})
        if left <= 0:
            raise HTTPException(status_code=429, detail="código errado demais: ele não vale mais; peça outro")
        raise HTTPException(status_code=400, detail=f"código incorreto ({left} {'tentativa' if left == 1 else 'tentativas'})")
    if not db.query_one("UPDATE auth_links SET used_at = now() WHERE id = %s AND used_at IS NULL RETURNING id", (link["id"],)):
        raise HTTPException(status_code=400, detail="código vencido ou já usado: peça outro")
    dest = _receiver(admin, link["target_user_id"])  # ainda admin e com acesso?
    if not db.execute("UPDATE app_settings SET master_user_id = %s WHERE id = 1 AND master_user_id = %s", (dest["id"], uid)):
        raise HTTPException(status_code=409, detail="o papel de master mudou enquanto isso; recarregue")
    from_name = people.profile(uid)["name"]
    to_name = people.profile(dest["id"])["name"]
    audit.record(_ctx(admin), "master.transfer", "user", dest["id"],
                 after={"to": to_name, "to_email": dest["email"], "by": admin["email"]})
    audit.record(_ctx(admin), "master.received", "user", dest["id"],
                 after={"from": from_name, "from_email": admin["email"]}, user_id=dest["id"])
    from .admin import role_notice  # import tardio: admin importa este módulo indiretamente
    role_notice(dest["id"], dest["email"], {"master"}, set(), admin, mail=False)
    if mailer.configured():
        threading.Thread(target=_send_quiet, args=(dest["email"], _received_mail(from_name)), daemon=True).start()
    return {"ok": True, "master": {"id": dest["id"], "name": to_name}}
