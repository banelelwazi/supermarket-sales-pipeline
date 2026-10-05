"""Store and product reference data.

The CSVs live in the dbt seeds folder so the Python checks and the warehouse
always agree on what counts as a valid store or product.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from pipeline.config import SEEDS_DIR


@dataclass(frozen=True)
class Store:
    store_id: str
    store_name: str
    city: str
    province: str
    store_size: str
    opening_hour: int
    closing_hour: int
    till_count: int

    def is_open(self, local_hour: int) -> bool:
        return self.opening_hour <= local_hour < self.closing_hour


@dataclass(frozen=True)
class Product:
    product_sku: str
    product_name: str
    category: str
    unit_price: float
    vat_rate: float


def load_stores(seeds_dir: Path = SEEDS_DIR) -> list[Store]:
    frame = pd.read_csv(seeds_dir / "stores.csv")
    return [
        Store(
            store_id=row.store_id,
            store_name=row.store_name,
            city=row.city,
            province=row.province,
            store_size=row.store_size,
            opening_hour=int(row.opening_hour),
            closing_hour=int(row.closing_hour),
            till_count=int(row.till_count),
        )
        for row in frame.itertuples(index=False)
    ]


def load_products(seeds_dir: Path = SEEDS_DIR) -> list[Product]:
    frame = pd.read_csv(seeds_dir / "products.csv")
    return [
        Product(
            product_sku=row.product_sku,
            product_name=row.product_name,
            category=row.category,
            unit_price=float(row.unit_price),
            vat_rate=float(row.vat_rate),
        )
        for row in frame.itertuples(index=False)
    ]
