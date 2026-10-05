"""Send one report per run by email and/or Slack.

All findings from a run go out together in a single message, so a bad hour
produces one email rather than five. If no channel is configured the report
is written to the log instead, which keeps local development quiet.
"""

from __future__ import annotations

import json
import logging
import smtplib
import urllib.request
from datetime import UTC, datetime
from email.message import EmailMessage

from pipeline.config import Settings
from pipeline.models import BatchOutcome, Finding, Severity, worst_severity

logger = logging.getLogger(__name__)


def format_report(findings: list[Finding], batches: list[BatchOutcome]) -> tuple[str, str]:
    worst = worst_severity(findings) or Severity.INFO
    headline = findings[0].title if len(findings) == 1 else f"{len(findings)} issues found"
    subject = f"[{worst.name}] Sales pipeline: {headline}"

    lines = [
        "Supermarket sales pipeline report",
        f"Worst severity: {worst.name}",
        f"Generated: {datetime.now(UTC):%Y-%m-%d %H:%M} UTC",
        "",
        "What needs attention",
    ]
    for finding in sorted(findings, key=lambda f: f.severity, reverse=True):
        when = f" for {finding.batch_hour:%Y-%m-%d %H:00} UTC" if finding.batch_hour else ""
        lines.append(f"[{finding.severity.name}] {finding.title}{when}")
        lines.extend(f"    {detail}" for detail in finding.details)

    if batches:
        lines += ["", "Hours processed in this run"]
        for b in batches:
            lines.append(
                f"{b.batch_hour:%Y-%m-%d %H:00} UTC  received {b.rows_received:,}  "
                f"loaded {b.rows_loaded:,}  rejected {b.rows_rejected:,}  ({b.status})"
            )

    lines += [
        "",
        "Rejected rows are kept in raw.rejected_records and every run is logged in "
        "audit.pipeline_runs. See docs/runbook.md for what to do next.",
    ]
    return subject, "\n".join(lines)


def send_report(
    findings: list[Finding], batches: list[BatchOutcome], settings: Settings
) -> list[str]:
    """Send the report if it meets the minimum severity. Returns the channels used."""
    worst = worst_severity(findings)
    if worst is None or worst < Severity.parse(settings.alert_min_severity):
        return []

    subject, body = format_report(findings, batches)
    delivered = []

    if settings.email_enabled:
        try:
            _send_email(subject, body, settings)
            delivered.append("email")
        except Exception:
            logger.exception("Could not send alert email")

    if settings.slack_webhook_url:
        try:
            _send_slack(subject, body, settings.slack_webhook_url)
            delivered.append("slack")
        except Exception:
            logger.exception("Could not send Slack alert")

    if delivered:
        logger.info("Alert sent via %s: %s", ", ".join(delivered), subject)
    else:
        logger.warning(
            "Alert not delivered (no channel configured or all failed)\n%s\n%s", subject, body
        )
    return delivered


def ping_healthcheck(url: str) -> None:
    """Tell an external dead man's switch that the pipeline is alive."""
    try:
        urllib.request.urlopen(url, timeout=10).close()  # noqa: S310
    except Exception:
        logger.exception("Health check ping failed")


def _send_email(subject: str, body: str, settings: Settings) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.alert_email_from
    message["To"] = ", ".join(settings.alert_email_to)
    message.set_content(body)

    if settings.smtp_port == 465:
        server: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
        server.starttls()
    with server:
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(message)


def _send_slack(subject: str, body: str, webhook_url: str) -> None:
    payload = json.dumps({"text": f"*{subject}*\n```{body}```"}).encode()
    request = urllib.request.Request(
        webhook_url, data=payload, headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(request, timeout=10).close()  # noqa: S310
