from dataclasses import replace
from uuid import uuid4

from pipeline import alerts
from pipeline.config import Settings
from pipeline.models import BatchOutcome, Finding, Severity
from tests.conftest import TRADING_HOUR

WARNING = Finding(Severity.WARNING, "2 rows rejected", ("unknown_product: 2",), TRADING_HOUR)
CRITICAL = Finding(Severity.CRITICAL, "dbt failed", ("test.x: 1 row",))


def _settings(monkeypatch, **overrides) -> Settings:
    for name in ("SMTP_HOST", "ALERT_EMAIL_FROM", "ALERT_EMAIL_TO", "SLACK_WEBHOOK_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(alerts, "Settings", Settings)
    return replace(Settings.from_env(), **overrides)


def test_report_leads_with_the_worst_severity():
    batch = BatchOutcome(TRADING_HOUR, uuid4(), "success_with_warnings", 100, 98, 2)
    subject, body = alerts.format_report([WARNING, CRITICAL], [batch])

    assert subject.startswith("[CRITICAL]")
    assert body.index("dbt failed") < body.index("2 rows rejected")
    assert "received 100" in body


def test_findings_below_the_minimum_severity_are_not_sent(monkeypatch):
    settings = _settings(monkeypatch, alert_min_severity="critical")
    assert alerts.send_report([WARNING], [], settings) == []


def test_without_channels_the_alert_is_only_logged(monkeypatch, caplog):
    settings = _settings(monkeypatch)
    assert alerts.send_report([CRITICAL], [], settings) == []
    assert "Alert not delivered" in caplog.text


def test_email_is_sent_when_configured(monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "_send_email", lambda subject, body, s: sent.append(subject))
    settings = _settings(
        monkeypatch,
        smtp_host="smtp.example.com",
        alert_email_from="pipeline@example.com",
        alert_email_to=("team@example.com",),
    )

    assert alerts.send_report([CRITICAL], [], settings) == ["email"]
    assert sent and sent[0].startswith("[CRITICAL]")


def test_a_broken_channel_does_not_crash_the_pipeline(monkeypatch):
    def explode(*_):
        raise ConnectionError("SMTP down")

    monkeypatch.setattr(alerts, "_send_email", explode)
    settings = _settings(
        monkeypatch,
        smtp_host="smtp.example.com",
        alert_email_from="pipeline@example.com",
        alert_email_to=("team@example.com",),
    )
    assert alerts.send_report([CRITICAL], [], settings) == []
