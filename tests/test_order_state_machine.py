import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from shared import order_acceptance, web_order_sync
from shared.models import Base, WebOrder
from shared.order_state import (
    ACCEPTED_PENDING_PAY,
    ACTIVE,
    CANCELLED,
    CLOSED,
    PENDING_CS_DISPATCH,
    STORED,
    WAITING_ACCEPTANCE,
    OrderStateTransitionError,
    can_transition_order_status,
    normalize_order_status,
    transition_order_state_in_connection,
)


def _create_order_tables(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                dispatch_message_id TEXT,
                updated_at TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE order_acceptance_meta (
                order_id INTEGER PRIMARY KEY,
                order_rule_key TEXT,
                required_staff_count INTEGER NOT NULL DEFAULT 1,
                min_protector_count INTEGER NOT NULL DEFAULT 0,
                allowed_role_ids_json TEXT,
                specified_staff_ids_json TEXT,
                point_benefits_allowed INTEGER NOT NULL DEFAULT 1,
                rule_version INTEGER,
                rule_snapshot_json TEXT,
                price_snapshot_json TEXT,
                status TEXT NOT NULL DEFAULT 'waiting_acceptance',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))


def test_order_state_aliases_and_terminal_guards():
    assert normalize_order_status("canceled") == CANCELLED
    assert normalize_order_status("completed") == CLOSED
    assert normalize_order_status("done") == CLOSED
    assert normalize_order_status("paid") == ACTIVE
    assert normalize_order_status("created") == PENDING_CS_DISPATCH

    assert can_transition_order_status(PENDING_CS_DISPATCH, WAITING_ACCEPTANCE)
    assert can_transition_order_status(WAITING_ACCEPTANCE, ACCEPTED_PENDING_PAY)
    assert can_transition_order_status(ACCEPTED_PENDING_PAY, ACTIVE)
    assert can_transition_order_status(ACTIVE, STORED)
    assert can_transition_order_status(STORED, ACTIVE)
    assert can_transition_order_status(ACTIVE, CLOSED)

    assert not can_transition_order_status(CLOSED, ACTIVE)
    assert not can_transition_order_status(CANCELLED, WAITING_ACCEPTANCE)


def test_transition_updates_order_acceptance_meta_and_history():
    engine = create_engine("sqlite:///:memory:")
    _create_order_tables(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO web_orders(id, status, updated_at)
                VALUES(1, :status, CURRENT_TIMESTAMP)
                """
            ),
            {"status": WAITING_ACCEPTANCE},
        )
        conn.execute(
            text(
                """
                INSERT INTO order_acceptance_meta(
                    order_id,
                    required_staff_count,
                    min_protector_count,
                    status,
                    created_at,
                    updated_at
                )
                VALUES(1, 1, 0, :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            ),
            {"status": WAITING_ACCEPTANCE},
        )

        result = transition_order_state_in_connection(
            conn,
            order_id=1,
            target_status=ACCEPTED_PENDING_PAY,
            source="test_claim",
            reason="claim full",
            actor_discord_id="123",
            expected_statuses={WAITING_ACCEPTANCE},
        )

        assert result.changed is True
        assert result.from_status == WAITING_ACCEPTANCE
        assert result.to_status == ACCEPTED_PENDING_PAY
        assert result.acceptance_meta_synced is True

        order_status = conn.execute(
            text("SELECT status FROM web_orders WHERE id = 1")
        ).scalar_one()
        meta_status = conn.execute(
            text("SELECT status FROM order_acceptance_meta WHERE order_id = 1")
        ).scalar_one()
        history = conn.execute(
            text(
                """
                SELECT from_status, to_status, source, reason, actor_discord_id
                FROM order_state_history
                WHERE order_id = 1
                """
            )
        ).mappings().one()

    assert order_status == ACCEPTED_PENDING_PAY
    assert meta_status == ACCEPTED_PENDING_PAY
    assert history["from_status"] == WAITING_ACCEPTANCE
    assert history["to_status"] == ACCEPTED_PENDING_PAY
    assert history["source"] == "test_claim"
    assert history["reason"] == "claim full"
    assert history["actor_discord_id"] == "123"


def test_terminal_order_cannot_be_reactivated():
    engine = create_engine("sqlite:///:memory:")
    _create_order_tables(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO web_orders(id, status, updated_at)
                VALUES(1, :status, CURRENT_TIMESTAMP)
                """
            ),
            {"status": CLOSED},
        )

        with pytest.raises(OrderStateTransitionError):
            transition_order_state_in_connection(
                conn,
                order_id=1,
                target_status=ACTIVE,
                source="invalid_reopen",
            )

        current = conn.execute(
            text("SELECT status FROM web_orders WHERE id = 1")
        ).scalar_one()

    assert current == CLOSED


def test_pending_cancel_guard_rejects_order_that_already_has_dispatch_message():
    engine = create_engine("sqlite:///:memory:")
    _create_order_tables(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO web_orders(
                    id,
                    status,
                    dispatch_message_id,
                    updated_at
                )
                VALUES(1, :status, '999999', CURRENT_TIMESTAMP)
                """
            ),
            {"status": PENDING_CS_DISPATCH},
        )

        with pytest.raises(OrderStateTransitionError):
            transition_order_state_in_connection(
                conn,
                order_id=1,
                target_status=CANCELLED,
                source="pending_cancel",
                expected_statuses={PENDING_CS_DISPATCH},
                require_empty_dispatch_message=True,
            )

        current = conn.execute(
            text("SELECT status FROM web_orders WHERE id = 1")
        ).scalar_one()

    assert current == PENDING_CS_DISPATCH


def test_resume_paid_stored_acceptance_order_returns_to_active(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                dispatch_message_id TEXT,
                updated_at TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE order_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                worker_discord_id TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            )
        """))

    monkeypatch.setattr(order_acceptance, "engine", engine)
    order_acceptance.ensure_acceptance_tables()

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO web_orders(id, status, updated_at)
                VALUES(1, :status, CURRENT_TIMESTAMP)
                """
            ),
            {"status": ACTIVE},
        )
        conn.execute(
            text(
                """
                INSERT INTO order_acceptance_meta(
                    order_id,
                    order_rule_key,
                    required_staff_count,
                    min_protector_count,
                    allowed_role_ids_json,
                    specified_staff_ids_json,
                    point_benefits_allowed,
                    status,
                    created_at,
                    updated_at
                )
                VALUES(
                    1,
                    'steam_play',
                    1,
                    0,
                    '[]',
                    '[]',
                    1,
                    :status,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """
            ),
            {"status": ACTIVE},
        )
        conn.execute(
            text(
                """
                INSERT INTO order_acceptance_claims(
                    order_id,
                    staff_discord_id,
                    staff_display_name,
                    staff_role_ids_json,
                    source,
                    is_active,
                    claimed_at
                )
                VALUES(1, '123', 'Worker', '[]', 'test', 1, CURRENT_TIMESTAMP)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO order_assignments(
                    order_id,
                    worker_discord_id,
                    is_active
                )
                VALUES(1, '123', 1)
                """
            )
        )

    stored = order_acceptance.pause_acceptance_order(
        1,
        source="test_store",
    )
    assert stored.status == STORED

    resumed = order_acceptance.resume_acceptance_order(
        1,
        source="test_resume",
    )

    assert resumed.status == ACTIVE

    with engine.begin() as conn:
        status = conn.execute(
            text("SELECT status FROM web_orders WHERE id = 1")
        ).scalar_one()
        meta_status = conn.execute(
            text("SELECT status FROM order_acceptance_meta WHERE order_id = 1")
        ).scalar_one()

    assert status == ACTIVE
    assert meta_status == ACTIVE

def test_dispatch_upsert_cannot_revive_closed_order(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    monkeypatch.setattr(web_order_sync, "SessionLocal", TestSession)

    with TestSession() as db:
        order = WebOrder(
            ticket_channel_id="12345",
            dispatch_channel_id="67890",
            dispatch_message_id="11111",
            customer_discord_id="999",
            customer_display_name="Customer",
            category="steam",
            item="Steam遊戲｜娛樂陪",
            quantity=1,
            amount=320,
            payment_method="轉帳",
            status=CLOSED,
        )
        db.add(order)
        db.commit()
        order_id = int(order.id)

    with pytest.raises(OrderStateTransitionError):
        web_order_sync.upsert_web_order_from_dispatch(
            ticket_channel_id="12345",
            dispatch_channel_id="67890",
            dispatch_message_id="22222",
            customer_discord_id="999",
            customer_display_name="Customer",
            category="steam",
            item="Steam遊戲｜娛樂陪",
            quantity=1,
            amount=320,
            payment_method="待付款",
            status=WAITING_ACCEPTANCE,
        )

    with TestSession() as db:
        current = db.get(WebOrder, order_id)

        assert current is not None
        assert current.status == CLOSED
        assert current.dispatch_message_id == "11111"

