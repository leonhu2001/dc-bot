from __future__ import annotations

import inspect
import json

from core import database, permissions, time_utils, vip_levels
from services import (
    logging_service,
    order_discounts,
    order_runtime,
    orders,
    rewards,
    self_service_runtime,
    smart_dispatch,
    ticket_identity,
)


# Stable module-owned dependencies must never be shadowed by startup wiring.
def test_self_service_runtime_uses_canonical_module_owned_dependencies():
    assert self_service_runtime.json is json
    assert self_service_runtime.ORDER_CATEGORY_LABELS is orders.ORDER_CATEGORY_LABELS
    assert self_service_runtime.ORDER_ITEM_GROUPS_BY_CATEGORY is orders.ORDER_ITEM_GROUPS_BY_CATEGORY
    assert self_service_runtime.ORDER_ITEM_TO_CATEGORY is orders.ORDER_ITEM_TO_CATEGORY
    assert self_service_runtime._to_int is orders._to_int
    assert self_service_runtime.build_self_service_order_embed is orders.build_self_service_order_embed
    assert self_service_runtime.get_order_item_detail_for_selection is orders.get_order_item_detail_for_selection
    assert self_service_runtime.get_order_item_details_for_group is orders.get_order_item_details_for_group
    assert self_service_runtime.get_order_item_group_label is orders.get_order_item_group_label
    assert self_service_runtime.get_self_service_quantity_meta is orders.get_self_service_quantity_meta
    assert self_service_runtime.delete_claim_row_from_db is database.delete_claim_row_from_db
    assert self_service_runtime.delete_order_row_from_db is database.delete_order_row_from_db
    assert self_service_runtime.remember_claim_data is database.remember_claim_data
    assert self_service_runtime.remember_order_data is database.remember_order_data
    assert self_service_runtime.save_bot_data is database.save_bot_data
    assert self_service_runtime.can_operate_self_service_order is permissions.can_operate_self_service_order
    assert self_service_runtime.is_customer_staff is permissions.is_customer_staff
    assert self_service_runtime.get_taipei_now_iso is time_utils.get_taipei_now_iso
    assert self_service_runtime.get_vip_discount_pay_rate is vip_levels.get_vip_discount_pay_rate
    assert self_service_runtime.send_order_log is logging_service.send_order_log
    assert (
        self_service_runtime.allocate_store_absorbed_fixed_discount
        is order_discounts.allocate_store_absorbed_fixed_discount
    )
    assert self_service_runtime.SelfServiceOrderCategorySelect is order_runtime.SelfServiceOrderCategorySelect
    assert self_service_runtime.SelfServiceOrderItemSelect is order_runtime.SelfServiceOrderItemSelect
    assert self_service_runtime.SelfServiceOrderDetailSelect is order_runtime.SelfServiceOrderDetailSelect
    assert self_service_runtime.SelfServiceOrderQuantitySelect is order_runtime.SelfServiceOrderQuantitySelect
    assert self_service_runtime._get_order_rule_by_item_label is order_runtime._get_order_rule_by_item_label
    assert self_service_runtime._self_service_quantity_meta is order_runtime._self_service_quantity_meta
    assert self_service_runtime.get_self_service_quantity_unit is order_runtime.get_self_service_quantity_unit
    assert self_service_runtime.log_self_service_proxy_action is order_runtime.log_self_service_proxy_action
    assert self_service_runtime.normalize_self_service_staff_count is order_runtime.normalize_self_service_staff_count
    assert self_service_runtime.get_current_reward_points is rewards.get_current_reward_points
    assert self_service_runtime.get_customer_reward_data is rewards.get_customer_reward_data
    assert self_service_runtime.get_effective_member_level is rewards.get_effective_member_level
    assert self_service_runtime.build_ticket_channel_name is ticket_identity.build_ticket_channel_name
    assert self_service_runtime.create_smart_dispatch_plan is smart_dispatch.create_smart_dispatch_plan
    assert self_service_runtime.set_specified_dm_results is smart_dispatch.set_specified_dm_results


def test_explicit_configurator_is_keyword_only_and_declares_the_bot_owned_boundary():
    signature = inspect.signature(
        self_service_runtime.configure_self_service_runtime_explicit
    )
    assert list(signature.parameters) == [
        "customer_category_id",
        "customer_role_id",
        "dispatch_channel_id",
        "order_claims",
        "point_redeem_items",
        "point_redeem_items_by_key",
        "order_selections",
        "order_control_view_type",
    ]
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )


def test_module_owned_dependency_names_are_explicitly_guarded():
    expected = {
        "json",
        "discord",
        "ORDER_CATEGORY_LABELS",
        "ORDER_ITEM_GROUPS_BY_CATEGORY",
        "ORDER_ITEM_TO_CATEGORY",
        "_to_int",
        "build_self_service_order_embed",
        "get_order_item_detail_for_selection",
        "get_order_item_details_for_group",
        "get_order_item_group_label",
        "get_self_service_quantity_meta",
        "remember_claim_data",
        "remember_order_data",
        "save_bot_data",
        "can_operate_self_service_order",
        "is_customer_staff",
        "get_taipei_now_iso",
        "send_order_log",
        "allocate_store_absorbed_fixed_discount",
        "get_self_service_quantity_unit",
        "get_current_reward_points",
        "get_customer_reward_data",
        "get_effective_member_level",
        "create_smart_dispatch_plan",
        "set_specified_dm_results",
    }
    assert expected <= self_service_runtime._MODULE_OWNED_RUNTIME_NAMES


def test_self_service_runtime_has_no_legacy_namespace_configurator():
    assert not hasattr(self_service_runtime, "configure_self_service_runtime")
    assert not hasattr(self_service_runtime, "_LEGACY_RUNTIME_NAMES")
