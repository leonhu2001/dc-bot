from pathlib import Path


def test_admin_order_workspace_data_bundle_is_owned_by_service():
    router = Path("web/app/routers/admin_order_workspace.py").read_text(encoding="utf-8")
    service = Path("web/app/services/admin_order_workspace_data.py").read_text(encoding="utf-8")

    assert "def _mw4a2r6_load_order_bundle" not in router
    assert "def _mw4a2r6_load_order_bundle" in service
    assert "def _mw4a2r6_staff_map" not in router
    assert "def _mw4a2r6_staff_map" in service
    assert "def _mw4a2r6_meta_map" not in router
    assert "def _mw4a2r6_meta_map" in service


def test_admin_order_workspace_router_keeps_http_actions_not_data_builder():
    router = Path("web/app/routers/admin_order_workspace.py").read_text(encoding="utf-8")
    service = Path("web/app/services/admin_order_workspace_data.py").read_text(encoding="utf-8")

    assert '@router.get("/admin/order-workspace/{order_id}")' in router
    assert "async def admin_order_workspace_edit_r8" in router
    assert "APIRouter" not in service
    assert "RedirectResponse" not in service
