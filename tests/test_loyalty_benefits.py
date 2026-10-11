from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text

from services import loyalty_benefits as loyalty
from services.order_rules import ORDER_RULES, get_service_quantity


def test_same_order_five_for_one_is_disabled():
    assert get_service_quantity(ORDER_RULES["basic_entertain_single"], 5) == 5
    assert ORDER_RULES["basic_entertain_single"].loyalty_benefits_enabled is True


def test_old_valorant_rules_are_removed():
    assert "valorant_entertain" not in ORDER_RULES
    assert "valorant_tech" not in ORDER_RULES
    assert "valorant_top_tech" not in ORDER_RULES


def test_zero_progress_is_not_listed(monkeypatch, tmp_path: Path):
    db = tmp_path / "loyalty.db"
    test_engine = create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(loyalty, "engine", test_engine)
    loyalty.ensure_loyalty_tables(test_engine)
    assert loyalty.list_customer_loyalty("1")["progress"] == []


def test_coupon_value_uses_normal_list_price_not_vip_discount():
    coupon = {"benefit_kind": "extra_hours", "benefit_units": 0.5}
    value = loyalty.calculate_coupon_service_value(
        rule_key="basic_entertain_single",
        player_count=1,
        coupon=coupon,
    )
    assert value == 160


def _setup_reconcile_db(monkeypatch, tmp_path: Path):
    db = tmp_path / "loyalty-reconcile.db"
    test_engine = create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(loyalty, "engine", test_engine)
    loyalty.ensure_loyalty_tables(test_engine)
    with test_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                customer_discord_id TEXT,
                order_rule_key TEXT,
                quantity INTEGER,
                amount INTEGER,
                original_amount INTEGER,
                customer_pay_amount INTEGER,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
                closed_at TEXT,
                price_snapshot_json TEXT,
                ticket_channel_id TEXT
            )
        """))
    return test_engine


def _insert_closed_order(engine, order_id: int, customer: str, quantity: int):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO web_orders (
                id, customer_discord_id, order_rule_key, quantity,
                amount, original_amount, customer_pay_amount, status,
                created_at, updated_at, closed_at, price_snapshot_json
            ) VALUES (
                :id, :customer, 'basic_entertain_single', :quantity,
                1000, 1000, 1000, 'closed',
                '2026-10-11 10:00:00', '2026-10-11 10:00:00',
                '2026-10-11 10:00:00', '{}'
            )
        """), {"id": order_id, "customer": customer, "quantity": quantity})


def test_reconcile_closed_order_quantity_increase_updates_progress_and_rewards(monkeypatch, tmp_path: Path):
    engine = _setup_reconcile_db(monkeypatch, tmp_path)
    _insert_closed_order(engine, 1, "owner-a", 4)
    loyalty.process_closed_order(1)

    with engine.begin() as conn:
        conn.execute(text("UPDATE web_orders SET quantity = 12 WHERE id = 1"))
        result = loyalty.reconcile_loyalty_after_order_edit_in_connection(
            conn, order_id=1, previous_customer_id="owner-a"
        )
        progress = conn.execute(text("""
            SELECT progress_units, debt_units
            FROM customer_loyalty_progress
            WHERE customer_discord_id = 'owner-a'
        """)).mappings().one()
        active = conn.execute(text("""
            SELECT COUNT(*) FROM customer_benefit_coupons
            WHERE customer_discord_id = 'owner-a' AND status = 'active'
        """)).scalar_one()
        paid_units = conn.execute(text(
            "SELECT paid_units FROM loyalty_order_events WHERE order_id = 1"
        )).scalar_one()

    assert result["issued"] == 1
    assert float(progress["progress_units"]) == 2.0
    assert float(progress["debt_units"]) == 0.0
    assert active == 1
    assert float(paid_units) == 12.0


def test_reconcile_closed_order_quantity_decrease_revokes_unused_reward(monkeypatch, tmp_path: Path):
    engine = _setup_reconcile_db(monkeypatch, tmp_path)
    _insert_closed_order(engine, 1, "owner-a", 12)
    loyalty.process_closed_order(1)

    with engine.begin() as conn:
        conn.execute(text("UPDATE web_orders SET quantity = 4 WHERE id = 1"))
        result = loyalty.reconcile_loyalty_after_order_edit_in_connection(
            conn, order_id=1, previous_customer_id="owner-a"
        )
        statuses = [row[0] for row in conn.execute(text("""
            SELECT status FROM customer_benefit_coupons
            WHERE customer_discord_id = 'owner-a'
            ORDER BY id
        """)).fetchall()]
        progress = conn.execute(text("""
            SELECT progress_units, debt_units
            FROM customer_loyalty_progress
            WHERE customer_discord_id = 'owner-a'
        """)).mappings().one()

    assert result["revoked"] == 1
    assert statuses == ["revoked"]
    assert float(progress["progress_units"]) == 4.0
    assert float(progress["debt_units"]) == 0.0


def test_reconcile_keeps_redeemed_reward_and_future_units_pay_debt_first(monkeypatch, tmp_path: Path):
    engine = _setup_reconcile_db(monkeypatch, tmp_path)
    _insert_closed_order(engine, 1, "owner-a", 12)
    loyalty.process_closed_order(1)

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE customer_benefit_coupons
            SET status = 'redeemed', redeemed_order_id = 999,
                redeemed_at = '2026-10-11T12:00:00+08:00'
            WHERE customer_discord_id = 'owner-a'
        """))
        conn.execute(text("UPDATE web_orders SET quantity = 4 WHERE id = 1"))
        loyalty.reconcile_loyalty_after_order_edit_in_connection(
            conn, order_id=1, previous_customer_id="owner-a"
        )
        progress = conn.execute(text("""
            SELECT progress_units, debt_units
            FROM customer_loyalty_progress
            WHERE customer_discord_id = 'owner-a'
        """)).mappings().one()
        redeemed = conn.execute(text("""
            SELECT COUNT(*) FROM customer_benefit_coupons
            WHERE customer_discord_id = 'owner-a' AND status = 'redeemed'
        """)).scalar_one()

    assert redeemed == 1
    assert float(progress["progress_units"]) == 0.0
    assert float(progress["debt_units"]) == 6.0

    _insert_closed_order(engine, 2, "owner-a", 8)
    loyalty.process_closed_order(2)
    with engine.begin() as conn:
        progress = conn.execute(text("""
            SELECT progress_units, debt_units
            FROM customer_loyalty_progress
            WHERE customer_discord_id = 'owner-a'
        """)).mappings().one()
        active = conn.execute(text("""
            SELECT COUNT(*) FROM customer_benefit_coupons
            WHERE customer_discord_id = 'owner-a' AND status = 'active'
        """)).scalar_one()
    assert float(progress["debt_units"]) == 0.0
    assert float(progress["progress_units"]) == 2.0
    assert active == 0

    _insert_closed_order(engine, 3, "owner-a", 8)
    loyalty.process_closed_order(3)
    with engine.begin() as conn:
        active = conn.execute(text("""
            SELECT COUNT(*) FROM customer_benefit_coupons
            WHERE customer_discord_id = 'owner-a' AND status = 'active'
        """)).scalar_one()
    assert active == 1


def test_reconcile_customer_move_rebuilds_old_and_new_owner_pools(monkeypatch, tmp_path: Path):
    engine = _setup_reconcile_db(monkeypatch, tmp_path)
    _insert_closed_order(engine, 1, "owner-a", 5)
    loyalty.process_closed_order(1)

    with engine.begin() as conn:
        conn.execute(text("UPDATE web_orders SET customer_discord_id = 'owner-b' WHERE id = 1"))
        loyalty.reconcile_loyalty_after_order_edit_in_connection(
            conn, order_id=1, previous_customer_id="owner-a"
        )
        old_progress = conn.execute(text("""
            SELECT COUNT(*) FROM customer_loyalty_progress
            WHERE customer_discord_id = 'owner-a'
        """)).scalar_one()
        new_progress = conn.execute(text("""
            SELECT progress_units FROM customer_loyalty_progress
            WHERE customer_discord_id = 'owner-b'
        """)).scalar_one()
        event_owner = conn.execute(text(
            "SELECT customer_discord_id FROM loyalty_order_events WHERE order_id = 1"
        )).scalar_one()

    assert old_progress == 0
    assert float(new_progress) == 5.0
    assert event_owner == "owner-b"
