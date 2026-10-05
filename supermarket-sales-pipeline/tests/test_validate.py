import pandas as pd
import pytest

from pipeline.validate import validate


def _corrupt(frame: pd.DataFrame, column: str, value) -> pd.DataFrame:
    damaged = frame.copy()
    damaged.loc[0, column] = value
    return damaged


@pytest.mark.parametrize(
    ("column", "bad_value", "expected_reason"),
    [
        ("product_sku", None, "missing_or_malformed_field"),
        ("quantity", "abc", "missing_or_malformed_field"),
        ("sold_at", "not a date", "missing_or_malformed_field"),
        ("quantity", "-2", "invalid_quantity"),
        ("quantity", "1.5", "invalid_quantity"),
        ("store_id", "XXX99", "unknown_store"),
        ("product_sku", "SKU-99999", "unknown_product"),
        ("unit_price", "999.99", "price_mismatch"),
        ("discount_amount", "-5", "invalid_discount"),
        ("line_total", "0.01", "line_total_mismatch"),
        ("payment_method", "crypto", "invalid_payment_method"),
        ("sold_at", "2030-01-01T00:00:00+00:00", "outside_batch_window"),
    ],
)
def test_each_rule_catches_its_problem(clean_export, context, column, bad_value, expected_reason):
    result = validate(_corrupt(clean_export, column, bad_value), context)

    assert len(result.rejected) == 1
    assert expected_reason in result.rejected.iloc[0]["reject_reasons"].split(";")
    assert len(result.valid) == len(clean_export) - 1


def test_duplicate_lines_keep_the_first_copy(clean_export, context):
    with_duplicate = pd.concat([clean_export, clean_export.iloc[[0]]], ignore_index=True)
    result = validate(with_duplicate, context)

    assert result.reason_counts == {"duplicate_line": 1}
    assert len(result.valid) == len(clean_export)


def test_payment_method_is_normalised_not_rejected(clean_export, context):
    result = validate(_corrupt(clean_export, "payment_method", "  CARD "), context)
    assert result.rejected.empty
    assert result.valid.loc[0, "payment_method"] == "card"


def test_rejected_rows_keep_their_original_values(clean_export, context):
    result = validate(_corrupt(clean_export, "quantity", "-2"), context)
    assert result.rejected.iloc[0]["quantity"] == "-2"


def test_empty_export_is_fine(clean_export, context):
    result = validate(clean_export.iloc[0:0], context)
    assert result.rows_received == 0
    assert result.reject_rate == 0.0
    assert result.valid.empty and result.rejected.empty
