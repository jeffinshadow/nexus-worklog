from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import config

pool = ConnectionPool(
    config.DATABASE_URL,
    min_size=1,
    max_size=10,
    kwargs={"row_factory": dict_row},
    open=False,
)


def init_pool() -> None:
    pool.open()
    pool.wait()


def query_one(sql: str, params=None):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchone()


def query_all(sql: str, params=None):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


def execute(sql: str, params=None) -> int:
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.rowcount


def execute_script(sql_text: str) -> None:
    """Roda um arquivo .sql inteiro. Sem parâmetros, o psycopg 3 aceita vários
    comandos numa chamada só (e numa transação: ou o arquivo todo, ou nada)."""
    with pool.connection() as conn:
        conn.execute(sql_text)
