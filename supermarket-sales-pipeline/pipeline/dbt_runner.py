"""Run dbt and turn its results into something the alerting can use."""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DbtResult:
    success: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def run_dbt_build(project_dir: Path) -> DbtResult:
    """`dbt build` loads seeds, builds models and runs every test in dependency order."""
    command = [
        "dbt", "--no-use-colors", "build",
        "--project-dir", str(project_dir),
        "--profiles-dir", str(project_dir),
    ]  # fmt: skip
    logger.info("Running: %s", " ".join(command))
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return DbtResult(success=False, failures=["dbt is not installed or not on PATH"])

    tail = "\n".join(completed.stdout.strip().splitlines()[-25:])
    logger.info("dbt output (last lines):\n%s", tail)

    result = parse_run_results(project_dir / "target" / "run_results.json")
    result.success = completed.returncode == 0 and not result.failures
    if completed.returncode != 0 and not result.failures:
        result.failures.append(f"dbt exited with code {completed.returncode}:\n{tail}")
    return result


def parse_run_results(path: Path) -> DbtResult:
    if not path.exists():
        return DbtResult(success=False, failures=["dbt did not produce run_results.json"])

    results = json.loads(path.read_text()).get("results", [])
    outcome = DbtResult(success=True)
    for node in results:
        status = node.get("status")
        name = node.get("unique_id", "unknown node")
        message = node.get("message") or ""
        if status in {"error", "fail"}:
            outcome.failures.append(f"{name}: {message}".strip())
        elif status == "warn":
            outcome.warnings.append(f"{name}: {message}".strip())
    outcome.success = not outcome.failures
    return outcome
