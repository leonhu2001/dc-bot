from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from services.loyalty_companion_fix_20261029 import (
    _repair_existing_progress,
    calculate_for_rule,
    extract_player_count,
)


def _rule(key: str, *, price: int, max_players: int = 4):
    return SimpleNamespace(
        key=key,
        price=price,
        required_staff_count="player_count",
        player_count_enabled=True,
        min_player_count=1,
        max_player_count=max_players,
        price_multiply_player_count=False,
    )


@pytest.mark.parametrize(
    ("rule_key", "base_price", "players", "expected"),
    [
        ("basic_entertain_single", 320, 1, 320),
        ("basic_entertain_single", 320, 2, 300),
        ("basic_entertain_female_single", 320, 2, 300),
        ("basic_entertain_male_single", 320, 2, 300),
        ("basic_mobile_entertain_single", 320, 2, 300),
        ("basic_mobile_entertain_female_single", 320, 2, 300),
        ("basic_mobile_entertain_male_single", 320, 2, 300),
        ("basic_black_tide_entertain", 320, 2, 300),
        ("basic_black_tide_entertain", 320, 3, 300),
        ("basic_black_tide_entertain", 320, 4, 300),
        ("basic_black_tide_tech", 400, 2, 380),
        ("basic_black_tide_tech", 400, 3, 380),
        ("basic_black_tide_tech", 400, 4, 380),
        ("steam_play", 320, 2, 320),
        ("steam_play", 320, 3, 320),
        ("steam_play", 320, 4, 320),
    ],
)
def test_loyalty_reward_uses_selected_tier_per_companion_share(
    rule_key: str, base_price: int, players: int, expected: int
):
    coupon = {"benefit_kind": "extra_hours", "benefit_units": 1}
    assert calculate_for_rule(
        _rule(rule_key, price=base_price), player_count=players, coupon=coupon
    ) == expected


def test_double_companion_half_hour_is_150():
    coupon = {"benefit_kind": "extra_hours", "benefit_units": 0.5}
    assert calculate_for_rule(
        _rule("basic_entertain_single", price=320, max_players=2),
        player_count=2,
        coupon=coupon,
    ) == 150


def test_linear_multi_seat_price_keeps_one_companion_share():
    rule = SimpleNamespace(
        key="linear_test",
        price=450,
        required_staff_count="player_count",
        player_count_enabled=True,
        min_player_count=1,
        max_player_count=4,
        price_multiply_player_count=True,
    )
    coupon = {"benefit_kind": "extra_hours", "benefit_units": 1}
    assert calculate_for_rule(rule, player_count=3, coupon=coupon) == 450


@pytest.mark.parametrize(
    "snapshot",
    [
        {"preview": {"quote": {"player_count": 2}}},
        {"input": {"player_count": 2}},
        {"preview": {"selection": {"requested_player_count": 2}}},
        {"order": {"service_player_count": 2}},
        {"data": {"companion_count": 2}},
    ],
)
def test_extract_player_count_supports_old_and_new_snapshots(snapshot):
    row = {"price_snapshot_json": json.dumps(snapshot, ensure_ascii=False)}
    assert extract_player_count(row) == 2


def test_extract_player_count_falls_back_to_one():
    assert extract_player_count({"price_snapshot_json": "{}"}) == 1


def test_loyalty_repair_is_claimed_once_during_concurrent_startup(tmp_path):
    db_path = tmp_path / "loyalty-race.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE loyalty_migrations (
                migration_key TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL,
                note TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE web_orders (
                customer_discord_id TEXT,
                order_rule_key TEXT,
                status TEXT
            )
        """))
        conn.execute(text("""
            INSERT INTO web_orders (customer_discord_id, order_rule_key, status)
            VALUES ('customer-a', 'basic_entertain_single', 'closed'),
                   ('customer-b', 'basic_entertain_single', 'closed')
        """))

    reconcile_calls: list[str] = []
    calls_lock = threading.Lock()
    start = threading.Barrier(2)

    def reconcile(_conn, customer_id: str):
        with calls_lock:
            reconcile_calls.append(customer_id)
        return {"issued": 1, "revoked": 0}

    loyalty = SimpleNamespace(
        engine=engine,
        ensure_loyalty_tables=lambda: None,
        get_taipei_now_iso=lambda: "2026-10-29T23:00:00+08:00",
        loyalty_policy_for_rule=lambda _key: {"enabled": True},
        reconcile_customer_loyalty_in_connection=reconcile,
    )

    def run_repair():
        start.wait(timeout=5)
        return _repair_existing_progress(loyalty)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: run_repair(), range(2)))

    assert sorted(result["customers"] for result in results) == [0, 2]
    assert sorted(result["issued"] for result in results) == [0, 2]
    assert sorted(reconcile_calls) == ["customer-a", "customer-b"]

    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT note FROM loyalty_migrations
            WHERE migration_key = '20261029_loyalty_companion_price_and_units_v5'
        """)).one()
    assert row[0] == "reconciled_customers=2;issued=2;revoked=0"
