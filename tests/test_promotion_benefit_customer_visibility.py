from pathlib import Path

from services import promotion_benefits as benefits
from services.promotion_benefit_presentation import (
    build_benefit_grant_dm,
    list_customer_promotion_benefits,
)


ROOT = Path(__file__).resolve().parents[1]
ADMIN_ROUTE = (ROOT / "web/app/routers/admin_benefits.py").read_text(encoding="utf-8")
ADMIN_TEMPLATE = (ROOT / "web/app/templates/admin_benefits.html").read_text(encoding="utf-8")
SITE_ROUTE = (ROOT / "web/app/routers/site.py").read_text(encoding="utf-8")
MEMBER_TEMPLATE = (ROOT / "web/app/templates/member_center.html").read_text(encoding="utf-8")
MEMBER_PORTAL = (ROOT / "views/member_portal.py").read_text(encoding="utf-8")


def _rules() -> dict:
    return {
        "effect_kind": benefits.EFFECT_FIXED_CASH,
        "effect_value": 300,
        "funding": benefits.FUNDING_STORE,
        "min_order_amount": 0,
        "scope_type": "all",
        "scope_values": [],
        "excluded_rule_keys": [],
        "valid_days": 30,
        "usage_limit": 2,
        "consume_mode": "one_shot",
        "seat_mode": "one_seat",
        "include_specify_fee": False,
        "allow_vip_discount": True,
        "allow_points": False,
    }


def test_manual_grant_is_presented_for_customer_and_dm(tmp_path):
    db_path = tmp_path / "benefits.db"
    template_id = benefits.create_template(
        name="客服補償 300T",
        rules=_rules(),
        web_db=db_path,
    )
    benefits.issue_benefit(
        template_id=template_id,
        customer_discord_id="123",
        web_db=db_path,
    )

    items = list_customer_promotion_benefits("123", web_db=db_path)
    assert len(items) == 1
    item = items[0]
    assert item["title"] == "客服補償 300T"
    assert item["effect_text"] == "300T 抵用"
    assert item["remaining_uses"] == 2
    assert item["is_available"] is True

    dm = build_benefit_grant_dm(item)
    assert "客服補償 300T" in dm
    assert "300T 抵用" in dm
    assert "可使用次數：2 次" in dm
    assert "Discord「我的福利」" in dm
    assert "網站會員中心" in dm


def test_bulk_issue_and_customer_visibility_wiring_stays_connected():
    assert 'form.getlist("customer_discord_ids")' in ADMIN_ROUTE
    assert "send_direct_message" in ADMIN_ROUTE
    assert "asyncio.to_thread" in ADMIN_ROUTE
    assert 'name="customer_discord_ids"' in ADMIN_TEMPLATE
    assert 'data-benefit-filter="benefit-member-picker"' in ADMIN_TEMPLATE

    assert "list_customer_promotion_benefits" in SITE_ROUTE
    assert 'benefits["promotions"] = promotions' in SITE_ROUTE
    assert "benefits.promotions" in MEMBER_TEMPLATE

    assert "list_customer_promotion_benefits" in MEMBER_PORTAL
    assert 'name="已發放福利券"' in MEMBER_PORTAL
