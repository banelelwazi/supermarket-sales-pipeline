"""Decide what is worth telling a person about.

Each check takes the facts from a run and returns zero or more findings.
Keeping these as plain functions makes the alerting rules easy to test and
easy to change without touching the pipeline itself.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from pipeline.config import LOCAL_TIMEZONE
from pipeline.dbt_runner import DbtResult
from pipeline.models import Finding, Severity
from pipeline.reference import Store
from pipeline.validate import ValidationResult


def check_rejections(
    result: ValidationResult, batch_hour: datetime, critical_threshold: float
) -> list[Finding]:
    """Any rejected row is worth a warning. A high share of them is critical."""
    if len(result.rejected) == 0:
        return []
    severity = Severity.CRITICAL if result.reject_rate > critical_threshold else Severity.WARNING
    details = tuple(f"{reason}: {count}" for reason, count in sorted(result.reason_counts.items()))
    title = (
        f"{len(result.rejected)} of {result.rows_received} rows rejected ({result.reject_rate:.1%})"
    )
    return [Finding(severity, title, details, batch_hour)]


def check_silent_stores(
    raw: pd.DataFrame, stores: list[Store], batch_hour: datetime
) -> list[Finding]:
    """A store that was open but sent nothing usually means a till system problem."""
    local_hour = batch_hour.astimezone(ZoneInfo(LOCAL_TIMEZONE)).hour
    reporting = {str(store_id).strip() for store_id in raw["store_id"].dropna()}
    silent = [s for s in stores if s.is_open(local_hour) and s.store_id not in reporting]
    if not silent:
        return []
    details = tuple(f"{s.store_id} {s.store_name} ({s.city})" for s in silent)
    title = f"No sales received from {len(silent)} open store(s)"
    return [Finding(Severity.WARNING, title, details)]


def check_dbt(result: DbtResult) -> list[Finding]:
    findings = []
    if result.failures:
        findings.append(
            Finding(Severity.CRITICAL, "dbt build or data tests failed", tuple(result.failures))
        )
    if result.warnings:
        findings.append(
            Finding(Severity.WARNING, "dbt data tests raised warnings", tuple(result.warnings))
        )
    return findings
