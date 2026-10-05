"""The contract for the hourly POS export file."""

from __future__ import annotations

from datetime import datetime

SOURCE_COLUMNS = [
    "transaction_id",
    "line_number",
    "store_id",
    "till_id",
    "product_sku",
    "quantity",
    "unit_price",
    "discount_amount",
    "line_total",
    "payment_method",
    "sold_at",
]

VALID_PAYMENT_METHODS = frozenset({"card", "cash", "mobile_wallet"})


def landing_file_name(batch_hour: datetime) -> str:
    """One file per hour, named by the UTC hour it covers, e.g. sales_20261005T1300Z.csv."""
    return f"sales_{batch_hour:%Y%m%dT%H}00Z.csv"
