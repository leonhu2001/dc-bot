import pytest

import services.self_service_runtime as runtime


class _DummyView:
    pass


def _dummy_callable(*args, **kwargs):
    return None


def _runtime_namespace():
    return {
        "CUSTOMER_CATEGORY_ID": 101,
        "CUSTOMER_ROLE_ID": 102,
        "DISPATCH_CHANNEL_ID": 103,
        "ORDER_CLAIMS": {},
        "ORDER_ITEM_GROUPS_BY_CATEGORY": {},
        "ORDER_ITEM_TO_CATEGORY": {},
        "POINT_REDEEM_ITEMS": [],
        "POINT_REDEEM_ITEMS_BY_KEY": {},
        "SELF_SERVICE_ORDER_SELECTIONS": {},
        "DispatchClaimView": _DummyView,
        "OrderControlView": _DummyView,
        "SelfServiceOrderCategorySelect": _DummyView,
        "SelfServiceOrderDetailSelect": _DummyView,
        "SelfServiceOrderItemSelect": _DummyView,
        "SelfServiceOrderQuantitySelect": _DummyView,
        "_get_order_rule_by_item_label": _dummy_callable,
        "_self_service_quantity_meta": _dummy_callable,
        "allocate_store_absorbed_fixed_discount": _dummy_callable,
        "build_ticket_channel_name": _dummy_callable,
        "can_operate_self_service_order": _dummy_callable,
        "configure_reorder_ticket_creator": _dummy_callable,
        "delete_order_row_from_db": _dummy_callable,
        "get_current_reward_points": _dummy_callable,
        "get_customer_reward_data": _dummy_callable,
        "get_effective_member_level": _dummy_callable,
        "get_order_item_detail_for_selection": _dummy_callable,
        "get_order_item_details_for_group": _dummy_callable,
        "get_order_item_group_label": _dummy_callable,
        "get_self_service_quantity_meta": _dummy_callable,
        "get_self_service_quantity_unit": _dummy_callable,
        "get_vip_discount_pay_rate": _dummy_callable,
        "log_self_service_proxy_action": _dummy_callable,
        "normalize_self_service_staff_count": _dummy_callable,
        "send_order_log": _dummy_callable,
    }


def test_configure_self_service_runtime_does_not_copy_unrelated_globals():
    runtime.__dict__.pop("UNRELATED_BOT_GLOBAL", None)
    namespace = _runtime_namespace()
    namespace["UNRELATED_BOT_GLOBAL"] = object()

    runtime.configure_self_service_runtime(namespace)

    assert "UNRELATED_BOT_GLOBAL" not in runtime.__dict__
    assert runtime.SELF_SERVICE_ORDER_SELECTIONS is namespace["SELF_SERVICE_ORDER_SELECTIONS"]
    assert runtime.ORDER_CLAIMS is namespace["ORDER_CLAIMS"]
    assert runtime.DISPATCH_CHANNEL_ID == 103
    assert runtime._CONFIGURED is True


def test_configure_self_service_runtime_fails_fast_for_missing_dependency():
    namespace = _runtime_namespace()
    namespace.pop("ORDER_CLAIMS")

    with pytest.raises(RuntimeError, match="ORDER_CLAIMS"):
        runtime.configure_self_service_runtime(namespace)
