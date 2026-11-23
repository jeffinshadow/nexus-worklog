from contextlib import contextmanager
from contextvars import ContextVar

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import config

# Nenhuma consulta passa de 15 s e ninguém espera mais de 10 s por uma
# conexão do pool (PoolTimeout vira 503 em main.py, como o Busy).
pool = ConnectionPool(
    config.DATABASE_URL,
    min_size=1,
    max_size=10,
    timeout=10,
    # jit=off: em conta grande o JIT custava mais de 1 s por consulta e não poupava nada.
    kwargs={"row_factory": dict_row, "options": "-c statement_timeout=15000 -c jit=off"},
    # Confere a conexão antes de entregá-la: depois de o Postgres reiniciar, as
    # que morreram são trocadas aqui em vez de virarem erro 500 nas próximas chamadas.
    check=ConnectionPool.check_connection,
    open=False,
)

# A conexão da transação aberta por transaction() nesta chamada (None = fora de
# uma: cada comando usa a sua conexão e grava sozinho, como sempre foi).
_tx: ContextVar = ContextVar("nexus_tx", default=None)


def init_pool() -> None:
    pool.open()
    pool.wait()


@contextmanager
def transaction():
    """Tudo ou nada para uma operação de vários comandos (desfazer, excluir um
    projeto, trocar a agenda de uma rotina): os db.* chamados aqui dentro usam a
    mesma conexão e só gravam no fim; uma exceção desfaz tudo, inclusive a linha
    do histórico. Uma dentro da outra é a mesma transação (a de fora decide).

    Cada comando roda num ponto de salvamento: um erro tratado pelo código (ex.:
    UniqueViolation da chave externa) não derruba a transação inteira.

    Vale para a chamada atual. Uma thread aberta aqui dentro (e-mail, push) usa
    outra conexão e NÃO enxerga o que ainda não foi gravado: dispare-a depois do
    bloco."""
    if _tx.get() is not None:
        yield
        return
    # O bloco de fora é a transação de verdade; os conn.transaction() de cada
    # comando (em _cursor) viram pontos de salvamento dentro dela.
    with pool.connection() as conn, conn.transaction():
        token = _tx.set(conn)
        try:
            yield
        finally:
            _tx.reset(token)


@contextmanager
def _cursor():
    conn = _tx.get()
    if conn is None:
        with pool.connection() as conn, conn.cursor() as cur:
            yield cur
    else:
        with conn.transaction(), conn.cursor() as cur:
            yield cur


def query_one(sql: str, params=None):
    with _cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchone()


def query_all(sql: str, params=None):
    with _cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


def execute(sql: str, params=None) -> int:
    with _cursor() as cur:
        cur.execute(sql, params or ())
        return cur.rowcount


def execute_script(sql_text: str) -> None:
    """Roda um arquivo .sql inteiro. Sem parâmetros, o psycopg 3 aceita vários
    comandos numa chamada só (e numa transação: ou o arquivo todo, ou nada).

    Migração não tem o teto de 15 s das rotas (uma que passasse disso nunca
    aplicaria e o backend não subiria). SET LOCAL vale só nesta transação: a
    conexão volta ao pool com os 15 s de sempre."""
    with pool.connection() as conn:
        conn.execute("SET LOCAL statement_timeout = 0")
        conn.execute(sql_text)
