from __future__ import annotations

import json
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


def test_single_double_and_dynamic_companion_counts_share_the_same_scope():
    assert loyalty.loyalty_scope_key("basic_entertain_single", 1) == loyalty.loyalty_scope_key(
        "basic_entertain_double", 2
    )

    scopes = {
        loyalty.loyalty_scope_key("valorant_entertain_ng", players)
        for players in (1, 2, 3, 4)
    }
    assert len(scopes) == 1


def test_different_games_never_share_loyalty_scope():
    valorant = loyalty.loyalty_scope_key("valorant_entertain_ng", 2)
    lol = loyalty.loyalty_scope_key("lol_entertain_ng", 2)
    apex = loyalty.loyalty_scope_key("apex_entertain_platinum", 2)
    assert len({valorant, lol, apex}) == 3


def test_single_and_double_orders_can_use_the_same_family_coupon(monkeypatch, tmp_path: Path):
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

    single = loyalty.list_applicable_coupons(
        "123",
        rule_key="basic_entertain_single",
        player_count=1,
    )
    double = loyalty.list_applicable_coupons(
        "123",
        rule_key="basic_entertain_double",
        player_count=2,
    )

    assert [row["id"] for row in single] == [1]
    assert [row["id"] for row in double] == [1]
    assert "單陪" not in single[0]["title"]
    assert "雙陪" not in double[0]["title"]
    assert "折抵" in single[0]["title"]


def test_coupon_value_is_one_companion_service_unit_not_whole_multi_order():
    coupon = {"benefit_kind": "extra_hours", "benefit_units": 0.5}

    single_value = loyalty.calculate_coupon_service_value(
        rule_key="basic_entertain_single",
        player_count=1,
        coupon=coupon,
    )
    double_value = loyalty.calculate_coupon_service_value(
        rule_key="basic_entertain_double",
        player_count=2,
        coupon=coupon,
    )
    valorant_four_value = loyalty.calculate_coupon_service_value(
        rule_key="valorant_entertain_ng",
        player_count=4,
        coupon=coupon,
    )

    assert single_value == 160
    assert double_value == 150
    assert valorant_four_value == 150


def test_existing_processed_progress_is_repaired_from_real_companion_units(monkeypatch, tmp_path: Path):
    test_engine = _test_engine(tmp_path)
    monkeypatch.setattr(loyalty, "engine", test_engine)

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

    loyalty.ensure_loyalty_tables(test_engine)

    # Reset only the marker so this fixture can represent a pre-migration DB.
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM loyalty_migrations"))
        old_scope = "valorant_entertain_ng|players:2"
        conn.execute(text("""
            INSERT INTO customer_loyalty_progress (
                customer_discord_id, scope_key, rule_key, rule_label,
                pricing_type, player_count, progress_units, threshold_units,
                benefit_kind, benefit_units, updated_at
            ) VALUES (
                '123', :scope_key, 'valorant_entertain_ng', 'VALORANT｜娛樂陪｜一般',
                'hourly', 2, 6, 10, 'extra_hours', 0.5, '2026-10-11T01:00:00+08:00'
            )
        """), {"scope_key": old_scope})
        for order_id in (1, 2):
            conn.execute(text("""
                INSERT INTO web_orders (
                    id, customer_discord_id, order_rule_key, quantity,
                    amount, original_amount, customer_pay_amount, status,
                    created_at, updated_at, closed_at, price_snapshot_json,
                    ticket_channel_id
                ) VALUES (
                    :id, '123', 'valorant_entertain_ng', 3,
                    1800, 1800, 1800, 'closed',
                    '2026-10-11T01:00:00+08:00',
                    '2026-10-11T02:00:00+08:00',
                    '2026-10-11T02:00:00+08:00',
                    :snapshot, 'ticket'
                )
            """), {
                "id": order_id,
                "snapshot": json.dumps({"input": {"player_count": 2}}),
            })
            conn.execute(text("""
                INSERT INTO loyalty_order_events (
                    order_id, customer_discord_id, scope_key, paid_units,
                    issued_coupon_count, processed_at, note
                ) VALUES (
                    :id, '123', :scope_key, 3, 0,
                    '2026-10-11T02:00:00+08:00', NULL
                )
            """), {"id": order_id, "scope_key": old_scope})

    loyalty.ensure_loyalty_tables(test_engine)
    data = loyalty.list_customer_loyalty("123")

    # 2 orders × 3h × 2 companions = 12 service-hours => one 0.5h coupon + 2h progress.
    assert data["active_count"] == 1
    assert len(data["progress"]) == 1
    assert data["progress"][0]["progress_units"] == 2
    assert "players:" not in data["progress"][0]["scope_key"]

    # The repair is idempotent and must not issue another coupon on the next startup.
    loyalty.ensure_loyalty_tables(test_engine)
    assert loyalty.list_customer_loyalty("123")["active_count"] == 1
