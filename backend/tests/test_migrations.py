"""Reaplicar as migrations sobre um banco CHEIO não muda dado nenhum (auditoria, testes-qualidade #11).

Todo arquivo de backend/sql roda de novo a cada subida do backend (main.run_migrations, no lifespan). Na suíte
elas só rodavam uma vez, em banco vazio: um UPDATE sem guarda numa migration nova reescreveria dado de usuário a
cada deploy sem nenhum teste avisar."""
from datetime import timedelta

from app import db, main
from tests.conftest import criar_chave, dia_hoje, uid_de


def _retrato():
    """{tabela: (linhas, hash do conteúdo)} de todas as tabelas do esquema public."""
    tabelas = [r["tablename"] for r in db.query_all("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")]
    return {t: tuple(db.query_one(
        f"SELECT count(*)::int AS n, md5(coalesce(string_agg(x::text, E'\\n' ORDER BY x::text), '')) AS h FROM \"{t}\" x"
    ).values()) for t in sorted(tabelas)}


def _ok(r):
    assert r.status_code in (200, 201), r.text
    return r.json() if r.content else None


def _popular(admin, usuario, colega):
    hoje = dia_hoje(usuario)
    _ok(admin.put(f"/admin/users/{uid_de(colega)}/roles", {"roles": ["user", "assigner", "viewer"]}))
    _ok(admin.post("/admin/teams", {"name": "Campo", "member_ids": [uid_de(usuario), uid_de(colega)]}))
    _ok(usuario.put("/me/viewers", {"accept": True}))
    _ok(usuario.put("/me/assignments", {"accept": True}))
    proj = _ok(usuario.post("/projects", {"name": "Cliente X"}))
    t = _ok(usuario.post("/worklog", {"title": "Trocar o switch", "project_id": proj["id"],
                                      "due_date": (hoje + timedelta(days=3)).isoformat()}))
    _ok(usuario.post(f"/worklog/{t['id']}/notes", {"body": "vi o modelo"}))
    _ok(usuario.post(f"/worklog/{t['id']}/checklist", {"label": "Levar o cabo"}))
    feita = _ok(usuario.post("/worklog", {"title": "Feita"}))
    _ok(usuario.post(f"/worklog/{feita['id']}/finish", {}))
    rid = _ok(usuario.post("/recurring", {"label": "Ronda", "freq": "weekly", "weekdays": 127}))["id"]
    _ok(usuario.post(f"/recurring/{rid}/toggle", {"done": True}))
    _ok(usuario.post(f"/recurring/{rid}/pause", {"until": (hoje + timedelta(days=2)).isoformat()}))
    _ok(usuario.post("/renewals", {"label": "Certificado", "expires_on": (hoje + timedelta(days=40)).isoformat()}))
    _ok(usuario.post("/calendar", {"include_recurring": True}))
    criar_chave(usuario)


def test_reaplicar_as_migrations_em_banco_cheio_nao_muda_dado(admin, usuario, novo_usuario):
    _popular(admin, usuario, novo_usuario("outro@example.com"))
    antes = _retrato()
    cheias = {t for t, (n, _) in antes.items() if n}
    # O teste só vale com dado de verdade nas tabelas principais.
    assert {"users", "user_roles", "worklog_tasks", "task_notes", "task_checklist", "recurring_tasks",
            "recurring_completions", "recurring_pauses", "projects", "renewals", "teams", "audit_log",
            "api_tokens", "calendar_feeds", "sessions"} <= cheias, sorted(cheias)
    for _ in range(2):  # duas subidas seguidas do backend
        main.run_migrations()
    depois = _retrato()
    mudou = {t: (antes.get(t), depois.get(t)) for t in set(antes) | set(depois) if antes.get(t) != depois.get(t)}
    assert not mudou, f"reaplicar as migrations mudou dado (tabela: (linhas, hash) antes e depois): {mudou}"
