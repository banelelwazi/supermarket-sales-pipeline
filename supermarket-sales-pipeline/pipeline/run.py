"""Orchestrator and command line entry point.

    python -m pipeline init-db                 create schemas and raw tables
    python -m pipeline hourly                  what the scheduler runs every hour
    python -m pipeline batch --hour 2026-10-05T13:00
    python -m pipeline backfill --start 2026-10-01T00:00 --end 2026-10-01T23:00

`hourly` does not just load "the last hour". It looks back over a window
(24 hours by default) and loads every hour that has no successful run yet.
If the scheduler skips a run, or an hour fails because the export was late,
the next run picks it up on its own.

Exit code is 1 when anything CRITICAL happened, so the scheduler marks the
run as failed too.
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from datetime import UTC, datetime, timedelta

from pipeline import audit
from pipeline.alerts import ping_healthcheck, send_report
from pipeline.checks import check_dbt, check_rejections, check_silent_stores
from pipeline.config import ARCHIVE_DIR, DBT_PROJECT_DIR, LANDING_DIR, Settings
from pipeline.db import connect, init_schema
from pipeline.dbt_runner import run_dbt_build
from pipeline.extract import SourceFileMissingError, SourceSchemaError, archive, extract
from pipeline.generator import SimulationConfig, generate_hour, write_landing_file
from pipeline.load import load_rejected_rows, load_valid_rows
from pipeline.models import BatchOutcome, Finding, Severity, worst_severity
from pipeline.reference import Product, Store, load_products, load_stores
from pipeline.validate import ValidationContext, ValidationResult, validate

logger = logging.getLogger("pipeline")

MAX_BACKFILL_HOURS = 24 * 31


def floor_to_hour(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def parse_hour(value: str) -> datetime:
    """Accept '2026-10-05T13:00' or '2026-10-05 13:00'. Naive times are treated as UTC."""
    moment = datetime.fromisoformat(value.strip())
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return floor_to_hour(moment)


def hours_to_process(
    processed: set[datetime], now: datetime, lookback_hours: int
) -> list[datetime]:
    """Every complete hour in the lookback window that has not loaded successfully yet."""
    latest_complete = floor_to_hour(now) - timedelta(hours=1)
    window = [latest_complete - timedelta(hours=i) for i in range(lookback_hours)]
    return sorted(hour for hour in window if hour not in processed)


def process_batch(
    conn, batch_hour: datetime, settings: Settings, stores: list[Store], products: list[Product]
) -> BatchOutcome:
    run_id = uuid.uuid4()
    logger.info("Processing %s UTC (run %s)", f"{batch_hour:%Y-%m-%d %H:00}", run_id)
    audit.start_run(conn, run_id, batch_hour)

    try:
        if settings.simulate_source:
            simulation = SimulationConfig(
                bad_record_rate=settings.bad_record_rate,
                incident_probability=settings.incident_probability,
                store_outage_probability=settings.store_outage_probability,
            )
            frame = generate_hour(batch_hour, stores, products, simulation)
            write_landing_file(frame, batch_hour, LANDING_DIR)

        raw = extract(batch_hour, LANDING_DIR)
        result = validate(raw, ValidationContext.for_batch(batch_hour, stores, products))
        loaded = _load_batch(conn, result, batch_hour, run_id)
        archive(batch_hour, LANDING_DIR, ARCHIVE_DIR)

        findings = check_rejections(result, batch_hour, settings.reject_rate_critical_threshold)
        findings += [
            Finding(f.severity, f.title, f.details, batch_hour)
            for f in check_silent_stores(raw, stores, batch_hour)
        ]
        status = "success_with_warnings" if findings else "success"
        audit.finish_run(conn, run_id, status, len(raw), loaded, len(result.rejected))
        logger.info(
            "Received %d, loaded %d new, rejected %d", len(raw), loaded, len(result.rejected)
        )
        return BatchOutcome(
            batch_hour, run_id, status, len(raw), loaded, len(result.rejected), findings
        )

    except (SourceFileMissingError, SourceSchemaError) as exc:
        conn.rollback()
        logger.error("Source problem: %s", exc)
        finding = Finding(Severity.CRITICAL, "POS export problem", (str(exc),), batch_hour)
        audit.finish_run(conn, run_id, "failed", error_message=str(exc))
        return BatchOutcome(batch_hour, run_id, "failed", findings=[finding])

    except Exception as exc:
        conn.rollback()
        logger.exception("Batch failed")
        message = f"{type(exc).__name__}: {exc}"
        finding = Finding(
            Severity.CRITICAL, "Batch failed with an unexpected error", (message,), batch_hour
        )
        audit.finish_run(conn, run_id, "failed", error_message=message)
        return BatchOutcome(batch_hour, run_id, "failed", findings=[finding])


def _load_batch(conn, result: ValidationResult, batch_hour: datetime, run_id: uuid.UUID) -> int:
    """Good rows and quarantined rows are committed together or not at all."""
    loaded = load_valid_rows(conn, result.valid, batch_hour, run_id)
    load_rejected_rows(conn, result.rejected, batch_hour, run_id)
    conn.commit()
    return loaded


def run_hours(batch_hours: list[datetime], settings: Settings, skip_dbt: bool = False) -> int:
    outcomes: list[BatchOutcome] = []
    findings: list[Finding] = []

    try:
        stores, products = load_stores(), load_products()
        with connect() as conn:
            for hour in batch_hours:
                outcome = process_batch(conn, hour, settings, stores, products)
                outcomes.append(outcome)
                findings.extend(outcome.findings)

            new_rows = sum(o.rows_loaded for o in outcomes)
            if skip_dbt:
                logger.info("Skipping dbt as requested")
            elif new_rows == 0:
                logger.info("No new rows loaded, so dbt has nothing to do")
            else:
                dbt_result = run_dbt_build(DBT_PROJECT_DIR)
                findings.extend(check_dbt(dbt_result))
                audit.set_dbt_status(
                    conn,
                    [o.run_id for o in outcomes if o.status != "failed"],
                    "success" if dbt_result.success else "failed",
                )
    except Exception as exc:
        logger.exception("Pipeline could not run")
        findings.append(
            Finding(Severity.CRITICAL, "Pipeline could not run", (f"{type(exc).__name__}: {exc}",))
        )

    send_report(findings, outcomes, settings)

    worst = worst_severity(findings)
    if worst != Severity.CRITICAL and settings.healthcheck_url:
        ping_healthcheck(settings.healthcheck_url)

    logger.info(
        "Finished %d hour(s). Worst severity: %s", len(outcomes), worst.name if worst else "none"
    )
    return 1 if worst == Severity.CRITICAL else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline", description="Hourly supermarket sales pipeline"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init-db", help="create schemas and raw tables (safe to re-run)")
    hourly = commands.add_parser("hourly", help="load every missing hour in the lookback window")
    batch = commands.add_parser("batch", help="load or reload one specific hour")
    batch.add_argument(
        "--hour", required=True, type=parse_hour, help="UTC hour, e.g. 2026-10-05T13:00"
    )
    backfill = commands.add_parser("backfill", help="load a range of hours (inclusive)")
    backfill.add_argument("--start", required=True, type=parse_hour)
    backfill.add_argument("--end", required=True, type=parse_hour)

    for sub in (hourly, batch, backfill):
        sub.add_argument("--skip-dbt", action="store_true", help="load raw data only")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()

    if args.command == "init-db":
        with connect() as conn:
            init_schema(conn)
        logger.info("Schemas and raw tables are ready")
        return 0

    if args.command == "batch":
        hours = [args.hour]
    elif args.command == "backfill":
        if args.end < args.start:
            raise SystemExit("--end must not be before --start")
        count = int((args.end - args.start).total_seconds() // 3600) + 1
        if count > MAX_BACKFILL_HOURS:
            raise SystemExit(f"Backfill is limited to {MAX_BACKFILL_HOURS} hours per run")
        hours = [args.start + timedelta(hours=i) for i in range(count)]
    else:
        now = datetime.now(UTC)
        since = floor_to_hour(now) - timedelta(hours=settings.lookback_hours)
        with connect() as conn:
            done = audit.processed_hours(conn, since)
        hours = hours_to_process(done, now, settings.lookback_hours)
        if not hours:
            logger.info("Nothing to do, every hour in the window is already loaded")
            if settings.healthcheck_url:
                ping_healthcheck(settings.healthcheck_url)
            return 0
        logger.info("%d hour(s) to process", len(hours))

    return run_hours(hours, settings, skip_dbt=args.skip_dbt)


if __name__ == "__main__":
    sys.exit(main())
