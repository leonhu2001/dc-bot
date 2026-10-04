from datetime import datetime, timedelta, timezone

import discord

from services.dispatch_presence import (
    count_online_dispatch_workers,
    get_online_dispatch_support_ids,
    get_online_dispatch_worker_ids,
    has_online_dispatch_support,
    touch_dispatch_presence,
    touch_dispatch_support_presence,
)
from views.dispatch_presence import (
    apply_display_only_permissions,
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
    assert format_dispatch_presence_channel_name(0) == "⚫┃暫無陪玩"
    assert format_dispatch_presence_channel_name(1) == "🟢┃在線陪玩：1"
    assert format_dispatch_presence_channel_name(2) == "🟢┃在線陪玩：2"
    assert format_dispatch_presence_channel_name(5) == "🟢┃在線陪玩：5"


def test_display_only_permissions_keep_channel_visible_but_disable_chat():
    overwrite = discord.PermissionOverwrite(
        view_channel=None,
        send_messages=True,
        add_reactions=True,
        read_message_history=True,
    )

    changed = apply_display_only_permissions(
        overwrite,
        reveal_channel=True,
    )

    assert changed is True
    assert overwrite.view_channel is True
    assert overwrite.send_messages is False
    assert overwrite.send_tts_messages is False
    assert overwrite.add_reactions is False
    assert overwrite.create_public_threads is False
    assert overwrite.create_private_threads is False
    assert overwrite.send_messages_in_threads is False
    assert overwrite.read_message_history is False
    assert overwrite.use_application_commands is False


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
