"""Runs against a real Postgres. Skipped automatically if one is not reachable."""

import os
from uuid import uuid4

import psycopg2
import pytest

from pipeline import audit
from pipeline.db import connect, init_schema
from pipeline.generator import SimulationConfig, generate_hour
from pipeline.load import load_rejected_rows, load_valid_rows
from pipeline.validate import ValidationContext, validate
from tests.conftest import TRADING_HOUR

pytestmark = pytest.mark.integration

FAULTY = SimulationConfig(bad_record_rate=0.1, incident_probability=1, store_outage_probability=0)


@pytest.fixture
def conn():
    # These tests wipe the raw tables, so never point them at a real database.
    if os.getenv("PGHOST", "localhost") not in {"localhost", "127.0.0.1"}:
        pytest.skip("integration tests only run against a local Postgres")
    try:
        with connect() as connection:
            init_schema(connection)
            with connection.cursor() as cur:
                cur.execute(
                    "TRUNCATE raw.pos_transactions, raw.rejected_records, audit.pipeline_runs"
                )
            connection.commit()
            yield connection
    except psycopg2.OperationalError as exc:
        pytest.skip(f"Postgres not available: {exc}")


@pytest.fixture
def faulty_hour(stores, products):
    export = generate_hour(TRADING_HOUR, stores, products, FAULTY).astype(str)
    export = export.replace({"None": None})
    return validate(export, ValidationContext.for_batch(TRADING_HOUR, stores, products))


def _count(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 (fixed table names)
        return cur.fetchone()[0]


def test_reloading_an_hour_never_duplicates_rows(conn, faulty_hour):
    first = load_valid_rows(conn, faulty_hour.valid, TRADING_HOUR, uuid4())
    load_rejected_rows(conn, faulty_hour.rejected, TRADING_HOUR, uuid4())
    conn.commit()

    second = load_valid_rows(conn, faulty_hour.valid, TRADING_HOUR, uuid4())
    load_rejected_rows(conn, faulty_hour.rejected, TRADING_HOUR, uuid4())
    conn.commit()

    assert first == len(faulty_hour.valid) > 0
    assert second == 0
    assert _count(conn, "raw.pos_transactions") == len(faulty_hour.valid)
    assert _count(conn, "raw.rejected_records") == len(faulty_hour.rejected) > 0


def test_only_successful_runs_count_as_processed(conn):
    good, bad = uuid4(), uuid4()
    audit.start_run(conn, good, TRADING_HOUR)
    audit.finish_run(conn, good, "success", 10, 10, 0)
    later = TRADING_HOUR.replace(hour=TRADING_HOUR.hour + 1)
    audit.start_run(conn, bad, later)
    audit.finish_run(conn, bad, "failed", error_message="boom")

    assert audit.processed_hours(conn, TRADING_HOUR) == {TRADING_HOUR}
