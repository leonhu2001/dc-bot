from pathlib import Path

from services.order_notification_presentation import (
    build_cancelled_order_notice,
    build_payment_apply_error_notice,
    build_payment_approved_notice,
    build_payment_rejected_notice,
    build_worker_change_embed,
    worker_change_marker,
)


def test_cancelled_notice_uses_canonical_status_and_reason():
    text = build_cancelled_order_notice("時間無法配合")
    assert "⛔ **已取消｜訂單已停止**" in text
    assert "原因：時間無法配合" in text
    assert "3 秒後關閉" in text


def test_worker_change_copy_covers_add_and_remove_with_retry_marker():
    added = build_worker_change_embed(
        order_id=12,
        event_id=34,
        action="admin_added_worker",
        worker_mention="<@123>",
    )
    removed = build_worker_change_embed(
        order_id=12,
        event_id=35,
        action="admin_removed_worker",
        worker_mention="<@456>",
    )

    assert added.title == "🔄 人員異動｜已加入服務人員"
    assert removed.title == "🔄 人員異動｜已移除服務人員"
    assert worker_change_marker(12, 34) == "WEB-12｜人員異動｜EVENT-34"
    assert added.footer.text == "WEB-12｜人員異動｜EVENT-34"
    assert removed.footer.text == "WEB-12｜人員異動｜EVENT-35"


def test_payment_result_copy_is_consistent_and_actionable():
    approved = build_payment_approved_notice(
        customer_id=123,
        payment_method="轉帳",
        amount=1200,
    )
    rejected = build_payment_rejected_notice(
        customer_id=123,
        reason="未確認到款",
    )
    apply_error = build_payment_apply_error_notice(
        customer_id=123,
        error_text="state mismatch",
    )

    assert "✅ **付款完成｜訂單已成立**" in approved
    assert "⚠️ **付款異常｜審核未通過**" in rejected
    assert "⚠️ **付款異常｜需要客服處理**" in apply_error
    assert "請勿重複套用付款" in apply_error


def test_notification_presentation_does_not_own_business_decisions():
    source = Path("services/order_notification_presentation.py").read_text(encoding="utf-8")
    forbidden = (
        "transition_order_state",
        "claim_acceptance_order",
        "unclaim_acceptance_order",
        "calculate_price",
        "recalculate",
        "payout_amount",
    )
    for token in forbidden:
        assert token not in source

    # 現行資料模型沒有獨立炸單狀態；人員變更以真實的 add/remove 事件呈現。
    assert "炸單" not in source
