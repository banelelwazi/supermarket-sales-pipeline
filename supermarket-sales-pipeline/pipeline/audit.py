"""Audit trail of pipeline runs, stored in audit.pipeline_runs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from psycopg2.extensions import connection as Connection

SUCCESS_STATUSES = ("success", "success_with_warnings")


def start_run(conn: Connection, run_id: UUID, batch_hour: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit.pipeline_runs (run_id, batch_hour, status) "
            "VALUES (%s, %s, 'running')",
            (str(run_id), batch_hour),
        )
    conn.commit()


def finish_run(
    conn: Connection,
    run_id: UUID,
    status: str,
    rows_received: int = 0,
    rows_loaded: int = 0,
    rows_rejected: int = 0,
    error_message: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE audit.pipeline_runs
               SET status = %s, rows_received = %s, rows_loaded = %s, rows_rejected = %s,
                   error_message = %s, finished_at = now()
             WHERE run_id = %s
            """,
            (status, rows_received, rows_loaded, rows_rejected, error_message, str(run_id)),
        )
    conn.commit()


def set_dbt_status(conn: Connection, run_ids: list[UUID], dbt_status: str) -> None:
    if not run_ids:
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE audit.pipeline_runs SET dbt_status = %s WHERE run_id::text = ANY(%s)",
            (dbt_status, [str(r) for r in run_ids]),
        )
    conn.commit()


def processed_hours(conn: Connection, since: datetime) -> set[datetime]:
    """Hours from `since` onwards that have at least one successful run."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT batch_hour FROM audit.pipeline_runs
             WHERE batch_hour >= %s AND status = ANY(%s)
            """,
            (since, list(SUCCESS_STATUSES)),
        )
        return {row[0] for row in cur.fetchall()}
