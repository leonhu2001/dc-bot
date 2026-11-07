from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from services import order_rule_store
from services.order_discounts import (
    FUNDING_SHARED,
    get_discount_funding_policy,
)
from services.order_rules import (
    ORDER_RULES,
    build_rule_with_override,
    calculate_price,
    get_base_rule,
    invalidate_rule_override_cache,
    rule_to_override_payload,
)
from services.order_rule_store import (
    ensure_order_rule_store,
    publish_rule_override,
)


ROOT = Path(__file__).resolve().parents[1]
KEY = "custom_custom_order"


@pytest.mark.parametrize("player_count", [1, 2, 3, 4])
@pytest.mark.parametrize("quantity", [1, 2, 6])
def test_custom_orders_have_no_automatic_charges_for_designation(player_count, quantity):
    rule = ORDER_RULES[KEY]
    role = rule.allowed_roles[0]
    result = calculate_price(
        rule,
        quantity=quantity,
        player_count=player_count,
        specified_roles=[role] * player_count,
    )
    assert result.base_amount == 0
    assert result.specify_fee == 0
    assert result.staff_adjustment_amount == 0
    assert result.total_amount == 0
    assert result.required_staff_count == player_count
    assert result.free_specify_fee is False


def test_custom_order_ignores_legacy_fee_overrides_and_automatic_addons(tmp_path, monkeypatch):
    db = tmp_path / "web_dashboard.db"
    ensure_order_rule_store(db)
    monkeypatch.setattr(order_rule_store, "default_db_path", lambda: db)
    base = get_base_rule(KEY)
    payload = rule_to_override_payload(base)
    payload.update({
        "pricing_type": "hourly",
        "price": 500,
        "price_multiply_player_count": True,
        "specify_fee_default": 100,
        "specify_fee_by_role": {role: 250 for role in base.allowed_roles},
        "specify_free_min_units": 2,
        "staff_adjustments": {"late": 800},
        "staff_adjustment_labels": {"late": "加價"},
    })
    preview = build_rule_with_override(base, payload)
    assert preview.pricing_type == "manual"
    assert preview.price == 0
    assert preview.specify_fee_default == 0
    assert preview.specify_fee_by_role == {}
    assert preview.staff_adjustments == {}

    publish_rule_override(
        rule_key=KEY,
        payload=payload,
        actor_discord_id="1",
        actor_display_name="test",
        expected_active_version=0,
        db_file=db,
    )
    invalidate_rule_override_cache()
    try:
        rule = ORDER_RULES[KEY]
        assert rule.pricing_type == "manual"
        assert rule.price == 0
        assert rule.specify_fee_default == 0
        assert rule.specify_fee_by_role == {}
        assert rule.staff_adjustments == {}
        total = calculate_price(
            rule,
            quantity=1,
            player_count=2,
            specified_roles=[rule.allowed_roles[0]],
        )
        assert total.total_amount == 0
        assert total.specify_fee == 0
        with pytest.raises(ValueError, match="客服填價"):
            calculate_price(rule, quantity=1, player_count=2, staff_adjustments=["late"])
    finally:
        invalidate_rule_override_cache()


def test_all_customer_service_entered_discounts_are_shared():
    assert get_discount_funding_policy("manual_percent") == FUNDING_SHARED
    assert get_discount_funding_policy("manual_fixed") == FUNDING_SHARED


def test_customer_service_discount_copy_matches_actual_shared_allocation():
    breakdown = (ROOT / "services/self_service_financial_breakdown_display.py").read_text(encoding="utf-8")
    modal = (ROOT / "services/self_service_ui_runtime.py").read_text(encoding="utf-8")
    quote = (ROOT / "services/self_service_financials.py").read_text(encoding="utf-8")
    assert "共同分攤，折後金額計入分潤基準" in breakdown
    assert "共同分攤，折後金額計入分潤基準" in modal
    assert "共同分攤，折後金額計入分潤基準" in quote
    assert "（店內吸收，不影響打手分潤）" not in modal
    assert "自訂單指定不加價" in modal
    assert "客服填寫價格為準" in (
        ROOT / "services/custom_order_quick_entry.py"
    ).read_text(encoding="utf-8")
