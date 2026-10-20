from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services import vip_timer
from services import vip_timer_pause_confirmation as pause_confirmation


def _install_fake_timer(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pause-confirm.db'}",
        connect_args={"check_same_thread": False},
    )
    local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(vip_timer, "SessionLocal", local)
    monkeypatch.setattr(
        vip_timer,
        "get_session",
        lambda order_id, db=None: {
            "order_id": int(order_id),
            "customer_discord_id": "customer-1",
            "status": "running",
        },
    )
    monkeypatch.setattr(vip_timer, "utc_now", lambda: datetime(2026, 10, 21, tzinfo=timezone.utc))
    monkeypatch.setattr(vip_timer, "_event", lambda *args, **kwargs: None)

    calls: list[tuple[int, str]] = []

    def fake_pause(order_id, actor_id):
        calls.append((int(order_id), str(actor_id)))
        return {"order_id": int(order_id), "status": "paused"}

    monkeypatch.setattr(vip_timer, "pause_timer", fake_pause)
    return calls


def test_customer_pause_request_needs_one_staff_confirmation(monkeypatch, tmp_path):
    calls = _install_fake_timer(monkeypatch, tmp_path)

    first = pause_confirmation.request_or_confirm_pause(
        10,
        "customer-1",
        ["staff-1", "staff-2"],
    )
    assert first["state"] == "pending"
    assert first["waiting_for"] == "staff"
    assert calls == []

    second = pause_confirmation.request_or_confirm_pause(
        10,
        "staff-2",
        ["staff-1", "staff-2"],
    )
    assert second["state"] == "paused"
    assert second["confirmed"] is True
    assert calls == [(10, "staff-2")]
    assert pause_confirmation.get_pause_request(10) is None


def test_one_staff_cannot_confirm_another_staff_request(monkeypatch, tmp_path):
    calls = _install_fake_timer(monkeypatch, tmp_path)

    first = pause_confirmation.request_or_confirm_pause(
        11,
        "staff-1",
        ["staff-1", "staff-2"],
    )
    assert first["state"] == "pending"
    assert first["waiting_for"] == "customer"

    same_side = pause_confirmation.request_or_confirm_pause(
        11,
        "staff-2",
        ["staff-1", "staff-2"],
    )
    assert same_side["state"] == "pending"
    assert same_side["already_requested"] is True
    assert calls == []

    confirmed = pause_confirmation.request_or_confirm_pause(
        11,
        "customer-1",
        ["staff-1", "staff-2"],
    )
    assert confirmed["state"] == "paused"
    assert calls == [(11, "customer-1")]


def test_support_pause_is_an_emergency_override(monkeypatch, tmp_path):
    calls = _install_fake_timer(monkeypatch, tmp_path)

    result = pause_confirmation.request_or_confirm_pause(
        12,
        "support-1",
        ["staff-1", "staff-2"],
    )

    assert result["state"] == "paused"
    assert result["forced"] is True
    assert calls == [(12, "support-1")]
