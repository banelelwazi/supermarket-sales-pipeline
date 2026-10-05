"""Small shared types used across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from uuid import UUID


class Severity(IntEnum):
    INFO = 10
    WARNING = 20
    CRITICAL = 30

    @classmethod
    def parse(cls, value: str) -> Severity:
        return cls[value.strip().upper()]


@dataclass(frozen=True)
class Finding:
    """Something a person should know about after a run."""

    severity: Severity
    title: str
    details: tuple[str, ...] = ()
    batch_hour: datetime | None = None


@dataclass
class BatchOutcome:
    """What happened when one hour of sales was processed."""

    batch_hour: datetime
    run_id: UUID
    status: str
    rows_received: int = 0
    rows_loaded: int = 0
    rows_rejected: int = 0
    findings: list[Finding] = field(default_factory=list)


def worst_severity(findings: list[Finding]) -> Severity | None:
    return max((f.severity for f in findings), default=None)
