from pipeline.generator import demand_multiplier, generate_hour
from pipeline.schema import SOURCE_COLUMNS
from pipeline.validate import validate
from tests.conftest import CLEAN, CLOSED_HOUR, TRADING_HOUR


def test_same_hour_gives_identical_data(stores, products):
    first = generate_hour(TRADING_HOUR, stores, products)
    second = generate_hour(TRADING_HOUR, stores, products)
    assert first.equals(second)


def test_output_matches_the_source_contract(stores, products):
    frame = generate_hour(TRADING_HOUR, stores, products, CLEAN)
    assert list(frame.columns) == SOURCE_COLUMNS
    assert len(frame) > 0


def test_every_open_store_trades_at_lunchtime(stores, products):
    frame = generate_hour(TRADING_HOUR, stores, products, CLEAN)
    assert set(frame["store_id"]) == {s.store_id for s in stores}


def test_closed_hours_produce_no_sales(stores, products):
    frame = generate_hour(CLOSED_HOUR, stores, products, CLEAN)
    assert frame.empty
    assert list(frame.columns) == SOURCE_COLUMNS


def test_clean_simulation_passes_every_validation_rule(clean_export, context):
    result = validate(clean_export, context)
    assert result.rejected.empty, result.reason_counts


def test_payday_weekend_is_busier_than_a_normal_weekday():
    from datetime import datetime

    normal_tuesday = datetime(2026, 10, 13, 12)
    payday_saturday = datetime(2026, 9, 26, 12)
    assert demand_multiplier(payday_saturday) > demand_multiplier(normal_tuesday)
