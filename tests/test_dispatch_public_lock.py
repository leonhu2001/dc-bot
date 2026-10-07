from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from shared import order_acceptance
from shared.order_state import WAITING_ACCEPTANCE


def _setup_waiting_order(monkeypatch, *, specified_staff_ids=()):
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(order_acceptance, "engine", engine)

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                dispatch_message_id TEXT,
                updated_at TEXT
            )
        """))
        conn.execute(
            text("""
                INSERT INTO web_orders(id, status, dispatch_message_id, updated_at)
                VALUES(1, :status, '999', CURRENT_TIMESTAMP)
            """),
            {"status": WAITING_ACCEPTANCE},
        )

    order_acceptance.create_or_update_acceptance_meta(
        order_id=1,
        order_rule_key="test_rule",
        required_staff_count=1,
        min_protector_count=0,
        allowed_role_ids=["100"],
        specified_staff_ids=list(specified_staff_ids),
        status=WAITING_ACCEPTANCE,
    )
    return engine


def test_public_staff_cannot_claim_during_first_minute(monkeypatch):
    _setup_waiting_order(monkeypatch)

    with pytest.raises(ValueError, match="1 分鐘接單保護期"):
        order_acceptance.claim_acceptance_order(
            order_id=1,
            staff_discord_id="A",
            staff_display_name="A",
            staff_role_ids=["100"],
            source="discord",
        )


def test_specified_staff_can_claim_during_first_minute(monkeypatch):
    _setup_waiting_order(monkeypatch, specified_staff_ids=["S"])

    state = order_acceptance.claim_acceptance_order(
        order_id=1,
        staff_discord_id="S",
        staff_display_name="Specified",
        staff_role_ids=["100"],
        source="discord",
    )

    assert state.accepted_count == 1
    assert state.claims[0].staff_discord_id == "S"


def test_public_staff_can_claim_after_first_minute(monkeypatch):
    engine = _setup_waiting_order(monkeypatch)
    unlocked_at = (
        datetime.utcnow()
        - timedelta(seconds=order_acceptance.PUBLIC_ACCEPTANCE_LOCK_SECONDS + 1)
    ).isoformat(timespec="seconds")

    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE order_acceptance_meta
                SET created_at = :created_at
                WHERE order_id = 1
            """),
            {"created_at": unlocked_at},
        )

    state = order_acceptance.claim_acceptance_order(
        order_id=1,
        staff_discord_id="A",
        staff_display_name="A",
        staff_role_ids=["100"],
        source="discord",
    )

    assert state.accepted_count == 1
    assert state.claims[0].staff_discord_id == "A"


def test_public_lock_uses_original_meta_created_at_on_updates(monkeypatch):
    engine = _setup_waiting_order(monkeypatch)
    original_created_at = (
        datetime.utcnow()
        - timedelta(minutes=5)
    ).isoformat(timespec="seconds")

    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE order_acceptance_meta
                SET created_at = :created_at
                WHERE order_id = 1
            """),
            {"created_at": original_created_at},
        )

    # Simulate a resume/rebuild path. The UPSERT updates metadata but must not
    # replace created_at, otherwise an old order would be locked again.
    order_acceptance.create_or_update_acceptance_meta(
        order_id=1,
        order_rule_key="test_rule",
        required_staff_count=1,
        min_protector_count=0,
        allowed_role_ids=["100"],
        specified_staff_ids=[],
        status=WAITING_ACCEPTANCE,
    )

    with engine.begin() as conn:
        persisted_created_at = conn.execute(
            text("SELECT created_at FROM order_acceptance_meta WHERE order_id = 1")
        ).scalar_one()

    assert persisted_created_at == original_created_at
