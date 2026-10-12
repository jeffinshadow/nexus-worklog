from datetime import date, timedelta

from app.services import get_report_range
from conftest import dia_hoje, recuar_criacao, uid_de


def _criar(u, label="Conferir backups"):
    r = u.post("/recurring", {"label": label})
    assert r.status_code == 201
    return r.json()["id"]


def test_retroativo_dentro_da_janela(usuario):
    tid = _criar(usuario)
    recuar_criacao(tid, 10)
    dia = (dia_hoje(usuario) - timedelta(days=3)).isoformat()
    r = usuario.post(f"/recurring/{tid}/toggle", {"done": True, "day": dia})
    assert r.status_code == 200
    b = usuario.get(f"/board?day={dia}").json()
    assert next(x for x in b["recurring"] if x["id"] == tid)["done_today"] is True


def test_retroativo_fora_da_janela_e_futuro(usuario):
    tid = _criar(usuario)
    recuar_criacao(tid, 30)
    hoje = dia_hoje(usuario)
    for d in (hoje - timedelta(days=8), hoje + timedelta(days=1)):
        assert usuario.post(f"/recurring/{tid}/toggle", {"done": True, "day": d.isoformat()}).status_code == 400
        assert usuario.get(f"/board?day={d.isoformat()}").status_code == 400


def test_nao_marca_dia_antes_de_existir(usuario):
    tid = _criar(usuario)  # criada hoje
    ontem = (dia_hoje(usuario) - timedelta(days=1)).isoformat()
    r = usuario.post(f"/recurring/{tid}/toggle", {"done": True, "day": ontem})
    assert r.status_code == 400


def test_removida_hoje_some_do_quadro_de_hoje(usuario):
    tid = _criar(usuario)
    usuario.delete(f"/recurring/{tid}")
    assert all(x["id"] != tid for x in usuario.get("/board").json()["recurring"])


def test_dia_nao_util_vira_extra(usuario):
    """Com só segunda útil, uma marcação num dia que não é segunda conta como extra."""
    tid = _criar(usuario)
    recuar_criacao(tid, 10)
    hoje = dia_hoje(usuario)
    nao_segunda = next(hoje - timedelta(days=i) for i in range(0, 7) if (hoje - timedelta(days=i)).weekday() != 0)
    usuario.post("/auth/settings", {"work_days": 2})  # só segunda
    usuario.post(f"/recurring/{tid}/toggle", {"done": True, "day": nao_segunda.isoformat()})
    r = get_report_range(uid_de(usuario), nao_segunda, nao_segunda)["summary"]
    assert (r["recurring_extra"], r["recurring_total"]) == (1, 0)  # fora da agenda: extra, não devida


def test_todos_os_dias_uteis_conta_tudo(usuario):
    tid = _criar(usuario)
    recuar_criacao(tid, 3)
    usuario.post("/auth/settings", {"work_days": 127})
    usuario.post(f"/recurring/{tid}/toggle", {"done": True})
    hoje = dia_hoje(usuario)
    r = get_report_range(uid_de(usuario), hoje, hoje)["summary"]
    assert (r["recurring_done"], r["recurring_total"], r["recurring_extra"]) == (1, 1, 0)
