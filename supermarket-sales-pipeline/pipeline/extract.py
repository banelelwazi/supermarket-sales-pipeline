"""Extract: read the hourly POS export from the landing zone."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from pipeline.schema import SOURCE_COLUMNS, landing_file_name


class SourceFileMissingError(Exception):
    """The till system did not deliver an export for this hour."""


class SourceSchemaError(Exception):
    """The export arrived but its columns are not what we agreed on."""


def landing_path(batch_hour: datetime, landing_dir: Path) -> Path:
    return landing_dir / landing_file_name(batch_hour)


def extract(batch_hour: datetime, landing_dir: Path) -> pd.DataFrame:
    """Read every value as text. Typing and checking is the validator's job."""
    path = landing_path(batch_hour, landing_dir)
    if not path.exists():
        raise SourceFileMissingError(
            f"No POS export found for {batch_hour:%Y-%m-%d %H:00} UTC (expected {path.name})"
        )

    frame = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
    missing = [column for column in SOURCE_COLUMNS if column not in frame.columns]
    if missing:
        raise SourceSchemaError(f"{path.name} is missing columns: {', '.join(missing)}")
    return frame[SOURCE_COLUMNS]


def archive(batch_hour: datetime, landing_dir: Path, archive_dir: Path) -> Path | None:
    """Move a processed file out of landing into a dated archive folder."""
    source = landing_path(batch_hour, landing_dir)
    if not source.exists():
        return None
    target_dir = archive_dir / f"{batch_hour:%Y/%m/%d}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.move(str(source), str(target))
    return target
