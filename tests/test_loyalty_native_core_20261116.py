from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from services import loyalty_benefits as loyalty
from services import loyalty_policy_20261023 as owner_policy


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def loyalty_db(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'loyalty-native.db'}",
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(loyalty, "engine", engine)
    loyalty.ensure_loyalty_tables(engine)
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
        conn.execute(text("""
            INSERT INTO customer_loyalty_progress (
                customer_discord_id, scope_key, rule_key, rule_label,
                pricing_type, player_count, progress_units, debt_units,
                threshold_units, benefit_kind, benefit_units, updated_at
            ) VALUES (
                'owner-native', :scope, 'basic_entertain_single', '娛樂陪',
                'hourly', 1, 8, 0, 10, 'extra_hours', 1,
                '2026-11-15T10:00:00+08:00'
            )
        """), {"scope": loyalty.loyalty_scope_key("basic_entertain_single")})
    return engine


@pytest.mark.parametrize("order_status,expected", [
    ("paid", True),
    ("active", True),
    ("stored", True),
    ("waiting_acceptance", False),
])
def test_native_loyalty_preview_includes_paid_open_orders_but_not_unpaid(
    loyalty_db, order_status, expected,
):
    with loyalty_db.begin() as conn:
        conn.execute(text("""
            INSERT INTO web_orders (
                id, customer_discord_id, order_rule_key, quantity, amount,
                original_amount, customer_pay_amount, status, created_at,
                updated_at, closed_at, price_snapshot_json, ticket_channel_id
            ) VALUES (
                101, 'owner-native', 'basic_entertain_single', 1, 320,
                320, 320, :status, '2026-11-15T10:00:00+08:00',
                '2026-11-15T10:00:00+08:00', NULL, '{}', NULL
            )
        """), {"status": order_status})

    reward = loyalty.preview_same_order_benefit(
        "owner-native",
        rule_key="basic_entertain_single",
        quantity=1,
        player_count=1,
    )
    assert (reward is not None) is expected
    if expected:
        assert reward["earned_count"] == 1
        assert reward["benefit_units"] == 1


def test_native_loyalty_preview_limits_one_coupon_per_order(loyalty_db):
    with loyalty_db.begin() as conn:
        conn.execute(text("""
            UPDATE customer_loyalty_progress
            SET progress_units=29
            WHERE customer_discord_id='owner-native'
        """))

    reward = loyalty.preview_same_order_benefit(
        "owner-native",
        rule_key="basic_entertain_single",
        quantity=2,
    )
    assert reward is not None
    assert reward["earned_count"] == 1
    assert reward["benefit_units"] == 1


def test_native_entertainment_thresholds_and_existing_migrations_stay_stable(loyalty_db):
    assert loyalty.HOURLY_THRESHOLD == 10.0
    assert loyalty.GAME_THRESHOLD == 15.0
    assert loyalty.loyalty_policy_for_rule("valorant_entertain_ranked")["threshold_units"] == 15.0

    def migrations():
        with loyalty_db.begin() as conn:
            return sorted(conn.execute(
                text("SELECT migration_key FROM loyalty_migrations")
            ).scalars().all())

    before = migrations()
    loyalty.ensure_loyalty_tables(loyalty_db)
    after = migrations()
    assert before == after
    assert owner_policy._MIGRATION_KEY in after
    assert owner_policy._FULL_RECONCILE_MIGRATION_KEY in after


def test_loyalty_owner_patch_installer_no_longer_rebinds_core_functions():
    startup = (ROOT / "services/__init__.py").read_text(encoding="utf-8")
    core = (ROOT / "services/loyalty_benefits.py").read_text(encoding="utf-8")
    owner = (ROOT / "services/loyalty_policy_20261023.py").read_text(encoding="utf-8")

    assert "install_loyalty_policy_20261023" not in startup
    assert "loyalty.ensure_loyalty_tables =" not in owner
    assert "loyalty.preview_same_order_benefit =" not in owner
    assert "_sync_existing_game_progress(loyalty, bind)" in core
    assert "_sync_all_entertainment_progress(loyalty, bind)" in core
    assert "_open_paid_units_for_scope(" in core
    assert '"earned_count": 1' in core
