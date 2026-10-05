"""Runtime settings.

Everything the pipeline needs to know about its environment comes in through
environment variables (a local .env file is loaded if one exists). Database
details use the standard PG* variables, so psycopg2 and dbt read the exact
same values and there is only one place to configure the connection.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LANDING_DIR = DATA_DIR / "landing"
ARCHIVE_DIR = DATA_DIR / "archive"
DBT_PROJECT_DIR = PROJECT_ROOT / "dbt" / "supermarket"
SEEDS_DIR = DBT_PROJECT_DIR / "seeds"
SQL_DIR = PROJECT_ROOT / "sql"

# Stores trade on South African time. Everything is stored in UTC and only
# converted to local time when we need trading hours or reporting dates.
LOCAL_TIMEZONE = "Africa/Johannesburg"


def _env_str(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _env_bool(name: str, default: bool) -> bool:
    value = _env_str(name)
    return default if value is None else value.lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = _env_str(name)
    return default if value is None else float(value)


def _env_int(name: str, default: int) -> int:
    value = _env_str(name)
    return default if value is None else int(value)


@dataclass(frozen=True)
class Settings:
    # Source
    simulate_source: bool
    bad_record_rate: float
    incident_probability: float
    store_outage_probability: float

    # Scheduling and data quality
    lookback_hours: int
    reject_rate_critical_threshold: float

    # Alerting
    alert_min_severity: str
    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_password: str | None
    alert_email_from: str | None
    alert_email_to: tuple[str, ...]
    slack_webhook_url: str | None
    healthcheck_url: str | None

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.alert_email_from and self.alert_email_to)

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(PROJECT_ROOT / ".env")
        recipients = tuple(
            address.strip()
            for address in os.getenv("ALERT_EMAIL_TO", "").split(",")
            if address.strip()
        )
        return cls(
            simulate_source=_env_bool("SIMULATE_SOURCE", True),
            bad_record_rate=_env_float("BAD_RECORD_RATE", 0.05),
            incident_probability=_env_float("INCIDENT_PROBABILITY", 0.03),
            store_outage_probability=_env_float("STORE_OUTAGE_PROBABILITY", 0.01),
            lookback_hours=_env_int("LOOKBACK_HOURS", 24),
            reject_rate_critical_threshold=_env_float("REJECT_RATE_CRITICAL_THRESHOLD", 0.05),
            alert_min_severity=_env_str("ALERT_MIN_SEVERITY") or "warning",
            smtp_host=_env_str("SMTP_HOST"),
            smtp_port=_env_int("SMTP_PORT", 587),
            smtp_user=_env_str("SMTP_USER"),
            smtp_password=_env_str("SMTP_PASSWORD"),
            alert_email_from=_env_str("ALERT_EMAIL_FROM"),
            alert_email_to=recipients,
            slack_webhook_url=_env_str("SLACK_WEBHOOK_URL"),
            healthcheck_url=_env_str("HEALTHCHECK_URL"),
        )
