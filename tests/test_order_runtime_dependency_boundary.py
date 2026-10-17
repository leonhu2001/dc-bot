from typing import Any, Mapping

import discord

from services import order_runtime
from services.orders import ORDER_CATEGORY_LABELS


EXPECTED_BINDING_NAMES = frozenset(
    {
        "DB_FILE",
        "DISPATCH_CHANNEL_ID",
        "ORDER_CONTROL_SELECTIONS",
        "SELF_SERVICE_ORDER_SELECTIONS",
        "SelfServiceOrderView",
        "_defer_and_refresh_self_service_panel",
        "_get_rule_from_self_service_data",
        "build_payment_method_embed",
        "build_self_service_panel_embed",
        "can_operate_self_service_order",
        "format_t_amount",
        "get_order_customer_id_from_channel",
        "get_wallet_balance",
        "is_customer_staff",
        "remember_order_data",
        "rename_ticket_channel",
        "send_order_log",
    }
)


def _dispatch_namespace() -> dict[str, object]:
    async def async_noop(*_args, **_kwargs):
        return None

    return {
        "BOOSTER_RECEIVER_ROLE_ID": 1,
        "DISPATCH_CHANNEL_ID": 123,
        "ORDER_CLAIMS": {},
        "SELF_SERVICE_ORDER_SELECTIONS": {},
        "_apply_acceptance_state_to_claim_data": lambda *_args, **_kwargs: None,
        "_member_display_name": lambda member: str(getattr(member, "id", "worker")),
        "_member_role_id_texts": lambda _member: [],
        "_order_requires_credentials": lambda _data: False,
        "revoke_order_credential_messages": async_noop,
        "send_acceptance_payment_panel_if_ready": async_noop,
    }


def test_order_runtime_namespace_binding_is_explicitly_scoped(monkeypatch):
    originals = {
        "Any": Any,
        "Mapping": Mapping,
        "discord": discord,
        "ORDER_CATEGORY_LABELS": ORDER_CATEGORY_LABELS,
    }
    order_control = {}
    marker = object()

    monkeypatch.delattr(order_runtime, "_order_runtime_boundary_marker", raising=False)
    monkeypatch.setattr(order_runtime, "_CONFIGURED", False)

    order_runtime.configure_order_runtime(
        {
            **_dispatch_namespace(),
            **{name: object() for name in originals},
            "ORDER_CONTROL_SELECTIONS": order_control,
            "_order_runtime_boundary_marker": marker,
        }
    )

    assert order_runtime._CONFIGURED is True
    assert order_runtime.ORDER_CONTROL_SELECTIONS is order_control
    assert not hasattr(order_runtime, "_order_runtime_boundary_marker")
    for name, original in originals.items():
        assert getattr(order_runtime, name) is original


def test_order_runtime_binding_allowlist_matches_direct_runtime_dependencies():
    assert order_runtime._ORDER_RUNTIME_BINDING_NAMES == EXPECTED_BINDING_NAMES


def test_order_runtime_owned_dependency_names_are_explicit():
    assert order_runtime._MODULE_OWNED_RUNTIME_NAMES == frozenset(
        {
            "Any",
            "Mapping",
            "discord",
        }
    )


def test_order_runtime_explicit_binding_assigns_direct_dependencies(monkeypatch):
    values = {
        "DB_FILE": object(),
        "DISPATCH_CHANNEL_ID": 987654,
        "ORDER_CONTROL_SELECTIONS": object(),
        "SELF_SERVICE_ORDER_SELECTIONS": object(),
        "SelfServiceOrderView": object(),
        "_defer_and_refresh_self_service_panel": object(),
        "_get_rule_from_self_service_data": object(),
        "build_payment_method_embed": object(),
        "build_self_service_panel_embed": object(),
        "can_operate_self_service_order": object(),
        "format_t_amount": object(),
        "get_order_customer_id_from_channel": object(),
        "get_wallet_balance": object(),
        "is_customer_staff": object(),
        "remember_order_data": object(),
        "rename_ticket_channel": object(),
        "send_order_log": object(),
    }

    for name in EXPECTED_BINDING_NAMES:
        monkeypatch.setattr(order_runtime, name, object(), raising=False)
    monkeypatch.setattr(order_runtime, "_CONFIGURED", False)

    order_runtime.configure_order_runtime_explicit(
        db_file=values["DB_FILE"],
        dispatch_channel_id=values["DISPATCH_CHANNEL_ID"],
        order_control_selections=values["ORDER_CONTROL_SELECTIONS"],
        order_selections=values["SELF_SERVICE_ORDER_SELECTIONS"],
        self_service_order_view_type=values["SelfServiceOrderView"],
        defer_and_refresh_self_service_panel=values["_defer_and_refresh_self_service_panel"],
        self_service_rule_getter=values["_get_rule_from_self_service_data"],
        payment_method_embed_builder=values["build_payment_method_embed"],
        self_service_panel_embed_builder=values["build_self_service_panel_embed"],
        can_operate_self_service_order_func=values["can_operate_self_service_order"],
        amount_formatter=values["format_t_amount"],
        order_customer_id_getter=values["get_order_customer_id_from_channel"],
        wallet_balance_getter=values["get_wallet_balance"],
        customer_staff_checker=values["is_customer_staff"],
        remember_order=values["remember_order_data"],
        ticket_channel_renamer=values["rename_ticket_channel"],
        order_log_sender=values["send_order_log"],
    )

    for name, value in values.items():
        assert getattr(order_runtime, name) is value
    assert order_runtime._CONFIGURED is False

