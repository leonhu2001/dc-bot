import inspect
from pathlib import Path

from services.web_sync import runtime as web_sync_runtime
from services.web_sync import self_service_bridge


EXPECTED_BRIDGE_DEPENDENCIES = {
    "customer_role_id",
    "order_control_view_type",
    "order_selections",
}


def test_web_sync_self_service_bridge_uses_explicit_dependencies():
    signature = inspect.signature(
        self_service_bridge.configure_web_sync_self_service_bridge
    )
    assert set(signature.parameters) == EXPECTED_BRIDGE_DEPENDENCIES
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )


def test_r13_self_service_bridge_is_physically_extracted():
    runtime_source = Path("services/web_sync/runtime.py").read_text(
        encoding="utf-8"
    )
    bridge_source = Path(
        "services/web_sync/self_service_bridge.py"
    ).read_text(encoding="utf-8")

    assert "def _r13_seed_website_order_into_self_service" not in runtime_source
    assert "async def _r13_ensure_website_unified_panels" not in runtime_source
    assert "def _r13_seed_website_order_into_self_service" in bridge_source
    assert "async def _r13_ensure_website_unified_panels" in bridge_source
    assert "import bot" not in bridge_source
    assert "from bot import" not in bridge_source
    assert (
        web_sync_runtime._r13_seed_website_order_into_self_service
        is self_service_bridge._r13_seed_website_order_into_self_service
    )
    assert (
        web_sync_runtime._r13_ensure_website_unified_panels
        is self_service_bridge._r13_ensure_website_unified_panels
    )
