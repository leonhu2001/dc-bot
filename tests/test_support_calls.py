from datetime import datetime, timedelta, timezone

from services import support_calls


TAIPEI_TZ = timezone(timedelta(hours=8))


def _fixed_now():
    return datetime(2026, 10, 2, 12, 0, 0, tzinfo=TAIPEI_TZ)


def test_support_call_lifecycle_prevents_duplicate_active_calls(tmp_path, monkeypatch):
    db_path = tmp_path / "web_dashboard.db"
    monkeypatch.setattr(support_calls, "_now", _fixed_now)

    first, created = support_calls.create_or_get_active_support_call(
        ticket_channel_id="100",
        customer_discord_id="200",
        customer_display_name="Boss",
        db_file=db_path,
    )

    assert created is True
    assert first["status"] == "open"

    duplicate, created = support_calls.create_or_get_active_support_call(
        ticket_channel_id="100",
        customer_discord_id="200",
        customer_display_name="Boss",
        db_file=db_path,
    )

    assert created is False
    assert duplicate["id"] == first["id"]

    support_calls.set_support_call_notification(
        first["id"],
        "999",
        db_file=db_path,
    )

    claimed, changed = support_calls.claim_support_call(
        first["id"],
        staff_discord_id="300",
        staff_display_name="CS",
        db_file=db_path,
    )

    assert changed is True
    assert claimed["status"] == "claimed"
    assert claimed["claimed_by_discord_id"] == "300"

    claimed_again, changed = support_calls.claim_support_call(
        first["id"],
        staff_discord_id="301",
        staff_display_name="Other CS",
        db_file=db_path,
    )

    assert changed is False
    assert claimed_again["claimed_by_discord_id"] == "300"

    resolved, changed = support_calls.resolve_support_call(
        first["id"],
        staff_discord_id="300",
        staff_display_name="CS",
        db_file=db_path,
    )

    assert changed is True
    assert resolved["status"] == "resolved"

    second, created = support_calls.create_or_get_active_support_call(
        ticket_channel_id="100",
        customer_discord_id="200",
        customer_display_name="Boss",
        db_file=db_path,
    )

    assert created is True
    assert second["id"] != first["id"]


def test_support_call_notification_lookup(tmp_path, monkeypatch):
    db_path = tmp_path / "web_dashboard.db"
    monkeypatch.setattr(support_calls, "_now", _fixed_now)

    call, _ = support_calls.create_or_get_active_support_call(
        ticket_channel_id="101",
        customer_discord_id="201",
        customer_display_name="Boss",
        db_file=db_path,
    )
    support_calls.set_support_call_notification(
        call["id"],
        "123456",
        db_file=db_path,
    )

    found = support_calls.get_support_call_by_notification(
        "123456",
        db_file=db_path,
    )

    assert found is not None
    assert found["id"] == call["id"]


def test_support_call_reminder_stage_is_monotonic_and_open_only(tmp_path, monkeypatch):
    db_path = tmp_path / "web_dashboard.db"
    monkeypatch.setattr(support_calls, "_now", _fixed_now)

    call, _ = support_calls.create_or_get_active_support_call(
        ticket_channel_id="102",
        customer_discord_id="202",
        customer_display_name="Boss",
        db_file=db_path,
    )

    assert support_calls.mark_support_call_reminder(
        call["id"],
        1,
        db_file=db_path,
    ) is True

    assert support_calls.mark_support_call_reminder(
        call["id"],
        1,
        db_file=db_path,
    ) is False

    assert support_calls.mark_support_call_reminder(
        call["id"],
        2,
        db_file=db_path,
    ) is True

    support_calls.claim_support_call(
        call["id"],
        staff_discord_id="302",
        staff_display_name="CS",
        db_file=db_path,
    )

    assert support_calls.mark_support_call_reminder(
        call["id"],
        3,
        db_file=db_path,
    ) is False


def test_support_call_snapshot_calculates_sla(tmp_path, monkeypatch):
    db_path = tmp_path / "web_dashboard.db"
    monkeypatch.setattr(support_calls, "_now", _fixed_now)
    support_calls.ensure_support_call_tables(db_path)

    called_1 = (_fixed_now() - timedelta(minutes=20)).isoformat(timespec="seconds")
    claimed_1 = (_fixed_now() - timedelta(minutes=17)).isoformat(timespec="seconds")
    called_2 = (_fixed_now() - timedelta(minutes=10)).isoformat(timespec="seconds")
    claimed_2 = (_fixed_now() - timedelta(minutes=3)).isoformat(timespec="seconds")

    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            f"""
            INSERT INTO support_calls (
                ticket_channel_id,
                customer_discord_id,
                status,
                called_at,
                claimed_at,
                claimed_by_discord_id,
                reminder_stage,
                updated_at
            )
            VALUES
                ('1', '11', 'resolved', '{called_1}', '{claimed_1}', '31', 0, '{claimed_1}'),
                ('2', '12', 'claimed', '{called_2}', '{claimed_2}', '32', 1, '{claimed_2}');
            """
        )
        conn.commit()

    snapshot = support_calls.build_support_call_snapshot(
        db_file=db_path,
        days=30,
    )

    assert snapshot["active_count"] == 1
    assert snapshot["claimed_count"] == 1
    assert snapshot["open_count"] == 0
    assert snapshot["response_count"] == 2
    assert snapshot["within_5_count"] == 1
    assert snapshot["within_5_rate"] == 50.0
    assert snapshot["average_response_seconds"] == 300
    assert snapshot["median_response_seconds"] == 300


def test_resolved_support_call_duration_stops_at_resolved_at(tmp_path, monkeypatch):
    db_path = tmp_path / "web_dashboard.db"
    monkeypatch.setattr(support_calls, "_now", _fixed_now)
    support_calls.ensure_support_call_tables(db_path)

    import sqlite3

    called = (_fixed_now() - timedelta(minutes=40)).isoformat(timespec="seconds")
    claimed = (_fixed_now() - timedelta(minutes=35)).isoformat(timespec="seconds")
    resolved = (_fixed_now() - timedelta(minutes=30)).isoformat(timespec="seconds")

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO support_calls (
                ticket_channel_id,
                customer_discord_id,
                status,
                called_at,
                claimed_at,
                resolved_at,
                claimed_by_discord_id,
                resolved_by_discord_id,
                reminder_stage,
                updated_at
            )
            VALUES (?, ?, 'resolved', ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                "150",
                "250",
                called,
                claimed,
                resolved,
                "350",
                "350",
                resolved,
            ),
        )
        conn.commit()

    snapshot = support_calls.build_support_call_snapshot(
        db_file=db_path,
        days=30,
    )

    row = snapshot["rows"][0]

    assert row["status_label"] == "已完成"
    assert row["duration_label"] == "實際處理耗時"
    assert row["age_seconds"] == 300
    assert row["age_text"] == "5 分 0 秒"
    assert row["response_seconds"] == 300


def test_claimed_support_call_duration_starts_from_claim_time(tmp_path, monkeypatch):
    row = {
        "status": "claimed",
        "called_at": (_fixed_now() - timedelta(minutes=20)).isoformat(timespec="seconds"),
        "claimed_at": (_fixed_now() - timedelta(minutes=7)).isoformat(timespec="seconds"),
    }

    seconds, label = support_calls._stage_duration(
        row,
        now=_fixed_now(),
    )

    assert seconds == 420
    assert label == "目前處理時間"


def test_resolve_requires_claimed_state(tmp_path, monkeypatch):
    db_path = tmp_path / "web_dashboard.db"
    monkeypatch.setattr(support_calls, "_now", _fixed_now)

    call, _ = support_calls.create_or_get_active_support_call(
        ticket_channel_id="103",
        customer_discord_id="203",
        customer_display_name="Boss",
        db_file=db_path,
    )

    latest, changed = support_calls.resolve_support_call(
        call["id"],
        staff_discord_id="303",
        staff_display_name="CS",
        db_file=db_path,
    )

    assert changed is False
    assert latest["status"] == "open"


def test_close_support_calls_for_ticket_retires_active_calls(tmp_path, monkeypatch):
    db_path = tmp_path / "web_dashboard.db"
    monkeypatch.setattr(support_calls, "_now", _fixed_now)

    call, _ = support_calls.create_or_get_active_support_call(
        ticket_channel_id="104",
        customer_discord_id="204",
        customer_display_name="Boss",
        db_file=db_path,
    )

    closed = support_calls.close_support_calls_for_ticket(
        "104",
        reason="order_closed",
        db_file=db_path,
    )

    assert closed == 1

    latest = support_calls.get_support_call(
        call["id"],
        db_file=db_path,
    )

    assert latest is not None
    assert latest["status"] == "cancelled"
    assert latest["cancel_reason"] == "order_closed"

    active = support_calls.list_active_support_calls(
        db_file=db_path,
    )

    assert active == []
