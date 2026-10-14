from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, text

from services import loyalty_benefits as loyalty
from web.app.services.checkout_preview import calculate_checkout_financials


def _setup(monkeypatch, tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'same-order.db'}",
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
                'owner-a', 'delta_desktop_basic|basic_entertain',
                'basic_entertain_single', '娛樂陪〈端遊〉',
                'hourly', 1, 9, 0, 10, 'extra_hours', 1,
                '2026-10-14T10:00:00+08:00'
            )
        """))
    return engine


def test_current_order_can_use_reward_when_it_crosses_threshold(monkeypatch, tmp_path: Path):
    _setup(monkeypatch, tmp_path)
    reward = loyalty.preview_same_order_benefit(
        'owner-a',
        rule_key='basic_entertain_single',
        quantity=1,
        player_count=1,
    )
    assert reward is not None
    assert reward['source'] == 'same_order'
    assert reward['earned_count'] == 1
    assert reward['benefit_units'] == 1.0

    finance = calculate_checkout_financials(
        service_amount=320,
        vip_pay_rate=100,
        specify_fee=0,
        point_item=None,
        wallet_balance=0,
        use_wallet=False,
        benefit_coupon=reward,
        benefit_service_value=320,
    )
    assert finance['benefit_coupon_id'] is None
    assert finance['customer_pay_amount'] == 0
    assert finance['payout_base_amount'] == 320


def test_same_order_reward_is_not_issued_again_on_close(monkeypatch, tmp_path: Path):
    engine = _setup(monkeypatch, tmp_path)
    scope = 'delta_desktop_basic|basic_entertain'
    snapshot = json.dumps({
        'preview': {
            'finance': {
                'service_after_vip': 320,
                'service_amount': 320,
                'subtotal_before_wallet': 0,
            },
            'benefit_coupon': {
                'id': None,
                'source': 'same_order',
                'same_order': True,
                'earned_count': 1,
                'scope_key': scope,
                'benefit_kind': 'extra_hours',
                'benefit_units': 1.0,
            },
        }
    })
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO web_orders (
                id, customer_discord_id, order_rule_key, quantity, amount,
                original_amount, customer_pay_amount, status, created_at,
                updated_at, closed_at, price_snapshot_json, ticket_channel_id
            ) VALUES (
                1, 'owner-a', 'basic_entertain_single', 1, 0, 320, 0,
                'closed', '2026-10-14 10:00:00', '2026-10-14 10:00:00',
                '2026-10-14 10:00:00', :snapshot, NULL
            )
        """), {'snapshot': snapshot})

    result = loyalty.process_closed_order(1)
    assert result is not None
    assert result['issued_coupon_count'] == 0
    with engine.begin() as conn:
        progress = conn.execute(text("""
            SELECT progress_units, debt_units
            FROM customer_loyalty_progress
            WHERE customer_discord_id = 'owner-a'
        """)).mappings().one()
        coupon_count = conn.execute(text("""
            SELECT COUNT(*) FROM customer_benefit_coupons
            WHERE customer_discord_id = 'owner-a'
        """)).scalar_one()
    assert float(progress['progress_units']) == 0.0
    assert float(progress['debt_units']) == 0.0
    assert coupon_count == 0


def test_pending_order_claim_blocks_duplicate_same_order_reward(monkeypatch, tmp_path: Path):
    engine = _setup(monkeypatch, tmp_path)
    scope = 'delta_desktop_basic|basic_entertain'
    snapshot = json.dumps({
        'preview': {
            'benefit_coupon': {
                'source': 'same_order',
                'earned_count': 1,
                'scope_key': scope,
            }
        }
    })
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO web_orders (
                id, customer_discord_id, order_rule_key, quantity, amount,
                original_amount, customer_pay_amount, status, created_at,
                updated_at, closed_at, price_snapshot_json, ticket_channel_id
            ) VALUES (
                2, 'owner-a', 'basic_entertain_single', 1, 0, 320, 0,
                'waiting_acceptance', '2026-10-14 10:00:00',
                '2026-10-14 10:00:00', NULL, :snapshot, NULL
            )
        """), {'snapshot': snapshot})

    assert loyalty.preview_same_order_benefit(
        'owner-a',
        rule_key='basic_entertain_single',
        quantity=1,
        player_count=1,
    ) is None
