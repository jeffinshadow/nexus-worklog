"""Gera o PDF do 'Relatorio Worklog' (extracao por periodo) com fpdf2.

Sem dependencia do resto do app: recebe os dados ja montados por
services.get_report_range e devolve os bytes do PDF. Usa as fontes core
(Helvetica) em latin-1 -- cobrem os acentos do PT-BR; qualquer caractere fora
disso e substituido para nao quebrar a geracao.
"""

from datetime import date

from fpdf import FPDF

_WEEKDAYS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def _br_date(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _weekday(d: date) -> str:
    return _WEEKDAYS[d.weekday()]


def _s(text: str) -> str:
    """Sanitiza para latin-1 (fonte core do fpdf2)."""
    return (text or "").encode("latin-1", "replace").decode("latin-1")


class _Report(FPDF):
    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(130, 130, 130)
        self.cell(0, 8, text=_s(f"Página {self.page_no()}/{{nb}}"), align="C")


def build_report_pdf(user_email: str, start: date, end: date, data: dict) -> bytes:
    pdf = _Report(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_title(_s(f"Relatório Worklog - {user_email}"))
    pdf.add_page()

    lm = pdf.l_margin

    # --- Titulo ---
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, text=_s("Relatório Worklog"), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(70, 70, 70)
    pdf.cell(0, 6, text=_s(f"Usuário: {user_email}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(
        0, 6,
        text=_s(f"Período: {_br_date(start)} a {_br_date(end)}"),
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(3)

    # --- Resumo ---
    s = data["summary"]
    pdf.set_fill_color(238, 238, 240)
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, text=_s("Resumo do período"), new_x="LMARGIN", new_y="NEXT", fill=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(50, 50, 50)
    lines = [f"Recorrentes concluídas (dias úteis): {s['recurring_done']}/{s['recurring_total']}"]
    if s.get("recurring_extra"):
        lines.append(f"Recorrentes extras (dias não úteis): {s['recurring_extra']}")
    lines += [
        f"Pontuais concluídas: {s['pontual_done']}",
        f"Dias com atividade: {s['active_days']}",
    ]
    for line in lines:
        pdf.cell(0, 6, text=_s(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    if not data["days"]:
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(0, 8, text=_s("Nenhuma atividade no período."), new_x="LMARGIN", new_y="NEXT")
        return bytes(pdf.output())

    # --- Detalhamento diario ---
    for day in data["days"]:
        d = day["date"]

        # Evita titulo de dia "orfao" no pe da pagina: se nao cabe o cabecalho
        # e as primeiras linhas (~35 mm), o dia comeca na pagina seguinte.
        if pdf.get_y() > pdf.h - pdf.b_margin - 35:
            pdf.add_page()

        # Cabecalho do dia
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_fill_color(224, 227, 245)
        pdf.set_text_color(20, 20, 45)
        pdf.cell(
            0, 7,
            text=_s(f"{_weekday(d)}, {_br_date(d)}"
                    + ("" if day.get("work_day", True) else "  ·  dia não útil")),
            new_x="LMARGIN", new_y="NEXT", fill=True,
        )
        pdf.ln(1)

        # Recorrentes (concluidas e nao concluidas)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(40, 40, 40)
        if day.get("work_day", True):
            rec_title = f"Recorrentes ({day['recurring_done']}/{day['recurring_total']})"
        else:
            rec_title = f"Recorrentes extras ({day.get('recurring_extra', 0)})"
        pdf.cell(0, 5, text=_s(rec_title), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        if day["recurring"]:
            for r in day["recurring"]:
                if r["done"]:
                    pdf.set_text_color(30, 120, 45)
                    mark = "[x]"
                else:
                    pdf.set_text_color(155, 55, 55)
                    mark = "[ ]"
                pdf.set_x(lm + 3)
                pdf.multi_cell(0, 5, text=_s(f"{mark} {r['label']}"), new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_text_color(120, 120, 120)
            pdf.set_x(lm + 3)
            pdf.cell(0, 5, text=_s("(nenhuma)"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

        # Pontuais concluidas no dia
        pont = day["pontual"]
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(40, 40, 40)
        pdf.cell(0, 5, text=_s(f"Pontuais concluídas ({len(pont)})"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        if pont:
            for w in pont:
                pdf.set_text_color(40, 40, 40)
                pdf.set_x(lm + 3)
                pdf.multi_cell(0, 5, text=_s(f"- {w['title']}"), new_x="LMARGIN", new_y="NEXT")
                if w.get("description"):
                    pdf.set_font("Helvetica", "", 9)
                    pdf.set_text_color(110, 110, 110)
                    pdf.set_x(lm + 6)
                    pdf.multi_cell(0, 4.5, text=_s(w["description"]), new_x="LMARGIN", new_y="NEXT")
                    pdf.set_font("Helvetica", "", 10)
        else:
            pdf.set_text_color(120, 120, 120)
            pdf.set_x(lm + 3)
            pdf.cell(0, 5, text=_s("(nenhuma)"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    return bytes(pdf.output())
