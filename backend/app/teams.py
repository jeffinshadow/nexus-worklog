"""Equipes (Admin › Equipes, sql/043) e o admin master: as peças que as regras
únicas usam (visibility.py para "Vê a equipe", assignable.py para "Manda
tarefas", org.py para "Para empresas"). Nada aqui decide sozinho quem vê ou
quem recebe: só responde "estão na mesma equipe?", "está em alguma equipe?",
"é o master?".

  - Uma pessoa pode estar em várias equipes; todo mundo começa sem equipe e só
    o admin define. Equipe arquivada não conta para nada (guarda os membros).
  - Instância sem nenhuma equipe ativa (uso pessoal) = tudo como antes das
    equipes: o escopo só passa a valer quando o admin cria a primeira.
  - Admin master (app_settings.master_user_id): o primeiro admin da instância,
    sempre exatamente um. Vê e atribui para todos, com ou sem equipe, só com os
    próprios papéis "Vê a equipe"/"Manda tarefas" ligados.

As funções *_sql recebem expressões SQL já seguras (um alias de coluna como
"u.id", ou um id inteiro, que vira literal com int()).
"""
import re

from fastapi import HTTPException

from . import db

ANY_SQL = "EXISTS (SELECT 1 FROM teams tx WHERE tx.archived_at IS NULL)"


_COL = re.compile(r"^[a-z_][a-z0-9_]*\.id$")


def _x(v) -> str:
    """Id inteiro vira literal; senão, só uma coluna "alias.id" (nunca texto de fora)."""
    if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
        return str(int(v))
    if isinstance(v, str) and _COL.match(v):
        return v
    raise ValueError(f"expressão inválida: {v!r}")


def in_team_sql(who) -> str:
    """`who` está em pelo menos uma equipe ativa."""
    return (f"EXISTS (SELECT 1 FROM team_members ti JOIN teams tti ON tti.id = ti.team_id AND tti.archived_at IS NULL"
            f" WHERE ti.user_id = {_x(who)})")


def shares_sql(a, b) -> str:
    """`a` e `b` estão juntos em pelo menos uma equipe ativa."""
    return (f"EXISTS (SELECT 1 FROM team_members ts1 JOIN team_members ts2 ON ts2.team_id = ts1.team_id"
            f" JOIN teams tts ON tts.id = ts1.team_id AND tts.archived_at IS NULL"
            f" WHERE ts1.user_id = {_x(a)} AND ts2.user_id = {_x(b)})")


_TCOL = re.compile(r"^[a-z_][a-z0-9_]*\.team_id$")


def member_of_sql(who, team_col: str) -> str:
    """`who` é membro de uma equipe ATIVA cujo id está na coluna `team_col`
    ("alias.team_id"): quem vê um item compartilhado com a equipe (Vencimentos)."""
    if not _TCOL.match(team_col):
        raise ValueError(f"coluna inválida: {team_col!r}")
    return (f"EXISTS (SELECT 1 FROM team_members tc JOIN teams ttc ON ttc.id = tc.team_id AND ttc.archived_at IS NULL"
            f" WHERE tc.team_id = {team_col} AND tc.user_id = {_x(who)})")


def master_sql(who, role: str) -> str:
    """`who` é o admin master E tem o papel `role` ligado (viewer/assigner)."""
    assert role in ("viewer", "assigner")
    return (f"(EXISTS (SELECT 1 FROM app_settings tm WHERE tm.id = 1 AND tm.master_user_id = {_x(who)})"
            f" AND EXISTS (SELECT 1 FROM user_roles tmr WHERE tmr.user_id = {_x(who)} AND tmr.role = '{role}'))")


def company_sql(who) -> str:
    """"Para empresas" vale para `who`: a instância não tem equipes, ou ele está em alguma."""
    return f"(NOT {ANY_SQL} OR {in_team_sql(who)})"


def scope_sql(actor, who, role: str) -> str:
    """O escopo de equipe entre quem age (`actor`, com o papel `role`) e `who`:
    sem equipes na instância, todos; senão, quem compartilha equipe, ou o master
    com o papel ligado."""
    return f"(NOT {ANY_SQL} OR {shares_sql(actor, who)} OR {master_sql(actor, role)})"


# ------------------------------------------------------------------ leituras --

def any_active() -> bool:
    return bool(db.query_one(f"SELECT 1 WHERE {ANY_SQL}"))


def company_applies(user_id: int) -> bool:
    return bool(db.query_one(f"SELECT 1 WHERE {company_sql(int(user_id))}"))


def master_id() -> int | None:
    r = db.query_one("SELECT master_user_id FROM app_settings WHERE id = 1")
    return r["master_user_id"] if r else None


def is_master(user_id: int) -> bool:
    return master_id() == user_id


def ensure_master() -> None:
    """Sempre existe um master: sem ele (ou se não for mais admin), o admin mais antigo assume."""
    db.execute(
        """UPDATE app_settings s
              SET master_user_id = (SELECT u.id FROM users u
                                     WHERE EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = u.id AND r.role = 'admin')
                                     ORDER BY u.created_at, u.id LIMIT 1)
            WHERE s.id = 1
              AND (s.master_user_id IS NULL
                   OR NOT EXISTS (SELECT 1 FROM user_roles r WHERE r.user_id = s.master_user_id AND r.role = 'admin'))""")


def of_user(user_id: int, archived: bool = False) -> list[dict]:
    """Equipes da pessoa (ativas; com archived=True, também as arquivadas), por nome."""
    return db.query_all(
        f"""SELECT t.id, t.name, t.archived_at IS NOT NULL AS archived FROM teams t
              JOIN team_members m ON m.team_id = t.id
             WHERE m.user_id = %s {'' if archived else 'AND t.archived_at IS NULL'}
             ORDER BY lower(t.name)""", (user_id,))


def choosable(user_id: int) -> list[dict]:
    """Equipes com que a pessoa pode compartilhar um item (Vencimentos): as
    ativas dela; o admin master, todas as ativas."""
    if is_master(user_id):
        return db.query_all("SELECT id, name FROM teams WHERE archived_at IS NULL ORDER BY lower(name)")
    return [{"id": t["id"], "name": t["name"]} for t in of_user(user_id)]


def is_member(user_id: int, team_id) -> bool:
    """A pessoa está nessa equipe (ativa)?"""
    if team_id is None:
        return False
    return bool(db.query_one(
        """SELECT 1 FROM team_members m JOIN teams t ON t.id = m.team_id AND t.archived_at IS NULL
            WHERE m.team_id = %s AND m.user_id = %s""", (team_id, user_id)))


def joined_at(user_id: int):
    """Desde quando a pessoa está em alguma equipe ativa (o aviso único de
    "Para empresas" volta quando ela entra numa equipe depois de ter visto)."""
    r = db.query_one("""SELECT min(m.created_at) AS at FROM team_members m
                          JOIN teams t ON t.id = m.team_id AND t.archived_at IS NULL WHERE m.user_id = %s""", (user_id,))
    return r["at"] if r else None


def selector(actor_id: int, role: str) -> dict:
    """O que o seletor de equipe mostra para quem vê (role='viewer') ou atribui
    (role='assigner'): as equipes ativas dele; o master com o papel ligado vê
    todas, mais "Sem equipe". `on`: a instância tem equipes."""
    on = any_active()
    master = on and bool(db.query_one(f"SELECT 1 WHERE {master_sql(int(actor_id), role)}"))
    if master:
        rows = db.query_all("SELECT id, name FROM teams WHERE archived_at IS NULL ORDER BY lower(name)")
    elif on:
        rows = [{"id": t["id"], "name": t["name"]} for t in of_user(actor_id)]
    else:
        rows = []
    return {"on": on, "master": master, "teams": rows, "none": master}


def filter_sql(alias: str, actor_id: int, role: str, team) -> str:
    """Recorte do seletor (sobre o escopo, nunca além dele): None = todas as
    equipes de quem age; um id = só essa equipe (precisa ser dele, ou ele ser o
    master com o papel); "none" = só quem está sem equipe (só o master)."""
    if team in (None, "", "all"):
        return "TRUE"
    sel = selector(actor_id, role)
    if team == "none":
        if not sel["none"]:
            raise HTTPException(status_code=404, detail="equipe não encontrada")
        return f"NOT {in_team_sql(alias + '.id')}"
    try:
        tid = int(team)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="equipe inválida") from None
    if not any(t["id"] == tid for t in sel["teams"]):
        raise HTTPException(status_code=404, detail="equipe não encontrada")
    return (f"EXISTS (SELECT 1 FROM team_members tf WHERE tf.team_id = {tid} AND tf.user_id = {alias}.id)")


def shared_names_sql(actor, who) -> str:
    """Nomes das equipes ativas que `actor` e `who` compartilham (array, para agrupar no Atribuir)."""
    return (f"ARRAY(SELECT tn.name FROM teams tn JOIN team_members tn1 ON tn1.team_id = tn.id AND tn1.user_id = {_x(actor)}"
            f" JOIN team_members tn2 ON tn2.team_id = tn.id AND tn2.user_id = {_x(who)}"
            f" WHERE tn.archived_at IS NULL ORDER BY lower(tn.name))")


def names_sql(who) -> str:
    """Nomes das equipes ativas de `who` (array)."""
    return (f"ARRAY(SELECT tw.name FROM teams tw JOIN team_members twm ON twm.team_id = tw.id AND twm.user_id = {_x(who)}"
            f" WHERE tw.archived_at IS NULL ORDER BY lower(tw.name))")
