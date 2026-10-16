from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, text

from services import loyalty_benefits as loyalty


def _engine(monkeypatch, tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'apex-loyalty.db'}",
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(loyalty, "engine", engine)
    with engine.begin() as conn:
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
    loyalty.ensure_loyalty_tables(engine)
    return engine


def _rerun_apex_v4(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM loyalty_migrations WHERE migration_key = :key"
        ), {"key": loyalty._LOYALTY_APEX_SHARED_SCOPE_MIGRATION_KEY})
        loyalty._repair_apex_entertainment_shared_scope_v4(conn)


def test_apex_entertainment_ng_and_ranked_share_scope_and_label():
    ng_scope = loyalty.loyalty_scope_key("apex_entertain_ng")
    ranked_scope = loyalty.loyalty_scope_key("apex_entertain_ranked")

    assert ng_scope == "apex|apex_entertain"
    assert ranked_scope == ng_scope
    assert loyalty._loyalty_display_label(
        "apex_entertain_ng", "APEX｜娛樂陪｜NG"
    ) == "APEX｜娛樂陪"
    assert loyalty._loyalty_display_label(
        "apex_entertain_ranked", "APEX｜娛樂陪｜積分"
    ) == "APEX｜娛樂陪"


def test_apex_v4_merges_existing_progress_and_coupon(monkeypatch, tmp_path: Path):
    engine = _engine(monkeypatch, tmp_path)

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO web_orders (
                id, customer_discord_id, order_rule_key, quantity,
                amount, original_amount, customer_pay_amount, status,
                created_at, updated_at, closed_at, price_snapshot_json,
                ticket_channel_id
            ) VALUES
                (1, 'owner-a', 'apex_entertain_ng', 6,
                 1800, 1800, 1800, 'closed',
                 '2026-10-15 10:00:00', '2026-10-15 10:00:00',
                 '2026-10-15 10:00:00', '{}', NULL),
                (2, 'owner-a', 'apex_entertain_ranked', 6,
                 2100, 2100, 2100, 'closed',
                 '2026-10-15 12:00:00', '2026-10-15 12:00:00',
                 '2026-10-15 12:00:00', '{}', NULL)
        """))
        conn.execute(text("""
            INSERT INTO customer_loyalty_progress (
                customer_discord_id, scope_key, rule_key, rule_label,
                pricing_type, player_count, progress_units, debt_units,
                threshold_units, benefit_kind, benefit_units, updated_at
            ) VALUES
                ('owner-a', 'apex|apex_entertain_ng',
                 'apex_entertain_ng', 'APEX｜娛樂陪｜NG',
                 'hourly', 1, 6, 0, 10, 'extra_hours', 1,
                 '2026-10-15T10:00:00+08:00'),
                ('owner-a', 'apex|apex_entertain_ranked',
                 'apex_entertain_ranked', 'APEX｜娛樂陪｜積分',
                 'hourly', 1, 6, 0, 10, 'extra_hours', 1,
                 '2026-10-15T12:00:00+08:00')
        """))
        conn.execute(text("""
            INSERT INTO customer_benefit_coupons (
                customer_discord_id, scope_key, rule_key, rule_label,
                pricing_type, player_count, benefit_kind, benefit_units,
                status, source, issued_at, expires_at
            ) VALUES (
                'owner-a', 'apex|apex_entertain_ng',
                'apex_entertain_ng', 'APEX｜娛樂陪｜NG',
                'hourly', 1, 'extra_hours', 1,
                'active', 'loyalty', '2026-10-15T10:00:00+08:00',
                '2027-01-13T10:00:00+08:00'
            )
        """))

    _rerun_apex_v4(engine)

    with engine.begin() as conn:
        progress = conn.execute(text("""
            SELECT scope_key, rule_label, progress_units, debt_units
            FROM customer_loyalty_progress
            WHERE customer_discord_id = 'owner-a'
        """)).mappings().all()
        coupons = conn.execute(text("""
            SELECT id, scope_key, rule_label, status
            FROM customer_benefit_coupons
            WHERE customer_discord_id = 'owner-a'
              AND source = 'loyalty'
            ORDER BY id
        """)).mappings().all()
        events = conn.execute(text("""
            SELECT order_id, scope_key, paid_units
            FROM loyalty_order_events
            WHERE customer_discord_id = 'owner-a'
            ORDER BY order_id
        """)).mappings().all()

    assert len(progress) == 1
    assert progress[0]["scope_key"] == "apex|apex_entertain"
    assert progress[0]["rule_label"] == "APEX｜娛樂陪"
    assert float(progress[0]["progress_units"]) == 2.0
    assert float(progress[0]["debt_units"]) == 0.0

    assert len(coupons) == 1
    assert coupons[0]["scope_key"] == "apex|apex_entertain"
    assert coupons[0]["rule_label"] == "APEX｜娛樂陪"
    assert coupons[0]["status"] == "active"

    assert [row["scope_key"] for row in events] == [
        "apex|apex_entertain",
        "apex|apex_entertain",
    ]
    assert [float(row["paid_units"]) for row in events] == [6.0, 6.0]

    ng_coupons = loyalty.list_applicable_coupons(
        "owner-a", rule_key="apex_entertain_ng"
    )
    ranked_coupons = loyalty.list_applicable_coupons(
        "owner-a", rule_key="apex_entertain_ranked"
    )
    assert [item["id"] for item in ng_coupons] == [coupons[0]["id"]]
    assert [item["id"] for item in ranked_coupons] == [coupons[0]["id"]]


def test_pending_same_order_apex_reward_matches_new_shared_scope():
    old_snapshot = {
        "preview": {
            "benefit_coupon": {
                "source": "same_order",
                "earned_count": 1,
                "scope_key": "apex|apex_entertain_ranked",
                "rule_key": "apex_entertain_ranked",
                "player_count": 1,
            }
        }
    }
    row = {"price_snapshot_json": json.dumps(old_snapshot, ensure_ascii=False)}

    assert loyalty._extract_same_order_benefit_count(
        row,
        scope_key="apex|apex_entertain",
    ) == 1
