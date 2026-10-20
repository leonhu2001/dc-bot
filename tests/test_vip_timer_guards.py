from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import services.vip_timer as vip_timer
import services.vip_timer_catalog_guard as catalog_guard
import services.vip_timer_lifecycle as lifecycle


@pytest.fixture()
def lifecycle_env(tmp_path, monkeypatch):
    db_path = tmp_path / "vip-timer-lifecycle.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    monkeypatch.setattr(vip_timer, "SessionLocal", local)
    monkeypatch.setattr(lifecycle, "SessionLocal", local)

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL
            )
        """))
        conn.execute(text("INSERT INTO web_orders(id, status) VALUES (1, 'cancelled')"))
        conn.execute(text("INSERT INTO web_orders(id, status) VALUES (2, 'closed')"))

    vip_timer.ensure_vip_timer_tables()

    with engine.begin() as conn:
        for order_id, customer_id, status in (
            (1, "customer-a", "running"),
            (2, "customer-b", "pending_payment"),
        ):
            conn.execute(
                text("""
                    INSERT INTO vip_timer_sessions (
                        order_id,
                        customer_discord_id,
                        status,
                        current_rule_key,
                        current_rule_label,
                        current_category_label,
                        current_hourly_rate,
                        final_amount,
                        created_at,
                        updated_at
                    ) VALUES (
                        :order_id,
                        :customer_id,
                        :status,
                        'rule',
                        '測試玩法',
                        '測試分類',
                        300,
                        0,
                        '2026-01-01T00:00:00+00:00',
                        '2026-01-01T00:00:00+00:00'
                    )
                """),
                {
                    "order_id": order_id,
                    "customer_id": customer_id,
                    "status": status,
                },
            )

    return SimpleNamespace(engine=engine, SessionLocal=local)


def test_cancelled_timer_session_is_released(lifecycle_env):
    lifecycle._sync_terminal_session(1, "cancelled")

    with lifecycle_env.engine.begin() as conn:
        status = conn.execute(
            text("SELECT status FROM vip_timer_sessions WHERE order_id = 1")
        ).scalar_one()

    assert status == "cancelled"
    assert vip_timer.has_open_vip_timer("customer-a") is False


def test_paid_timer_session_is_reconciled(lifecycle_env):
    lifecycle._sync_terminal_session(2, "closed")

    with lifecycle_env.engine.begin() as conn:
        status = conn.execute(
            text("SELECT status FROM vip_timer_sessions WHERE order_id = 2")
        ).scalar_one()

    assert status == "paid"
    assert vip_timer.has_open_vip_timer("customer-b") is False


def test_terminal_order_rejects_old_timer_component(lifecycle_env):
    with pytest.raises(ValueError, match="已取消"):
        lifecycle._assert_order_open(1)


def test_timer_catalog_excludes_hidden_legacy_and_minimum_hour_rules(monkeypatch):
    from services import order_product_status, order_rules, orders

    class FakeRules(dict):
        def is_custom(self, key):
            return str(key) == "custom_hourly"

    def rule(*, price=300, min_quantity=1, pricing_type="hourly"):
        return SimpleNamespace(
            pricing_type=pricing_type,
            price=price,
            min_quantity=min_quantity,
        )

    rules = FakeRules({
        "valid_hourly": rule(),
        "hidden_hourly": rule(),
        "minimum_three_hours": rule(min_quantity=3),
        "legacy_not_in_catalog": rule(),
        "custom_hourly": rule(price=450),
        "game_priced": rule(pricing_type="game"),
    })

    monkeypatch.setattr(order_rules, "ORDER_RULES", rules)
    monkeypatch.setattr(
        orders,
        "SELF_SERVICE_ORDER_CATALOG",
        {
            "test": [
                {
                    "label": "測試",
                    "details": [
                        {"rule_key": "valid_hourly"},
                        {"rule_key": "hidden_hourly"},
                        {"rule_key": "minimum_three_hours"},
                        {"rule_key": "game_priced"},
                    ],
                }
            ]
        },
    )
    monkeypatch.setattr(orders, "CATALOG_HIDDEN_RULE_KEYS", {"hidden_hourly"})
    monkeypatch.setattr(
        order_product_status,
        "is_order_product_active",
        lambda key: True,
    )

    assert catalog_guard.public_timer_rule_keys() == {
        "valid_hourly",
        "custom_hourly",
    }
