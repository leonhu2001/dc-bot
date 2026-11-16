"""Expand staff-operated, display-only timer to Delta non-fun hourly orders."""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from services import simple_order_timer as clock


@pytest.mark.parametrize("key,expected", [
    ("basic_black_tide_entertain", True),
    ("basic_black_tide_tech", True),
    ("basic_entertain_single", True),
    ("basic_mobile_entertain_single", True),
    ("basic_exbar_tech", True),
    ("valorant_entertain_ng", True),
    ("lol_entertain_aram", True),
    ("steam_play", True),
    ("fun_lovebirds", False),
    ("basic_trial_500", False),
    ("farm_season_3x3_normal", False),
])
def test_real_hourly_rule_eligibility(key, expected):
    assert clock.eligible_hourly_rule(key) is expected


def test_admin_created_fun_named_hourly_item_not_eligible(monkeypatch):
    monkeypatch.setattr(
        clock, "get_rule",
        lambda _key: SimpleNamespace(
            category="delta_desktop_basic",
            pricing_type="hourly",
            key="admin_fun_price",
            catalog_group_label="趣味單",
        ),
    )
    assert not clock.eligible_hourly_rule("admin_fun_price")
    monkeypatch.setattr(
        clock, "get_rule",
        lambda _key: SimpleNamespace(
            category="delta_desktop_fun", pricing_type="hourly", key="fun_test",
        ),
    )
    assert not clock.eligible_hourly_rule("fun_test")


def test_non_hourly_snapshot_does_not_become_timer_on_repriced_rule():
    assert not clock.eligible_hourly_rule(
        "basic_black_tide_tech", '{"pricing_type":"fixed"}',
    )
    assert clock.eligible_hourly_rule(
        "basic_black_tide_tech", '{"rule":{"pricing_type":"hourly"}}',
    )


def test_delta_ticket_timekeeping_is_worker_only_and_preserves_accounting(
    tmp_path, monkeypatch,
):
    path = tmp_path / "web_dashboard.db"
    monkeypatch.setattr(clock, "DATABASE", path)
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE web_orders(
                id INTEGER PRIMARY KEY, status TEXT, ticket_channel_id TEXT,
                item TEXT, quantity INTEGER, order_rule_key TEXT,
                rule_snapshot_json TEXT, amount INTEGER
            );
            CREATE TABLE order_assignments (
                order_id INTEGER, worker_discord_id TEXT, is_active INTEGER
            );
            INSERT INTO web_orders VALUES
                (1, 'active', '20001', '黑潮爆破｜技術陪', 2,
                 'basic_black_tide_tech', NULL, 1700),
                (2, 'active', '20002', '趣味單', 1, 'fun_lovebirds', NULL, 2000);
            INSERT INTO order_assignments VALUES (1, '12345', 1);
        """)
    clock.ensure_tables()
    eligible = clock._eligible_orders()
    assert [item["id"] for item in eligible] == [1]
    assert clock._register_order(eligible[0])
    with pytest.raises(PermissionError):
        clock.change_clock(20001, 67890, "start", now=100)
    session = clock.change_clock(20001, 12345, "start", now=100)
    assert session["state"] == "running"
    assert clock.recorded_seconds(session, now=3700) == 3600
    paused = clock.change_clock(20001, 12345, "pause", now=3700)
    assert clock.recorded_seconds(paused, now=5000) == 3600
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT amount FROM web_orders WHERE id=1"
        ).fetchone()[0] == 1700
        db.execute("UPDATE web_orders SET status='closed' WHERE id=1")
    assert clock._finish_non_active() == [(1, "20001")]
    assert clock._session(20001)["state"] == "finished"


def test_delta_timer_embed_preserves_original_text_and_buttons():
    session = {
        "order_id": 123, "quantity": 2, "state": "paused",
        "elapsed_seconds": 5400, "running_since": None,
    }
    embed = clock.timer_embed(session)
    assert embed.title == "⏱️ 陪玩時數紀錄"
    assert "不會自動修改訂單金額、薪資或 VIP 累積" in embed.description
    assert [field.name for field in embed.fields] == [
        "目前狀態", "累積遊玩時間", "訂購時數",
    ]
    assert embed.fields[1].value == "01:30:00"
    view = clock.SimpleHourlyTimerView("paused")
    labels = [item.label for item in view.children]
    assert labels == ["繼續計時", "暫停"]
    assert view.children[1].disabled
