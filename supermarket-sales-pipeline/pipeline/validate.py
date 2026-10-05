"""Validate: the first data quality gate, before anything touches the database.

Every rule is a small function that returns True for rows that break it. A row
that breaks any rule is quarantined with the names of every rule it broke, so
whoever investigates can see exactly what was wrong. Good rows carry on.

Rules only judge values that are actually present. Missing or unparseable
values are caught once, by the first rule, so the reasons stay precise.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from pipeline.reference import Product, Store
from pipeline.schema import SOURCE_COLUMNS, VALID_PAYMENT_METHODS

TEXT_COLUMNS = ["transaction_id", "store_id", "till_id", "product_sku", "payment_method"]
NUMERIC_COLUMNS = ["line_number", "quantity", "unit_price", "discount_amount", "line_total"]
MONEY_TOLERANCE = 0.005


@dataclass(frozen=True)
class ValidationContext:
    batch_start: datetime
    batch_end: datetime
    store_ids: frozenset[str]
    catalogue_prices: dict[str, float]

    @classmethod
    def for_batch(
        cls, batch_hour: datetime, stores: list[Store], products: list[Product]
    ) -> ValidationContext:
        return cls(
            batch_start=batch_hour,
            batch_end=batch_hour + timedelta(hours=1),
            store_ids=frozenset(s.store_id for s in stores),
            catalogue_prices={p.product_sku: p.unit_price for p in products},
        )


@dataclass
class ValidationResult:
    rows_received: int
    valid: pd.DataFrame
    rejected: pd.DataFrame
    reason_counts: dict[str, int]

    @property
    def reject_rate(self) -> float:
        return len(self.rejected) / self.rows_received if self.rows_received else 0.0


Rule = Callable[[pd.DataFrame, ValidationContext], pd.Series]


def _missing_or_malformed(df: pd.DataFrame, ctx: ValidationContext) -> pd.Series:
    return df[SOURCE_COLUMNS].isna().any(axis=1)


def _invalid_quantity(df: pd.DataFrame, ctx: ValidationContext) -> pd.Series:
    quantity = df["quantity"]
    return quantity.notna() & ((quantity <= 0) | (quantity % 1 != 0))


def _unknown_store(df: pd.DataFrame, ctx: ValidationContext) -> pd.Series:
    return df["store_id"].notna() & ~df["store_id"].isin(ctx.store_ids)


def _unknown_product(df: pd.DataFrame, ctx: ValidationContext) -> pd.Series:
    return df["product_sku"].notna() & ~df["product_sku"].isin(ctx.catalogue_prices.keys())


def _price_mismatch(df: pd.DataFrame, ctx: ValidationContext) -> pd.Series:
    expected = df["product_sku"].map(ctx.catalogue_prices)
    return expected.notna() & ((df["unit_price"] - expected).abs() > MONEY_TOLERANCE)


def _invalid_discount(df: pd.DataFrame, ctx: ValidationContext) -> pd.Series:
    gross = df["quantity"] * df["unit_price"]
    return df["discount_amount"].notna() & (
        (df["discount_amount"] < 0)
        | ((gross > 0) & (df["discount_amount"] > gross + MONEY_TOLERANCE))
    )


def _line_total_mismatch(df: pd.DataFrame, ctx: ValidationContext) -> pd.Series:
    expected = (df["quantity"] * df["unit_price"]).round(2) - df["discount_amount"]
    return expected.notna() & ((expected - df["line_total"]).abs() > MONEY_TOLERANCE)


def _invalid_payment_method(df: pd.DataFrame, ctx: ValidationContext) -> pd.Series:
    method = df["payment_method"]
    return method.notna() & ~method.isin(VALID_PAYMENT_METHODS)


def _outside_batch_window(df: pd.DataFrame, ctx: ValidationContext) -> pd.Series:
    sold_at = df["sold_at"]
    start = pd.Timestamp(ctx.batch_start)
    end = pd.Timestamp(ctx.batch_end)
    return sold_at.notna() & ((sold_at < start) | (sold_at >= end))


def _duplicate_line(df: pd.DataFrame, ctx: ValidationContext) -> pd.Series:
    return df.duplicated(subset=["transaction_id", "line_number"], keep="first")


RULES: dict[str, Rule] = {
    "missing_or_malformed_field": _missing_or_malformed,
    "invalid_quantity": _invalid_quantity,
    "unknown_store": _unknown_store,
    "unknown_product": _unknown_product,
    "price_mismatch": _price_mismatch,
    "invalid_discount": _invalid_discount,
    "line_total_mismatch": _line_total_mismatch,
    "invalid_payment_method": _invalid_payment_method,
    "outside_batch_window": _outside_batch_window,
    "duplicate_line": _duplicate_line,
}


def coerce_types(raw: pd.DataFrame) -> pd.DataFrame:
    """Turn the all text export into proper types. Anything unparseable becomes NaN."""
    df = raw.copy()
    for column in TEXT_COLUMNS:
        values = df[column].astype("string").str.strip()
        if column == "payment_method":
            values = values.str.lower()
        df[column] = values.mask(values == "").astype(object)
    for column in NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["sold_at"] = pd.to_datetime(df["sold_at"], errors="coerce", utc=True, format="ISO8601")
    return df


def validate(raw: pd.DataFrame, ctx: ValidationContext) -> ValidationResult:
    typed = coerce_types(raw)
    failures = pd.DataFrame(
        {name: rule(typed, ctx).fillna(False).astype(bool) for name, rule in RULES.items()},
        index=typed.index,
    )
    is_bad = failures.any(axis=1)

    rejected = raw.loc[is_bad].copy()
    if not rejected.empty:
        bad = failures.loc[is_bad]
        rejected["reject_reasons"] = [";".join(bad.columns[row]) for row in bad.to_numpy()]
    else:
        rejected["reject_reasons"] = pd.Series(dtype=str)

    valid = typed.loc[~is_bad].copy()
    valid["line_number"] = valid["line_number"].astype(int)
    valid["quantity"] = valid["quantity"].astype(int)

    counts = failures.sum()
    return ValidationResult(
        rows_received=len(raw),
        valid=valid,
        rejected=rejected,
        reason_counts={name: int(n) for name, n in counts.items() if n > 0},
    )
