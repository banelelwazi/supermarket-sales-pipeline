from datetime import UTC, datetime

import pandas as pd
import pytest

from pipeline.generator import SimulationConfig, generate_hour
from pipeline.reference import load_products, load_stores
from pipeline.validate import ValidationContext

# 10:00 UTC is 12:00 in Johannesburg, the lunchtime peak, so every store is open.
TRADING_HOUR = datetime(2026, 10, 5, 10, tzinfo=UTC)
# 01:00 UTC is 03:00 in Johannesburg, every store is closed.
CLOSED_HOUR = datetime(2026, 10, 5, 1, tzinfo=UTC)

CLEAN = SimulationConfig(bad_record_rate=0, incident_probability=0, store_outage_probability=0)


@pytest.fixture(scope="session")
def stores():
    return load_stores()


@pytest.fixture(scope="session")
def products():
    return load_products()


@pytest.fixture
def context(stores, products):
    return ValidationContext.for_batch(TRADING_HOUR, stores, products)


@pytest.fixture
def clean_export(stores, products) -> pd.DataFrame:
    """A clean hour, as text, the way extract() hands it to the validator."""
    return generate_hour(TRADING_HOUR, stores, products, CLEAN).astype(str)
