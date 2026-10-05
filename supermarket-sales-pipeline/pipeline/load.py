"""Load: write validated rows and quarantined rows to Postgres.

Both writes are idempotent so any hour can be re-run safely:
  * good rows use ON CONFLICT DO NOTHING on the natural key, so a line that is
    already there is skipped rather than duplicated
  * rejected rows for the hour are replaced, not appended
The caller commits, so both writes land together or not at all.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

import pandas as pd
from psycopg2.extensions import connection as Connection
from psycopg2.extras import execute_values

INSERT_SALES_SQL = """
    INSERT INTO raw.pos_transactions (
        transaction_id, line_number, store_id, till_id, product_sku, quantity,
        unit_price, discount_amount, line_total, payment_method, sold_at,
        batch_hour, run_id
    )
    VALUES %s
    ON CONFLICT (transaction_id, line_number) DO NOTHING
    RETURNING 1
"""

INSERT_REJECTS_SQL = """
    INSERT INTO raw.rejected_records (batch_hour, run_id, reject_reasons, raw_record)
    VALUES %s
"""


def load_valid_rows(
    conn: Connection, valid: pd.DataFrame, batch_hour: datetime, run_id: UUID
) -> int:
    """Insert good rows. Returns how many were new (already loaded rows are skipped)."""
    if valid.empty:
        return 0
    rows = [
        (
            r.transaction_id,
            int(r.line_number),
            r.store_id,
            r.till_id,
            r.product_sku,
            int(r.quantity),
            round(float(r.unit_price), 2),
            round(float(r.discount_amount), 2),
            round(float(r.line_total), 2),
            r.payment_method,
            r.sold_at.to_pydatetime(),
            batch_hour,
            str(run_id),
        )
        for r in valid.itertuples(index=False)
    ]
    with conn.cursor() as cur:
        inserted = execute_values(cur, INSERT_SALES_SQL, rows, page_size=1000, fetch=True)
    return len(inserted)


def load_rejected_rows(
    conn: Connection, rejected: pd.DataFrame, batch_hour: datetime, run_id: UUID
) -> int:
    """Replace this hour's quarantined rows with the latest result."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM raw.rejected_records WHERE batch_hour = %s", (batch_hour,))
        if rejected.empty:
            return 0
        original = rejected.drop(columns=["reject_reasons"])
        records = original.astype(object).where(original.notna(), None).to_dict(orient="records")
        rows = [
            (batch_hour, str(run_id), reasons, json.dumps(record, default=str))
            for record, reasons in zip(records, rejected["reject_reasons"], strict=True)
        ]
        execute_values(cur, INSERT_REJECTS_SQL, rows, page_size=1000)
    return len(rows)
