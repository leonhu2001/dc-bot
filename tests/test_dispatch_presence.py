import json
import sqlite3
from datetime import datetime, timedelta, timezone

from services.dispatch_presence import (
    count_online_dispatch_companions_for_role,
    count_online_dispatch_workers,
    get_dispatch_companion_ids_for_role,
    get_online_dispatch_support_ids,
    get_online_dispatch_worker_ids,
    has_online_dispatch_support,
    touch_dispatch_presence,
    touch_dispatch_support_presence,
)
from views.dispatch_presence import (
    format_companion_presence_channel_name,
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


def test_dispatch_presence_can_count_companions_by_role(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    female_role_id = "1482080315798192210"
    male_role_id = "1500751059239440575"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE web_staff_members (
                discord_id TEXT PRIMARY KEY,
                roles_json TEXT,
                is_active INTEGER,
                is_companion INTEGER
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO web_staff_members (
                discord_id,
                roles_json,
                is_active,
                is_companion
            ) VALUES (?, ?, 1, 1)
            """,
            [
                ("100", json.dumps([female_role_id])),
                ("200", json.dumps([male_role_id])),
                ("300", json.dumps([female_role_id, male_role_id])),
            ],
        )
        conn.commit()

    touch_dispatch_presence("100", db_file=db_path, now=now)
    touch_dispatch_presence("200", db_file=db_path, now=now)
    touch_dispatch_presence("300", db_file=db_path, now=now)

    assert get_dispatch_companion_ids_for_role(
        female_role_id,
        db_file=db_path,
    ) == ["100", "300"]
    assert count_online_dispatch_companions_for_role(
        female_role_id,
        db_file=db_path,
        now=now,
    ) == 2
    assert count_online_dispatch_companions_for_role(
        male_role_id,
        db_file=db_path,
        now=now,
    ) == 2


def test_dispatch_presence_channel_name_reflects_count():
    assert format_dispatch_presence_channel_name(0) == "⚫┃暫無陪玩"
    assert format_dispatch_presence_channel_name(1) == "🟢┃在線陪玩：1"
    assert format_dispatch_presence_channel_name(2) == "🟢┃在線陪玩：2"
    assert format_dispatch_presence_channel_name(5) == "🟢┃在線陪玩：5"

    assert (
        format_companion_presence_channel_name("女陪", "👩", 0)
        == "👩┃女陪・⚫0人在線"
    )
    assert (
        format_companion_presence_channel_name("女陪", "👩", 3)
        == "👩┃女陪・🟢3人在線"
    )
    assert (
        format_companion_presence_channel_name("男陪", "🧑", 1)
        == "🧑┃男陪・🟢1人在線"
    )


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
    assert format_dispatch_support_channel_name(False) == "🛎️┃點單・客服中心"
    assert format_dispatch_support_channel_name(True) == "🟢┃點單・客服值班中"
