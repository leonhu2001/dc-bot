from __future__ import annotations

from types import SimpleNamespace

from services import order_runtime
from services import orders as orders_service
from services import quick_order_v2_fixes
from services.order_rules import ORDER_RULES
from services.self_service_selection_state import (
    apply_self_service_category_selection,
    apply_self_service_detail_selection,
    apply_self_service_item_group_selection,
)


def test_desktop_entertain_detail_enables_hour_quantity(monkeypatch):
    channel_id = 9001
    data = {
        "customer_id": 42,
        "category": "delta_desktop_basic",
        "item_group": "娛樂陪",
        "selected_same_order_benefit": True,
        "selected_benefit_coupon_id": 999,
        "benefit_discount_amount": 123,
        "customer_pay_amount": 456,
    }
    detail = orders_service.get_order_item_detail_for_selection(
        data["category"], data["item_group"], "single"
    )
    assert detail is not None

    apply_self_service_detail_selection(data, detail)

    assert data["item_detail_value"] == "single"
    assert data["order_rule_key"] == "basic_entertain_single"
    assert data["item"] == ORDER_RULES["basic_entertain_single"].label
    assert data["quantity"] == 1
    assert "selected_same_order_benefit" not in data
    assert "selected_benefit_coupon_id" not in data
    assert "benefit_discount_amount" not in data
    assert "customer_pay_amount" not in data

    state = {channel_id: data}
    monkeypatch.setattr(
        order_runtime,
        "_RUNTIME_STATE",
        SimpleNamespace(order_selections=state),
    )
    select = order_runtime.SelfServiceOrderQuantitySelect(
        customer_id=42,
        channel_id=channel_id,
        selected_item=data["item"],
        selected_quantity=data["quantity"],
    )
    assert select.disabled is False
    assert len(select.options) == 24
    assert select.options[0].label == "1 小時"
    assert select.options[-1].label == "24 小時"


def test_group_and_category_switch_clear_product_dependent_state():
    data = {
        "category": "delta_desktop_basic",
        "item_group": "娛樂陪",
        "item_detail_value": "single",
        "item": "old",
        "order_rule_key": "old",
        "quantity": 8,
        "selected_point_benefit_key": "cash_100",
        "selected_vip_monthly_benefit_id": 12,
        "selected_same_order_benefit": True,
        "point_benefit_name": "old",
        "benefit_coupon_title": "old",
        "manual_staff_amount": 9999,
        "manual_discount_percent": 90,
        "cash_coupon_amount": 100,
    }

    apply_self_service_item_group_selection(data, "技術陪")
    assert "selected_point_benefit_key" not in data
    assert "selected_vip_monthly_benefit_id" not in data
    assert "selected_same_order_benefit" not in data
    assert "manual_staff_amount" not in data
    assert data["manual_discount_percent"] == 90
    assert data["cash_coupon_amount"] == 100

    apply_self_service_category_selection(data, "apex")
    assert data["category"] == "apex"
    for key in ("item_group", "item_detail_value", "item", "order_rule_key", "quantity"):
        assert key not in data


def test_single_detail_group_uses_same_canonical_transition():
    data = {
        "category": "delta_desktop_basic",
        "selected_benefit_coupon_id": 1,
        "benefit_coupon_title": "stale",
    }
    detail = apply_self_service_item_group_selection(data, "絕巴技術陪")
    assert detail is not None
    assert data["item_detail_value"] == detail["value"]
    assert data["item"] == detail["item"]
    assert data["order_rule_key"] == detail["rule_key"]
    assert data["quantity"] == int(detail["min_quantity"])
    assert "selected_benefit_coupon_id" not in data
    assert "benefit_coupon_title" not in data


def test_all_active_catalog_paths_have_valid_discord_detail_and_quantity_contracts():
    # Production quick-order installs this resolver before exposing the public
    # selector. Install the same layer here so the contract test observes the
    # actual runtime catalog, including the five-scheme 賽季3x3 group.
    quick_order_v2_fixes._install_canonical_group_resolver()

    for category in orders_service.SELF_SERVICE_ACTIVE_CATEGORIES:
        groups = orders_service.ORDER_ITEM_GROUPS_BY_CATEGORY.get(category, [])
        assert groups, category
        assert len(groups) <= 25, category

        for group in groups:
            details = orders_service.get_order_item_details_for_group(category, group)
            assert details, (category, group)
            assert len(details) <= 25, (category, group)

            values = [str(detail.get("value") or "") for detail in details]
            assert all(values), (category, group, values)
            assert len(values) == len(set(values)), (category, group, values)

            for detail in details:
                rule_key = str(detail.get("rule_key") or "")
                assert rule_key in ORDER_RULES, (category, group, rule_key)
                assert str(detail.get("item") or ""), (category, group, detail)
                minimum = int(detail.get("min_quantity") or 1)
                maximum = int(detail.get("max_quantity") or 1)
                assert 1 <= minimum <= maximum <= 24, (category, group, detail)
                resolved = orders_service.get_order_item_detail_for_selection(
                    category, group, detail["value"]
                )
                assert resolved is not None
                assert resolved["rule_key"] == detail["rule_key"]
