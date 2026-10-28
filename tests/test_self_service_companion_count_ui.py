import asyncio
from types import SimpleNamespace

from services import order_runtime
from services import self_service_ui_runtime as base_ui
from services.order_rules import ORDER_RULES
from services.self_service_companion_count_runtime import (
    EnhancedSelfServiceOrderView,
    SelfServicePlayerCountButton,
)


def _configure_runtime(monkeypatch, selections: dict):
    state = SimpleNamespace(
        order_selections=selections,
        remember_order=lambda _channel_id, _data: None,
    )
    monkeypatch.setattr(order_runtime, "_RUNTIME_STATE", state)
    monkeypatch.setattr(base_ui, "SELF_SERVICE_ORDER_SELECTIONS", selections)
    monkeypatch.setattr(
        base_ui,
        "_get_rule_from_self_service_data",
        lambda data: ORDER_RULES[str(data["order_rule_key"])],
    )


def _component_custom_ids(view) -> list[list[str]]:
    return [
        [str(component.get("custom_id") or "") for component in row.get("components", [])]
        for row in view.to_components()
    ]


def test_selected_category_reflows_to_five_actions_then_submit(monkeypatch):
    channel_id = 12345
    data = {
        "category": "delta_desktop_basic",
        "item_group": "黑潮爆破",
        "item_detail_value": "entertain",
        "item": "黑潮爆破｜娛樂陪",
        "order_rule_key": "basic_black_tide_entertain",
        "quantity": 1,
        "player_count": 3,
    }
    _configure_runtime(monkeypatch, {channel_id: data})

    async def build_view():
        return EnhancedSelfServiceOrderView(
            customer_id=777,
            channel_id=channel_id,
            selected_category="delta_desktop_basic",
        )

    view = asyncio.run(build_view())
    rows = _component_custom_ids(view)

    assert rows == [
        ["self_service_order_item_select"],
        ["self_service_order_detail_select"],
        ["self_service_order_quantity_select"],
        [
            "self_service_order_player_count_button",
            "self_service_order_specified_staff_button",
            "self_service_order_point_benefit_button",
            "self_service_order_staff_price_button",
            "self_service_order_staff_discount_coupon_button",
        ],
        ["self_service_order_go_payment_button"],
    ]

    labels = {
        str(getattr(child, "custom_id", "") or ""): str(getattr(child, "label", "") or "")
        for child in view.children
    }
    assert labels["self_service_order_player_count_button"] == "陪玩人數：3"
    assert labels["self_service_order_specified_staff_button"] == "指定成員"
    assert labels["self_service_order_point_benefit_button"] == "點數福利"
    assert labels["self_service_order_staff_price_button"] == "客服填價"
    assert labels["self_service_order_staff_discount_coupon_button"] == "手動折扣"
    assert labels["self_service_order_go_payment_button"] == "送出訂單"


def test_before_category_count_control_is_visible_and_disabled(monkeypatch):
    channel_id = 12346
    _configure_runtime(monkeypatch, {channel_id: {}})

    async def build_view():
        return EnhancedSelfServiceOrderView(
            customer_id=777,
            channel_id=channel_id,
            selected_category=None,
        )

    view = asyncio.run(build_view())
    rows = _component_custom_ids(view)

    assert rows[-1] == [
        "self_service_order_player_count_button",
        "self_service_order_specified_staff_button",
        "self_service_order_point_benefit_button",
        "self_service_order_staff_price_button",
        "self_service_order_staff_discount_coupon_button",
    ]
    assert all(
        bool(child.disabled)
        for child in view.children
        if str(getattr(child, "custom_id", "") or "") in set(rows[-1])
    )
    assert not any(
        str(getattr(child, "custom_id", "") or "") == "self_service_order_go_payment_button"
        for child in view.children
    )


def test_fixed_count_product_shows_locked_count_button():
    async def build_button():
        return SelfServicePlayerCountButton(
            rule=ORDER_RULES["basic_trial_500"],
            current_count=1,
            disabled=False,
        )

    button = asyncio.run(build_button())
    assert button.label == "陪玩人數：1"
    assert button.disabled is True
