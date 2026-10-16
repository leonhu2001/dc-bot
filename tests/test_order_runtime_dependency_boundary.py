from typing import Any, Mapping

import discord

from services import order_runtime


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


def test_order_runtime_legacy_injection_cannot_shadow_module_owned_imports():
    originals = {
        "Any": Any,
        "Mapping": Mapping,
        "discord": discord,
    }
    marker = object()

    order_runtime.configure_order_runtime(
        {
            **_dispatch_namespace(),
            **{name: object() for name in originals},
            "_order_runtime_boundary_marker": marker,
        }
    )

    for name, original in originals.items():
        assert getattr(order_runtime, name) is original
    assert order_runtime._order_runtime_boundary_marker is marker


def test_order_runtime_owned_dependency_names_are_explicit():
    assert order_runtime._MODULE_OWNED_RUNTIME_NAMES == frozenset(
        {
            "Any",
            "Mapping",
            "discord",
        }
    )
