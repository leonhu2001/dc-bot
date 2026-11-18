"""Internal employee wash/AW must not award VIP, with a reversible history repair."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.vip_levels import BASE_MEMBER_LEVELS
from services import rewards, wallet_spend_rewards
from services.internal_non_vip_policy import (
    INTERNAL_NO_VIP_RULE_KEYS,
    is_internal_non_vip_order,
)
from scripts import repair_internal_staff_vip_20261119 as history


def _order(*, user=42, category="staff_internal", key="staff_internal_ammo_dump_100m",
           counted=True, amount=550, wallet=0, **kwargs):
    return {
        "category": category, "order_rule_key": key, "customer_id": user,
        "payment_method": "銀行轉帳",
        "reward_counted": counted, "reward_amount": amount,
        "reward_excluded": False, "wallet_points_counted": bool(wallet),
        "wallet_point_amount": wallet, "amount": amount,
        **kwargs,
    }


def _row(channel, order):
    return {
        "channel_id": channel, "category": order["category"],
        "customer_id": order["customer_id"],
        "data_json": json.dumps(order, ensure_ascii=False),
    }


def _customer(user=42, total=5000, points=50, wallet=0, **kwargs):
    data = {
        "total_spent": total, "points": points, "wallet_point_spend_total": wallet,
        "vip_level_index": 1, "vip_progress_reset_active": False,
        "point_adjustment": points - total // 100, **kwargs,
    }
    return {
        "customer_id": user, "total_spent": total,
        "points": points, "level": "銀級魔丸",
        "data_json": json.dumps(data, ensure_ascii=False),
    }


def _db(path: Path, orders: list[dict], customers: list[dict]):
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE orders (channel_id INTEGER PRIMARY KEY, category TEXT, "
            "customer_id INTEGER, data_json TEXT, amount INTEGER)"
        )
        db.execute(
            "CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, total_spent INTEGER,"
            " points INTEGER, level TEXT, data_json TEXT)"
        )
        for order in orders:
            d = json.loads(order["data_json"])
            db.execute(
                "INSERT INTO orders VALUES (?, ?, ?, ?, ?)",
                (order["channel_id"], order["category"], order["customer_id"],
                 order["data_json"], d.get("amount", 0)),
            )
        for customer in customers:
            db.execute(
                "INSERT INTO customers VALUES (?, ?, ?, ?, ?)",
                tuple(customer[x] for x in (
                    "customer_id", "total_spent", "points", "level", "data_json"
                )),
            )


@pytest.mark.parametrize("rule_key", sorted(INTERNAL_NO_VIP_RULE_KEYS))
def test_internal_rule_keys_are_excluded_even_from_old_aliased_category(rule_key):
    assert is_internal_non_vip_order({"category": "basic", "order_rule_key": rule_key})
    assert is_internal_non_vip_order({"category": "staff_internal"})


@pytest.mark.parametrize("rule_key", (
    "farm_coin_wash_ammo_dump_500m", "farm_aw_collision_1_100",
    "basic_entertain_single",
))
def test_public_orders_are_not_excluded(rule_key):
    assert not is_internal_non_vip_order({
        "category": "farm", "order_rule_key": rule_key,
    })


@pytest.mark.asyncio
async def test_non_wallet_staff_payment_counts_order_not_vip_or_points(monkeypatch):
    orders = {7: {"category": "staff_internal", "order_rule_key": "staff_internal_aw_collision"}}
    users = {}
    monkeypatch.setattr(rewards, "_ORDER_SELECTIONS", orders)
    monkeypatch.setattr(rewards, "_CUSTOMER_REWARDS", users)
    monkeypatch.setattr(rewards, "_SAVE_BOT_DATA", lambda: None)
    rewards.configure_rewards(member_levels=[dict(x) for x in BASE_MEMBER_LEVELS])
    result = await rewards.add_customer_reward_from_order(None, 7, 42, "3000T")
    assert "不累積 VIP" in result
    assert users[42]["total_spent"] == 0
    assert users[42]["order_count"] == 1
    assert users[42]["points"] == 0
    assert orders[7]["reward_counted"] is True
    assert orders[7]["reward_amount"] == 0
    assert orders[7]["reward_excluded"] is True
    await rewards.add_customer_reward_from_order(None, 7, 42, "3000T")
    assert users[42]["order_count"] == 1
    assert rewards.sync_reward_counted_order_amount(orders[7], 3100) is None
    assert users[42]["total_spent"] == 0


@pytest.mark.asyncio
async def test_wallet_staff_payment_keeps_topup_progress_but_no_spend_points(monkeypatch):
    orders = {7: {
        "category": "staff_internal",
        "order_rule_key": "staff_internal_ammo_dump_200m",
        "payment_method": rewards.WALLET_PAYMENT_METHOD,
        "amount": 1220,
    }}
    users = {42: {"total_spent": 6000, "point_adjustment": 3,
                   "wallet_point_spend_total": 200, "order_count": 2}}
    monkeypatch.setattr(rewards, "_ORDER_SELECTIONS", orders)
    monkeypatch.setattr(rewards, "_CUSTOMER_REWARDS", users)
    monkeypatch.setattr(rewards, "_SAVE_BOT_DATA", lambda: None)
    rewards.configure_rewards(member_levels=[dict(x) for x in BASE_MEMBER_LEVELS])
    result = await wallet_spend_rewards._wallet_aware_add_customer_reward_from_order(
        None, 7, 42, "1220"
    )
    assert "不累積 VIP" in result
    assert users[42]["total_spent"] == 6000
    assert users[42]["wallet_point_spend_total"] == 200
    assert users[42]["point_adjustment"] == 3
    assert users[42]["order_count"] == 3
    assert orders[7]["wallet_points_counted"] is True
    assert orders[7]["wallet_point_amount"] == 0


def test_history_plan_excludes_only_proven_internal_rewards():
    orders = [
        _row(11, _order(amount=550)),
        _row(12, _order(key="staff_internal_aw_collision", amount=0, wallet=220)),
        _row(13, _order(category="farm", key="farm_coin_wash_car_500m", amount=5000)),
    ]
    plan = history.build_plan(orders, [_customer(total=7500, points=81, wallet=1000)])
    assert len(plan["candidates"]) == 2
    assert plan["blockers"] == []
    change = plan["changes"][0]
    assert change["before"] == 7500
    assert change["after"] == 6950
    assert change["new_data"]["wallet_point_spend_total"] == 780
    assert change["after_points"] == 72  # -6 VIP base, -3 wallet spending
    assert change["new_data"]["point_adjustment"] == 3
    assert change["level_after"] == "金級魔丸"


def test_history_plan_blocks_missing_receipt_or_amount_larger_than_vip_total():
    missing = _order()
    missing.pop("reward_amount")
    plan = history.build_plan([_row(15, missing)], [_customer()])
    assert plan["blockers"]
    plan = history.build_plan([_row(15, _order(amount=6000))], [_customer(total=3000)])
    assert plan["blockers"]


def test_history_repair_is_atomic_idempotent_and_preserves_order_amount(tmp_path, monkeypatch):
    path = tmp_path / "bot.db"
    internal = _order(amount=550)
    public = _order(category="farm", key="farm_coin_wash_car_500m", amount=5000)
    _db(path, [_row(11, internal), _row(12, public)],
        [_customer(total=8000, points=80), _customer(user=99, total=12000, points=120)])
    monkeypatch.setattr(history, "_services_stopped", lambda: True)
    preview = history.repair(path)
    assert len(preview["candidates"]) == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT total_spent FROM customers WHERE customer_id=42").fetchone()[0] == 8000

    history.repair(path, apply=True)
    with sqlite3.connect(path) as db:
        c = db.execute("SELECT total_spent, points FROM customers WHERE customer_id=42").fetchone()
        assert c == (7450, 74)
        assert db.execute("SELECT total_spent FROM customers WHERE customer_id=99").fetchone()[0] == 12000
        assert db.execute("SELECT amount FROM orders WHERE channel_id=11").fetchone()[0] == 550
        data = json.loads(db.execute("SELECT data_json FROM orders WHERE channel_id=11").fetchone()[0])
        assert data["reward_excluded"] is True and data["reward_amount"] == 0
        assert data["vip_internal_exclusion_reversed_amount"] == 550
        other = json.loads(db.execute("SELECT data_json FROM orders WHERE channel_id=12").fetchone()[0])
        assert other["reward_amount"] == 5000
    assert list((tmp_path / "_archive").glob("staff_internal_vip_*/bot.db"))
    assert not history.repair(path, apply=True)["candidates"]


def test_vip_monthly_maintenance_excludes_staff_internal_rows(tmp_path, monkeypatch):
    db_file = tmp_path / "bot.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE orders (customer_id INTEGER, amount INTEGER, status TEXT,"
                     " closed_at TEXT, category TEXT, data_json TEXT)")
        now = "2026-11-10T12:00:00+08:00"
        conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?)", [
            (42, 3000, "closed", now, "staff_internal",
             json.dumps({"order_rule_key": "staff_internal_aw_collision"})),
            (42, 600, "closed", now, "farm",
             json.dumps({"order_rule_key": "farm_coin_wash_car_500m"})),
        ])
    monkeypatch.setattr(rewards, "init_database", lambda: None)
    monkeypatch.setattr(rewards, "_REWARD_DB_FILE", db_file)
    start = datetime(2026, 11, 1, tzinfo=timezone(timedelta(hours=8)))
    end = datetime(2026, 12, 1, tzinfo=timezone(timedelta(hours=8)))
    assert rewards.get_customer_closed_spend_between(42, start, end) == 600
