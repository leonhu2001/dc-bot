from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from services import rewards
from services.web_sync.event_store import load_cancelled_order_refs, claim_pending_events


@pytest.fixture
def reward_store():
    customer_rewards: dict[int, dict] = {}
    rewards.configure_reward_storage(customer_rewards)
    yield customer_rewards
    rewards.configure_reward_storage({})


def test_cancelled_cash_paid_order_reverses_vip_spend_points_and_count_once(reward_store):
    user_id = 500001
    member = rewards.get_customer_reward_data(user_id)
    member.update({"total_spent": 6000, "order_count": 3, "point_adjustment": 0})
    order = {
        "customer_id": user_id, "amount": 3750, "total_amount": 3750,
        "reward_counted": True, "reward_excluded": False,
        "reward_amount": 3750, "status": "active",
    }
    result = rewards.reverse_cancelled_order_rewards(order)
    assert result is not None
    assert result["old_amount"] == 3750
    assert result["new_total_spent"] == 2250
    assert result["new_points"] == 22
    assert member["total_spent"] == 2250
    assert member["order_count"] == 2
    assert order["amount"] == 3750  # financial audit history unchanged
    assert order["reward_amount"] == 0
    assert order["reward_cancel_reconciled"] is True
    assert rewards.reverse_cancelled_order_rewards(order) is None
    assert member["total_spent"] == 2250
    assert member["order_count"] == 2


def test_cancelled_unpaid_order_never_deducts_anyone_vip(reward_store):
    member = rewards.get_customer_reward_data(500002)
    member.update({"total_spent": 3750, "order_count": 1})
    order = {"customer_id": 500002, "amount": 3750, "status": "cancelled"}
    assert rewards.reverse_cancelled_order_rewards(order) is None
    assert member["total_spent"] == 3750
    assert member["order_count"] == 1


def test_cancelled_wallet_paid_order_leaves_topup_vip_but_reverses_earned_points(reward_store):
    member = rewards.get_customer_reward_data(500003)
    member.update({
        "total_spent": 3000,
        "order_count": 3,
        "wallet_point_spend_total": 175,
        "point_adjustment": 1,
    })
    order = {
        "customer_id": 500003, "amount": 75, "payment_method": "我的錢包",
        "reward_counted": True, "reward_excluded": True, "reward_amount": 0,
        "wallet_points_counted": True, "wallet_point_amount": 75,
        "wallet_points_awarded": 0,
    }
    result = rewards.reverse_cancelled_order_rewards(order)
    assert result is not None
    assert result["reversed_wallet_spend"] == 75
    assert member["total_spent"] == 3000
    assert member["wallet_point_spend_total"] == 100
    assert member["order_count"] == 2
    assert order["amount"] == 75
    assert rewards.reverse_cancelled_order_rewards(order) is None


def test_cancelled_order_wallet_point_threshold_rollback_uses_cumulative_bucket(reward_store):
    member = rewards.get_customer_reward_data(500004)
    member.update({
        "total_spent": 4000, "order_count": 4,
        "wallet_point_spend_total": 220, "point_adjustment": 2,
    })
    order = {
        "customer_id": 500004, "reward_counted": True,
        "reward_excluded": True, "reward_amount": 0,
        "wallet_points_counted": True, "wallet_point_amount": 120,
    }
    rewards.reverse_cancelled_order_rewards(order)
    assert member["wallet_point_spend_total"] == 100
    assert member["point_adjustment"] == 1
    assert member["points"] == 41


def test_excluded_non_wallet_order_does_not_subtract_completions_never_credited(reward_store):
    user_id = 500010
    member = rewards.get_customer_reward_data(user_id)
    member.update({"total_spent": 3200, "order_count": 2})
    order = {
        "customer_id": user_id, "amount": 450, "item": "幣號",
        "payment_method": "轉帳",
        "reward_counted": True, "reward_excluded": True,
        "reward_amount": 0,
    }
    summary = rewards.reverse_cancelled_order_rewards(order)
    assert summary is not None
    assert member["total_spent"] == 3200
    assert member["order_count"] == 2
    assert rewards.reverse_cancelled_order_rewards(order) is None


def test_cancelled_order_missing_evidence_must_not_guess(reward_store):
    member = rewards.get_customer_reward_data(500005)
    member.update({"total_spent": 2000, "order_count": 2})
    missing_amount = {"customer_id": 500005, "reward_counted": True}
    with pytest.raises(ValueError, match="缺少 VIP 入帳金額"):
        rewards.reverse_cancelled_order_rewards(missing_amount)
    assert member["total_spent"] == 2000
    assert "reward_cancel_reconciled" not in missing_amount
    inconsistent = {
        "customer_id": 500005, "reward_counted": True,
        "reward_amount": 3750,
    }
    with pytest.raises(ValueError, match="高於會員總累積"):
        rewards.reverse_cancelled_order_rewards(inconsistent)
    assert member["total_spent"] == 2000


def test_cancelled_web_state_and_amount_worker_have_status_for_safe_reversal(tmp_path: Path):
    path = tmp_path / "web_dashboard.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE web_orders (
              id INTEGER PRIMARY KEY, ticket_channel_id TEXT,
              customer_discord_id TEXT, bot_order_no TEXT,
              dispatch_channel_id TEXT, dispatch_message_id TEXT,
              category TEXT, item TEXT, quantity INTEGER, amount INTEGER,
              customer_display_name TEXT, status TEXT
            );
            CREATE TABLE sync_events (
              id INTEGER PRIMARY KEY, order_id INTEGER,
              event_type TEXT, retry_count INTEGER NOT NULL DEFAULT 0,
              payload_json TEXT, status TEXT NOT NULL,
              processed_at TEXT, error_message TEXT
            );
            INSERT INTO web_orders VALUES
              (1, '321', '500001', 'MO20261108003', '50', '60',
               '技術陪', '機密', 1, 3750, '大花生', 'cancelled');
            INSERT INTO web_orders VALUES
              (2, '333', '500001', 'MO20261108004', '50', '61',
               '技術陪', '機密', 1, 2000, '大花生', 'active');
            INSERT INTO sync_events VALUES
              (1, 1, 'order_updated', 0,
               '{"sync_kind":"order_amount_correction"}', 'pending', NULL, NULL);
            """
        )
    assert load_cancelled_order_refs(db_file=path) == [
        {"order_id": 1, "ticket_channel_id": "321", "customer_discord_id": "500001"}
    ]
    events = claim_pending_events(db_file=path)
    assert len(events) == 1
    assert events[0]["status"] == "cancelled"


def test_all_cancellation_routes_and_legacy_repair_are_wired():
    bot = Path("bot.py").read_text(encoding="utf-8")
    discord = Path("services/order_dispatch_runtime.py").read_text(encoding="utf-8")
    service = Path("services/order_cancel_vip_reconciliation.py").read_text(encoding="utf-8")
    assert "order_status in {\"cancelled\", \"canceled\"}" in service
    assert "reverse_cancelled_order_rewards(order_data)" in service
    assert "await _repair_existing_cancelled_web_vip_rewards()" in bot
    assert "reverse_cancelled_order_rewards(data)" in discord
    assert 'order_data["reward_cancel_reconciled"]' not in bot  # shared idempotency only


def test_cancellation_event_worker_reverses_paid_reward_and_persists_before_ack(reward_store):
    import asyncio

    from services.order_cancel_vip_reconciliation import process_cancel_aware_amount_event

    member = rewards.get_customer_reward_data(500015)
    member.update({"total_spent": 6000, "order_count": 2})
    order = {
        "customer_id": 500015, "amount": 3750,
        "reward_counted": True, "reward_excluded": False,
        "reward_amount": 3750,
    }
    state = {333: order}
    progress = []
    event = {
        "event_id": 200, "retry_count": 0, "payload_json": "{}",
        "ticket_channel_id": "333", "status": "cancelled",
        "amount": 3750,
    }

    def done(event_id):
        assert order["reward_cancel_reconciled"] is True
        assert progress[-1] == "saved"
        progress.append(("done", event_id))

    def failed(*args):
        raise AssertionError(f"unexpected reconciliation failure: {args}")

    async def process():
        await process_cancel_aware_amount_event(
            event,
            apply_wallet_adjustment=lambda *_: None,
            order_selections=state,
            remember_order=lambda *_: progress.append("remembered"),
            save_data=lambda: progress.append("saved"),
            mark_done=done,
            mark_failed=failed,
            guild=None,
        )

    asyncio.run(process())
    assert member["total_spent"] == 2250
    assert member["order_count"] == 1
    assert order["amount"] == 3750
    assert order["status"] == "cancelled"
    assert progress[-1] == ("done", 200)

    asyncio.run(process())
    assert member["total_spent"] == 2250
    assert member["order_count"] == 1


def test_legacy_cancelled_web_order_uses_saved_reward_evidence_only(reward_store):
    import asyncio

    from services.order_cancel_vip_reconciliation import repair_existing_cancelled_web_vip_rewards

    member = rewards.get_customer_reward_data(500016)
    member.update({"total_spent": 3750, "order_count": 1})
    order = {
        "customer_id": 500016, "reward_counted": True,
        "reward_excluded": False, "reward_amount": 3750,
        "amount": 3750,
    }
    rows = [
        {"order_id": 1, "ticket_channel_id": "1001", "customer_discord_id": "500016"},
        {"order_id": 2, "ticket_channel_id": "1002", "customer_discord_id": "500016"},
    ]
    saved = []
    async def repair():
        return await repair_existing_cancelled_web_vip_rewards(
            order_selections={1001: order, 1002: {"customer_id": 500016, "amount": 500}},
            remember_order=lambda *_: saved.append(True),
            save_data=lambda: None,
            guild=None,
            load_refs=lambda: rows,
        )

    assert asyncio.run(repair()) == 1
    assert member["total_spent"] == 0
    assert member["order_count"] == 0
    assert asyncio.run(repair()) == 0
    assert member["total_spent"] == 0
    assert saved == [True]
