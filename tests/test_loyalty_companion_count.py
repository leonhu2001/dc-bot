from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text

from services import loyalty_benefits as loyalty
from services.order_rules import ORDER_RULES


def _test_engine(tmp_path: Path):
    db = tmp_path / "loyalty_companion_count.db"
    return create_engine(
        f"sqlite:///{db}",
        connect_args={"check_same_thread": False},
    )


def _insert_coupon(conn, *, coupon_id: int, customer_id: str, rule_key: str) -> None:
    rule = ORDER_RULES[rule_key]
    scope_key = loyalty.loyalty_scope_key(rule_key, 1)
    conn.execute(text("""
        INSERT INTO customer_benefit_coupons (
            id,
            customer_discord_id,
            scope_key,
            rule_key,
            rule_label,
            pricing_type,
            player_count,
            benefit_kind,
            benefit_units,
            status,
            source,
            issued_at,
            expires_at
        ) VALUES (
            :id,
            :customer_id,
            :scope_key,
            :rule_key,
            :rule_label,
            'hourly',
            1,
            'extra_hours',
            0.5,
            'active',
            'loyalty',
            '2026-10-11T00:00:00+08:00',
            '2099-01-01T00:00:00+08:00'
        )
    """), {
        "id": coupon_id,
        "customer_id": customer_id,
        "scope_key": scope_key,
        "rule_key": rule_key,
        "rule_label": rule.label,
    })


def test_single_and_double_companion_rewards_use_distinct_scopes():
    single_scope = loyalty.loyalty_scope_key("basic_entertain_single", 1)
    double_scope = loyalty.loyalty_scope_key("basic_entertain_double", 1)

    assert single_scope != double_scope
    assert "basic_entertain_single" in single_scope
    assert "basic_entertain_double" in double_scope


def test_single_coupon_cannot_be_used_on_double_and_vice_versa(monkeypatch, tmp_path: Path):
    test_engine = _test_engine(tmp_path)
    monkeypatch.setattr(loyalty, "engine", test_engine)
    loyalty.ensure_loyalty_tables(test_engine)

    with test_engine.begin() as conn:
        _insert_coupon(
            conn,
            coupon_id=1,
            customer_id="123",
            rule_key="basic_entertain_single",
        )
        _insert_coupon(
            conn,
            coupon_id=2,
            customer_id="123",
            rule_key="basic_entertain_double",
        )

    single = loyalty.list_applicable_coupons(
        "123",
        rule_key="basic_entertain_single",
        player_count=1,
    )
    double = loyalty.list_applicable_coupons(
        "123",
        rule_key="basic_entertain_double",
        player_count=1,
    )

    assert [row["id"] for row in single] == [1]
    assert [row["id"] for row in double] == [2]
    assert "單陪" in single[0]["title"]
    assert "雙陪" in double[0]["title"]


def test_double_companion_coupon_keeps_double_service_value():
    coupon = {"benefit_kind": "extra_hours", "benefit_units": 0.5}

    single_value = loyalty.calculate_coupon_service_value(
        rule_key="basic_entertain_single",
        player_count=1,
        coupon=coupon,
    )
    double_value = loyalty.calculate_coupon_service_value(
        rule_key="basic_entertain_double",
        player_count=1,
        coupon=coupon,
    )

    assert single_value == 160
    assert double_value == 300
    assert double_value > single_value
