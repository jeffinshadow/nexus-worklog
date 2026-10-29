"""Gera o PDF do relatório de atividades (extração por período) com fpdf2.

Sem dependência do resto do app: recebe os dados já montados por
services.get_report_range (+ a identidade visual) e devolve os bytes do PDF.

Conceito editorial: página branca, sem caixas; a hierarquia vem da
tipografia (Google Sans Flex, estáticas em assets/fonts) e de linhas finas.
Um parágrafo de abertura conta o período em texto corrido; os números
grandes vêm logo abaixo. A cor é só para dados: azul (#5294E2, o do app)
para o que foi feito, vermelho para o que ficou para trás, as cores dos
projetos só nos pontos. A matriz de rotinas (um ponto por dia) mostra a
aderência do período de relance.
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
INK = (20, 20, 23)
INK2 = (74, 74, 82)
DIM = (138, 138, 148)
FAINT = (196, 196, 204)
LINE = (226, 226, 231)
HAIR = (238, 238, 242)
ACCENT = (82, 148, 226)
ACCENT_MID = (168, 201, 241)
ACCENT_SOFT = (237, 244, 252)
BAD = (204, 70, 60)
WARN = (190, 134, 14)
WHITE = (255, 255, 255)
BAND = (18, 18, 19)  # o fundo do app: o ícone do logo

M = 18  # margem lateral (mm)


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
        self.set_margins(M, 24, M)
        self.set_auto_page_break(auto=True, margin=20)
        self.alias_nb_pages()

    def header(self):
        if self.page_no() == 1:
            return
        self.font("labelb", 6.8, INK2)
        self.text_at(M, 11, 90, 4, f"{self.brand['line1']} {self.brand['line2']}".strip())
        self.font("label", 6.8, DIM)
        self.text_at(self.w - M - 110, 11, 110, 4, self.period_text, "R")
        self.hline(16.5, LINE)
        self.set_y(24)

    def footer(self):
        self.font("label", 6.6, DIM)
        self.text_at(M, self.h - 12, 120, 4, f"gerado em {self.generated}")
        self.text_at(self.w - M - 40, self.h - 12, 40, 4, f"{self.page_no()} / {{nb}}", "R")

    # atalhos
    def font(self, fam: str, size: float, color=INK):
        self.set_font(fam, "", size)
        self.set_text_color(*color)

    def hline(self, y: float, color=LINE, x1=None, x2=None, width=0.2):
        self.set_draw_color(*color)
        self.set_line_width(width)
        self.line(M if x1 is None else x1, y, self.w - M if x2 is None else x2, y)

    def vline(self, x: float, y1: float, y2: float, color=LINE, width=0.2):
        self.set_draw_color(*color)
        self.set_line_width(width)
        self.line(x, y1, x, y2)

    def fill(self, color):
        self.set_fill_color(*color)

    def box(self, x, y, w, h, color, r=0.0):
        self.fill(color)
        if r:
            self.rect(x, y, w, h, style="F", round_corners=True, corner_radius=min(r, w / 2, h / 2))
        else:
            self.rect(x, y, w, h, style="F")

    def dot(self, x, y, d, color, outline=None, lw=0.3):
        """Círculo de diâmetro d com canto superior esquerdo em (x, y); outline sem fill = anel."""
        if outline:
            self.set_draw_color(*outline)
            self.set_line_width(lw)
        if color is None:
            self.circle(x + d / 2, y + d / 2, d / 2, style="D")
            return
        self.fill(color)
        self.circle(x + d / 2, y + d / 2, d / 2, style="DF" if outline else "F")

    @property
    def cw(self) -> float:
        return self.w - 2 * M

    @property
    def bottom(self) -> float:
        return self.h - self.b_margin

    def room(self, need: float) -> None:
        """Quebra a página se não couberem `need` mm a partir do y atual."""
        if self.get_y() + need > self.bottom:
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

    def para(self, x, y, w, lh, text) -> float:
        """Parágrafo com quebra (alinhado à esquerda); devolve o y depois dele."""
        self.set_xy(x, y)
        self.multi_cell(w, lh, _s(text), align="L", new_x="LMARGIN", new_y="NEXT")
        return self.get_y()


# ------------------------------------------------------------------ blocos --

def _plural(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


def _lede(data: dict) -> str:
    """O período em texto corrido: o que foi feito, o tempo, as rotinas e o que fica."""
    s = data["summary"]
    by_project = bool(data.get("project"))
    frases = []
    if s["active_days"]:
        frases.append(f"Em {_plural(s['period_days'], 'dia', 'dias')}, "
                      f"{s['active_days'] if s['active_days'] != s['period_days'] else 'todos'} "
                      f"{'teve' if s['active_days'] == 1 else 'tiveram'} atividade registrada.")
    feito = []
    if s["pontual_done"]:
        feito.append(_plural(s["pontual_done"], "tarefa concluída", "tarefas concluídas"))
    if s["minutes"]:
        t = f"{_dur(s['minutes'])} de tempo apontado"
        if s.get("minutes_after_hours"):
            t += f" ({_dur(s['minutes_after_hours'])} em plantão)"
        feito.append(t)
    if feito:
        frases.append(("Foram " if s["pontual_done"] != 1 or s["minutes"] else "Foi ") + " e ".join(feito) + ".")
    if s["recurring_total"] and not by_project:
        pct = round(100 * s["recurring_done"] / s["recurring_total"])
        r = f"As rotinas ficaram em {pct}%: {s['recurring_done']} de {s['recurring_total']} verificações devidas"
        r += f", mais {_plural(s['recurring_extra'], 'extra', 'extras')}." if s["recurring_extra"] else "."
        frases.append(r)
    if s["open"]:
        a = f"Ficam {_plural(s['open'], 'tarefa', 'tarefas')} em aberto"
        a += f", {_plural(s['overdue'], 'atrasada', 'atrasadas')}." if s["overdue"] else ", nenhuma atrasada."
        frases.append(a)
    return " ".join(frases) or "Nenhuma atividade registrada no período."


def _cover(pdf: _Report, user_email: str, data: dict) -> None:
    brand = pdf.brand
    y = 15
    # Lockup: o logo (claro, feito para o app escuro) num ícone escuro
    # arredondado, como ícone de app; vale para qualquer logo do admin.
    icon = 9.6
    pdf.box(M, y - 1.6, icon, icon, BAND, r=2.4)
    for logo in (brand.get("logo"), (ASSETS / "dragon-mark.svg").read_bytes()):
        if not logo:
            continue
        try:
            pdf.image(io.BytesIO(logo), x=M + 1.4, y=y - 0.2, w=icon - 2.8, h=icon - 2.8, keep_aspect_ratio=True)
            break
        except Exception:  # logo que o fpdf2 não entende: cai no dragão
            continue
    w = icon
    pdf.set_font("sans", "B", 10)
    pdf.set_text_color(*INK)
    pdf.text_at(M + w + 2.6, y - 1.2, 40, 4.4, brand["line1"])
    pdf.set_text_color(*DIM)
    pdf.text_at(M + w + 2.6, y + 2.9, 40, 4.4, brand["line2"])
    pdf.font("labelb", 6.6, DIM)
    pdf.text_at(pdf.w - M - 90, y + 1.6, 90, 4,
                "RELATÓRIO DE ATIVIDADES" + (" · PROJETO" if data.get("project") else ""), "R")
    pdf.hline(y + 11, INK, width=0.35)

    # título: o período (ou o projeto) grande
    y += 21
    if data.get("project"):
        eyebrow = "projeto completo" if data.get("whole_project") and not data.get("project_truncated") else \
            "últimos 3 anos do projeto" if data.get("whole_project") else _period(data["start"], data["end"])
        if data.get("whole_project"):
            eyebrow += f" · desde {_dfull(data['start'])}"
    else:
        eyebrow = "período"
    pdf.font("labelb", 7.2, ACCENT)
    pdf.text_at(M, y, pdf.cw, 4, eyebrow.upper())
    pdf.font("sanss", 28, INK)
    titulo = data.get("project") or _period(data["start"], data["end"])
    pdf.text_at(M, y + 5, pdf.cw, 13, pdf.fit(titulo, pdf.cw))
    pdf.font("sans", 9, INK2)
    pdf.text_at(M, y + 19, pdf.cw, 5, user_email)

    # abertura: o período em texto corrido, com a marca azul do lado
    y += 31
    pdf.font("sans", 11.2, INK2)
    lede_w = pdf.cw * 0.86
    end = pdf.para(M + 5, y, lede_w, 5.6, _lede(data))
    pdf.box(M, y + 0.8, 0.9, end - y - 1.4, ACCENT)
    pdf.set_y(end + 8)


def _figures(pdf: _Report, data: dict) -> None:
    """Números grandes em colunas separadas por linhas finas (sem caixas)."""
    s = data["summary"]
    by_project = bool(data.get("project"))
    cols = []
    if not by_project:
        pct = round(100 * s["recurring_done"] / s["recurring_total"]) if s["recurring_total"] else None
        cols.append(("rotinas", f"{pct}%" if pct is not None else "—",
                     f"{s['recurring_done']} de {s['recurring_total']} devidas" if s["recurring_total"] else "nenhuma devida", pct))
    cols.append(("concluídas", str(s["pontual_done"]), "tarefas", None))
    cols.append(("tempo", _dur(s["minutes"]) if s["minutes"] else "—",
                 (f"{_dur(s['minutes_after_hours'])} em plantão" if s.get("minutes_after_hours") else
                  f"média {_dur(s['minutes'] // max(1, s.get('time_days') or s['active_days']))}/dia")
                 if s["minutes"] else "nada apontado", None))
    if by_project:
        cols.append(("em aberto", str(s["open"]), _plural(s["overdue"], "atrasada", "atrasadas") if s["overdue"] else "nenhuma atrasada", None))
    cols.append(("dias ativos", str(s["active_days"]), f"de {s['period_days']}", None))

    y = pdf.get_y()
    h = 25
    pdf.hline(y, LINE)
    w = pdf.cw / len(cols)
    for i, (label, value, sub, pct) in enumerate(cols):
        x = M + i * w + (0 if i == 0 else 5)
        if i:
            pdf.vline(M + i * w, y + 4, y + h - 4)
        pdf.font("labelb", 6.4, DIM)
        pdf.text_at(x, y + 4.5, w - 6, 3.5, label.upper())
        pdf.font("sans", 22, INK)
        pdf.text_at(x, y + 9, w - 6, 9, value)
        pdf.font("sans", 7.4, DIM)
        pdf.text_at(x, y + 18.4, w - 6, 3.8, pdf.fit(sub, w - 7))
    pdf.hline(y + h, LINE)
    pdf.set_y(y + h + 11)


def _section(pdf: _Report, title: str, note: str = "", need: float = 18, legend=None) -> float:
    """Título de seção: texto, nota ou legenda à direita e uma régua; devolve
    o y onde o conteúdo começa."""
    pdf.room(need + 12)
    y = pdf.get_y()
    pdf.font("sanss", 11.5, INK)
    pdf.text_at(M, y, 120, 6, title)
    if legend:
        _legend(pdf, pdf.w - M, y + 1.2, legend)
    elif note:
        pdf.font("label", 7, DIM)
        pdf.text_at(pdf.w - M - 120, y + 1, 120, 5, note, "R")
    pdf.hline(y + 8, INK, width=0.3)
    pdf.set_y(y + 12)
    return y + 12


def _legend(pdf: _Report, x_right: float, y: float, items: list) -> None:
    """Legenda pequena alinhada à direita: [(rótulo, desenho(x, y))]."""
    pdf.set_font("label", "", 6.8)
    widths = [pdf.get_string_width(_s(lab)) + 4.6 for lab, _ in items]
    x = x_right - sum(widths) - 4 * (len(items) - 1)
    for (lab, draw), wd in zip(items, widths):
        draw(x, y + 0.9)
        pdf.font("label", 6.8, INK2)
        pdf.text_at(x + 3.2, y, wd, 4, lab)
        x += wd + 4


def _chart(pdf: _Report, data: dict) -> None:
    series = data["series"]
    by_project = bool(data.get("project"))
    # Até 62 dias = por dia; até ~6 meses = por semana (domingo a sábado); acima, por mês.
    n_days = len(series)
    gran = "dia" if n_days <= 62 else "semana" if n_days <= 186 else "mês"
    if gran != "dia":
        buckets: dict[date, dict] = {}
        for p in series:
            k = week_start(p["date"]) if gran == "semana" else p["date"].replace(day=1)
            b = buckets.setdefault(k, {"date": k, "work_day": True, "recurring_done": 0, "pontual": 0, "minutes": 0})
            for f in ("recurring_done", "pontual", "minutes"):
                b[f] += p[f]
        series = list(buckets.values())

    has_min = any(p["minutes"] for p in series)
    use_time = has_min and (by_project or not any(p["recurring_done"] for p in series))
    if use_time:
        items = [("horas apontadas", lambda x, y: pdf.box(x, y, 2.2, 2.2, ACCENT, r=0.4))]
    elif by_project:
        items = [("tarefas concluídas", lambda x, y: pdf.box(x, y, 2.2, 2.2, ACCENT, r=0.4))]
    else:
        items = [("rotinas feitas", lambda x, y: pdf.box(x, y, 2.2, 2.2, ACCENT_MID, r=0.4)),
                 ("tarefas concluídas", lambda x, y: pdf.box(x, y, 2.2, 2.2, ACCENT, r=0.4))]
    y0 = _section(pdf, f"Ritmo por {gran}", need=56, legend=items)

    x0, y0, w, h = M, y0 + 5, pdf.cw, 36
    n = len(series)
    slot = w / max(n, 1)
    bw = min(slot * 0.56, 6)
    vals = [p["minutes"] / 60 if use_time else p["recurring_done"] + p["pontual"] for p in series]
    top = max(vals + [1])
    show_vals = n <= 21

    for frac in (0.5, 1.0):  # duas linhas de referência, bem claras
        yy = y0 + h - h * frac
        pdf.hline(yy, HAIR, x0, x0 + w, 0.15)
        pdf.font("label", 5.6, FAINT)
        ref = _dur(round(top * frac * 60)) if use_time else str(round(top * frac, 1)).rstrip("0").rstrip(".")
        pdf.text_at(x0 - 10.5, yy - 1.6, 9.5, 3, ref, "R")
    label_every = max(1, round(n / 16))
    for i, p in enumerate(series):
        cx = x0 + i * slot + slot / 2
        if use_time:
            parts = [(p["minutes"] / 60, ACCENT)]
        else:
            parts = [(p["recurring_done"], ACCENT_MID), (p["pontual"], ACCENT)]
        base = y0 + h
        for v, col in parts:
            bh = h * v / top
            if bh > 0:
                pdf.box(cx - bw / 2, base - bh, bw, bh, col)
                base -= bh
        if show_vals and vals[i]:
            pdf.font("labelb", 6, INK2)
            pdf.text_at(cx - 6, base - 4, 12, 3.4, _dur(p["minutes"]) if use_time else str(vals[i]), "C")
        if i % label_every == 0:
            off = gran == "dia" and not p["work_day"]
            if gran == "mês":
                lab = MESES[p["date"].month - 1] + (f" {p['date'].year % 100:02d}" if p["date"].month == 1 or i == 0 else "")
            elif gran == "semana":
                lab = _d(p["date"])
            else:
                lab = str(p["date"].day)
            pdf.font("labelb" if not off else "label", 6, INK2 if not off else FAINT)
            pdf.text_at(cx - 6, y0 + h + 1.6, 12, 3, lab, "C")
            if gran == "dia" and n <= 31:
                pdf.font("label", 5, FAINT if off else DIM)
                pdf.text_at(cx - 6, y0 + h + 4.4, 12, 2.6, DIAS_CURTOS[p["date"].weekday()], "C")
    pdf.hline(y0 + h, INK2, x0, x0 + w, 0.25)
    pdf.set_y(y0 + h + 13)


def _matrix(pdf: _Report, data: dict) -> bool:
    """Rotinas × dias: ● feita, ○ perdida (vermelho), ● claro = extra, · fora da
    agenda. Só para períodos de até 62 dias (depois, a lista com barras)."""
    stats = [r for r in data["recurring_stats"] if r["due"] or r["extra"]]
    series = data["series"]
    n = len(series)
    if not stats or n > 62:
        return False
    label_w, right_w = 52, 26
    grid_w = pdf.cw - label_w - right_w - 3
    step = min(grid_w / n, 11)  # período curto: os dias se espalham pela largura
    d = min(step * 0.62, 2.8)
    y = _section(pdf, "Rotinas", need=14 + 6 * min(len(stats), 6), legend=[
        ("feita", lambda x, yy: pdf.dot(x, yy, 2.2, ACCENT)),
        ("perdida", lambda x, yy: pdf.dot(x + 0.15, yy + 0.15, 1.9, None, outline=BAD, lw=0.35)),
        ("extra", lambda x, yy: pdf.dot(x, yy, 2.2, ACCENT_MID)),
        ("fora da agenda", lambda x, yy: pdf.dot(x + 0.75, yy + 0.75, 0.7, FAINT)),
    ])

    def head(yh):
        every = 1 if n <= 31 else 7
        for i, p in enumerate(series):
            if i % every == 0:
                off = not p["work_day"]
                pdf.font("label", 5.4, FAINT if off else DIM)
                pdf.text_at(M + label_w + i * step, yh, step, 3, str(p["date"].day), "C")
        pdf.font("labelb", 6, DIM)
        pdf.text_at(pdf.w - M - right_w, yh, right_w, 3, "FEITAS", "R")
        return yh + 5

    y = head(y)
    row_h = 6.4
    for r in stats:
        if y + row_h > pdf.bottom:
            pdf.add_page()
            y = head(pdf.get_y())
        pdf.font("sans", 8, INK)
        pdf.text_at(M, y, label_w - 3, row_h, pdf.fit(r["label"], label_w - 4))
        cy = y + (row_h - d) / 2
        for i, mk in enumerate(r.get("marks", "")):
            cx = M + label_w + i * step + (step - d) / 2
            if mk == "D":
                pdf.dot(cx, cy, d, ACCENT)
            elif mk == "E":
                pdf.dot(cx, cy, d, ACCENT_MID)
            elif mk == "M":
                pdf.dot(cx + 0.18, cy + 0.18, d - 0.36, None, outline=BAD, lw=0.35)
            elif mk == "P":
                pdf.dot(cx + 0.18, cy + 0.18, d - 0.36, None, outline=FAINT, lw=0.3)
            elif mk == "O":
                pdf.dot(cx + d / 2 - 0.35, cy + d / 2 - 0.35, 0.7, FAINT)
        pct = round(100 * r["done"] / r["due"]) if r["due"] else None
        pdf.font("labelb", 7.4, INK if pct is None or pct >= 60 else BAD)
        pdf.text_at(pdf.w - M - right_w, y, right_w, row_h,
                    (f"{pct}%" if pct is not None else "extra") + "", "R")
        pdf.font("label", 6, DIM)
        pdf.text_at(pdf.w - M - right_w, y, right_w - 11, row_h, f"{r['done']}/{r['due']}" + (f" +{r['extra']}" if r["extra"] else ""), "R")
        pdf.hline(y + row_h, HAIR)
        y += row_h
    pdf.set_y(y + 11)
    return True


def _recurring_list(pdf: _Report, data: dict) -> None:
    """Período longo: cada rotina com a barra de cumprimento."""
    stats = [r for r in data["recurring_stats"] if r["due"] or r["extra"]]
    if not stats:
        return
    y = _section(pdf, "Rotinas", "feitas / devidas", need=20)
    for r in stats:
        if y + 9 > pdf.bottom:
            pdf.add_page()
            y = pdf.get_y()
        pct = round(100 * r["done"] / r["due"]) if r["due"] else None
        pdf.font("sans", 8.4, INK)
        pdf.text_at(M, y, 70, 4.2, pdf.fit(r["label"], 68))
        pdf.font("label", 6.2, DIM)
        pdf.text_at(M, y + 4.2, 70, 3, _schedule(r) + (f" · +{r['extra']} extra" if r["extra"] else ""))
        bx, bw = M + 74, pdf.cw - 74 - 30
        pdf.box(bx, y + 2.4, bw, 1.2, HAIR, r=0.6)
        if pct:
            pdf.box(bx, y + 2.4, bw * min(pct, 100) / 100, 1.2, ACCENT if pct >= 60 else BAD, r=0.6)
        pdf.font("labelb", 7.4, INK if pct is None or pct >= 60 else BAD)
        pdf.text_at(pdf.w - M - 28, y + 0.6, 28, 4.2, f"{r['done']}/{r['due']}" + (f"  {pct}%" if pct is not None else ""), "R")
        y += 9
    pdf.set_y(y + 8)


def _projects(pdf: _Report, data: dict) -> None:
    projects = [p for p in data["projects"] if p["minutes"] or p["done"]]
    if data.get("project") or not projects:
        return
    y = _section(pdf, "Projetos", "tempo apontado · tarefas concluídas", need=10 + 8 * min(len(projects), 4))
    top = max([p["minutes"] for p in projects] + [1])
    for p in projects:
        if y + 8 > pdf.bottom:
            pdf.add_page()
            y = pdf.get_y()
        col = _hex(p["color"]) if p["name"] else FAINT
        pdf.dot(M, y + 1.4, 2.2, col)
        pdf.font("sans", 8.6, INK if p["name"] else INK2)
        pdf.text_at(M + 4, y, 52, 5, pdf.fit(p["name"] or "Sem projeto", 50))
        bx, bw = M + 58, pdf.cw - 58 - 34
        if p["minutes"]:
            pdf.box(bx, y + 1.9, bw * p["minutes"] / top, 1.4, col, r=0.7)
        pdf.font("labelb", 7.6, INK)
        pdf.text_at(pdf.w - M - 32, y, 18, 5, _dur(p["minutes"]) if p["minutes"] else "—", "R")
        pdf.font("label", 7.2, DIM)
        pdf.text_at(pdf.w - M - 13, y, 13, 5, str(p["done"]), "R")
        y += 8
    if data.get("multi_project"):  # a soma das linhas passa do total: explica
        pdf.font("label", 6.6, DIM)
        pdf.text_at(M, y, pdf.cw, 4, "Uma tarefa em mais de um projeto conta inteira em cada um.")
        y += 5
    pdf.set_y(y + 8)


def _table_head(pdf: _Report, cols: list) -> None:
    y = pdf.get_y()
    pdf.font("labelb", 6.2, DIM)
    x = M
    for label, w, align in cols:
        pdf.text_at(x, y, w, 4, label.upper(), align)
        x += w
    pdf.set_y(y + 6)


def _project_tag(pdf: _Report, name, color, x, y, w) -> None:
    if not name:
        pdf.font("label", 7.4, FAINT)
        pdf.text_at(x, y, w, 4.2, "—")
        return
    pdf.dot(x, y + 1.2, 1.9, _hex(color))
    pdf.font("sans", 7.6, INK2)
    pdf.text_at(x + 3.2, y, w - 3.2, 4.2, pdf.fit(name, w - 4))


def _deliveries(pdf: _Report, data: dict) -> None:
    rows = data["deliveries"]
    if not rows:
        return
    prio = [("prioridade alta", lambda x, y: pdf.dot(x + 0.4, y + 0.4, 1.4, WARN))] if any(r["priority"] == 1 for r in rows) else None
    _section(pdf, f"Tarefas concluídas ({len(rows)})", legend=prio)
    show_proj = not data.get("project")
    wp = 38 if show_proj else 0
    cols = [("dia", 14, "L"), ("tarefa", pdf.cw - 14 - wp - 16 - 14, "L")]
    if show_proj:
        cols.append(("projeto", wp, "L"))
    cols += [("tempo", 16, "R"), ("itens", 14, "R")]
    _table_head(pdf, cols)
    tw = cols[1][1] - 5
    for r in rows:
        pdf.set_font("sansm", "", 8.6)
        n1 = pdf.lines(r["title"], tw, 4.2)
        n2 = 0
        if r["description"]:
            pdf.set_font("sans", "", 7.4)
            n2 = pdf.lines(r["description"], tw, 3.6)
        h = n1 * 4.2 + n2 * 3.6 + 3.6
        if pdf.get_y() + h > pdf.bottom:
            pdf.add_page()
            _table_head(pdf, cols)
        y = pdf.get_y()
        pdf.font("label", 7.2, DIM)
        pdf.text_at(M, y, 14, 4.2, _d(r["done_date"]))
        x = M + 14
        if r["priority"] == 1:
            pdf.dot(x - 2.4, y + 1.5, 1.3, WARN)
        pdf.font("sansm", 8.6, INK)
        pdf.set_xy(x, y)
        pdf.multi_cell(tw, 4.2, _s(r["title"]), new_x="LEFT", new_y="NEXT")
        if r["description"]:
            pdf.font("sans", 7.4, DIM)
            pdf.set_x(x)
            pdf.multi_cell(tw, 3.6, _s(r["description"]), new_x="LEFT", new_y="NEXT")
        x += cols[1][1]
        if show_proj:
            _project_tag(pdf, r["project"], r["project_color"], x, y, wp)
            x += wp
        pdf.font("labelb", 7.6, ACCENT if r["minutes"] else FAINT)
        pdf.text_at(x, y, 16, 4.2, _dur(r["minutes"]) if r["minutes"] else "—", "R")
        x += 16
        pdf.font("label", 7.2, INK2 if r["check_total"] else FAINT)
        pdf.text_at(x, y, 14, 4.2, f"{r['check_done']}/{r['check_total']}" if r["check_total"] else "—", "R")
        pdf.set_y(y + h - 1.7)
        pdf.hline(pdf.get_y(), HAIR)
        pdf.set_y(pdf.get_y() + 1.9)
    pdf.ln(8)


def _open(pdf: _Report, data: dict) -> None:
    rows = data["open"]
    if not rows:
        return
    today = data["today"]
    s = data["summary"]
    note = f"em {_d(today)}" + (f" · {_plural(s['overdue'], 'atrasada', 'atrasadas')}" if s["overdue"] else "")
    _section(pdf, f"Em aberto ({len(rows)})", note,
             legend=[("prioridade alta", lambda x, y: pdf.dot(x + 0.4, y + 0.4, 1.4, WARN))] if any(r["priority"] == 1 for r in rows) else None)
    show_proj = not data.get("project")
    wp = 38 if show_proj else 0
    cols = [("situação", 26, "L"), ("tarefa", pdf.cw - 26 - wp - 28, "L")]
    if show_proj:
        cols.append(("projeto", wp, "L"))
    cols += [("prazo", 28, "R")]
    _table_head(pdf, cols)
    limit = 40
    for r in rows[:limit]:
        if pdf.get_y() + 7 > pdf.bottom:
            pdf.add_page()
            _table_head(pdf, cols)
        y = pdf.get_y()
        st_col = {"blocked": BAD, "in_progress": ACCENT}.get(r["status"], DIM)
        pdf.dot(M, y + 1.4, 1.6, st_col)
        pdf.font("label", 7.2, INK2)
        pdf.text_at(M + 3, y, 23, 4.2, _STATUS.get(r["status"], r["status"]))
        x = M + 26
        if r["priority"] == 1:
            pdf.dot(x - 2.4, y + 1.5, 1.3, WARN)
        pdf.font("sansm" if r["priority"] == 1 else "sans", 8.6, INK if r["priority"] != 3 else INK2)
        tw = cols[1][1] - 4
        tx = r["title"] + (f" — {r['check_done']}/{r['check_total']} itens" if r["check_total"] else "")
        pdf.text_at(x, y, tw, 4.2, pdf.fit(tx, tw))
        x += cols[1][1]
        if show_proj:
            _project_tag(pdf, r["project"], r["project_color"], x, y, wp)
            x += wp
        if r["due_date"]:
            late, hoje = r["due_date"] < today, r["due_date"] == today
            pdf.font("labelb" if late or hoje else "label", 7.4, BAD if late else WARN if hoje else INK2)
            txt = ("atrasada · " if late else "hoje · " if hoje else "") + _d(r["due_date"])
        else:
            pdf.font("label", 7.4, FAINT)
            txt = "—"
        pdf.text_at(x, y, 28, 4.2, txt, "R")
        pdf.set_y(y + 5.6)
        pdf.hline(pdf.get_y(), HAIR)
        pdf.set_y(pdf.get_y() + 1.8)
    if len(rows) > limit:
        pdf.font("sans", 7.6, DIM)
        pdf.text_at(M, pdf.get_y(), 100, 4, f"+ {len(rows) - limit} outras")
        pdf.ln(5)
    pdf.ln(8)


def _tokens(pdf: _Report, items: list, x0: float, w: float) -> None:
    """Rotinas do dia em fluxo: ● feita, ○ perdida, ● claro = extra."""
    x, y = x0, pdf.get_y()
    for it in items:
        pdf.set_font("sans", "", 7.6)
        label = _s(it["label"])
        tw = min(pdf.get_string_width(label), w - 8)
        width = 3.6 + tw + 5
        if x + width > x0 + w:
            x, y = x0, y + 4.8
            if y + 5 > pdf.bottom:
                pdf.add_page()
                y = pdf.get_y()
        if it.get("extra"):
            pdf.dot(x, y + 1.2, 2, ACCENT_MID)
            color = INK2
        elif it["done"]:
            pdf.dot(x, y + 1.2, 2, ACCENT)
            color = INK2
        else:
            pdf.dot(x + 0.15, y + 1.35, 1.7, None, outline=BAD, lw=0.3)
            color = BAD
        pdf.font("sans", 7.6, color)
        pdf.text_at(x + 3.3, y, tw + 1, 4.4, pdf.fit(label, tw + 0.5))
        x += width
    pdf.set_y(y + 5.6)


def _diary(pdf: _Report, data: dict) -> None:
    days = data["days"]
    if not days:
        return
    pdf.add_page()
    _section(pdf, "Diário", "o que foi feito, dia a dia")
    show_proj = not data.get("project")
    gx = M + 22  # coluna de conteúdo
    gw = pdf.cw - 22
    by_month = (days[0]["date"].year, days[0]["date"].month) != (days[-1]["date"].year, days[-1]["date"].month)
    month = None
    for day in days:
        d = day["date"]
        est = 10 + (6 if day["recurring"] else 0) + 5 * len(day["pontual"]) + 4.6 * len(day["time"])
        if by_month and (d.year, d.month) != month:
            month = (d.year, d.month)
            pdf.room(min(est, 40) + 12)
            ym = pdf.get_y()
            pdf.font("labelb", 7.2, ACCENT)
            pdf.text_at(M, ym, 80, 4, f"{MESES_LONGOS[d.month - 1]} {d.year}".upper())
            pdf.set_y(ym + 8)
        pdf.room(min(est, 40))
        y = pdf.get_y()
        off = not day["work_day"]
        pdf.font("sans", 18, INK if not off else DIM)
        pdf.text_at(M, y - 1.2, 20, 8, str(d.day))
        pdf.font("labelb", 6.2, WARN if off else DIM)
        pdf.text_at(M, y + 6.8, 20, 3, DIAS_CURTOS[d.weekday()] + ("" if not off else " · não útil"))

        bits = []
        if day["recurring_total"]:
            bits.append(f"rotinas {day['recurring_done']}/{day['recurring_total']}")
        if day["recurring_extra"]:
            bits.append(f"+{day['recurring_extra']} extra")
        if day["pontual"]:
            bits.append(_plural(len(day["pontual"]), "concluída", "concluídas"))
        if day["minutes"]:
            bits.append(_dur(day["minutes"]))
        pdf.font("labelb", 6.6, DIM)
        pdf.text_at(gx, y, gw, 3.6, "   ".join(bits).upper())
        pdf.set_y(y + 5.4)

        if day["recurring"]:
            _tokens(pdf, day["recurring"], gx, gw)
            for r in day["recurring"]:
                if r.get("note"):
                    pdf.room(5)
                    yy = pdf.get_y()
                    pdf.font("sans", 7.4, INK2)
                    pdf.set_xy(gx + 3.3, yy)
                    pdf.multi_cell(gw - 3.3, 3.8, _s(f"“{r['note']}” — {r['label']}"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_y(pdf.get_y() + 1)

        for w in day["pontual"]:
            pdf.room(5)
            yy = pdf.get_y()
            pdf.set_draw_color(*ACCENT)
            pdf.set_line_width(0.45)
            pdf.line(gx + 0.2, yy + 2.3, gx + 0.9, yy + 3.0)
            pdf.line(gx + 0.9, yy + 3.0, gx + 2.2, yy + 1.4)
            pdf.font("sansm", 8.4, INK)
            title_w = gw - 4 - (42 if show_proj and w["project"] else 0) - 14
            pdf.text_at(gx + 3.3, yy, title_w, 4.6, pdf.fit(w["title"], title_w - 1))
            if show_proj and w["project"]:
                _project_tag(pdf, w["project"], w["project_color"], gx + gw - 56, yy + 0.2, 40)
            if w["minutes"]:
                pdf.font("labelb", 7.2, ACCENT)
                pdf.text_at(gx + gw - 14, yy, 14, 4.6, _dur(w["minutes"]), "R")
            pdf.set_y(yy + 5)

        # Tempo do dia: a linha da tarefa concluída no dia já tem o tempo; só
        # repete se tiver anotação (então mostra a anotação).
        feitas = {w["title"] for w in day["pontual"]}
        tempo = [e for e in day["time"] if e["title"] not in feitas or e["note"]]
        if tempo:
            for e in tempo:
                pdf.room(5)
                yy = pdf.get_y()
                pdf.font("labelb", 6.8, ACCENT)
                pdf.text_at(gx + 3.3, yy, 12, 4, _dur(e["minutes"]))
                pdf.font("sans", 7.4, DIM)
                txt = (e["note"] if e["title"] in feitas else e["title"] + (f" — {e['note']}" if e["note"] else ""))
                pdf.set_xy(gx + 16, yy)
                pdf.multi_cell(gw - 16, 4, _s(txt), new_x="LMARGIN", new_y="NEXT")
        end_y = max(pdf.get_y(), y + 12)
        pdf.set_y(end_y + 2.4)
        pdf.hline(pdf.get_y(), HAIR)
        pdf.set_y(pdf.get_y() + 4.4)


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
    _figures(pdf, data)

    if not data["days"] and not data["open"]:
        return bytes(pdf.output())

    if data["days"]:
        _chart(pdf, data)
    if not data.get("project") and not _matrix(pdf, data):
        _recurring_list(pdf, data)
    _projects(pdf, data)
    _deliveries(pdf, data)
    _open(pdf, data)
    _diary(pdf, data)
    return bytes(pdf.output())
