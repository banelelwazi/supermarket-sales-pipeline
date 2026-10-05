"""POS simulator.

In a real supermarket the till system would drop an export file every hour.
This module plays that role so the rest of the pipeline has realistic data to
work with: trading hours, lunch and after work peaks, busier weekends and
paydays, promotions, the odd till outage, and now and then a faulty till that
sends bad records.

Each hour is seeded from its own timestamp, so generating the same hour twice
gives exactly the same file. That is what makes reruns and backfills safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from pipeline.config import LOCAL_TIMEZONE
from pipeline.reference import Product, Store
from pipeline.schema import SOURCE_COLUMNS, landing_file_name

# Relative foot traffic by local hour, where 1.0 is the busiest hour of the day.
HOURLY_TRAFFIC = {
    7: 0.45, 8: 0.60, 9: 0.65, 10: 0.70, 11: 0.85, 12: 1.00, 13: 0.95,
    14: 0.70, 15: 0.75, 16: 0.90, 17: 1.00, 18: 0.95, 19: 0.70, 20: 0.45,
}  # fmt: skip

# Average number of baskets in the busiest hour, by store size.
BASKETS_PER_PEAK_HOUR = {"small": 14, "medium": 24, "large": 38}

# How likely a shopper is to pick something from each aisle.
CATEGORY_WEIGHTS = {
    "Bakery": 1.6,
    "Dairy & Eggs": 1.5,
    "Pantry": 1.3,
    "Produce": 1.1,
    "Beverages": 1.2,
    "Snacks": 1.0,
    "Meat": 0.8,
    "Household": 0.6,
    "Personal Care": 0.5,
    "Frozen": 0.5,
}

PAYMENT_METHODS = ("card", "cash", "mobile_wallet")
PAYMENT_WEIGHTS = (0.55, 0.32, 0.13)
QUANTITY_CHOICES = (1, 2, 3, 4, 6)
QUANTITY_WEIGHTS = (0.72, 0.17, 0.06, 0.03, 0.02)
PROMO_PROBABILITY = 0.08
PROMO_DISCOUNTS = (0.10, 0.20)

CORRUPTIONS = (
    "negative_quantity",
    "missing_sku",
    "unknown_sku",
    "price_mismatch",
    "future_timestamp",
    "bad_payment_method",
    "duplicate_line",
)


@dataclass(frozen=True)
class SimulationConfig:
    bad_record_rate: float = 0.05
    incident_probability: float = 0.03
    store_outage_probability: float = 0.01


def demand_multiplier(local_time: datetime) -> float:
    """Weekends and the days around month end payday are busier."""
    multiplier = 1.0
    if local_time.weekday() >= 5:
        multiplier *= 1.25
    if local_time.day >= 25 or local_time.day <= 2:
        multiplier *= 1.35
    return multiplier


def generate_hour(
    batch_hour: datetime,
    stores: list[Store],
    products: list[Product],
    config: SimulationConfig | None = None,
) -> pd.DataFrame:
    """Simulate one hour of line level sales across every open store."""
    config = config or SimulationConfig()
    rng = np.random.default_rng(int(batch_hour.timestamp()) // 3600)
    local_time = batch_hour.astimezone(ZoneInfo(LOCAL_TIMEZONE))
    weights = _product_weights(products)

    frames = []
    for store in stores:
        if not store.is_open(local_time.hour):
            continue
        # Draw both numbers up front so every store uses the same amount of
        # randomness. That keeps each hour reproducible.
        outage, incident = rng.random(), rng.random()
        if outage < config.store_outage_probability:
            continue  # till system down, this store sends nothing this hour
        lines = _simulate_store_hour(rng, store, batch_hour, local_time, products, weights)
        if incident < config.incident_probability and not lines.empty:
            lines = _corrupt(rng, lines, config.bad_record_rate)
        frames.append(lines)

    if not frames:
        return pd.DataFrame(columns=SOURCE_COLUMNS)
    return pd.concat(frames, ignore_index=True)[SOURCE_COLUMNS]


def write_landing_file(frame: pd.DataFrame, batch_hour: datetime, landing_dir: Path) -> Path:
    """Write the export the way the till system would. Empty hours still get a file."""
    landing_dir.mkdir(parents=True, exist_ok=True)
    path = landing_dir / landing_file_name(batch_hour)
    frame.to_csv(path, index=False)
    return path


def _product_weights(products: list[Product]) -> np.ndarray:
    per_category: dict[str, int] = {}
    for product in products:
        per_category[product.category] = per_category.get(product.category, 0) + 1
    raw = np.array(
        [CATEGORY_WEIGHTS.get(p.category, 1.0) / per_category[p.category] for p in products]
    )
    return raw / raw.sum()


def _simulate_store_hour(
    rng: np.random.Generator,
    store: Store,
    batch_hour: datetime,
    local_time: datetime,
    products: list[Product],
    weights: np.ndarray,
) -> pd.DataFrame:
    expected_baskets = (
        BASKETS_PER_PEAK_HOUR[store.store_size]
        * HOURLY_TRAFFIC.get(local_time.hour, 0.4)
        * demand_multiplier(local_time)
    )
    basket_count = int(rng.poisson(expected_baskets))
    offsets = np.sort(rng.integers(0, 3600, size=basket_count))

    rows = []
    for basket_no, offset in enumerate(offsets, start=1):
        transaction_id = f"{store.store_id}-{local_time:%Y%m%d%H}-{basket_no:04d}"
        till_id = f"T{int(rng.integers(1, store.till_count + 1)):02d}"
        payment_method = str(rng.choice(PAYMENT_METHODS, p=PAYMENT_WEIGHTS))
        sold_at = (batch_hour + timedelta(seconds=int(offset))).isoformat(timespec="seconds")
        line_count = min(1 + int(rng.poisson(3)), len(products))
        picks = rng.choice(len(products), size=line_count, replace=False, p=weights)

        for line_number, index in enumerate(picks, start=1):
            product = products[int(index)]
            quantity = int(rng.choice(QUANTITY_CHOICES, p=QUANTITY_WEIGHTS))
            gross = round(quantity * product.unit_price, 2)
            discount = 0.0
            if rng.random() < PROMO_PROBABILITY:
                discount = round(gross * float(rng.choice(PROMO_DISCOUNTS)), 2)
            rows.append(
                {
                    "transaction_id": transaction_id,
                    "line_number": line_number,
                    "store_id": store.store_id,
                    "till_id": till_id,
                    "product_sku": product.product_sku,
                    "quantity": quantity,
                    "unit_price": product.unit_price,
                    "discount_amount": discount,
                    "line_total": round(gross - discount, 2),
                    "payment_method": payment_method,
                    "sold_at": sold_at,
                }
            )
    return pd.DataFrame(rows, columns=SOURCE_COLUMNS)


def _corrupt(rng: np.random.Generator, lines: pd.DataFrame, rate: float) -> pd.DataFrame:
    """Simulate a faulty till by damaging a share of one store's lines for the hour."""
    lines = lines.astype(object)
    count = min(len(lines), max(1, round(len(lines) * rate)))
    targets = rng.choice(lines.index.to_numpy(), size=count, replace=False)
    duplicates = []

    for index in targets:
        match CORRUPTIONS[int(rng.integers(len(CORRUPTIONS)))]:
            case "negative_quantity":
                lines.at[index, "quantity"] = -abs(int(lines.at[index, "quantity"]))
            case "missing_sku":
                lines.at[index, "product_sku"] = None
            case "unknown_sku":
                lines.at[index, "product_sku"] = "SKU-99999"
            case "price_mismatch":
                lines.at[index, "unit_price"] = round(float(lines.at[index, "unit_price"]) * 1.5, 2)
            case "future_timestamp":
                sold_at = datetime.fromisoformat(lines.at[index, "sold_at"]) + timedelta(days=3)
                lines.at[index, "sold_at"] = sold_at.isoformat(timespec="seconds")
            case "bad_payment_method":
                lines.at[index, "payment_method"] = "crypto"
            case "duplicate_line":
                duplicates.append(lines.loc[index].copy())

    if duplicates:
        lines = pd.concat([lines, pd.DataFrame(duplicates)], ignore_index=True)
    return lines
