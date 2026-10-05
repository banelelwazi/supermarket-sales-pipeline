from datetime import UTC, datetime, timedelta

from pipeline.run import hours_to_process, parse_hour

NOW = datetime(2026, 10, 5, 14, 7, tzinfo=UTC)
LAST_COMPLETE = datetime(2026, 10, 5, 13, tzinfo=UTC)


def test_normal_run_processes_only_the_last_complete_hour():
    done = {LAST_COMPLETE - timedelta(hours=i) for i in range(1, 24)}
    assert hours_to_process(done, NOW, 24) == [LAST_COMPLETE]


def test_missed_and_failed_hours_are_caught_up_in_order():
    missing = {LAST_COMPLETE - timedelta(hours=5), LAST_COMPLETE - timedelta(hours=2)}
    done = {LAST_COMPLETE - timedelta(hours=i) for i in range(24)} - missing
    assert hours_to_process(done, NOW, 24) == sorted(missing)


def test_nothing_to_do_when_everything_is_loaded():
    done = {LAST_COMPLETE - timedelta(hours=i) for i in range(24)}
    assert hours_to_process(done, NOW, 24) == []


def test_the_current_hour_is_never_processed_while_still_open():
    assert all(hour <= LAST_COMPLETE for hour in hours_to_process(set(), NOW, 24))


def test_parse_hour_floors_and_assumes_utc():
    assert parse_hour("2026-10-05 13:45") == datetime(2026, 10, 5, 13, tzinfo=UTC)
    assert parse_hour("2026-10-05T15:30+02:00") == datetime(2026, 10, 5, 13, tzinfo=UTC)
