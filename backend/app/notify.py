"""Avisos por e-mail: o que entra em cada um e quando sai.

Tipos (opt-in em Configurações > Avisos, cada um com sua hora):
  morning  "Seu dia": rotinas devidas hoje, prazos de hoje e atrasadas.
  evening  Rotinas de hoje ainda não feitas (não sai se já fez tudo).
  weekly   Resumo da semana anterior (sai às segundas).

morning/evening só saem nos dias úteis do usuário. Cada (usuário, tipo, dia)
é registrado em notification_log ANTES do envio: nunca manda duas vezes,
mesmo reiniciando. Aviso sem nada a dizer não sai (fica registrado assim).
"""
import asyncio
import html
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import db, mailer
from .config import config
from .labels import dur as _dur
from .services import _week_start, get_board, get_report_range, is_work_day, work_mask

log = logging.getLogger("uvicorn.error")

_WD = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
_MES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
KINDS = ("morning", "evening", "weekly")
LIST_MAX = 10
CATCH_UP_HOURS = 2

DEFAULT_PREFS = {"morning": False, "morning_hour": 8, "evening": False, "evening_hour": 17,
                 "weekly": False, "weekly_hour": 8, "show_titles": True}


def get_prefs(uid: int) -> dict:
    row = db.query_one(
        """SELECT morning, morning_hour, evening, evening_hour, weekly, weekly_hour, show_titles
             FROM notification_prefs WHERE user_id = %s""", (uid,))
    return dict(row) if row else dict(DEFAULT_PREFS)


def _day(d: date) -> str:
    return f"{_WD[d.weekday()]}, {d.day} {_MES[d.month - 1]}"


# --------------------------------------------------------------- montagem --

class Mail:
    """Conteúdo de um aviso: título, blocos (título + itens) e números."""

    def __init__(self, subject: str, title: str, intro: str):
        self.subject, self.title, self.intro = subject, title, intro
        self.blocks: list[tuple[str, list[str]]] = []

    def block(self, heading: str, items: list[str], show_titles: bool):
        if not items:
            return
        if not show_titles:
            self.blocks.append((f"{heading}: {len(items)}", []))
            return
        extra = len(items) - LIST_MAX
        self.blocks.append((heading, items[:LIST_MAX] + ([f"+ {extra} outras"] if extra > 0 else [])))

    @property
    def empty(self) -> bool:
        return not self.blocks

    def text(self) -> str:
        out = [self.title, "", self.intro, ""]
        for heading, items in self.blocks:
            out.append(heading)
            out += [f"  - {i}" for i in items]
            out.append("")
        out += [f"Abrir o Nexus: {config.APP_URL}/", "",
                "Você recebe este aviso porque o ativou em Configurações > Avisos.",
                f"Para desligar: {config.APP_URL}/index.html#/config?aba=avisos"]
        return "\n".join(out)

    def html(self) -> str:
        e = html.escape
        brand = db.query_one("SELECT line1, line2 FROM app_branding WHERE id = 1") or {"line1": "nexus", "line2": "worklog"}
        parts = []
        for heading, items in self.blocks:
            parts.append(f'<p style="margin:22px 0 8px;font:600 14px/1.4 Arial,sans-serif;color:#18181b">{e(heading)}</p>')
            if items:
                lis = "".join(f'<li style="margin:0 0 6px">{e(i)}</li>' for i in items)
                parts.append(f'<ul style="margin:0;padding:0 0 0 18px;font:14px/1.5 Arial,sans-serif;color:#3f3f46">{lis}</ul>')
        return f"""<!doctype html><html lang="pt-BR"><body style="margin:0;padding:0;background:#f4f5f7">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f5f7;padding:24px 12px"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e4e4e7">
<tr><td style="background:#121213;padding:18px 24px;border-bottom:2px solid #5294E2">
<span style="font:700 15px/1.1 Arial,sans-serif;color:#ffffff">{e(brand['line1'])}</span>
<span style="font:700 15px/1.1 Arial,sans-serif;color:#a1a1a8"> {e(brand['line2'])}</span></td></tr>
<tr><td style="padding:24px 24px 28px">
<p style="margin:0 0 6px;font:600 20px/1.3 Arial,sans-serif;color:#18181b">{e(self.title)}</p>
<p style="margin:0;font:14px/1.5 Arial,sans-serif;color:#52525b">{e(self.intro)}</p>
{''.join(parts)}
<p style="margin:26px 0 0"><a href="{e(config.APP_URL)}/" style="display:inline-block;background:#5294E2;color:#0b0d10;text-decoration:none;font:600 14px/1 Arial,sans-serif;padding:12px 20px;border-radius:999px">Abrir o Nexus</a></p>
</td></tr></table>
<p style="max-width:560px;margin:14px auto 0;font:12px/1.5 Arial,sans-serif;color:#86868e">Você recebe este aviso porque o ativou em Configurações &gt; Avisos.
<a href="{e(config.APP_URL)}/index.html#/config?aba=avisos" style="color:#86868e">Mudar ou desligar</a>.</p>
</td></tr></table></body></html>"""


def build_morning(uid: int, today: date, show: bool) -> Mail:
    b = get_board(uid, today)
    rotinas = [r["label"] for r in b["recurring"] if r.get("due") and not r["done_today"]]
    abertas = b["in_progress"]
    hoje = [t["title"] for t in abertas if t["due_date"] == today]
    atrasadas = [f"{t['title']} (prazo {t['due_date']:%d/%m})" for t in abertas if t["due_date"] and t["due_date"] < today]
    alta = [t["title"] for t in abertas if t["priority"] == 1 and t["title"] not in hoje
            and not (t["due_date"] and t["due_date"] < today)]
    m = Mail(f"Seu dia · {_day(today)}", f"Bom dia — {_day(today)}",
             f"{len(rotinas)} rotina{'s' if len(rotinas) != 1 else ''} para hoje e {len(abertas)} tarefa{'s' if len(abertas) != 1 else ''} em aberto.")
    m.block("Atrasadas", atrasadas, show)
    m.block("Vencem hoje", hoje, show)
    m.block("Rotinas de hoje", rotinas, show)
    m.block("Prioridade alta", alta, show)
    return m


def build_evening(uid: int, today: date, show: bool) -> Mail:
    b = get_board(uid, today)
    devidas = [r for r in b["recurring"] if r.get("due")]
    faltam = [r["label"] for r in devidas if not r["done_today"]]
    feitas = len(devidas) - len(faltam)
    m = Mail(f"Faltam {len(faltam)} rotina{'s' if len(faltam) != 1 else ''} hoje",
             "Antes de encerrar o dia",
             f"Você fez {feitas} de {len(devidas)} rotinas de hoje. Se já fez as outras, é só marcar no app.")
    m.block("Ainda não marcadas", faltam, show)
    return m


def build_weekly(uid: int, today: date, show: bool) -> Mail:
    end = _week_start(today) - timedelta(days=1)  # sábado passado
    start = end - timedelta(days=6)               # domingo anterior
    r = get_report_range(uid, start, end)
    s = r["summary"]
    pct = f"{round(100 * s['recurring_done'] / s['recurring_total'])}%" if s["recurring_total"] else "—"
    intro = (f"Rotinas {s['recurring_done']}/{s['recurring_total']} ({pct}) · "
             f"{s['pontual_done']} entrega{'s' if s['pontual_done'] != 1 else ''} · "
             f"{_dur(s['minutes']) if s['minutes'] else 'nada'} apontado · {s['active_days']} dia{'s' if s['active_days'] != 1 else ''} com atividade.")
    m = Mail(f"Sua semana · {start:%d/%m} a {end:%d/%m}", f"Semana de {start:%d/%m} a {end:%d/%m}", intro)
    m.block("Entregas", [w["title"] + (f" [{w['project']}]" if w["project"] else "") for w in r["deliveries"]], show)
    m.block("Tempo por projeto", [f"{p['name'] or 'Sem projeto'}: {_dur(p['minutes'])}" for p in r["projects"] if p["minutes"]], show)
    m.block("Rotinas que ficaram para trás",
            [f"{x['label']} ({x['done']}/{x['due']})" for x in r["recurring_stats"] if x["due"] > x["done"]], show)
    b = get_board(uid, today)
    atrasadas = [t["title"] for t in b["in_progress"] if t["due_date"] and t["due_date"] < today]
    m.block("Atrasadas agora", atrasadas, show)
    if m.empty and not s["active_days"]:
        return m  # semana vazia e nada atrasado: não manda
    if m.empty:
        m.blocks.append(("Sem entregas nem atrasos na semana.", []))
    return m


BUILDERS = {"morning": build_morning, "evening": build_evening, "weekly": build_weekly}


def build_test(uid: int, today: date, show: bool) -> Mail:
    m = Mail("Teste de aviso do Nexus", "Os avisos estão funcionando",
             "Este é um e-mail de teste pedido em Configurações > Avisos. Abaixo, uma prévia do aviso da manhã.")
    preview = build_morning(uid, today, show)
    m.blocks = preview.blocks or [("Nada para hoje — o aviso da manhã não sairia.", [])]
    return m


# --------------------------------------------------------------- agendador --

def _claim(uid: int, kind: str, ref: date) -> bool:
    """Reserva o envio (usuário, tipo, dia). False = já foi."""
    return bool(db.query_one(
        """INSERT INTO notification_log (user_id, kind, ref_date) VALUES (%s, %s, %s)
           ON CONFLICT DO NOTHING RETURNING 1""", (uid, kind, ref)))


def _finish(uid: int, kind: str, ref: date, ok: bool | None, error: str | None) -> None:
    db.execute("UPDATE notification_log SET ok = %s, error = %s, sent_at = now() WHERE user_id = %s AND kind = %s AND ref_date = %s",
               (ok, error, uid, kind, ref))


def deliver(uid: int, email: str, kind: str, ref: date, mail: Mail, send=None) -> str:
    """Manda (ou registra que não havia nada). Devolve 'sent', 'empty' ou 'error'."""
    send = send or mailer.send
    if mail.empty:
        _finish(uid, kind, ref, None, "nada a avisar")
        return "empty"
    try:
        send(email, mail.subject, mail.text(), mail.html())
    except Exception as e:  # noqa: BLE001 — registra e segue para o próximo
        _finish(uid, kind, ref, False, str(e)[:300])
        log.warning("aviso %s para usuário %s falhou: %s", kind, uid, e)
        return "error"
    _finish(uid, kind, ref, True, None)
    return "sent"


def run_once(now: datetime, send=None) -> list[tuple[int, str, str]]:
    """Uma passada do agendador no horário local `now`. Devolve o que fez."""
    today = now.date()
    done = []
    users = db.query_all(
        """SELECT u.id, u.email, p.morning, p.morning_hour, p.evening, p.evening_hour,
                  p.weekly, p.weekly_hour, p.show_titles
             FROM notification_prefs p JOIN users u ON u.id = p.user_id
            WHERE (p.morning OR p.evening OR p.weekly) AND NOT u.must_change_password""")
    for u in users:
        mask = work_mask(u["id"])
        for kind in KINDS:
            if not u[kind] or now.hour < u[f"{kind}_hour"]:
                continue
            if kind == "weekly":
                if today.weekday() != 0:  # segunda
                    continue
            elif not is_work_day(today, mask):
                continue
            # Backend fora do ar no horário: recupera até 2h depois; mais que
            # isso o aviso perdeu o sentido ("bom dia" às 15h) e fica para amanhã.
            if now.hour - u[f"{kind}_hour"] > CATCH_UP_HOURS:
                continue
            if not _claim(u["id"], kind, today):
                continue
            mail = BUILDERS[kind](u["id"], today, u["show_titles"])
            done.append((u["id"], kind, deliver(u["id"], u["email"], kind, today, mail, send)))
    return done


async def scheduler() -> None:
    """Loop do agendador (uma passada por minuto), dentro do backend."""
    tz = ZoneInfo(config.APP_TZ)
    log.info("avisos por e-mail: agendador ativo (%s)", config.SMTP_HOST)
    while True:
        try:
            await asyncio.to_thread(run_once, datetime.now(tz))
        except Exception:  # noqa: BLE001
            log.exception("agendador de avisos falhou nesta passada")
        await asyncio.sleep(60)

