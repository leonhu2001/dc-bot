from __future__ import annotations

import json
import sqlite3

import pytest

from services.payout_policy_migration import (
    LEGACY_POLICY,
    freeze_existing_orders_on_legacy_cs_policy,
)
from shared.payout import (
    calculate_customer_service_payout_base_amount,
    calculate_order_payout,
)


def _snapshot(finance: dict | None = None) -> str:
    return json.dumps({"preview": {"finance": finance or {}}}, ensure_ascii=False)


def test_migration_tags_only_orders_existing_at_first_run(tmp_path):
    db_path = tmp_path / "web.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE web_orders (id INTEGER PRIMARY KEY, price_snapshot_json TEXT)"
        )
        conn.execute(
            "INSERT INTO web_orders (id, price_snapshot_json) VALUES (1, ?)",
            (_snapshot({"payout_base_amount": 1000}),),
        )
        conn.commit()

    assert freeze_existing_orders_on_legacy_cs_policy(db_path) == 1

    with sqlite3.connect(db_path) as conn:
        old_snapshot = json.loads(
            conn.execute(
                "SELECT price_snapshot_json FROM web_orders WHERE id=1"
            ).fetchone()[0]
        )
        assert (
            old_snapshot["preview"]["finance"]["customer_service_payout_policy"]
            == LEGACY_POLICY
        )

        # Simulate an order created after deployment.
        conn.execute(
            "INSERT INTO web_orders (id, price_snapshot_json) VALUES (2, ?)",
            (_snapshot({"payout_base_amount": 1000}),),
        )
        conn.commit()

    # Idempotent restart: new orders must not be reclassified as legacy.
    assert freeze_existing_orders_on_legacy_cs_policy(db_path) == 0
    with sqlite3.connect(db_path) as conn:
        new_snapshot = json.loads(
            conn.execute(
                "SELECT price_snapshot_json FROM web_orders WHERE id=2"
            ).fetchone()[0]
        )
        assert "customer_service_payout_policy" not in new_snapshot["preview"]["finance"]


def test_legacy_tag_survives_normal_recalculation_path():
    base = calculate_customer_service_payout_base_amount(
        payout_base_amount=1000,
        price_snapshot_json=_snapshot(
            {
                "customer_service_payout_policy": LEGACY_POLICY,
            }
        ),
    )
    payout = calculate_order_payout(
        total_amount=1000,
        worker_discord_ids=["worker"],
        named_bonus_worker_ids=["worker"],
        customer_service_total_amount=base,
    )
    # Historical orders keep both pieces of the pre-change settlement policy:
    # named +5% and CS gross 5%.
    assert payout.worker_payouts[0].final_payout == pytest.approx(850)
    assert payout.worker_payouts[0].named_bonus_rate == pytest.approx(0.05)
    assert payout.named_bonus_rate == pytest.approx(0.05)
    assert payout.customer_service_payout == pytest.approx(50)
    assert payout.customer_service_rate == pytest.approx(0.05)


def test_new_order_uses_margin_pool_policy():
    base = calculate_customer_service_payout_base_amount(
        payout_base_amount=1000,
        price_snapshot_json=_snapshot({}),
    )
    payout = calculate_order_payout(
        total_amount=1000,
        worker_discord_ids=["worker"],
        named_bonus_worker_ids=["worker"],
        customer_service_total_amount=base,
    )
    # New named policy is +3%; CS receives 25% of the remaining 17% margin.
    assert payout.worker_payouts[0].final_payout == pytest.approx(830)
    assert payout.worker_payouts[0].named_bonus_rate == pytest.approx(0.03)
    assert payout.customer_service_payout == pytest.approx(42.5)
    assert payout.customer_service_rate == pytest.approx(0.0425)
