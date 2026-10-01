from datetime import datetime

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from shared.models import (
    AdminAuditLog,
    CustomerServicePayout,
    OrderAssignment,
    SyncEvent,
    WebOrder,
    WorkerPayout,
)
from services.wallet_service import adjust_wallet_balance
from web.app.services import accounting_repair as accounting_repair_module
from web.app.services.accounting_repair import (
    QUEUE_WALLET_ORDER_RECONCILIATION,
    RECOGNIZE_HISTORICAL_DISCOUNT,
    RECALCULATE_UNPAID_PAYOUTS,
    VOID_CANCELLED_PAYOUTS,
    apply_accounting_repair_in_session,
)


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE order_acceptance_meta (
                    order_id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL
                )
                """
            )
        )

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return Session()


def _seed_order(
    db,
    *,
    status: str = "closed",
    worker_payout_status: str = "unpaid",
    worker_paid_at=None,
    worker_amount: int = 159,
    cs_amount: int = 9,
):
    order = WebOrder(
        id=1,
        bot_order_no="MO20261002001",
        customer_discord_id="customer-1",
        customer_display_name="Customer",
        category="steam",
        item="Steam遊戲｜娛樂陪",
        quantity=1,
        amount=200,
        payout_base_amount=200,
        customer_pay_amount=200,
        payment_method="轉帳",
        status=status,
        customer_service_discord_id="cs-1",
        customer_service_display_name="客服一號",
    )
    db.add(order)
    db.flush()

    db.add(
        OrderAssignment(
            order_id=1,
            worker_discord_id="worker-1",
            worker_display_name="Worker",
            role_type="booster",
            is_active=True,
            has_named_bonus=False,
        )
    )

    db.add(
        WorkerPayout(
            order_id=1,
            worker_discord_id="worker-1",
            worker_display_name="Worker",
            gross_share=200,
            base_rate=0.80,
            base_payout=worker_amount,
            named_bonus_rate=0.05,
            named_bonus_amount=0,
            has_named_bonus=False,
            final_payout=worker_amount,
            payout_status=worker_payout_status,
            paid_at=worker_paid_at,
        )
    )

    db.add(
        CustomerServicePayout(
            order_id=1,
            customer_service_discord_id="cs-1",
            customer_service_display_name="客服一號",
            rate=0.05,
            payout_amount=cs_amount,
            payout_status="unpaid",
        )
    )
    db.flush()


def test_recalculate_unpaid_payouts_repairs_values_and_writes_audit():
    db = _make_session()
    try:
        _seed_order(db)

        result = apply_accounting_repair_in_session(
            db,
            order_id=1,
            action=RECALCULATE_UNPAID_PAYOUTS,
            actor={
                "id": "manager-1",
                "username": "Manager",
            },
        )

        db.flush()

        worker_rows = list(
            db.scalars(
                select(WorkerPayout)
                .where(WorkerPayout.order_id == 1)
            ).all()
        )
        cs_rows = list(
            db.scalars(
                select(CustomerServicePayout)
                .where(CustomerServicePayout.order_id == 1)
            ).all()
        )
        audit = db.scalar(
            select(AdminAuditLog)
            .where(
                AdminAuditLog.action
                == "accounting_recalculate_unpaid_payouts"
            )
        )

        assert result["action"] == RECALCULATE_UNPAID_PAYOUTS
        assert len(worker_rows) == 1
        assert worker_rows[0].final_payout == 160
        assert worker_rows[0].payout_status == "unpaid"
        assert len(cs_rows) == 1
        assert cs_rows[0].payout_amount == 10
        assert cs_rows[0].payout_status == "unpaid"

        assert audit is not None
        assert audit.admin_discord_id == "manager-1"
        assert audit.target_type == "order"
        assert audit.target_id == "1"
        assert '"final_payout": 159' in str(audit.before_json)
        assert '"final_payout": 160' in str(audit.after_json)
    finally:
        db.close()


def test_recalculate_blocks_any_paid_payout_and_leaves_data_unchanged():
    db = _make_session()
    try:
        paid_at = datetime(2026, 10, 2, 1, 30, 0)
        _seed_order(
            db,
            worker_payout_status="paid",
            worker_paid_at=paid_at,
        )

        with pytest.raises(ValueError, match="禁止自動重算"):
            apply_accounting_repair_in_session(
                db,
                order_id=1,
                action=RECALCULATE_UNPAID_PAYOUTS,
                actor={"id": "manager-1"},
            )

        worker = db.scalar(
            select(WorkerPayout)
            .where(WorkerPayout.order_id == 1)
        )
        audit = db.scalar(select(AdminAuditLog))

        assert worker is not None
        assert worker.final_payout == 159
        assert worker.payout_status == "paid"
        assert worker.paid_at == paid_at
        assert audit is None
    finally:
        db.close()


def test_recalculate_requires_real_customer_service():
    db = _make_session()
    try:
        _seed_order(db)
        order = db.get(WebOrder, 1)
        assert order is not None
        order.customer_service_discord_id = None
        db.flush()

        with pytest.raises(ValueError, match="缺少真實客服"):
            apply_accounting_repair_in_session(
                db,
                order_id=1,
                action=RECALCULATE_UNPAID_PAYOUTS,
                actor={"id": "manager-1"},
            )
    finally:
        db.close()


def test_void_cancelled_unpaid_payouts_only():
    db = _make_session()
    try:
        _seed_order(
            db,
            status="cancelled",
            worker_amount=160,
            cs_amount=10,
        )

        result = apply_accounting_repair_in_session(
            db,
            order_id=1,
            action=VOID_CANCELLED_PAYOUTS,
            actor={"id": "manager-1"},
        )
        db.flush()

        worker = db.scalar(
            select(WorkerPayout)
            .where(WorkerPayout.order_id == 1)
        )
        cs = db.scalar(
            select(CustomerServicePayout)
            .where(CustomerServicePayout.order_id == 1)
        )
        audit = db.scalar(
            select(AdminAuditLog)
            .where(
                AdminAuditLog.action
                == "accounting_void_cancelled_payouts"
            )
        )

        assert result["action"] == VOID_CANCELLED_PAYOUTS
        assert worker is not None
        assert worker.payout_status == "void"
        assert worker.paid_at is None
        assert cs is not None
        assert cs.payout_status == "void"
        assert cs.paid_at is None
        assert audit is not None
    finally:
        db.close()


def test_void_cancelled_blocks_paid_payout():
    db = _make_session()
    try:
        _seed_order(
            db,
            status="cancelled",
            worker_payout_status="paid",
            worker_paid_at=datetime(2026, 10, 2, 1, 30, 0),
            worker_amount=160,
            cs_amount=10,
        )

        with pytest.raises(ValueError, match="不能自動 void"):
            apply_accounting_repair_in_session(
                db,
                order_id=1,
                action=VOID_CANCELLED_PAYOUTS,
                actor={"id": "manager-1"},
            )

        worker = db.scalar(
            select(WorkerPayout)
            .where(WorkerPayout.order_id == 1)
        )

        assert worker is not None
        assert worker.payout_status == "paid"
    finally:
        db.close()

def _seed_wallet_order_for_repair(
    db,
    *,
    expected_pay_amount: int,
):
    _seed_order(db)
    order = db.get(WebOrder, 1)
    assert order is not None
    order.ticket_channel_id = "ticket-1"
    order.payment_method = "我的錢包"
    order.amount = int(expected_pay_amount)
    order.customer_pay_amount = int(expected_pay_amount)
    order.payout_base_amount = int(expected_pay_amount)
    db.flush()
    return order


def _create_wallet_history(
    path,
    *,
    topup_amount: int,
    payment_amount: int,
):
    adjust_wallet_balance(
        customer_id="customer-1",
        amount=int(topup_amount),
        tx_type="topup",
        order_no="TOPUP-TEST",
        db_file=path,
    )
    adjust_wallet_balance(
        customer_id="customer-1",
        amount=-int(payment_amount),
        tx_type="payment",
        order_channel_id="ticket-1",
        order_no="MO20261002001",
        db_file=path,
    )


def test_queue_wallet_reconciliation_creates_one_pending_event_and_audit(
    monkeypatch,
    tmp_path,
):
    db = _make_session()
    bot_db = tmp_path / "bot.db"

    try:
        _seed_wallet_order_for_repair(
            db,
            expected_pay_amount=1152,
        )
        _create_wallet_history(
            bot_db,
            topup_amount=2000,
            payment_amount=652,
        )
        monkeypatch.setattr(
            accounting_repair_module,
            "_bot_db_path",
            lambda: bot_db,
        )

        result = apply_accounting_repair_in_session(
            db,
            order_id=1,
            action=QUEUE_WALLET_ORDER_RECONCILIATION,
            actor={
                "id": "manager-1",
                "username": "Manager",
            },
        )
        db.flush()

        events = list(
            db.scalars(
                select(SyncEvent)
                .where(SyncEvent.order_id == 1)
            ).all()
        )
        audit = db.scalar(
            select(AdminAuditLog)
            .where(
                AdminAuditLog.action
                == "accounting_queue_wallet_reconciliation"
            )
        )

        assert result["delta"] == -500
        assert "補扣 500T" in result["message"]
        assert len(events) == 1
        assert events[0].status == "pending"
        assert '"sync_kind": "wallet_reconciliation"' in str(
            events[0].payload_json
        )
        assert '"old_customer_pay_amount": 652' in str(
            events[0].payload_json
        )
        assert '"new_customer_pay_amount": 1152' in str(
            events[0].payload_json
        )
        assert audit is not None

        with pytest.raises(ValueError, match="已有待處理"):
            apply_accounting_repair_in_session(
                db,
                order_id=1,
                action=QUEUE_WALLET_ORDER_RECONCILIATION,
                actor={"id": "manager-1"},
            )
    finally:
        db.close()


def test_queue_wallet_reconciliation_blocks_insufficient_balance(
    monkeypatch,
    tmp_path,
):
    db = _make_session()
    bot_db = tmp_path / "bot.db"

    try:
        _seed_wallet_order_for_repair(
            db,
            expected_pay_amount=1152,
        )
        _create_wallet_history(
            bot_db,
            topup_amount=700,
            payment_amount=652,
        )
        monkeypatch.setattr(
            accounting_repair_module,
            "_bot_db_path",
            lambda: bot_db,
        )

        with pytest.raises(ValueError, match="不足以補扣 500T"):
            apply_accounting_repair_in_session(
                db,
                order_id=1,
                action=QUEUE_WALLET_ORDER_RECONCILIATION,
                actor={"id": "manager-1"},
            )

        assert db.scalar(select(SyncEvent)) is None
    finally:
        db.close()


def test_queue_wallet_reconciliation_can_queue_refund(
    monkeypatch,
    tmp_path,
):
    db = _make_session()
    bot_db = tmp_path / "bot.db"

    try:
        _seed_wallet_order_for_repair(
            db,
            expected_pay_amount=1274,
        )
        _create_wallet_history(
            bot_db,
            topup_amount=2000,
            payment_amount=1300,
        )
        monkeypatch.setattr(
            accounting_repair_module,
            "_bot_db_path",
            lambda: bot_db,
        )

        result = apply_accounting_repair_in_session(
            db,
            order_id=1,
            action=QUEUE_WALLET_ORDER_RECONCILIATION,
            actor={"id": "manager-1"},
        )

        assert result["delta"] == 26
        assert "退款 26T" in result["message"]
    finally:
        db.close()

def test_recognize_historical_discount_updates_web_snapshot_only(
    monkeypatch,
    tmp_path,
):
    db = _make_session()
    bot_db = tmp_path / "bot.db"

    try:
        _seed_wallet_order_for_repair(
            db,
            expected_pay_amount=1152,
        )
        order = db.get(WebOrder, 1)
        assert order is not None
        order.status = "closed"
        order.store_absorbed_amount = 0
        order.payout_base_amount = 1152

        _create_wallet_history(
            bot_db,
            topup_amount=2000,
            payment_amount=652,
        )
        before_balance = 1348

        monkeypatch.setattr(
            accounting_repair_module,
            "_bot_db_path",
            lambda: bot_db,
        )

        result = apply_accounting_repair_in_session(
            db,
            order_id=1,
            action=RECOGNIZE_HISTORICAL_DISCOUNT,
            actor={
                "id": "manager-1",
                "username": "Manager",
            },
        )
        db.flush()

        order = db.get(WebOrder, 1)
        audit = db.scalar(
            select(AdminAuditLog)
            .where(
                AdminAuditLog.action
                == "accounting_recognize_historical_discount"
            )
        )

        assert order is not None
        assert order.customer_pay_amount == 652
        assert order.store_absorbed_amount == 500
        assert order.payout_base_amount == 1152
        assert result["discount_amount"] == 500
        assert "錢包與既有分潤皆未修改" in result["message"]
        assert audit is not None

        from services.wallet_service import get_wallet_balance

        assert get_wallet_balance("customer-1", bot_db) == before_balance

        worker = db.scalar(
            select(WorkerPayout)
            .where(WorkerPayout.order_id == 1)
        )
        cs = db.scalar(
            select(CustomerServicePayout)
            .where(CustomerServicePayout.order_id == 1)
        )

        assert worker is not None
        assert worker.final_payout == 159
        assert cs is not None
        assert cs.payout_amount == 9
    finally:
        db.close()


def test_recognize_historical_discount_requires_closed_order(
    monkeypatch,
    tmp_path,
):
    db = _make_session()
    bot_db = tmp_path / "bot.db"

    try:
        _seed_wallet_order_for_repair(
            db,
            expected_pay_amount=1152,
        )
        order = db.get(WebOrder, 1)
        assert order is not None
        order.status = "active"

        _create_wallet_history(
            bot_db,
            topup_amount=2000,
            payment_amount=652,
        )
        monkeypatch.setattr(
            accounting_repair_module,
            "_bot_db_path",
            lambda: bot_db,
        )

        with pytest.raises(ValueError, match="只有已結單"):
            apply_accounting_repair_in_session(
                db,
                order_id=1,
                action=RECOGNIZE_HISTORICAL_DISCOUNT,
                actor={"id": "manager-1"},
            )
    finally:
        db.close()


def test_recognize_historical_discount_rejects_overpayment(
    monkeypatch,
    tmp_path,
):
    db = _make_session()
    bot_db = tmp_path / "bot.db"

    try:
        _seed_wallet_order_for_repair(
            db,
            expected_pay_amount=1274,
        )
        order = db.get(WebOrder, 1)
        assert order is not None
        order.status = "closed"

        _create_wallet_history(
            bot_db,
            topup_amount=2000,
            payment_amount=1300,
        )
        monkeypatch.setattr(
            accounting_repair_module,
            "_bot_db_path",
            lambda: bot_db,
        )

        with pytest.raises(ValueError, match="沒有低於"):
            apply_accounting_repair_in_session(
                db,
                order_id=1,
                action=RECOGNIZE_HISTORICAL_DISCOUNT,
                actor={"id": "manager-1"},
            )
    finally:
        db.close()

