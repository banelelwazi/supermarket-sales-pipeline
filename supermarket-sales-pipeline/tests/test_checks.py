import pandas as pd

from pipeline.checks import check_dbt, check_rejections, check_silent_stores
from pipeline.dbt_runner import DbtResult
from pipeline.models import Severity
from pipeline.validate import ValidationResult
from tests.conftest import CLOSED_HOUR, TRADING_HOUR


def _result(received: int, rejected: int) -> ValidationResult:
    return ValidationResult(
        rows_received=received,
        valid=pd.DataFrame(index=range(received - rejected)),
        rejected=pd.DataFrame(index=range(rejected)),
        reason_counts={"unknown_product": rejected} if rejected else {},
    )


def test_no_rejections_means_no_findings():
    assert check_rejections(_result(100, 0), TRADING_HOUR, 0.05) == []


def test_a_few_rejections_is_a_warning():
    [finding] = check_rejections(_result(100, 2), TRADING_HOUR, 0.05)
    assert finding.severity == Severity.WARNING
    assert "unknown_product: 2" in finding.details


def test_many_rejections_is_critical():
    [finding] = check_rejections(_result(100, 20), TRADING_HOUR, 0.05)
    assert finding.severity == Severity.CRITICAL


def test_open_store_with_no_sales_is_flagged(stores):
    reporting = [s.store_id for s in stores if s.store_id != "DBN01"]
    [finding] = check_silent_stores(pd.DataFrame({"store_id": reporting}), stores, TRADING_HOUR)
    assert finding.severity == Severity.WARNING
    assert any("DBN01" in detail for detail in finding.details)


def test_closed_stores_are_not_flagged(stores):
    assert check_silent_stores(pd.DataFrame({"store_id": []}), stores, CLOSED_HOUR) == []


def test_dbt_failures_are_critical_and_warnings_are_warnings():
    findings = check_dbt(DbtResult(success=False, failures=["test.a: 3 rows"], warnings=["w"]))
    assert [f.severity for f in findings] == [Severity.CRITICAL, Severity.WARNING]
