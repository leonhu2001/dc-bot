from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "DispatchCancelClaimButton",
    "sync_single_discord_claim_event_to_web",
    "maybe_handle_prepay_acceptance_claim",
    "maybe_handle_prepay_acceptance_unclaim",
    "DispatchClaimView",
    "delete_dispatch_claim_panel_for_order",
    "sync_web_order_status_from_bot",
}


def _top_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _dispatch_namespace(**overrides):
    async def async_noop(*_args, **_kwargs):
        return None

    namespace = {
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
    namespace.update(overrides)
    return namespace


def test_dispatch_implementation_has_single_canonical_owner():
    legacy = _top_level_names(ROOT / "services/order_runtime.py")
    dispatch = _top_level_names(ROOT / "services/order_dispatch_runtime.py")
    assert TARGETS.isdisjoint(legacy)
    assert TARGETS.issubset(dispatch)


def test_order_runtime_reexports_dispatch_public_surface():
    import services.order_dispatch_runtime as dispatch
    import services.order_runtime as order_runtime

    for name in TARGETS:
        assert getattr(order_runtime, name) is getattr(dispatch, name)


def test_dispatch_runtime_has_no_bot_entrypoint_dependency():
    source = (ROOT / "services/order_dispatch_runtime.py").read_text(encoding="utf-8")
    assert "import bot" not in source
    assert "from bot import" not in source


def test_dispatch_runtime_configuration_is_explicitly_scoped():
    import services.order_dispatch_runtime as dispatch

    marker = object()
    dispatch.configure_order_dispatch_runtime(
        _dispatch_namespace(
            ORDER_CLAIMS=marker,
            UNRELATED_SENTINEL=object(),
        )
    )
    assert dispatch.DISPATCH_CHANNEL_ID == 123
    assert dispatch.ORDER_CLAIMS is marker
    assert not hasattr(dispatch, "UNRELATED_SENTINEL")
