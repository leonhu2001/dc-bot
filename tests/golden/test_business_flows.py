from __future__ import annotations

import asyncio
import sqlite3

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import shared.db as shared_db
from core.vip_levels import BASE_MEMBER_LEVELS
from services import rewards
from services.order_wallet_reconciliation import (
    build_wallet_payment_adjustment_plan,
    validate_wallet_net_before_adjustment,
)
from services.payment_reviews import (
    PAYMENT_REVIEW_APPLIED,
    approve_payment_review,
    create_payment_review,
    get_payment_review,
    mark_payment_review_applied,
)
from services.wallet_service import (
    adjust_wallet_balance,
    ensure_wallet_tables,
    get_wallet_balance,
)
from shared import order_acceptance
from shared.models import (
    Base,
    CustomerServicePayout,
    OrderAssignment,
    OrderStateHistory,
    PayoutStatus,
    WebOrder,
    WorkerPayout,
)
from shared.order_state import (
    ACCEPTED_PENDING_PAY,
    ACTIVE,
    CANCELLED,
    CLOSED,
    PENDING_CS_DISPATCH,
    WAITING_ACCEPTANCE,
    transition_order_state_in_connection,
)
from web.app.services.accounting_reconciliation import (
    build_accounting_reconciliation_snapshot,
)
from web.app.services.accounting_repair import (
    VOID_CANCELLED_PAYOUTS,
    apply_accounting_repair_in_session,
)
from web.app.services.order_financial_edit import (
    preserve_order_financial_gaps,
)
from web.app.services.order_service import recalculate_order_payouts


CUSTOMER_ID = 1001
CUSTOMER_DISCORD_ID = str(CUSTOMER_ID)
WORKER_ID = "2001"
CS_ID = "3001"


async def _no_member(*_args, **_kwargs):
    return None


def _setup_environment(tmp_path, monkeypatch):
    web_db = tmp_path / "web_dashboard.db"
    bot_db = tmp_path / "bot.db"

    engine = create_engine(
        f"sqlite:///{web_db}",
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
    ensure_wallet_tables(bot_db)

    rewards.configure_rewards(
        member_levels=BASE_MEMBER_LEVELS,
        reward_point_divisor=100,
    )
    rewards.configure_reward_storage({})
    rewards.configure_reward_order_context({}, lambda: None)
    monkeypatch.setattr(rewards, "fetch_member_safely", _no_member)

    return {
        "web_db": web_db,
        "bot_db": bot_db,
        "engine": engine,
        "Session": TestSession,
        "order_selections": rewards._ORDER_SELECTIONS,
    }


def _create_dispatched_order(env, *, payment_method: str, amount: int = 1000):
    Session = env["Session"]

    with Session() as db:
        order = WebOrder(
            bot_order_no=None,
            ticket_channel_id="9001",
            dispatch_channel_id="9002",
            dispatch_message_id="9003",
            customer_discord_id=CUSTOMER_DISCORD_ID,
            customer_display_name="Golden Boss",
            category="三角洲",
            item="娛樂陪",
            quantity=1,
            amount=amount,
            original_amount=amount,
            customer_pay_amount=amount,
            payout_base_amount=amount,
            payment_method=payment_method,
            status=PENDING_CS_DISPATCH,
            customer_service_discord_id=CS_ID,
            customer_service_display_name="客服 Golden",
        )
        db.add(order)
        db.commit()
        order_id = int(order.id)

    with env["engine"].begin() as conn:
        transition_order_state_in_connection(
            conn,
            order_id=order_id,
            target_status=WAITING_ACCEPTANCE,
            source="golden_dispatch",
            reason="Golden Flow：客服確認並送出正式派單",
            expected_statuses={PENDING_CS_DISPATCH},
        )

    order_acceptance.create_or_update_acceptance_meta(
        order_id=order_id,
        order_rule_key="golden_single_worker",
        required_staff_count=1,
        min_protector_count=0,
        allowed_role_ids=[],
        specified_staff_ids=[],
        point_benefits_allowed=True,
        status=WAITING_ACCEPTANCE,
    )

    state = order_acceptance.claim_acceptance_order(
        order_id=order_id,
        staff_discord_id=WORKER_ID,
        staff_display_name="Golden Worker",
        staff_role_ids=["golden-role"],
        source="golden_flow",
    )

    assert state.status == ACCEPTED_PENDING_PAY
    assert state.is_full is True

    return order_id


def _promote_after_payment(
    order_id: int,
    *,
    payment_method: str,
    amount: int,
):
    promoted = order_acceptance.promote_acceptance_claims_to_assignments(
        order_id=order_id,
        payment_method=payment_method,
        amount=amount,
        payout_base_amount=amount,
        customer_pay_amount=amount,
        original_amount=amount,
        bot_order_no=f"MO-GOLDEN-{order_id}",
    )
    assert promoted == 1


def _record_reward(env, *, amount: int):
    ticket_id = 9001
    env["order_selections"][ticket_id] = {
        "customer_id": CUSTOMER_ID,
        "item": "娛樂陪",
        "amount": amount,
        "total_amount": amount,
        "reward_counted": False,
    }

    result = asyncio.run(
        rewards.add_customer_reward_from_order(
            None,
            ticket_id,
            CUSTOMER_ID,
            f"{amount}T",
        )
    )

    assert "會員累積已更新" in result
    return env["order_selections"][ticket_id]


def _order_scoped_issues(snapshot, order_id: int):
    return [
        issue
        for issue in snapshot["issues"]
        if int(issue.get("order_id") or 0) == int(order_id)
    ]


def test_golden_happy_path_order_to_payment_to_close_to_payout_and_vip(
    tmp_path,
    monkeypatch,
):
    env = _setup_environment(tmp_path, monkeypatch)
    order_id = _create_dispatched_order(
        env,
        payment_method="轉帳",
        amount=1000,
    )

    review = create_payment_review(
        source_type="order",
        source_id=order_id,
        ticket_channel_id=9001,
        customer_discord_id=CUSTOMER_DISCORD_ID,
        customer_display_name="Golden Boss",
        amount=1000,
        payment_method="轉帳",
        db_file=env["web_db"],
    )
    approve_payment_review(
        int(review["id"]),
        operator_discord_id="9999",
        operator_display_name="Golden Admin",
        db_file=env["web_db"],
    )
    mark_payment_review_applied(
        int(review["id"]),
        db_file=env["web_db"],
    )

    _promote_after_payment(
        order_id,
        payment_method="轉帳",
        amount=1000,
    )

    active_state = order_acceptance.get_acceptance_state(order_id)
    assert active_state.status == ACTIVE

    Session = env["Session"]
    with Session() as db:
        assignment = db.scalar(
            select(OrderAssignment)
            .where(OrderAssignment.order_id == order_id)
            .where(OrderAssignment.is_active.is_(True))
        )
        worker_payout = db.scalar(
            select(WorkerPayout)
            .where(WorkerPayout.order_id == order_id)
        )
        cs_payout = db.scalar(
            select(CustomerServicePayout)
            .where(CustomerServicePayout.order_id == order_id)
        )

        assert assignment is not None
        assert assignment.worker_discord_id == WORKER_ID
        assert worker_payout is not None
        assert worker_payout.final_payout == 800
        assert worker_payout.payout_status == PayoutStatus.UNPAID.value
        assert cs_payout is not None
        assert cs_payout.payout_amount == 50
        assert cs_payout.payout_status == PayoutStatus.UNPAID.value

    closed_state = order_acceptance.close_acceptance_order(
        order_id,
        source="golden_close",
    )
    assert closed_state.status == CLOSED

    reward_order = _record_reward(env, amount=1000)
    reward_data = rewards.get_customer_reward_data(CUSTOMER_ID)

    assert reward_order["reward_counted"] is True
    assert reward_order["reward_amount"] == 1000
    assert reward_data["total_spent"] == 1000
    assert reward_data["order_count"] == 1
    assert reward_data["points"] == 10

    # Idempotency: a repeated close-side reward call must not double count.
    second = asyncio.run(
        rewards.add_customer_reward_from_order(
            None,
            9001,
            CUSTOMER_ID,
            "1000T",
        )
    )
    assert "未重複累積" in second
    assert rewards.get_customer_reward_data(CUSTOMER_ID)["total_spent"] == 1000

    stored_review = get_payment_review(
        int(review["id"]),
        db_file=env["web_db"],
    )
    assert stored_review is not None
    assert stored_review["status"] == PAYMENT_REVIEW_APPLIED

    with Session() as db:
        history = list(
            db.scalars(
                select(OrderStateHistory)
                .where(OrderStateHistory.order_id == order_id)
                .order_by(OrderStateHistory.id.asc())
            ).all()
        )

    assert [row.to_status for row in history] == [
        WAITING_ACCEPTANCE,
        ACCEPTED_PENDING_PAY,
        ACTIVE,
        CLOSED,
    ]

    snapshot = build_accounting_reconciliation_snapshot(tmp_path)
    assert _order_scoped_issues(snapshot, order_id) == []


def test_golden_paid_wallet_order_cancel_refund_and_void_payouts(
    tmp_path,
    monkeypatch,
):
    env = _setup_environment(tmp_path, monkeypatch)

    adjust_wallet_balance(
        customer_id=CUSTOMER_DISCORD_ID,
        amount=2000,
        tx_type="adjustment",
        note="Golden Flow opening balance",
        db_file=env["bot_db"],
    )

    order_id = _create_dispatched_order(
        env,
        payment_method="我的錢包",
        amount=1000,
    )

    adjust_wallet_balance(
        customer_id=CUSTOMER_DISCORD_ID,
        amount=-1000,
        tx_type="payment",
        order_channel_id="9001",
        order_no=f"MO-GOLDEN-{order_id}",
        db_file=env["bot_db"],
    )

    _promote_after_payment(
        order_id,
        payment_method="我的錢包",
        amount=1000,
    )

    assert get_wallet_balance(
        CUSTOMER_DISCORD_ID,
        env["bot_db"],
    ) == 1000

    cancelled = order_acceptance.cancel_acceptance_order(
        order_id,
        source="golden_cancel",
    )
    assert cancelled.status == CANCELLED

    adjust_wallet_balance(
        customer_id=CUSTOMER_DISCORD_ID,
        amount=1000,
        tx_type="refund",
        order_channel_id="9001",
        order_no=f"MO-GOLDEN-{order_id}",
        note="Golden Flow cancellation refund",
        db_file=env["bot_db"],
    )

    Session = env["Session"]
    with Session() as db:
        result = apply_accounting_repair_in_session(
            db,
            order_id=order_id,
            action=VOID_CANCELLED_PAYOUTS,
            actor={
                "id": "9999",
                "global_name": "Golden Admin",
            },
        )
        db.commit()

        worker_payout = db.scalar(
            select(WorkerPayout)
            .where(WorkerPayout.order_id == order_id)
        )
        cs_payout = db.scalar(
            select(CustomerServicePayout)
            .where(CustomerServicePayout.order_id == order_id)
        )

        assert result["action"] == VOID_CANCELLED_PAYOUTS
        assert worker_payout is not None
        assert worker_payout.payout_status == PayoutStatus.VOID.value
        assert cs_payout is not None
        assert cs_payout.payout_status == PayoutStatus.VOID.value

    assert get_wallet_balance(
        CUSTOMER_DISCORD_ID,
        env["bot_db"],
    ) == 2000

    # Cancelled before close: VIP spend must never have been counted.
    reward_data = rewards.get_customer_reward_data(CUSTOMER_ID)
    assert reward_data["total_spent"] == 0
    assert reward_data["order_count"] == 0
    assert reward_data["points"] == 0


def test_golden_paid_wallet_amount_edit_syncs_wallet_payout_vip_and_accounting(
    tmp_path,
    monkeypatch,
):
    env = _setup_environment(tmp_path, monkeypatch)

    adjust_wallet_balance(
        customer_id=CUSTOMER_DISCORD_ID,
        amount=3000,
        tx_type="adjustment",
        note="Golden Flow opening balance",
        db_file=env["bot_db"],
    )

    order_id = _create_dispatched_order(
        env,
        payment_method="我的錢包",
        amount=1000,
    )

    adjust_wallet_balance(
        customer_id=CUSTOMER_DISCORD_ID,
        amount=-1000,
        tx_type="payment",
        order_channel_id="9001",
        order_no=f"MO-GOLDEN-{order_id}",
        db_file=env["bot_db"],
    )

    _promote_after_payment(
        order_id,
        payment_method="我的錢包",
        amount=1000,
    )
    order_acceptance.close_acceptance_order(
        order_id,
        source="golden_close_before_edit",
    )

    reward_order = _record_reward(env, amount=1000)
    assert rewards.get_customer_reward_data(CUSTOMER_ID)["total_spent"] == 1000

    preserved = preserve_order_financial_gaps(
        previous_amount=1000,
        previous_customer_pay_amount=1000,
        previous_payout_base_amount=1000,
        new_amount=1200,
    )
    assert preserved == {
        "customer_pay_amount": 1200,
        "payout_base_amount": 1200,
    }

    plan = build_wallet_payment_adjustment_plan(
        old_amount=1000,
        new_amount=1200,
        old_payment_method="我的錢包",
        new_payment_method="我的錢包",
        old_customer_id=CUSTOMER_DISCORD_ID,
        new_customer_id=CUSTOMER_DISCORD_ID,
    )
    assert plan is not None
    assert plan["amount"] == -200

    with sqlite3.connect(env["bot_db"]) as conn:
        actual_net = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM wallet_transactions
            WHERE customer_discord_id = ?
              AND order_channel_id = ?
              AND type IN ('payment', 'payment_adjustment')
            """,
            (CUSTOMER_DISCORD_ID, "9001"),
        ).fetchone()[0]

    validate_wallet_net_before_adjustment(
        old_amount=1000,
        old_payment_method="我的錢包",
        actual_wallet_net=int(actual_net),
    )

    adjust_wallet_balance(
        customer_id=CUSTOMER_DISCORD_ID,
        amount=int(plan["amount"]),
        tx_type="payment_adjustment",
        order_channel_id="9001",
        order_no=f"WEB-{order_id}:AMOUNT-ADJ:1",
        note="Golden Flow order amount correction",
        db_file=env["bot_db"],
    )

    Session = env["Session"]
    with Session() as db:
        order = db.get(WebOrder, order_id)
        assert order is not None

        order.amount = 1200
        order.customer_pay_amount = 1200
        order.payout_base_amount = 1200
        recalculate_order_payouts(db, order_id)
        db.commit()

        worker_payout = db.scalar(
            select(WorkerPayout)
            .where(WorkerPayout.order_id == order_id)
        )
        cs_payout = db.scalar(
            select(CustomerServicePayout)
            .where(CustomerServicePayout.order_id == order_id)
        )

        assert worker_payout is not None
        assert worker_payout.final_payout == 960
        assert cs_payout is not None
        assert cs_payout.payout_amount == 60

    reward_result = rewards.sync_reward_counted_order_amount(
        reward_order,
        1200,
    )
    assert reward_result is not None
    assert reward_result["delta"] == 200
    assert reward_result["new_total_spent"] == 1200
    assert reward_result["new_points"] == 12

    assert reward_order["amount"] == 1200
    assert reward_order["total_amount"] == 1200
    assert reward_order["reward_amount"] == 1200

    assert get_wallet_balance(
        CUSTOMER_DISCORD_ID,
        env["bot_db"],
    ) == 1800

    snapshot = build_accounting_reconciliation_snapshot(tmp_path)
    assert _order_scoped_issues(snapshot, order_id) == []
