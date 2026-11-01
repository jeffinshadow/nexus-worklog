"""Paginação das listas grandes: `limit` + `offset` na consulta e o total no
cabeçalho X-Total-Count. A resposta continua sendo a mesma lista (a API, o MCP
e as integrações de antes não mudam); quem quer páginas lê o cabeçalho. A ordem
de toda lista paginada termina no id, para um item não aparecer em duas páginas."""
from fastapi import Response

TOTAL_HEADER = "X-Total-Count"


def put_total(response, total: int) -> None:
    """Total no cabeçalho (chamada direta, como a do MCP, não tem resposta)."""
    if isinstance(response, Response):
        response.headers[TOTAL_HEADER] = str(int(total))


def clamp(value, low: int, high: int, default: int) -> int:
    """Número dentro dos limites também quando a rota é chamada direto (MCP),
    sem a validação do Query."""
    try:
        return max(low, min(int(value), high))
    except (TypeError, ValueError):
        return default
