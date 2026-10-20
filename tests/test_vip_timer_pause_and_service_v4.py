from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from services import vip_timer
from services import vip_timer_billing_guard as billing
from services import vip_timer_pause_confirmation as pause_confirmation
from services import vip_timer_selector_order_v4 as v4


def test_v4_sweet_fourth_layer_is_gender_specific():
    female_single = SimpleNamespace(
        label="三角洲端遊｜甜蜜單｜女單陪",
        required_staff_count=1,
        allowed_roles=("female_companion",),
    )
    male_single = SimpleNamespace(
        label="三角洲端遊｜甜蜜單｜男單陪",
        required_staff_count=1,
        allowed_roles=("male_companion",),
    )
    female_double = SimpleNamespace(
        label="三角洲端遊｜甜蜜單｜女雙陪",
        required_staff_count=2,
        allowed_roles=("female_companion",),
    )
    male_double = SimpleNamespace(
        label="三角洲端遊｜甜蜜單｜男雙陪",
        required_staff_count=2,
        allowed_roles=("male_companion",),
    )
    any_double = SimpleNamespace(
        label="三角洲端遊｜甜蜜單｜雙陪(不限)",
        required_staff_count=2,
        allowed_roles=("female_companion", "male_companion"),
    )

    assert v4._service_type("甜蜜單", {"label": "女單陪"}, female_single) == "女單陪"
    assert v4._service_type("甜蜜單", {"label": "男單陪"}, male_single) == "男單陪"
    assert v4._service_type("甜蜜單", {"label": "女雙陪"}, female_double) == "女雙陪"
    assert v4._service_type("甜蜜單", {"label": "男雙陪"}, male_double) == "男雙陪"
    assert v4._service_type("甜蜜單", {"label": "雙陪(不限)"}, any_double) == "不支援"


def test_v4_teaching_fourth_layer_is_one_to_one():
    rule = SimpleNamespace(
        label="APEX｜教學單｜1對1",
        required_staff_count=1,
        allowed_roles=(),
    )
    assert v4._service_type("教學單", {"label": "1對1"}, rule) == "1對1教學"
    assert v4._is_teaching_rule(
        "apex_teaching_one",
        SimpleNamespace(label="APEX｜教學單｜1對1", pricing_type="hourly", price=500),
    ) is True


def _pause_env(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pause.db'}",
        connect_args={"check_same_thread": False},
    )
    local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(vip_timer, "SessionLocal", local)
    vip_timer.ensure_vip_timer_tables()

    now = vip_timer.utc_iso(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO vip_timer_sessions(
                order_id, customer_discord_id, status, current_rule_key,
                current_rule_label, current_category_label, current_hourly_rate,
                started_at, created_at, updated_at
            ) VALUES (1, 'customer', 'running', 'hour_a', '玩法 A', 'STEAM', 300,
                      :now, :now, :now)
        """), {"now": now})
        conn.execute(text("""
            INSERT INTO vip_timer_segments(
                order_id, seq, rule_key, rule_label, category_label,
                hourly_rate, started_at, active_started_at, billable_seconds,
                staff_ids_json, created_at, updated_at
            ) VALUES (1, 1, 'hour_a', '玩法 A', 'STEAM', 300,
                      :now, :now, 0, '["staff-1","staff-2"]', :now, :now)
        """), {"now": now})
    return engine


def test_pause_customer_request_can_be_confirmed_by_any_one_staff(tmp_path, monkeypatch):
    _pause_env(tmp_path, monkeypatch)

    first = pause_confirmation.request_or_confirm_pause(
        1,
        "customer",
        ["staff-1", "staff-2"],
    )
    assert first["state"] == "requested"
    assert vip_timer.get_session(1)["status"] == "running"

    confirmed = pause_confirmation.request_or_confirm_pause(
        1,
        "staff-2",
        ["staff-1", "staff-2"],
    )
    assert confirmed["state"] == "paused"
    assert vip_timer.get_session(1)["status"] == "paused"


def test_second_staff_does_not_count_as_other_side(tmp_path, monkeypatch):
    _pause_env(tmp_path, monkeypatch)

    first = pause_confirmation.request_or_confirm_pause(
        1,
        "staff-1",
        ["staff-1", "staff-2"],
    )
    assert first["state"] == "requested"

    same_side = pause_confirmation.request_or_confirm_pause(
        1,
        "staff-2",
        ["staff-1", "staff-2"],
    )
    assert same_side["state"] == "waiting"
    assert vip_timer.get_session(1)["status"] == "running"

    customer = pause_confirmation.request_or_confirm_pause(
        1,
        "customer",
        ["staff-1", "staff-2"],
    )
    assert customer["state"] == "paused"


def test_whole_order_minimum_is_fifteen_minutes(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'billing.db'}",
        connect_args={"check_same_thread": False},
    )
    local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(vip_timer, "SessionLocal", local)
    vip_timer.ensure_vip_timer_tables()

    now = vip_timer.utc_iso(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO vip_timer_segments(
                order_id, seq, rule_key, rule_label, category_label,
                hourly_rate, started_at, ended_at, billable_seconds,
                staff_ids_json, created_at, updated_at
            ) VALUES (2, 1, 'hour_a', '玩法 A', 'STEAM', 600,
                      :now, :now, 600, '[]', :now, :now)
        """), {"now": now})

    amount, actual_seconds = billing.calculate_total_with_minimum(2)
    assert actual_seconds == 10 * 60
    assert amount == 150
