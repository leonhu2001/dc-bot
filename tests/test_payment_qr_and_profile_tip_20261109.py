from __future__ import annotations

from pathlib import Path

import discord
import pytest

from services import payment_qr_assets as qr
from services.order_flow import build_payment_method_embed
from services.worker_tips import (
    configure_worker_tip_store,
    create_worker_tip,
    get_worker_tip,
    mark_worker_tip_paid,
)
from services.profile_tip_ticket_runtime import _tip_topic_parts
from views.profile_tip_ticket import WorkerTipProfileStartView
from views.staff_profiles import (
    StaffProfilePanelView,
    CustomerFavoriteActionsView,
    PublicStaffProfileActionsView,
)


def test_qr_attachments_for_selected_bank_and_jkopay(tmp_path, monkeypatch):
    monkeypatch.setattr(qr, "_PAYMENT_IMAGE_DIR", tmp_path)
    assert qr.payment_qr_send_kwargs("轉帳") == {}
    assert qr.payment_qr_edit_kwargs("轉帳") == {"attachments": []}
    (tmp_path / "cathay_qr.jpg").write_bytes(b"fake-cathay-image")
    (tmp_path / "jkopay_qr.jpg").write_bytes(b"fake-jkopay-image")
    for method, filename in (("轉帳", "cathay_qr.jpg"), ("街口", "jkopay_qr.jpg")):
        assert qr.payment_qr_path(method).name == filename
        embed = build_payment_method_embed(
            customer_id=1234, category_label="三角洲",
            item="陪玩", quantity=1, amount=500,
            payment_method=method,
        )
        assert embed.image.url == "attachment://payment_qr.jpg"
        assert any(f.name == "付款資訊" for f in embed.fields)
        attachments = qr.payment_qr_edit_kwargs(method)["attachments"]
        assert len(attachments) == 1
        assert attachments[0].filename == "payment_qr.jpg"
        attachments[0].close()
    assert qr.payment_qr_edit_kwargs("我的錢包") == {"attachments": []}
    wallet = build_payment_method_embed(
        customer_id=1234, category_label="三角洲",
        item="陪玩", quantity=1, amount=500,
        payment_method="我的錢包",
    )
    assert wallet.image.url is None


def test_order_payment_surface_paths_use_same_qr_helper():
    root = Path(__file__).resolve().parents[1]
    for file in (
        "services/order_runtime.py",
        "services/acceptance/payment_panel.py",
        "services/order_payment_review_submission.py",
        "services/order_payment_runtime.py",
        "services/payment_review_runtime.py",
    ):
        assert "payment_qr_edit_kwargs(" in (root / file).read_text(encoding="utf-8"), file
    assert "payment_qr_send_kwargs(" in (root / "views/worker_tips.py").read_text(encoding="utf-8")


def test_all_staff_card_action_views_include_chicken_leg():
    views = [
        StaffProfilePanelView("123456789"),
        CustomerFavoriteActionsView("111111111", "123456789"),
        PublicStaffProfileActionsView("111111111", "123456789"),
    ]
    for view in views:
        assert any(
            isinstance(item, discord.ui.Button) and "加雞腿" in str(item.label)
            for item in view.children
        )


def test_profile_tip_private_ticket_view_and_topic():
    view = WorkerTipProfileStartView(
        customer_id=111111111,
        target={"staff_id": "123456789", "display_name": "伴玩"},
    )
    assert view.is_persistent()
    assert view.children[0].custom_id == "worker_tip_profile_start:111111111:123456789"
    assert _tip_topic_parts("tip_customer_id=111111111;tip_staff_id=123456789") == {
        "tip_customer_id": "111111111",
        "tip_staff_id": "123456789",
    }


def test_profile_tip_uses_existing_payroll_ledger_without_fake_order(tmp_path):
    file = tmp_path / "web_dashboard.db"
    configure_worker_tip_store(db_path_provider=lambda: file)
    tip_id = create_worker_tip(
        order=None,
        ticket_channel_id="123",
        customer_id=111,
        customer_display_name="老闆",
        target={"staff_id": "222", "display_name": "伴玩"},
        amount=120,
        payment_method="街口",
        payment_status="pending_review",
        source="staff_profile",
    )
    row = get_worker_tip(tip_id)
    assert row["source"] == "staff_profile"
    assert row["order_id"] is None
    assert row["amount"] == 120
    assert row["worker_discord_id"] == "222"
    assert row["payment_status"] == "pending_review"
    assert row["payout_status"] == "unpaid"
    paid = mark_worker_tip_paid(tip_id)
    assert paid["payment_status"] == "paid"
    assert paid["payout_status"] == "unpaid"
