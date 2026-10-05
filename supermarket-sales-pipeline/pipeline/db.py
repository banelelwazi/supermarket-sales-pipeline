"""Database connection helpers.

Connection details come from the standard PG* environment variables
(PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE, PGSSLMODE), which libpq
reads on its own. dbt's profile reads the same variables.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg2
from psycopg2.extensions import connection as Connection

from pipeline.config import SQL_DIR


@contextmanager
def connect() -> Iterator[Connection]:
    conn = psycopg2.connect(connect_timeout=15, application_name="sales-pipeline")
    try:
        yield conn
    finally:
        conn.close()


def init_schema(conn: Connection) -> None:
    with conn.cursor() as cur:
        cur.execute((SQL_DIR / "init.sql").read_text())
    conn.commit()
