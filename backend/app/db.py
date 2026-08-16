"""Postgres access. One small connection pool, plus a read-only helper for
anything the LLM or the user is allowed to run."""

from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import DSN, SQL_TIMEOUT_MS

pool = ConnectionPool(DSN, min_size=1, max_size=10, kwargs={"row_factory": dict_row}, open=False)


def init() -> None:
    pool.open()
    sql = (Path(__file__).resolve().parent.parent / "schema.sql").read_text()
    with pool.connection() as conn:
        conn.execute(sql)


def shutdown() -> None:
    pool.close()


@contextmanager
def conn():
    with pool.connection() as c:
        yield c


def query(sql: str, params: tuple | dict | None = None) -> list[dict]:
    with pool.connection() as c:
        cur = c.execute(sql, params)
        return cur.fetchall() if cur.description else []


def one(sql: str, params: tuple | dict | None = None) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple | dict | None = None) -> None:
    with pool.connection() as c:
        c.execute(sql, params)


def read_only(sql: str, limit_note: str = "") -> tuple[list[str], list[list]]:
    """Run a statement in a read-only transaction with a hard timeout.
    Returns (columns, rows). Raises psycopg errors on bad SQL."""
    with psycopg.connect(DSN) as c:
        c.read_only = True
        with c.cursor() as cur:
            cur.execute(f"SET LOCAL statement_timeout = {SQL_TIMEOUT_MS}")
            cur.execute(sql)
            cols = [d.name for d in cur.description] if cur.description else []
            rows = cur.fetchall() if cur.description else []
    return cols, [list(r) for r in rows]
