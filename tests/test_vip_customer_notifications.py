from datetime import datetime, timedelta, timezone

from services.vip_customer_notifications import (
    list_expiry_reminders,
    list_retention_renewals,
    mark_expiry_reminder_sent,
    mark_retention_resolved,
)


TZ = timezone(timedelta(hours=8))


def _row(*, customer_id="123", expiry_at: datetime, days_remaining: int) -> dict:
    return {
        "customer_id": customer_id,
        "current_index": 3,
        "current_level": "白金魔丸",
        "expiry_at": expiry_at.isoformat(timespec="seconds"),
        "days_remaining": days_remaining,
        "is_due": False,
    }


def test_expiry_reminder_is_once_per_expiry(tmp_path):
    db = tmp_path / "vip.db"
    expiry = datetime(2026, 10, 23, 12, 0, tzinfo=TZ)
    row = _row(expiry_at=expiry, days_remaining=7)

    assert list_expiry_reminders([row], db_file=db) == [row]

    mark_expiry_reminder_sent(row, db_file=db)

    assert list_expiry_reminders([row], db_file=db) == []


def test_reminder_waits_until_seven_day_window(tmp_path):
    db = tmp_path / "vip.db"
    expiry = datetime(2026, 11, 15, 12, 0, tzinfo=TZ)
    row = _row(expiry_at=expiry, days_remaining=8)

    assert list_expiry_reminders([row], db_file=db) == []


def test_renewal_is_detected_after_reminded_expiry_moves_forward(tmp_path):
    db = tmp_path / "vip.db"
    old_expiry = datetime(2026, 10, 23, 12, 0, tzinfo=TZ)
    new_expiry = old_expiry + timedelta(days=60)
    old_row = _row(expiry_at=old_expiry, days_remaining=7)
    new_row = _row(expiry_at=new_expiry, days_remaining=60)

    mark_expiry_reminder_sent(old_row, db_file=db)

    assert list_retention_renewals([new_row], db_file=db) == [new_row]

    mark_retention_resolved("123", new_row["expiry_at"], db_file=db)

    assert list_retention_renewals([new_row], db_file=db) == []


def test_same_or_earlier_expiry_is_not_a_renewal(tmp_path):
    db = tmp_path / "vip.db"
    expiry = datetime(2026, 10, 23, 12, 0, tzinfo=TZ)
    row = _row(expiry_at=expiry, days_remaining=7)
    mark_expiry_reminder_sent(row, db_file=db)

    same = _row(expiry_at=expiry, days_remaining=6)
    earlier = _row(expiry_at=expiry - timedelta(days=1), days_remaining=5)

    assert list_retention_renewals([same, earlier], db_file=db) == []
