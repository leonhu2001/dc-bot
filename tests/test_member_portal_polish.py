from pathlib import Path

from shared.payout import calculate_order_payout


ROOT = Path(__file__).resolve().parents[1]


def test_gifted_service_can_raise_worker_payout_without_raising_cs():
    result = calculate_order_payout(
        total_amount=1750,
        worker_discord_ids=["worker"],
        customer_service_total_amount=1000,
    )
    assert result.worker_payouts[0].final_payout == 1400
    assert result.customer_service_payout == 50


def test_member_portal_panel_is_scheduled_when_staff_sync_cog_loads():
    source = (ROOT / "cogs/staff_sync.py").read_text(encoding="utf-8")
    assert "asyncio.create_task(" in source
    assert "self._ensure_member_portal_panel()" in source
    assert "[member-portal] panel created" in source


def test_loyalty_coupons_have_ninety_day_expiry():
    source = (ROOT / "services/loyalty_benefits.py").read_text(encoding="utf-8")
    assert "COUPON_VALID_DAYS = 90" in source
    assert "expires_at TEXT" in source
    assert "SET status = 'expired'" in source


def test_cs_payout_base_excludes_point_and_loyalty_service_value():
    source = (ROOT / "web/app/services/order_service.py").read_text(encoding="utf-8")
    assert 'finance.get("point_service_value")' in source
    assert 'finance.get("benefit_service_value")' in source
    assert "customer_service_total_amount=_customer_service_payout_base(order)" in source


def test_member_center_uses_recomposed_dashboard():
    source = (ROOT / "web/app/templates/member_center.html").read_text(encoding="utf-8")
    assert "mc-shortcuts" in source
    assert "現在最重要的" in source
    assert "有效至 {{ coupon.expires_at_text" in source
