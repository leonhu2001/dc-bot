from datetime import datetime, timedelta, timezone

from core.discord_settings import (
    DISPATCH_ACTIVE_TIMEOUT_SECONDS,
    DISPATCH_RECENT_TIMEOUT_SECONDS,
    SMART_DISPATCH_FULL_EXPANSION_SECONDS,
    SMART_DISPATCH_PUBLIC_ACCEPTANCE_OPEN_SECONDS,
    SMART_DISPATCH_REPEAT_REMINDER_SECONDS,
    SMART_DISPATCH_SECOND_WAVE_SECONDS,
)
from services.dispatch_presence import classify_dispatch_presence
from views import smart_dispatch


def test_dispatch_cadence_has_one_source_of_truth():
    assert smart_dispatch.PUBLIC_ACCEPTANCE_OPEN_SECONDS == SMART_DISPATCH_PUBLIC_ACCEPTANCE_OPEN_SECONDS == 60
    assert smart_dispatch.SECOND_WAVE_SECONDS == SMART_DISPATCH_SECOND_WAVE_SECONDS == 240
    assert smart_dispatch.FULL_EXPANSION_SECONDS == SMART_DISPATCH_FULL_EXPANSION_SECONDS == 420
    assert smart_dispatch.REPEAT_REMINDER_SECONDS == SMART_DISPATCH_REPEAT_REMINDER_SECONDS == 600


def test_presence_windows_are_active_then_recent():
    assert DISPATCH_ACTIVE_TIMEOUT_SECONDS == 90
    assert DISPATCH_RECENT_TIMEOUT_SECONDS == 300
    assert DISPATCH_ACTIVE_TIMEOUT_SECONDS < DISPATCH_RECENT_TIMEOUT_SECONDS


def test_presence_classifier_keeps_short_disconnect_as_recent(monkeypatch):
    from services import dispatch_presence

    monkeypatch.setattr(
        dispatch_presence,
        "get_online_dispatch_worker_ids",
        lambda **kwargs: ["A"],
    )
    monkeypatch.setattr(
        dispatch_presence,
        "get_recent_dispatch_worker_ids",
        lambda **kwargs: ["A", "B"],
    )

    result = classify_dispatch_presence(["A", "B", "C"])
    assert result == {"A": "active", "B": "recent", "C": "offline"}
