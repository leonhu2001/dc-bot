from core.time_utils import (
    format_taipei_datetime_from_utc,
    get_taipei_date_from_utc,
    parse_utc_datetime_safe,
)


def test_utc_naive_timestamp_crosses_into_next_taipei_date():
    assert get_taipei_date_from_utc(
        "2026-10-03 20:45:32.727807"
    ) == "2026-10-04"


def test_utc_naive_timestamp_formats_as_taipei_wall_clock():
    assert format_taipei_datetime_from_utc(
        "2026-10-03 20:45:32.727807"
    ) == "2026-10-04 04:45"


def test_aware_timestamp_respects_existing_offset():
    assert get_taipei_date_from_utc(
        "2026-10-04T00:30:00+08:00"
    ) == "2026-10-04"


def test_invalid_utc_timestamp_returns_none():
    assert parse_utc_datetime_safe("not-a-time") is None
