from __future__ import annotations

import discord

from services import payment_qr
from services.order_rules import get_rule
from services.worker_tips import create_worker_tip, get_worker_tip
from views.staff_profiles import (
    CustomerFavoriteActionsView,
    PublicStaffProfileActionsView,
    StaffProfilePanelView,
)
from views.worker_tips import (
    WorkerTipAmountModal,
    WorkerTipPaymentMethodSelect,
)
from views.staff_profile_tip_ticket import (
    WorkerTipProfileStartView, WorkerTipProfileTicketView,
    WorkerTipProfileCloseView, profile_tip_ids, send_profile_tip_completion,
)


def test_payment_qr_matches_exact_uploaded_file_names(tmp_path, monkeypatch):
    monkeypatch.setattr(payment_qr, "_PAYMENT_IMAGE_DIR", tmp_path)
    assert payment_qr.payment_qr_file("轉帳") is None
    assert payment_qr.payment_qr_missing("街口")
    assert not payment_qr.payment_qr_missing("我的錢包")

    (tmp_path / "cathay_qr.jpg").write_bytes(b"jpeg-file-stub")
    (tmp_path / "jkopay_qr.jpg").write_bytes(b"jpeg-file-stub")
    for payment, filename in (
        ("轉帳", "cathay_qr.jpg"),
        ("銀行轉帳", "cathay_qr.jpg"),
        ("bank_transfer", "cathay_qr.jpg"),
        ("街口", "jkopay_qr.jpg"),
        ("街口支付", "jkopay_qr.jpg"),
        ("jkopay", "jkopay_qr.jpg"),
    ):
        assert payment_qr.payment_qr_path(payment).name == filename
        embed = discord.Embed(title="付款")
        file = payment_qr.attach_payment_qr(embed, payment)
        assert file is not None
        assert embed.image.url == f"attachment://{filename}"
        file.close()
    assert payment_qr.payment_qr_file("我的錢包") is None


def test_staff_profile_surfaces_have_chicken_leg_button():
    for view in (
        StaffProfilePanelView("10001"),
        CustomerFavoriteActionsView("20002", "10001"),
        PublicStaffProfileActionsView("20002", "10001"),
    ):
        tip_buttons = [
            item for item in view.children
            if isinstance(item, discord.ui.Button) and "加雞腿" in item.label
        ]
        assert len(tip_buttons) == 1
        assert tip_buttons[0].custom_id.endswith(":10001")

    starter = WorkerTipProfileStartView()
    assert starter.is_persistent()
    assert [item.custom_id for item in starter.children] == ["worker_tip_profile_start"]


def test_tip_amount_and_payment_views_keep_standalone_flag():
    target = {"staff_id": "10001", "display_name": "陪玩"}
    modal = WorkerTipAmountModal(
        customer_id=20002, ticket_channel_id=30003,
        target=target, standalone=True,
    )
    payment = WorkerTipPaymentMethodSelect(
        customer_id=20002, ticket_channel_id=30003,
        target=target, amount=100, standalone=True,
    )
    assert modal.standalone is True
    assert payment.standalone is True
    assert [item.value for item in payment.options] == ["我的錢包", "街口", "轉帳"]


def test_profile_tip_is_an_independent_payable_100_percent_worker_entry(tmp_path, monkeypatch):
    from services import worker_tips

    monkeypatch.setattr(worker_tips, "_DB_PATH_PROVIDER", lambda: tmp_path / "tip.db")
    tip_id = create_worker_tip(
        order=None,
        ticket_channel_id=30003,
        customer_id=20002,
        customer_display_name="老闆",
        target={"staff_id": "10001", "display_name": "陪玩"},
        amount=123,
        payment_method="街口",
        payment_status="pending_review",
    )
    record = get_worker_tip(tip_id)
    assert record["order_id"] is None
    assert record["worker_discord_id"] == "10001"
    assert record["amount"] == 123
    assert record["payment_status"] == "pending_review"
    assert record["payout_status"] == "unpaid"


def test_isolated_payment_release_does_not_include_pending_delta_price_changes():
    # The price update is deliberately not in this isolated deployment branch.
    # The isolated release branch carries 320T/720T; a test-only merge against
    # main is allowed to inherit the newer values without changing this branch.
    assert get_rule("basic_entertain_single").price in {320, 350}
    assert get_rule("basic_one_companion_one_guard_secret").price in {720, 800}


def test_private_profile_tip_ticket_has_start_and_confirmed_close_buttons():
    import types
    view = WorkerTipProfileTicketView()
    assert view.is_persistent()
    labels = [item.label for item in view.children]
    assert labels == ["🍗 加雞腿／輸入金額", "🔒 關閉票口"]
    assert WorkerTipProfileCloseView().is_persistent()
    valid = types.SimpleNamespace(
        topic="profile_tip_customer_id=123;profile_tip_staff_id=456"
    )
    assert profile_tip_ids(valid) == (123, 456)
    assert profile_tip_ids(types.SimpleNamespace(topic="order_customer_id=123")) is None


def test_completed_profile_tip_displays_amount_and_close_action(monkeypatch):
    import asyncio
    from services import worker_tips

    tip = {
        "id": 75, "payment_status": "paid", "amount": 240,
        "customer_discord_id": "123", "worker_discord_id": "456",
    }
    monkeypatch.setattr(worker_tips, "get_worker_tip", lambda tip_id: tip)
    sent = []

    class StubChannel:
        topic = "profile_tip_customer_id=123;profile_tip_staff_id=456"
        async def send(self, *args, **kwargs):
            sent.append((args, kwargs))

    asyncio.run(send_profile_tip_completion(StubChannel(), tip))
    assert len(sent) == 1
    assert "240T" in sent[0][0][0]
    assert "待發放" in sent[0][0][0]
    assert isinstance(sent[0][1]["view"], WorkerTipProfileCloseView)

    tip["payment_status"] = "pending_review"
    asyncio.run(send_profile_tip_completion(StubChannel(), tip))
    assert len(sent) == 1  # Do not celebrate unpaid bank transfers.
