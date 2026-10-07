from pathlib import Path

from services.dispatch_display import (
    build_service_display,
    dispatch_status_display,
)


def test_hour_service_display_keeps_point_extra_time():
    display = build_service_display(
        quantity=2,
        rule_snapshot={"unit_label": "H"},
        price_data={
            "point_benefit_name": "加時 30 分鐘",
            "point_extra_hours": 0.5,
            "service_bonus_text": "服務時間 +30 分鐘",
        },
    )

    assert display["purchased_text"] == "2 小時"
    assert display["total_text"] == "2 小時 30 分鐘"
    assert display["has_bonus"] is True
    assert "加時 30 分鐘" in display["bonus_text"]


def test_game_service_display_combines_promotion_and_point_extra_game():
    display = build_service_display(
        quantity=2,
        rule_snapshot={"unit_label": "局"},
        price_data={
            "service_quantity": 3,
            "service_bonus_quantity": 1,
            "service_promotion_text": "活動加贈：購買 2 局，額外贈送 1 局｜活動後共 3 局",
            "point_benefit_name": "加場一場保撤",
            "point_extra_games": 1,
            "service_bonus_text": "服務局數 +1 局",
        },
    )

    assert display["purchased_text"] == "2 局"
    assert display["total_text"] == "4 局"
    assert "活動加贈" in display["bonus_text"]
    assert "加場一場保撤" in display["bonus_text"]


def test_dispatch_status_labels_are_shared_across_surfaces():
    assert dispatch_status_display(
        status="waiting_acceptance",
        locked=True,
        current_staff_count=0,
        required_staff_count=2,
    )[0] == "🔒 接單保護期"

    assert dispatch_status_display(
        status="waiting_acceptance",
        locked=False,
        current_staff_count=1,
        required_staff_count=2,
    )[0] == "🟢 接單中｜1/2 人"

    assert dispatch_status_display(
        status="accepted_pending_pay",
        current_staff_count=2,
        required_staff_count=2,
    )[0] == "🟡 接單完成｜等待付款"

    assert dispatch_status_display(
        status="active",
        current_staff_count=2,
        required_staff_count=2,
    )[0] == "🟢 服務進行中"


def test_acceptance_lock_has_no_specified_staff_time_bypass():
    source = Path("shared/order_acceptance.py").read_text(encoding="utf-8")

    assert "if is_public_acceptance_locked(meta):" in source
    assert "staff_discord_id not in specified_staff_ids" not in source
    assert "所有接單人員將於派單 1 分鐘後同時開放接單" in source


def test_smart_dispatch_restores_three_stage_timing_after_unlock():
    source = Path("views/smart_dispatch.py").read_text(encoding="utf-8")

    assert "PUBLIC_ACCEPTANCE_OPEN_SECONDS = 60" in source
    assert "FIRST_EXPANSION_AFTER_OPEN_SECONDS = 180" in source
    assert "FULL_EXPANSION_AFTER_OPEN_SECONDS = 360" in source
    assert "第一輪通知" in source
    assert "第二輪通知" in source
    assert "第三輪全量通知" in source
    assert "REPEAT_REMINDER_SECONDS = 600" in source


def test_web_dispatch_only_alerts_after_unlock_and_uses_browser_countdown():
    state_source = Path("web/app/routers/dispatch_state.py").read_text(encoding="utf-8")
    template_source = Path("web/app/templates/dispatch.html").read_text(encoding="utf-8")

    assert 'if bool(rule.get("acceptance_locked")):' in state_source
    assert "data-dispatch-lock-countdown" in template_source
    assert "data-acceptance-opens-at" in template_source
    assert "setInterval(refreshDispatchLockCountdowns, 1000)" in template_source
    assert "dispatch_service_total_text" in template_source


def test_discord_renderer_reads_persisted_state_for_both_claim_surfaces():
    source = Path("services/dispatch_discord.py").read_text(encoding="utf-8")

    assert "get_acceptance_state(int(order_id))" in source
    assert 'name="服務內容"' in source
    assert 'name="實際服務"' in source
    assert "refresh_unified_dispatch_message" in source

    smart_source = Path("views/smart_dispatch.py").read_text(encoding="utf-8")
    assert "_refresh_panel_on_state_change" in smart_source
    assert "refresh_unified_dispatch_message" in smart_source


def test_protected_orders_stay_visible_on_available_board():
    source = Path("web/app/routers/dispatch.py").read_text(encoding="utf-8")

    assert "keep_protected_orders_on_available_board" in source
    assert 'dispatch_acceptance_locked' in source
