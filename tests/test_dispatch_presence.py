from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from views.dispatch_presence import (
    DISPATCH_PRESENCE_TTL_SECONDS,
    ensure_dispatch_presence_tables,
    format_dispatch_support_channel_name,
    get_online_dispatch_presence_ids,
    get_online_dispatch_support_ids,
    has_online_dispatch_support,
    touch_dispatch_presence,
)


UTC = timezone.utc


def _db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_dispatch_presence_tracks_users_and_expires(tmp_path):
    db_path = tmp_path / "presence.db"
    now = datetime(2026, 10, 17, 0, 0, tzinfo=UTC)

    ensure_dispatch_presence_tables(db_path)
    touch_dispatch_presence(
        discord_id="100",
        is_companion=True,
        is_support=False,
        display_name="陪玩A",
        db_file=db_path,
        now=now,
    )
    touch_dispatch_presence(
        discord_id="200",
        is_companion=False,
        is_support=True,
        display_name="客服B",
        db_file=db_path,
        now=now,
    )

    assert get_online_dispatch_presence_ids(
        role="companion",
        db_file=db_path,
        now=now + timedelta(seconds=DISPATCH_PRESENCE_TTL_SECONDS - 1),
    ) == ["100"]
    assert get_online_dispatch_presence_ids(
        role="support",
        db_file=db_path,
        now=now + timedelta(seconds=DISPATCH_PRESENCE_TTL_SECONDS - 1),
    ) == ["200"]

    assert get_online_dispatch_presence_ids(
        role="companion",
        db_file=db_path,
        now=now + timedelta(seconds=DISPATCH_PRESENCE_TTL_SECONDS + 1),
    ) == []


def test_dispatch_presence_touch_is_upsert(tmp_path):
    db_path = tmp_path / "presence.db"
    first = datetime(2026, 10, 17, 0, 0, tzinfo=UTC)
    second = first + timedelta(seconds=30)

    touch_dispatch_presence(
        discord_id="100",
        is_companion=True,
        is_support=False,
        display_name="陪玩A",
        db_file=db_path,
        now=first,
    )
    touch_dispatch_presence(
        discord_id="100",
        is_companion=True,
        is_support=True,
        display_name="陪玩A2",
        db_file=db_path,
        now=second,
    )

    with _db(db_path) as conn:
        rows = conn.execute("SELECT * FROM dispatch_presence").fetchall()

    assert len(rows) == 1
    assert rows[0]["discord_id"] == "100"
    assert rows[0]["display_name"] == "陪玩A2"
    assert rows[0]["is_companion"] == 1
    assert rows[0]["is_support"] == 1


def test_dispatch_support_online_only_counts_support(tmp_path):
    db_path = tmp_path / "presence.db"
    now = datetime(2026, 10, 17, 0, 0, tzinfo=UTC)

    touch_dispatch_presence(
        discord_id="100",
        is_companion=True,
        is_support=False,
        display_name="陪玩A",
        db_file=db_path,
        now=now,
    )
    assert not has_online_dispatch_support(db_file=db_path, now=now)

    touch_dispatch_presence(
        discord_id="900",
        is_companion=False,
        is_support=True,
        display_name="客服A",
        db_file=db_path,
        now=now,
    )
    assert get_online_dispatch_support_ids(db_file=db_path, now=now) == ["900"]
    assert has_online_dispatch_support(db_file=db_path, now=now)

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
    assert format_dispatch_support_channel_name(False) == "🛎️┃聯絡客服"
    assert format_dispatch_support_channel_name(True) == "🟢┃聯絡客服"
