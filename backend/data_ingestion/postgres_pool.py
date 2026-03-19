from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from psycopg import Connection
from psycopg_pool import ConnectionPool


def create_pool(postgres_dsn: str, min_size: int = 1, max_size: int = 10) -> ConnectionPool:
    return ConnectionPool(conninfo=postgres_dsn, min_size=min_size, max_size=max_size, open=True)


@contextmanager
def get_connection(pool: ConnectionPool):
    with pool.connection() as conn:  # type: Connection
        yield conn


def apply_schema(conn: Connection, schema_path: Path) -> None:
    sql = schema_path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
