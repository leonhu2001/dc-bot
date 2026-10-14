from __future__ import annotations

from pathlib import Path


state_service = Path("services/self_service_selection_state.py")
state_service.write_text(
    '''from __future__ import annotations

from typing import Any

from services.orders import get_order_item_details_for_group


# Benefit selections and calculated quote fields belong to one concrete product.
# They must never leak into another category / item / detail selection.
_PRODUCT_DEPENDENT_KEYS = (
    "selected_point_benefit_key",
    "selected_benefit_coupon_id",
    "selected_vip_monthly_benefit_id",
    "selected_same_order_benefit",
    "vip_monthly_benefit_id",
    "vip_monthly_benefit_key",
    "vip_monthly_benefit_title",
    "vip_monthly_cash_amount",
    "point_benefit_key",
    "point_benefit_name",
    "point_benefit_cost",
    "point_discount_coupon_amount",
    "point_waived_specify_fee",
    "point_free_first_hour_amount",
    "point_extra_hours",
    "point_extra_games",
    "service_bonus_text",
    "benefit_coupon_id",
    "benefit_coupon_title",
    "benefit_coupon",
    "benefit_service_value",
    "benefit_discount_amount",
    "benefit_service_note",
    "store_absorbed_amount",
    "customer_pay_amount",
    "payout_base_amount",
    "amount",
    "total_amount",
    "amount_text",
    "rule_original_amount",
    "service_original_amount",
    "original_amount",
    "priced_amount",
    "manual_discount_amount",
    "percent_discount_amount",
    "discount_rate_percent",
    "discount_source",
    "vip_level_name",
    "effective_specify_fee",
    "specified_fee_before_waiver",
    "price_formula_version",
    # A manually entered base price belongs to one product only. Percentage/fixed
    # discounts are order-level inputs and are recalculated against the new product.
    "manual_staff_amount",
    "manual_staff_price_reason",
    "manual_staff_price_set_by",
    "manual_staff_price_set_at",
)


def clear_product_dependent_selection_state(data: dict[str, Any]) -> None:
    for key in _PRODUCT_DEPENDENT_KEYS:
        data.pop(key, None)
    data.pop("payment_method", None)


def apply_self_service_category_selection(data: dict[str, Any], category: str) -> None:
    data["category"] = category
    for key in (
        "item_group",
        "item_detail_value",
        "item",
        "order_rule_key",
        "quantity",
        "player_count",
        "specified_staff_ids",
        "companion_preference",
    ):
        data.pop(key, None)
    clear_product_dependent_selection_state(data)


def apply_self_service_detail_selection(data: dict[str, Any], detail: dict[str, Any]) -> None:
    clear_product_dependent_selection_state(data)
    data["item_detail_value"] = str(detail.get("value") or "")
    data["item"] = str(detail.get("item") or detail.get("label") or "")
    data["order_rule_key"] = str(detail.get("rule_key") or "")

    if detail.get("player_count") is not None:
        data["player_count"] = int(detail["player_count"])
    else:
        data.pop("player_count", None)

    data["quantity"] = int(detail.get("min_quantity") or 1)
    data.pop("specified_staff_ids", None)
    data["companion_preference"] = "不指定陪玩/打手"


def apply_self_service_item_group_selection(
    data: dict[str, Any],
    selected_group: str,
) -> dict[str, Any] | None:
    data["item_group"] = selected_group
    for key in ("item_detail_value", "item", "order_rule_key", "player_count", "specified_staff_ids"):
        data.pop(key, None)
    clear_product_dependent_selection_state(data)
    data["companion_preference"] = "不指定陪玩/打手"

    details = get_order_item_details_for_group(data.get("category"), selected_group)
    if len(details) == 1:
        detail = details[0]
        apply_self_service_detail_selection(data, detail)
        return detail

    data["quantity"] = 1
    return None
''',
    encoding="utf-8",
)

p = Path("services/order_runtime.py")
text = p.read_text(encoding="utf-8")

old = """from services.payment_methods import PAYMENT_METHOD_OPTIONS, WALLET_PAYMENT_METHOD
from services.wallet_service import get_wallet_payment_transaction
"""
new = """from services.payment_methods import PAYMENT_METHOD_OPTIONS, WALLET_PAYMENT_METHOD
from services.wallet_service import get_wallet_payment_transaction
from services.orders import (
    ORDER_CATEGORY_LABELS,
    ORDER_ITEM_GROUPS_BY_CATEGORY,
    SELF_SERVICE_ACTIVE_CATEGORIES,
    _to_int,
    get_order_item_detail_for_selection,
    get_order_item_details_for_group,
    get_order_item_group_label,
    get_self_service_quantity_meta,
)
from services.self_service_selection_state import (
    apply_self_service_category_selection,
    apply_self_service_detail_selection,
    apply_self_service_item_group_selection,
)
"""
if old not in text:
    raise SystemExit("order_runtime import anchor missing")
text = text.replace(old, new, 1)

old = """        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data[\"customer_id\"] = self.customer_id
        data[\"category\"] = selected_category
        data.pop(\"item_group\", None)
        data.pop(\"item_detail_value\", None)
        data.pop(\"item\", None)
        data.pop(\"order_rule_key\", None)
        data.pop(\"quantity\", None)
        data.pop(\"player_count\", None)
        data.pop(\"specified_staff_ids\", None)
        data.pop(\"companion_preference\", None)
        data.pop(\"payment_method\", None)
        remember_order_data(self.channel_id, data)
"""
new = """        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data[\"customer_id\"] = self.customer_id
        apply_self_service_category_selection(data, selected_category)
        remember_order_data(self.channel_id, data)
"""
if old not in text:
    raise SystemExit("category callback anchor missing")
text = text.replace(old, new, 1)

old = """        selected_group = self.values[0]
        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data[\"customer_id\"] = self.customer_id
        data[\"item_group\"] = selected_group
        data.pop(\"item_detail_value\", None)
        data.pop(\"item\", None)
        data.pop(\"order_rule_key\", None)
        data.pop(\"player_count\", None)
        data.pop(\"specified_staff_ids\", None)
        data.pop(\"payment_method\", None)
        data[\"companion_preference\"] = \"不指定陪玩/打手\"

        details = get_order_item_details_for_group(data.get(\"category\"), selected_group)

        # 只有一個規格時直接選好，但第三欄仍會顯示該規格。
        if len(details) == 1:
            detail = details[0]
            data[\"item_detail_value\"] = str(detail.get(\"value\") or \"\")
            data[\"item\"] = detail[\"item\"]
            data[\"order_rule_key\"] = detail[\"rule_key\"]
            if detail.get(\"player_count\") is not None:
                data[\"player_count\"] = int(detail[\"player_count\"])
            data[\"quantity\"] = int(detail.get(\"min_quantity\") or 1)
        else:
            data[\"quantity\"] = 1

        remember_order_data(self.channel_id, data)
"""
new = """        selected_group = self.values[0]
        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data[\"customer_id\"] = self.customer_id
        apply_self_service_item_group_selection(data, selected_group)
        remember_order_data(self.channel_id, data)
"""
if old not in text:
    raise SystemExit("item callback anchor missing")
text = text.replace(old, new, 1)

old = """        data[\"item_detail_value\"] = str(detail.get(\"value\") or \"\")
        data[\"item\"] = detail[\"item\"]
        data[\"order_rule_key\"] = detail[\"rule_key\"]

        if detail.get(\"player_count\") is not None:
            data[\"player_count\"] = int(detail[\"player_count\"])
        else:
            data.pop(\"player_count\", None)

        data[\"quantity\"] = int(detail.get(\"min_quantity\") or 1)
        data.pop(\"specified_staff_ids\", None)
        data.pop(\"payment_method\", None)
        data[\"companion_preference\"] = \"不指定陪玩/打手\"
        remember_order_data(self.channel_id, data)
"""
new = """        apply_self_service_detail_selection(data, detail)
        remember_order_data(self.channel_id, data)
"""
if old not in text:
    raise SystemExit("detail callback anchor missing")
text = text.replace(old, new, 1)
p.write_text(text, encoding="utf-8")

p = Path("services/self_service_runtime.py")
text = p.read_text(encoding="utf-8")
old = """    except discord.HTTPException as exc:
        try:
            await interaction.followup.send(f\"更新自助下單 panel 失敗：{exc}\", ephemeral=True)
        except discord.HTTPException:
            pass
"""
new = """    except Exception as exc:
        print(
            f\"[self-service] panel refresh failed channel_id={channel_id}: \"
            f\"{type(exc).__name__}: {exc}\",
            flush=True,
        )
        try:
            await interaction.followup.send(
                \"訂單選項已儲存，但面板更新失敗。請再操作一次；若仍發生請通知客服。\"
                f\"（{type(exc).__name__}）\",
                ephemeral=True,
            )
        except discord.HTTPException:
            pass
"""
if old not in text:
    raise SystemExit("panel refresh error anchor missing")
text = text.replace(old, new, 1)
p.write_text(text, encoding="utf-8")

test = Path("tests/test_self_service_selection_flow.py")
test.write_text(
    '''from __future__ import annotations

from services import order_runtime
from services.order_rules import ORDER_RULES
from services.orders import (
    ORDER_ITEM_GROUPS_BY_CATEGORY,
    SELF_SERVICE_ACTIVE_CATEGORIES,
    get_order_item_detail_for_selection,
    get_order_item_details_for_group,
)
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
    detail = get_order_item_detail_for_selection(
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
    monkeypatch.setattr(order_runtime, "SELF_SERVICE_ORDER_SELECTIONS", state, raising=False)
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
    for category in SELF_SERVICE_ACTIVE_CATEGORIES:
        groups = ORDER_ITEM_GROUPS_BY_CATEGORY.get(category, [])
        assert groups, category
        assert len(groups) <= 25, category

        for group in groups:
            details = get_order_item_details_for_group(category, group)
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
                resolved = get_order_item_detail_for_selection(category, group, detail["value"])
                assert resolved is not None
                assert resolved["rule_key"] == detail["rule_key"]
''',
    encoding="utf-8",
)
