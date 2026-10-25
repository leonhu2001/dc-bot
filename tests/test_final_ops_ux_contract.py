from pathlib import Path


def test_cancellation_runtime_uses_unified_notice_without_changing_delay():
    source = Path("services/order_lifecycle_runtime.py").read_text(encoding="utf-8")
    assert "build_cancelled_order_notice(" in source
    assert "cancellation_reason_label(" in source
    assert "await asyncio.sleep(3)" in source
    assert "已確認取消訂單，這個頻道將在 3 秒後關閉" not in source


def test_admin_worker_change_sync_sends_idempotent_notice():
    source = Path("services/acceptance/sync_worker.py").read_text(encoding="utf-8")
    assert "admin_added_worker" in source
    assert "admin_removed_worker" in source
    assert "worker_change_marker(" in source
    assert "_channel_has_footer(" in source
    assert "build_worker_change_embed(" in source
    assert "grant_ticket_access" in source
    assert "revoke_ticket_access" in source


def test_payment_review_runtime_has_canonical_success_rejection_and_apply_error_copy():
    source = Path("services/payment_review_runtime.py").read_text(encoding="utf-8")
    order_section = source.split("async def _apply_order_approval", 1)[1].split(
        "async def _notify_worker_tip_paid", 1
    )[0]

    assert "build_payment_approved_notice(" in order_section
    assert "build_payment_rejected_notice(" in order_section
    assert "付款審核已通過" not in order_section
    assert "❌ **付款審核未通過**" not in order_section

    assert "build_payment_apply_error_notice(" in source
    assert "mark_payment_review_apply_error(" in source


def test_admin_action_center_has_explicit_p0_p1_priority_only():
    source = Path("web/app/static/js/pages/admin_dashboard.js").read_text(encoding="utf-8")
    assert 'priorityLabel: "P0"' in source
    assert 'title: "需注意訂單"' in source
    assert 'priorityLabel: "P1"' in source
    assert 'title: "待客服確認"' in source
    assert "等待接單、等待付款、進行中的訂單維持流程追蹤" in source
    assert "left.meta.priority - right.meta.priority" in source


def test_final_cleanup_keeps_business_logic_out_of_new_presentation_layer():
    source = Path("services/order_notification_presentation.py").read_text(encoding="utf-8")
    assert "SessionLocal" not in source
    assert "WebOrder" not in source
    assert "SyncEvent" not in source
    assert "transition_order_state" not in source
