from datetime import datetime, timedelta, timezone

from services.dispatch_presence import (
    count_online_dispatch_workers,
    get_online_dispatch_support_ids,
    get_online_dispatch_worker_ids,
    has_online_dispatch_support,
    touch_dispatch_presence,
    touch_dispatch_support_presence,
)
from views.dispatch_presence import (
    format_dispatch_presence_channel_name,
    format_dispatch_support_channel_name,
)


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
    assert format_dispatch_presence_channel_name(0) == "⏳｜排隊房・⚫暫無陪玩"
    assert format_dispatch_presence_channel_name(1) == "⏳｜排隊房・⚫暫無陪玩"
    assert format_dispatch_presence_channel_name(2) == "⏳｜排隊房・🟢在線陪玩2人"
    assert format_dispatch_presence_channel_name(5) == "⏳｜排隊房・🟢在線陪玩5人"


def test_dispatch_support_presence_expires_after_timeout(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)

    touch_dispatch_support_presence(
        "900",
        display_name="Support A",
        db_file=db_path,
        now=now,
    )

    assert get_online_dispatch_support_ids(
        db_file=db_path,
        now=now + timedelta(seconds=89),
    ) == ["900"]
    assert has_online_dispatch_support(
        db_file=db_path,
        now=now + timedelta(seconds=89),
    )

    assert get_online_dispatch_support_ids(
        db_file=db_path,
        now=now + timedelta(seconds=91),
    ) == []
    assert not has_online_dispatch_support(
        db_file=db_path,
        now=now + timedelta(seconds=91),
    )


def test_dispatch_support_channel_name_reflects_any_online_staff():
    assert format_dispatch_support_channel_name(False) == "🛎️┃點單・服務大廳"
    assert format_dispatch_support_channel_name(True) == "🟢┃點單・服務大廳"
