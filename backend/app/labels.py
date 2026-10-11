"""Rótulos e formatos usados em mais de um lugar (PDF, e-mail, MCP, ICS, CSV,
histórico, busca). Um lugar só para cada regra de apresentação."""

STATUS_PT = {"todo": "a fazer", "in_progress": "em andamento", "blocked": "bloqueada", "done": "concluída"}
PRIO_PT = {1: "alta", 2: "normal", 3: "baixa"}

# Sem acento e minúsculo; a mesma tabela da função nx_fold() do banco (sql/007).
_FOLD = str.maketrans("áàâãäåéèêëíìîïóòôõöúùûüçñ", "aaaaaaeeeeiiiiooooouuuucn")


def fold(text: str | None) -> str:
    return (text or "").lower().translate(_FOLD)


def dur(minutes: int | None) -> str:
    """Minutos → "45 min", "1h", "1h30"."""
    h, m = divmod(int(minutes or 0), 60)
    if not h:
        return f"{m} min"
    return f"{h}h{m:02d}" if m else f"{h}h"
