"""Matriz de rotinas do PDF: um caractere por dia do período em cada rotina."""
from datetime import timedelta

from app import db
from app.services import get_report_range
from conftest import dia_hoje, uid_de


def test_marcas_por_dia(usuario):
    hoje = dia_hoje(usuario)
    rid = usuario.post("/recurring", {"label": "Todo dia", "freq": "weekly", "weekdays": 127}).json()["id"]
    db.execute("UPDATE recurring_tasks SET created_at = now() - interval '10 days' WHERE id = %s", (rid,))
    ontem, anteontem = hoje - timedelta(days=1), hoje - timedelta(days=2)
    assert usuario.post(f"/recurring/{rid}/toggle", {"done": True, "day": anteontem.isoformat()}).status_code == 200
    d = get_report_range(uid_de(usuario), hoje - timedelta(days=3), hoje)
    r = next(x for x in d["recurring_stats"] if x["label"] == "Todo dia")
    # 3 dias atrás: perdida; anteontem: feita; ontem: perdida; hoje: pendente (ainda dá tempo).
    assert r["marks"] == "MDMP" and len(r["marks"]) == len(d["series"])
    assert (r["due"], r["done"]) == (3, 1)
    r = usuario.get(f"/reports/export?start={(hoje - timedelta(days=3)).isoformat()}&end={hoje.isoformat()}")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


def test_pdf_de_periodo_longo_corta_tabela_e_diario():
    """Um ano: a tabela de concluídas vai até as 500 mais recentes e o diário sai (o resto no CSV)."""
    from datetime import date
    from app import report_pdf
    rows = [{"title": f"T{i}", "description": None, "priority": 3, "done_date": date(2026, 1, 1), "project": None,
             "project_color": None, "minutes": 0, "check_total": 0, "check_done": 0, "resolution": None,
             "last_note": None, "photos_count": 0} for i in range(600)]
    assert report_pdf.MAX_ROWS == 500 and report_pdf.LONG_DAYS == 62
    assert len(rows) > report_pdf.MAX_ROWS
