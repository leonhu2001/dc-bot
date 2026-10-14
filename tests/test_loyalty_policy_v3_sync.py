from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text

from services import loyalty_benefits as loyalty


def _engine(monkeypatch, tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'loyalty-v3.db'}",
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


def _rerun_v3(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM loyalty_migrations WHERE migration_key = :key"
        ), {"key": loyalty._LOYALTY_POLICY_V3_MIGRATION_KEY})
        loyalty._repair_entertainment_loyalty_policy_v3(conn)


def test_v3_keeps_entertainment_progress_removes_ineligible_progress_and_grandfathers_coupon(
    monkeypatch, tmp_path: Path
):
    engine = _engine(monkeypatch, tmp_path)
    entertainment_scope = loyalty.loyalty_scope_key("basic_entertain_single")
    tech_scope = loyalty.loyalty_scope_key("basic_exbar_tech")
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO customer_loyalty_progress (
                customer_discord_id, scope_key, rule_key, rule_label,
                pricing_type, player_count, progress_units, debt_units,
                threshold_units, benefit_kind, benefit_units, updated_at
            ) VALUES
                ('owner-a', :ent_scope, 'basic_entertain_single', '娛樂陪',
                 'hourly', 1, 7, 0, 10, 'extra_hours', 0.5, '2026-10-13T10:00:00+08:00'),
                ('owner-a', :tech_scope, 'basic_exbar_tech', '技術陪',
                 'hourly', 1, 4, 0, 10, 'extra_hours', 0.5, '2026-10-13T10:00:00+08:00')
        """), {"ent_scope": entertainment_scope, "tech_scope": tech_scope})
        conn.execute(text("""
            INSERT INTO customer_benefit_coupons (
                customer_discord_id, scope_key, rule_key, rule_label,
                pricing_type, player_count, benefit_kind, benefit_units,
                status, source, issued_at, expires_at
            ) VALUES (
                'owner-a', :tech_scope, 'basic_exbar_tech', '技術陪',
                'hourly', 1, 'extra_hours', 0.5,
                'active', 'loyalty', '2026-10-13T10:00:00+08:00',
                '2027-01-11T10:00:00+08:00'
            )
        """), {"tech_scope": tech_scope})

    _rerun_v3(engine)

    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT rule_key, progress_units, benefit_units
            FROM customer_loyalty_progress
            WHERE customer_discord_id = 'owner-a'
            ORDER BY rule_key
        """)).mappings().all()
    assert [row["rule_key"] for row in rows] == ["basic_entertain_single"]
    assert float(rows[0]["progress_units"]) == 7.0
    assert float(rows[0]["benefit_units"]) == 1.0

    coupons = loyalty.list_applicable_coupons(
        'owner-a', rule_key='basic_exbar_tech', player_count=1
    )
    assert len(coupons) == 1
    assert float(coupons[0]['benefit_units']) == 0.5


def test_v3_blocks_old_ranked_order_but_keeps_post_rollout_order(
    monkeypatch, tmp_path: Path
):
    engine = _engine(monkeypatch, tmp_path)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO web_orders (
                id, customer_discord_id, order_rule_key, quantity,
                amount, original_amount, customer_pay_amount, status,
                created_at, updated_at, closed_at, price_snapshot_json, ticket_channel_id
            ) VALUES
                (1, 'owner-b', 'valorant_entertain_ranked', 3,
                 300, 300, 300, 'closed',
                 '2026-10-13 20:00:00', '2026-10-13 20:00:00',
                 '2026-10-13 20:00:00', '{}', NULL),
                (2, 'owner-b', 'valorant_entertain_ranked', 2,
                 200, 200, 200, 'closed',
                 '2026-10-14 16:00:00', '2026-10-14 16:00:00',
                 '2026-10-14 16:00:00', '{}', NULL)
        """))

    _rerun_v3(engine)

    with engine.begin() as conn:
        old_event = conn.execute(text(
            "SELECT note FROM loyalty_order_events WHERE order_id = 1"
        )).mappings().one()
        assert loyalty._POLICY_V3_NONRETROACTIVE_MARKER in str(old_event['note'])
        post_rollout_event = conn.execute(text(
            "SELECT note FROM loyalty_order_events WHERE order_id = 2"
        )).mappings().first()
        assert post_rollout_event is None

    result = loyalty.process_closed_order(2)
    assert result is not None
    assert result['paid_units'] == 2.0

    with engine.begin() as conn:
        summary = loyalty.reconcile_customer_loyalty_in_connection(conn, 'owner-b')
        assert summary['issued'] == 0
        progress = conn.execute(text("""
            SELECT progress_units
            FROM customer_loyalty_progress
            WHERE customer_discord_id = 'owner-b'
              AND rule_key = 'valorant_entertain_ranked'
        """)).scalar_one()
        old_event_after = conn.execute(text(
            "SELECT note FROM loyalty_order_events WHERE order_id = 1"
        )).mappings().one()
    assert float(progress) == 2.0
    assert loyalty._POLICY_V3_NONRETROACTIVE_MARKER in str(old_event_after['note'])
