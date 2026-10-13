"""Gera o PDF do relatório de atividades (extração por período) com fpdf2.

Sem dependência do resto do app: recebe os dados já montados por
services.get_report_range (+ a identidade visual) e devolve os bytes do PDF.

Visual alinhado ao app: Google Sans Flex (OFL, em assets/fonts, estáticas
geradas da fonte variável do web; rótulos em Medium/SemiBold), grafite + azul #5294E2, faixa escura no topo
com a linha azul do login e o lockup configurado pelo admin.
"""

import io
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

from fontTools.ttLib import TTFont
from fpdf import FPDF

from .labels import DIAS_CURTOS, MESES, MESES_LONGOS
from .labels import STATUS_PT as _STATUS
from .labels import dur as _dur
from .services import week_start

ASSETS = Path(__file__).parent / "assets"
FONTS = ASSETS / "fonts"


# Paleta (impressão em fundo branco; o azul é o mesmo do app).
INK = (24, 24, 27)
INK2 = (82, 82, 91)
DIM = (130, 130, 140)
LINE = (229, 229, 234)
TILE = (245, 246, 248)
BAND = (18, 18, 19)
ACCENT = (82, 148, 226)
ACCENT_MID = (160, 196, 240)
ACCENT_SOFT = (232, 240, 251)
OK = (52, 150, 90)
BAD = (214, 76, 66)
WARN = (196, 140, 16)

M = 16  # margem lateral (mm)


# ----------------------------------------------------------------- helpers --

def _hex(color: str | None, default=DIM) -> tuple:
    try:
        c = (color or "").lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return default


def _d(d: date) -> str:
    return d.strftime("%d/%m")


def _dfull(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _period(start: date, end: date) -> str:
    if start == end:
        return f"{start.day} {MESES[start.month - 1]} {start.year}"
    if start.year == end.year:
        if start.month == end.month:
            return f"{start.day} – {end.day} {MESES[end.month - 1]} {end.year}"
        return f"{start.day} {MESES[start.month - 1]} – {end.day} {MESES[end.month - 1]} {end.year}"
    return f"{_dfull(start)} – {_dfull(end)}"


def _schedule(r: dict) -> str:
    f = r.get("freq") or "daily"
    if f == "weekly":
        bits = r.get("weekdays") or 0
        # máscara com domingo = bit 0; listamos de segunda a domingo
        dias = [DIAS_CURTOS[i] for i in range(7) if (bits >> ((i + 1) % 7)) & 1]
        return "todo dia" if len(dias) == 7 else ", ".join(dias)
    if f == "monthly":
        return "último dia do mês" if (r.get("month_day") or 0) >= 31 else f"todo dia {r['month_day']}"
    if f == "interval":
        return f"a cada {r['interval_days']} dias"
    return "dias úteis"


_CMAP: set[int] | None = None


def _s(text) -> str:
    """Normaliza e troca caracteres que a fonte (subconjunto latino) não tem."""
    global _CMAP
    if _CMAP is None:
        _CMAP = set(TTFont(FONTS / "GoogleSansFlex-Regular.ttf").getBestCmap())
    out = []
    for ch in unicodedata.normalize("NFC", str(text or "")):
        if ord(ch) in _CMAP or ch in "\n":
            out.append(ch)
        elif ch.isspace():
            out.append(" ")
        else:
            base = unicodedata.normalize("NFD", ch)[0]
            out.append(base if ord(base) in _CMAP else "?")
    return "".join(out)


# ------------------------------------------------------------------ página --

class _Report(FPDF):
    def __init__(self, brand: dict, period: str, generated: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.brand = brand
        self.period_text = period
        self.generated = generated
        for fam, style, file in [
            ("sans", "", "GoogleSansFlex-Regular"), ("sans", "B", "GoogleSansFlex-Bold"),
            ("sansm", "", "GoogleSansFlex-Medium"), ("sanss", "", "GoogleSansFlex-SemiBold"),
            ("label", "", "GoogleSansFlex-Medium"), ("labelb", "", "GoogleSansFlex-SemiBold"),
        ]:
            self.add_font(fam, style, str(FONTS / f"{file}.ttf"))
        self.set_margins(M, 22, M)
        self.set_auto_page_break(auto=True, margin=18)
        self.alias_nb_pages()

    def header(self):
        if self.page_no() == 1:
            return
        self.font("labelb", 7, DIM)
        self.set_xy(M, 9)
        self.cell(90, 4, _s(f"{self.brand['line1']} {self.brand['line2']}".strip()))
        self.set_xy(self.w - M - 90, 9)
        self.cell(90, 4, _s(self.period_text), align="R")
        self.hline(14.5, LINE)
        self.set_y(20)

    def footer(self):
        self.hline(self.h - 13, LINE)
        self.font("label", 6.8, DIM)
        self.set_xy(M, self.h - 11.5)
        self.cell(120, 4, _s(f"gerado em {self.generated} · {self.brand['line1']} {self.brand['line2']}".strip()))
        self.set_xy(self.w - M - 40, self.h - 11.5)
        self.cell(40, 4, _s(f"página {self.page_no()} de {{nb}}"), align="R")

    # atalhos
    def font(self, fam: str, size: float, color=INK):
        self.set_font(fam, "", size)
        self.set_text_color(*color)

    def hline(self, y: float, color=LINE, x1=None, x2=None, width=0.2):
        self.set_draw_color(*color)
        self.set_line_width(width)
        self.line(M if x1 is None else x1, y, self.w - M if x2 is None else x2, y)

    def fill(self, color):
        self.set_fill_color(*color)

    def box(self, x, y, w, h, color, r=0.0):
        self.fill(color)
        if r:
            self.rect(x, y, w, h, style="F", round_corners=True, corner_radius=min(r, w / 2, h / 2))
        else:
            self.rect(x, y, w, h, style="F")

    def dot(self, x, y, d, color, outline=None):
        """Círculo de diâmetro d com canto superior esquerdo em (x, y)."""
        if outline:
            self.set_draw_color(*outline)
            self.set_line_width(0.3)
        self.fill(color)
        self.circle(x + d / 2, y + d / 2, d / 2, style="DF" if outline else "F")

    @property
    def cw(self) -> float:
        return self.w - 2 * M

    def room(self, need: float) -> None:
        """Quebra a página se não couberem `need` mm a partir do y atual."""
        if self.get_y() + need > self.h - self.b_margin:
            self.add_page()

    def text_at(self, x, y, w, h, text, align="L"):
        self.set_xy(x, y)
        self.cell(w, h, _s(text), align=align)

    def fit(self, text: str, w: float) -> str:
        """Corta com reticências para caber em w mm (fonte atual)."""
        t = _s(text)
        if self.get_string_width(t) <= w:
            return t
        while t and self.get_string_width(t + "…") > w:
            t = t[:-1]
        return t.rstrip() + "…"

    def lines(self, text: str, w: float, h: float) -> int:
        return len(self.multi_cell(w, h, _s(text), dry_run=True, output="LINES")) or 1


# ------------------------------------------------------------------ blocos --

def _cover(pdf: _Report, user_email: str, data: dict) -> None:
    band_h = 46
    pdf.box(0, 0, pdf.w, band_h, BAND)
    # Linha azul com brilho (a mesma assinatura do login), em degradê manual.
    steps = 120
    for i in range(steps):
        t = i / (steps - 1)
        a = max(0.0, 1 - abs(t - 0.58) / 0.5) ** 1.4
        col = tuple(round(BAND[k] + (ACCENT[k] - BAND[k]) * a) for k in range(3))
        pdf.box(pdf.w * i / steps, band_h - 0.6, pdf.w / steps + 0.2, 0.6, col)

    brand = pdf.brand
    x, y, mark_h = M, 14, 15
    w = 0.0
    for logo in (brand.get("logo"), (ASSETS / "dragon-mark.svg").read_bytes()):
        if not logo:
            continue
        try:
            info = pdf.image(io.BytesIO(logo), x=x, y=y, h=mark_h)
            w = float(getattr(info, "rendered_width", 0) or mark_h * 0.87)
            break
        except Exception:  # logo que o fpdf2 não entende: cai no dragão
            continue
    tx = x + (w + 3.2 if w else 0)
    pdf.font("sans", 15.5, (255, 255, 255))
    pdf.set_font("sans", "B", 15.5)
    pdf.text_at(tx, y + 0.6, 80, 6.6, brand["line1"])
    pdf.set_text_color(161, 161, 168)
    pdf.text_at(tx, y + 7.2, 80, 6.6, brand["line2"])

    rx, rw = pdf.w - M - 110, 110
    pdf.font("labelb", 7, ACCENT_MID)
    pdf.text_at(rx, 12, rw, 4, "RELATÓRIO DE ATIVIDADES" + (" · PROJETO" if data.get("project") else ""), "R")
    pdf.font("sanss", 17, (255, 255, 255))
    pdf.text_at(rx, 17, rw, 8, data.get("project") or _period(data["start"], data["end"]), "R")
    pdf.font("label", 7.6, (161, 161, 168))
    if data.get("whole_project"):
        escopo = "últimos 3 anos do projeto" if data.get("project_truncated") else "projeto completo"
        sub = f"{escopo} · desde {_dfull(data['start'])} · {user_email}"
    elif data.get("project"):
        sub = f"{_period(data['start'], data['end'])} · {user_email}"
    else:
        sub = user_email
    pdf.text_at(rx, 27, rw, 4, sub, "R")
    pdf.set_y(band_h + 9)


def _kpis(pdf: _Report, data: dict) -> None:
    s = data["summary"]
    by_project = bool(data.get("project"))
    tiles = []
    if not by_project:
        pct = round(100 * s["recurring_done"] / s["recurring_total"]) if s["recurring_total"] else None
        sub = f"{s['recurring_done']} de {s['recurring_total']} devidas"
        if s["recurring_extra"]:
            sub += f" · +{s['recurring_extra']} extra"
        tiles.append(("rotinas", f"{pct}%" if pct is not None else "—", sub if s["recurring_total"] else "nenhuma devida", pct))
    tiles.append(("concluídas", str(s["pontual_done"]), "tarefas concluídas", None))
    tiles.append(("tempo apontado", _dur(s["minutes"]) if s["minutes"] else "—",
                  f"média {_dur(s['minutes'] // max(1, s.get('time_days') or s['active_days']))} por dia com tempo" if s["minutes"] else "nada apontado", None))
    if by_project:
        tiles.append(("em aberto", str(s["open"]), f"{s['overdue']} atrasada{'s' if s['overdue'] != 1 else ''}" if s["overdue"] else "nenhuma atrasada", None))
    tiles.append(("dias com atividade", str(s["active_days"]),
                  f"em {s['period_days']} dias de projeto" if data.get("whole_project") else f"de {s['period_days']} no período", None))

    gap, h = 3.5, 27
    w = (pdf.cw - gap * (len(tiles) - 1)) / len(tiles)
    y = pdf.get_y()
    for i, (label, value, sub, pct) in enumerate(tiles):
        x = M + i * (w + gap)
        pdf.box(x, y, w, h, TILE, r=2.6)
        pdf.font("labelb", 6.6, DIM)
        pdf.text_at(x + 4.5, y + 4, w - 9, 3.5, label.upper())
        pdf.font("sanss", 20, INK)
        pdf.text_at(x + 4.5, y + 9, w - 9, 9, value)
        if pct is not None:
            pdf.box(x + 4.5, y + 19.2, w - 9, 1.3, LINE, r=0.65)
            if pct:
                pdf.box(x + 4.5, y + 19.2, (w - 9) * min(pct, 100) / 100, 1.3, ACCENT if pct >= 60 else WARN, r=0.65)
            pdf.font("sans", 6.8, INK2)
            pdf.text_at(x + 4.5, y + 21.4, w - 9, 3.5, pdf.fit(sub, w - 9))
        else:
            pdf.font("sans", 7.2, INK2)
            pdf.text_at(x + 4.5, y + 19.5, w - 9, 4, pdf.fit(sub, w - 9))
    pdf.set_y(y + h + 9)


def _section(pdf: _Report, title: str, note: str = "", need: float = 18, prio_legend: bool = False) -> None:
    pdf.room(need + 12)
    y = pdf.get_y()
    pdf.font("sanss", 12, INK)
    pdf.text_at(M, y, 120, 6, title)
    right = pdf.w - M
    if prio_legend:
        pdf.font("label", 7, DIM)
        lab = "prioridade alta"
        lw = pdf.get_string_width(lab)
        pdf.text_at(right - lw, y + 1, lw + 1, 5, lab)
        pdf.dot(right - lw - 3, y + 2.75, 1.5, WARN)
        right -= lw + 8
    if note:
        pdf.font("label", 7, DIM)
        pdf.text_at(right - 110, y + 1, 110, 5, note, "R")
    pdf.set_y(y + 9)


def _chart(pdf: _Report, data: dict) -> None:
    series = data["series"]
    by_project = bool(data.get("project"))
    # Períodos longos agrupam: até 62 dias = por dia; até ~6 meses = por
    # semana (domingo a sábado); acima disso (projeto inteiro) = por mês.
    n_days = len(series)
    gran = "dia" if n_days <= 62 else "semana" if n_days <= 186 else "mês"
    weekly = gran != "dia"
    if weekly:
        buckets: dict[date, dict] = {}
        for p in series:
            if gran == "semana":
                k = week_start(p["date"])
            else:
                k = p["date"].replace(day=1)
            b = buckets.setdefault(k, {"date": k, "work_day": True, "recurring_done": 0, "pontual": 0, "minutes": 0})
            for f in ("recurring_done", "pontual", "minutes"):
                b[f] += p[f]
        series = list(buckets.values())

    has_min = any(p["minutes"] for p in series)
    use_time = has_min and (by_project or not any(p["recurring_done"] for p in series))
    _section(pdf, "Ritmo do período", f"por {gran}", need=48)
    x0, y0, w, h = M, pdf.get_y() + 2, pdf.cw, 34
    n = len(series)
    slot = w / max(n, 1)
    bw = min(slot * 0.62, 7)

    if use_time:
        vals = [p["minutes"] / 60 for p in series]
        top = max(vals + [1]) * 1.12
    else:
        top = max([p["recurring_done"] + p["pontual"] for p in series] + [1]) * 1.12

    # grade leve
    pdf.hline(y0 + h - h / 1.12, LINE, x0, x0 + w, 0.15)
    pdf.font("label", 6.2, DIM)
    peak = top / 1.12
    pdf.text_at(x0, y0 - 3.6, 60, 3, ("pico " + _dur(round(peak * 60))) if use_time else f"pico {round(peak)} itens/{gran}")

    label_every = max(1, round(n / 16))
    for i, p in enumerate(series):
        cx = x0 + i * slot + slot / 2
        if not weekly and not p["work_day"]:
            pdf.box(x0 + i * slot + 0.3, y0, slot - 0.6, h, (250, 250, 252))
        if use_time:
            bh = h * (p["minutes"] / 60) / top
            if bh:
                pdf.box(cx - bw / 2, y0 + h - bh, bw, bh, ACCENT, r=min(0.8, bw / 2))
        else:
            r_h = h * p["recurring_done"] / top
            p_h = h * p["pontual"] / top
            if r_h:
                pdf.box(cx - bw / 2, y0 + h - r_h, bw, r_h, ACCENT_MID, r=0.6 if not p_h else 0)
            if p_h:
                pdf.box(cx - bw / 2, y0 + h - r_h - p_h, bw, p_h, ACCENT, r=0)
        if i % label_every == 0:
            pdf.font("label", 5.8, DIM)
            if gran == "mês":
                lab = MESES[p["date"].month - 1] + (f" {p['date'].year % 100:02d}" if p["date"].month == 1 or i == 0 else "")
            else:
                lab = _d(p["date"]) if weekly else str(p["date"].day)
            pdf.text_at(cx - 6, y0 + h + 1.2, 12, 3, lab, "C")
    pdf.hline(y0 + h, (200, 200, 208), x0, x0 + w, 0.25)

    # legenda
    ly = y0 + h + 6
    if use_time:
        items = [("horas apontadas", ACCENT)]
    elif by_project:
        items = [("tarefas concluídas", ACCENT)]
    else:
        items = [("rotinas feitas", ACCENT_MID), ("tarefas concluídas", ACCENT)]
    if not weekly and not use_time and not by_project:
        items.append(("dia não útil", (238, 238, 242)))
    lx = x0
    for label, col in items:
        pdf.box(lx, ly + 0.8, 2.6, 2.6, col, r=0.6)
        pdf.font("sans", 7, INK2)
        pdf.text_at(lx + 4, ly, 50, 4, label)
        lx += 6 + pdf.get_string_width(_s(label)) + 5
    pdf.set_y(ly + 10)


def _row_y(pdf: _Report, y: float, h: float, flow: bool) -> float:
    """Em coluna única (flow), quebra a página antes de uma linha que não cabe."""
    if flow and y + h > pdf.h - pdf.b_margin:
        pdf.add_page()
        return pdf.get_y()
    return y


def _recurring_block(pdf: _Report, stats: list, x: float, w: float, y: float, flow: bool = False) -> float:
    pdf.font("sanss", 10, INK)
    pdf.text_at(x, y, w, 5, "Rotinas")
    pdf.font("label", 6.6, DIM)
    pdf.text_at(x, y + 0.4, w, 5, "feitas / devidas", "R")
    y += 8
    for r in stats:
        if not r["due"] and not r["extra"]:
            continue
        y = _row_y(pdf, y, 12.5, flow)
        pct = round(100 * r["done"] / r["due"]) if r["due"] else None
        pdf.font("sans", 8.4, INK)
        pdf.text_at(x, y, w - 30, 4.2, pdf.fit(r["label"], w - 30))
        pdf.font("labelb", 7.4, INK if pct is None or pct >= 60 else WARN)
        right = f"{r['done']}/{r['due']}" + (f"  {pct}%" if pct is not None else "")
        pdf.text_at(x + w - 30, y, 30, 4.2, right, "R")
        pdf.font("label", 6.2, DIM)
        sub = _schedule(r) + (f" · +{r['extra']} extra" if r["extra"] else "")
        pdf.text_at(x, y + 4.3, w, 3.2, sub)
        pdf.box(x, y + 8, w, 1.1, LINE, r=0.55)
        if pct:
            pdf.box(x, y + 8, w * min(pct, 100) / 100, 1.1, ACCENT if pct >= 60 else WARN, r=0.55)
        y += 12.5
    return y


def _projects_block(pdf: _Report, projects: list, x: float, w: float, y: float, flow: bool = False) -> float:
    pdf.font("sanss", 10, INK)
    pdf.text_at(x, y, w, 5, "Projetos")
    pdf.font("label", 6.6, DIM)
    pdf.text_at(x, y + 0.4, w, 5, "tempo · concluídas", "R")
    y += 8
    top = max([p["minutes"] for p in projects] + [1])
    for p in projects:
        y = _row_y(pdf, y, 10, flow)
        col = _hex(p["color"]) if p["name"] else DIM
        pdf.dot(x, y + 1.1, 2.2, col)
        pdf.font("sans", 8.4, INK if p["name"] else INK2)
        pdf.text_at(x + 3.6, y, w - 34, 4.2, pdf.fit(p["name"] or "Sem projeto", w - 34))
        pdf.font("labelb", 7.4, INK)
        right = (_dur(p["minutes"]) if p["minutes"] else "—") + f" · {p['done']}"
        pdf.text_at(x + w - 30, y, 30, 4.2, right, "R")
        pdf.box(x, y + 6, w, 1.1, LINE, r=0.55)
        if p["minutes"]:
            pdf.box(x, y + 6, w * p["minutes"] / top, 1.1, col, r=0.55)
        y += 10
    return y


def _overview(pdf: _Report, data: dict) -> None:
    stats = [r for r in data["recurring_stats"] if r["due"] or r["extra"]] if not data.get("project") else []
    projects = [p for p in data["projects"] if p["minutes"] or p["done"]]
    if data.get("project"):
        projects = []  # num relatório de projeto, o bloco seria uma linha só
    if not stats and not projects:
        return
    need = 8 + max(len(stats) * 12.5, len(projects) * 10)
    pdf.room(min(need, 60))
    y = pdf.get_y()
    if stats and projects and y + need <= pdf.h - pdf.b_margin:
        # cabe na página: rotinas e projetos lado a lado
        col = (pdf.cw - 10) / 2
        y1 = _recurring_block(pdf, stats, M, col, y)
        y2 = _projects_block(pdf, projects, M + col + 10, col, y)
        pdf.set_y(max(y1, y2) + 6)
        return
    # não cabe (muitas rotinas): um bloco embaixo do outro, quebrando por linha
    if stats:
        y = _recurring_block(pdf, stats, M, pdf.cw, y, flow=True) + 6
    if projects:
        y = _row_y(pdf, y, 18, True)
        y = _projects_block(pdf, projects, M, pdf.cw, y, flow=True) + 6
    pdf.set_y(y)


def _table_head(pdf: _Report, cols: list) -> None:
    y = pdf.get_y()
    pdf.font("labelb", 6.4, DIM)
    x = M
    for label, w, align in cols:
        pdf.text_at(x, y, w, 4, label.upper(), align)
        x += w
    pdf.hline(y + 5, (210, 210, 216))
    pdf.set_y(y + 7)


def _project_tag(pdf: _Report, name, color, x, y, w) -> None:
    if not name:
        pdf.font("label", 7, DIM)
        pdf.text_at(x, y, w, 4, "—")
        return
    pdf.dot(x, y + 1.05, 2, _hex(color))
    pdf.font("sans", 7.6, INK2)
    pdf.text_at(x + 3.2, y, w - 3.2, 4, pdf.fit(name, w - 4))


def _deliveries(pdf: _Report, data: dict) -> None:
    rows = data["deliveries"]
    if not rows:
        return
    note = f"{len(rows)} concluída{'s' if len(rows) != 1 else ''}"
    _section(pdf, "Tarefas concluídas", note, prio_legend=any(r["priority"] == 1 for r in rows))
    show_proj = not data.get("project")
    wp = 36 if show_proj else 0
    cols = [("data", 15, "L"), ("tarefa", pdf.cw - 15 - wp - 16 - 15, "L")]
    if show_proj:
        cols.append(("projeto", wp, "L"))
    cols += [("tempo", 16, "R"), ("checklist", 15, "R")]
    _table_head(pdf, cols)
    tw = cols[1][1] - 4
    for r in rows:
        pdf.set_font("sansm", "", 8.8)
        n1 = pdf.lines(r["title"], tw, 4.2)
        n2 = 0
        if r["description"]:
            pdf.set_font("sans", "", 7.6)
            n2 = pdf.lines(r["description"], tw, 3.6)
        h = n1 * 4.2 + n2 * 3.6 + 3.4
        if pdf.get_y() + h > pdf.h - pdf.b_margin:
            pdf.add_page()
            _table_head(pdf, cols)
        y = pdf.get_y()
        pdf.font("label", 7.4, INK2)
        pdf.text_at(M, y, 15, 4.2, _d(r["done_date"]))
        x = M + 15
        if r["priority"] == 1:
            pdf.dot(x - 2.6, y + 1.4, 1.5, WARN)
        pdf.font("sansm", 8.8, INK)
        pdf.set_xy(x, y)
        pdf.multi_cell(tw, 4.2, _s(r["title"]), new_x="LEFT", new_y="NEXT")
        if r["description"]:
            pdf.font("sans", 7.6, INK2)
            pdf.set_x(x)
            pdf.multi_cell(tw, 3.6, _s(r["description"]), new_x="LEFT", new_y="NEXT")
        x += cols[1][1]
        if show_proj:
            _project_tag(pdf, r["project"], r["project_color"], x, y, wp)
            x += wp
        pdf.font("labelb", 7.6, ACCENT if r["minutes"] else DIM)
        pdf.text_at(x, y, 16, 4.2, _dur(r["minutes"]) if r["minutes"] else "—", "R")
        x += 16
        pdf.font("label", 7.4, OK if r["check_total"] and r["check_done"] == r["check_total"] else INK2)
        pdf.text_at(x, y, 15, 4.2, f"{r['check_done']}/{r['check_total']}" if r["check_total"] else "—", "R")
        pdf.set_y(y + h - 1.6)
        pdf.hline(pdf.get_y(), LINE)
        pdf.set_y(pdf.get_y() + 1.8)
    pdf.ln(6)


def _open(pdf: _Report, data: dict) -> None:
    rows = data["open"]
    if not rows:
        return
    today = data["today"]
    s = data["summary"]
    note = f"{len(rows)} em aberto em {_d(today)}" + (f" · {s['overdue']} atrasada{'s' if s['overdue'] != 1 else ''}" if s["overdue"] else "")
    _section(pdf, "Em aberto", note, prio_legend=any(r["priority"] == 1 for r in rows))
    show_proj = not data.get("project")
    wp = 36 if show_proj else 0
    cols = [("status", 24, "L"), ("tarefa", pdf.cw - 24 - wp - 28 - 15, "L")]
    if show_proj:
        cols.append(("projeto", wp, "L"))
    cols += [("prazo", 28, "R"), ("checklist", 15, "R")]
    _table_head(pdf, cols)
    limit = 40
    for r in rows[:limit]:
        if pdf.get_y() + 7 > pdf.h - pdf.b_margin:
            pdf.add_page()
            _table_head(pdf, cols)
        y = pdf.get_y()
        st_col = {"blocked": BAD, "in_progress": ACCENT}.get(r["status"], INK2)
        pdf.font("label", 7.2, st_col)
        pdf.text_at(M, y, 24, 4.2, _STATUS.get(r["status"], r["status"]))
        x = M + 24
        if r["priority"] == 1:
            pdf.dot(x - 2.6, y + 1.4, 1.5, WARN)
        pdf.font("sansm" if r["priority"] == 1 else "sans", 8.6, INK if r["priority"] != 3 else INK2)
        pdf.text_at(x, y, cols[1][1] - 3, 4.2, pdf.fit(r["title"], cols[1][1] - 4))
        x += cols[1][1]
        if show_proj:
            _project_tag(pdf, r["project"], r["project_color"], x, y, wp)
            x += wp
        if r["due_date"]:
            late = r["due_date"] < today
            pdf.font("labelb" if late else "label", 7.4, BAD if late else (WARN if r["due_date"] == today else INK2))
            txt = ("atrasada · " if late else "hoje · " if r["due_date"] == today else "") + _d(r["due_date"])
        else:
            pdf.font("label", 7.4, DIM)
            txt = "—"
        pdf.text_at(x, y, 28, 4.2, txt, "R")
        x += 28
        pdf.font("label", 7.4, INK2)
        pdf.text_at(x, y, 15, 4.2, f"{r['check_done']}/{r['check_total']}" if r["check_total"] else "—", "R")
        pdf.set_y(y + 5.4)
        pdf.hline(pdf.get_y(), LINE)
        pdf.set_y(pdf.get_y() + 1.6)
    if len(rows) > limit:
        pdf.font("sans", 7.6, DIM)
        pdf.text_at(M, pdf.get_y(), 100, 4, f"+ {len(rows) - limit} outras")
        pdf.ln(5)
    pdf.ln(6)


def _tokens(pdf: _Report, items: list, x0: float, w: float) -> None:
    """Recorrentes do dia em fluxo: ● feita, ○ não feita, + extra."""
    x, y = x0, pdf.get_y()
    pdf.set_font("sans", "", 7.8)
    for it in items:
        label = _s(it["label"])
        tw = min(pdf.get_string_width(label), w - 8)
        width = 4 + tw + 5
        if x + width > x0 + w:
            x, y = x0, y + 5
            if y + 5 > pdf.h - pdf.b_margin:
                pdf.add_page()
                y = pdf.get_y()
        if it.get("extra"):
            pdf.dot(x, y + 1.05, 2.3, ACCENT_SOFT, outline=ACCENT)
            color = ACCENT
        elif it["done"]:
            pdf.dot(x, y + 1.05, 2.3, ACCENT)
            color = INK
        else:
            pdf.dot(x, y + 1.05, 2.3, (255, 255, 255), outline=BAD)
            color = BAD
        pdf.set_font("sans", "", 7.8)
        pdf.set_text_color(*color)
        pdf.text_at(x + 3.6, y, tw + 1, 4.4, pdf.fit(label, tw + 0.5))
        x += width
    pdf.set_y(y + 6)


def _diary(pdf: _Report, data: dict) -> None:
    days = data["days"]
    if not days:
        return
    pdf.add_page()
    _section(pdf, "Diário", "o que foi feito, dia a dia")
    show_proj = not data.get("project")
    gx = M + 24  # coluna de conteúdo
    gw = pdf.cw - 24
    # Período com mais de um mês: o diário ganha um separador por mês (com ano).
    by_month = (days[0]["date"].year, days[0]["date"].month) != (days[-1]["date"].year, days[-1]["date"].month)
    month = None
    for day in days:
        d = day["date"]
        est = 9 + (6 if day["recurring"] else 0) + 5 * len(day["pontual"]) + 5 * len(day["time"])
        if by_month and (d.year, d.month) != month:
            month = (d.year, d.month)
            pdf.room(min(est, 40) + 10)
            ym = pdf.get_y()
            pdf.font("labelb", 7.4, ACCENT)
            pdf.text_at(M, ym, 80, 4, f"{MESES_LONGOS[d.month - 1]} {d.year}".upper())
            pdf.set_y(ym + 7)
        pdf.room(min(est, 40))
        y = pdf.get_y()
        page0 = pdf.page_no()
        # coluna da data
        pdf.font("sanss", 17, INK)
        pdf.text_at(M, y - 0.6, 22, 7, str(d.day))
        pdf.font("labelb", 6.4, DIM)
        pdf.text_at(M, y + 6.6, 22, 3, f"{DIAS_CURTOS[d.weekday()]} · {MESES[d.month - 1]}")
        if not day["work_day"]:
            pdf.font("label", 5.8, WARN)
            pdf.text_at(M, y + 10, 22, 3, "não útil")

        # resumo da linha
        pdf.set_y(y)
        bits = []
        if day["recurring_total"]:
            bits.append(f"rotinas {day['recurring_done']}/{day['recurring_total']}")
        if day["recurring_extra"]:
            bits.append(f"+{day['recurring_extra']} extra")
        if day["pontual"]:
            bits.append(f"{len(day['pontual'])} concluída{'s' if len(day['pontual']) != 1 else ''}")
        if day["minutes"]:
            bits.append(_dur(day["minutes"]))
        pdf.font("label", 6.8, DIM)
        pdf.text_at(gx, y, gw, 3.6, "  ·  ".join(bits))
        pdf.set_y(y + 5)

        if day["recurring"]:
            _tokens(pdf, day["recurring"], gx, gw)

        for w in day["pontual"]:
            pdf.room(5)
            yy = pdf.get_y()
            pdf.box(gx, yy + 1.1, 2.3, 2.3, OK, r=0.5)
            pdf.font("sansm", 8.4, INK)
            title_w = gw - 4 - (40 if show_proj and w["project"] else 0) - (14 if w["minutes"] else 0)
            pdf.text_at(gx + 3.6, yy, title_w, 4.4, pdf.fit(w["title"], title_w - 1))
            xr = gx + gw
            if w["minutes"]:
                pdf.font("labelb", 7.2, ACCENT)
                pdf.text_at(xr - 14, yy, 14, 4.4, _dur(w["minutes"]), "R")
                xr -= 16
            if show_proj and w["project"]:
                _project_tag(pdf, w["project"], w["project_color"], xr - 38, yy + 0.2, 38)
            pdf.set_y(yy + 5)

        if day["time"]:
            for e in day["time"]:
                pdf.room(5)
                yy = pdf.get_y()
                pdf.font("labelb", 7.2, ACCENT)
                pdf.text_at(gx, yy, 13, 4.2, _dur(e["minutes"]))
                pdf.font("sans", 7.8, INK2)
                txt = e["title"] + (f" — {e['note']}" if e["note"] else "")
                pdf.set_xy(gx + 14, yy)
                pdf.multi_cell(gw - 14, 4.2, _s(txt), new_x="LMARGIN", new_y="NEXT")
        # Se o dia quebrou de página, o "y" inicial era da página anterior.
        end_y = max(pdf.get_y(), y + 13) if pdf.page_no() == page0 else pdf.get_y()
        pdf.set_y(end_y + 1.5)
        pdf.hline(pdf.get_y(), LINE)
        pdf.set_y(pdf.get_y() + 4)


# ---------------------------------------------------------------- entrada --

def build_report_pdf(user_email: str, start: date, end: date, data: dict, branding: dict | None = None) -> bytes:
    brand = {"line1": "nexus", "line2": "worklog", "logo": None}
    brand.update({k: v for k, v in (branding or {}).items() if v is not None})
    generated = data.get("generated_at") or datetime.now()
    period = _period(start, end)

    if data.get("whole_project"):
        period = f"desde {_dfull(start)}"
    pdf = _Report(brand, (f"{data['project']} · " if data.get("project") else "") + period, generated.strftime("%d/%m/%Y %H:%M"))
    title = f"Relatório {brand['line1']} {brand['line2']} · {period}"
    pdf.set_title(_s(title))
    pdf.set_author(_s(user_email))
    pdf.set_creator("Nexus Worklog")
    pdf.add_page()

    _cover(pdf, user_email, data)
    _kpis(pdf, data)

    if not data["days"] and not data["open"]:
        pdf.box(M, pdf.get_y(), pdf.cw, 22, TILE, r=2.6)
        pdf.font("sans", 10, INK2)
        pdf.text_at(M, pdf.get_y() + 7, pdf.cw, 8, "Nenhuma atividade registrada no período.", "C")
        return bytes(pdf.output())

    if data["days"]:
        _chart(pdf, data)
    _overview(pdf, data)
    _deliveries(pdf, data)
    _open(pdf, data)
    _diary(pdf, data)
    return bytes(pdf.output())
