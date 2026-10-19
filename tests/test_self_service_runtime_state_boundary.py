from pathlib import Path


RUNTIME = Path("services/self_service_runtime.py")

LEGACY_INJECTED_GLOBALS = (
    "CUSTOMER_CATEGORY_ID",
    "CUSTOMER_ROLE_ID",
    "DISPATCH_CHANNEL_ID",
    "ORDER_CLAIMS",
    "POINT_REDEEM_ITEMS",
    "POINT_REDEEM_ITEMS_BY_KEY",
    "SELF_SERVICE_ORDER_SELECTIONS",
    "OrderControlView",
)


def test_self_service_runtime_uses_single_explicit_state_container():
    source = RUNTIME.read_text(encoding="utf-8")

    assert "@dataclass(frozen=True)" in source
    assert "class _SelfServiceRuntimeState:" in source
    assert "_RUNTIME_STATE: _SelfServiceRuntimeState | None = None" in source
    assert "def _require_runtime_state() -> _SelfServiceRuntimeState:" in source

    for legacy_name in LEGACY_INJECTED_GLOBALS:
        assert legacy_name not in source


def test_self_service_runtime_keeps_explicit_startup_and_state_forwarding():
    source = RUNTIME.read_text(encoding="utf-8")

    assert "def configure_self_service_runtime_explicit(" in source
    assert "point_redeem_items_by_key=state.point_redeem_items_by_key" in source
    assert "customer_role_id=state.customer_role_id" in source
    assert "customer_category_id=state.customer_category_id" in source
    assert "order_selections=state.order_selections" in source
    assert "order_claims=state.order_claims" in source
    assert "dispatch_channel_id=state.dispatch_channel_id" in source
    assert source.count("state = _require_runtime_state()") == 2
