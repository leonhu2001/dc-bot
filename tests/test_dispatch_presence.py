from datetime import datetime, timedelta, timezone

from services.dispatch_presence import (
    count_online_dispatch_workers,
    get_online_dispatch_worker_ids,
    touch_dispatch_presence,
)
from views.dispatch_presence import format_dispatch_presence_channel_name


def test_dispatch_presence_expires_after_timeout(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)

    touch_dispatch_presence(
        "100",
        display_name="Worker A",
        db_file=db_path,
        now=now,
    )

    assert get_online_dispatch_worker_ids(
        db_file=db_path,
        now=now + timedelta(seconds=89),
    ) == ["100"]

    assert get_online_dispatch_worker_ids(
        db_file=db_path,
        now=now + timedelta(seconds=91),
    ) == []


def test_dispatch_presence_can_filter_candidates(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)

    touch_dispatch_presence("100", db_file=db_path, now=now)
    touch_dispatch_presence("200", db_file=db_path, now=now)

    assert get_online_dispatch_worker_ids(
        candidate_ids=["200", "300"],
        db_file=db_path,
        now=now,
    ) == ["200"]

    assert count_online_dispatch_workers(
        candidate_ids=["100", "200", "300"],
        db_file=db_path,
        now=now,
    ) == 2


def test_dispatch_presence_channel_name_reflects_count():
    assert format_dispatch_presence_channel_name(0) == "⚫｜可接單・0人"
    assert format_dispatch_presence_channel_name(5) == "🟢｜可接單・5人"
