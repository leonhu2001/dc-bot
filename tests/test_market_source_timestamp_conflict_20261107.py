from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.market.poll_diagnostics import (
    load_market_poll,
    market_delay_diagnosis,
    record_market_poll,
)
from services.market.providers.public_852941 import _parse_source_time


def test_provider_uses_latest_of_both_upstream_market_timestamps():
    now = datetime.now(timezone.utc)
    taipei = timezone(timedelta(hours=8))
    old = (now - timedelta(hours=4)).astimezone(taipei).strftime("%Y-%m-%d %H:%M:%S")
    new = (now - timedelta(minutes=10)).astimezone(taipei).strftime("%Y-%m-%d %H:%M:%S")
    parsed = _parse_source_time({
        "latest_market_time": old,
        "snapshot_group_time": new,
    })
    assert abs((parsed - (now - timedelta(minutes=10))).total_seconds()) < 2
    # Both endpoints can report a newer timestamp, no first-field bias.
    parsed_reversed = _parse_source_time({
        "latest_market_time": new,
        "snapshot_group_time": old,
    })
    assert parsed_reversed == parsed


def test_identical_upstream_timestamp_but_changed_prices_is_not_ordinary_duplicate(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MARKET_POLL_STATE_FILE", str(tmp_path / "market.json"))
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=4)
    record_market_poll(
        game_key="delta_force", status="stored", provider="reader",
        checked_at=now - timedelta(minutes=15),
        source_updated_at=old, price_signature="price-a",
    )
    record_market_poll(
        game_key="delta_force", status="duplicate", provider="reader",
        checked_at=now, source_updated_at=old,
        price_signature="price-b",
    )
    poll = load_market_poll()
    assert poll is not None
    assert poll["status"] == "timestamp_price_conflict"
    diag = market_delay_diagnosis(source_updated_at=old, now=now, poll=poll)
    assert diag["reason"] == "source_timestamp_price_conflict"
    assert "價格已改變" in diag["message"]


def test_conflict_persists_until_source_time_advances(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_POLL_STATE_FILE", str(tmp_path / "market.json"))
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=4)
    for status, signature in (("stored", "a"), ("duplicate", "b"), ("duplicate", "b")):
        record_market_poll(
            game_key="delta_force", status=status, provider="reader",
            source_updated_at=old, price_signature=signature, checked_at=now,
        )
    assert load_market_poll()["status"] == "timestamp_price_conflict"
    record_market_poll(
        game_key="delta_force", status="stored", provider="reader",
        source_updated_at=now, price_signature="b", checked_at=now,
    )
    assert load_market_poll()["status"] == "stored"
