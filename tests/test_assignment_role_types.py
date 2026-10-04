import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import shared.db as shared_db
from shared import order_acceptance
from shared.models import Base, OrderAssignment, WebOrder
from shared.order_state import ACCEPTED_PENDING_PAY, WAITING_ACCEPTANCE
from shared.web_order_sync import sync_dispatch_claims_to_web


COMPANION_ROLE_ID = "1500751059239440575"
PROTECTOR_ROLE_ID = "1500234130871550004"


def _setup_db(tmp_path, monkeypatch):
    db_file = tmp_path / "roles.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)

    TestSession = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
    )

    monkeypatch.setattr(order_acceptance, "engine", engine)
    monkeypatch.setattr(shared_db, "engine", engine)
    monkeypatch.setattr(shared_db, "SessionLocal", TestSession)
    order_acceptance.ensure_acceptance_tables()

    return engine, TestSession


def _create_order(Session, *, status, dispatch_message_id):
    with Session() as db:
        order = WebOrder(
            ticket_channel_id=f"ticket-{dispatch_message_id}",
            dispatch_channel_id="dispatch-channel",
            dispatch_message_id=str(dispatch_message_id),
            customer_discord_id="1001",
            customer_display_name="Boss",
            category="三角洲",
            item="陪玩",
            quantity=1,
            amount=1000,
            customer_pay_amount=1000,
            payout_base_amount=1000,
            payment_method="轉帳",
            status=status,
            customer_service_discord_id="3001",
            customer_service_display_name="客服",
        )
        db.add(order)
        db.commit()
        return int(order.id)


@pytest.mark.parametrize(
    ("role_ids", "expected_role_type"),
    [
        ([COMPANION_ROLE_ID], "companion"),
        ([PROTECTOR_ROLE_ID], "booster"),
        ([COMPANION_ROLE_ID, PROTECTOR_ROLE_ID], "booster"),
        (["unknown-role"], "booster"),
    ],
)
def test_payment_promotion_preserves_assignment_role_type(
    tmp_path,
    monkeypatch,
    role_ids,
    expected_role_type,
):
    _engine, Session = _setup_db(tmp_path, monkeypatch)
    order_id = _create_order(
        Session,
        status=WAITING_ACCEPTANCE,
        dispatch_message_id="9001",
    )

    order_acceptance.create_or_update_acceptance_meta(
        order_id=order_id,
        order_rule_key="role-type-test",
        required_staff_count=1,
        allowed_role_ids=[],
        specified_staff_ids=[],
        status=WAITING_ACCEPTANCE,
    )

    state = order_acceptance.claim_acceptance_order(
        order_id=order_id,
        staff_discord_id="2001",
        staff_display_name="Worker",
        staff_role_ids=role_ids,
        source="test",
    )
    assert state.status == ACCEPTED_PENDING_PAY

    promoted = order_acceptance.promote_acceptance_claims_to_assignments(
        order_id=order_id,
        payment_method="轉帳",
        amount=1000,
        payout_base_amount=1000,
        customer_pay_amount=1000,
        original_amount=1000,
    )
    assert promoted == 1

    with Session() as db:
        assignment = db.scalar(
            select(OrderAssignment)
            .where(OrderAssignment.order_id == order_id)
            .where(OrderAssignment.worker_discord_id == "2001")
        )
        assert assignment is not None
        assert assignment.role_type == expected_role_type


def test_full_discord_claim_sync_preserves_companion_and_booster_types(
    tmp_path,
    monkeypatch,
):
    _engine, Session = _setup_db(tmp_path, monkeypatch)
    order_id = _create_order(
        Session,
        status="active",
        dispatch_message_id="9002",
    )

    synced = sync_dispatch_claims_to_web(
        dispatch_message_id="9002",
        companion_ids=["2002"],
        booster_ids=["2001"],
        worker_display_names={
            "2001": "Booster",
            "2002": "Companion",
        },
    )
    assert synced is True

    with Session() as db:
        assignments = list(
            db.scalars(
                select(OrderAssignment)
                .where(OrderAssignment.order_id == order_id)
                .order_by(OrderAssignment.worker_discord_id.asc())
            ).all()
        )

    assert [
        (row.worker_discord_id, row.role_type, row.is_active)
        for row in assignments
    ] == [
        ("2001", "booster", True),
        ("2002", "companion", True),
    ]
