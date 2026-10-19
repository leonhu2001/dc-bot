from pathlib import Path


ROUTER = Path("web/app/routers/admin_order_workspace.py")
META_SERVICE = Path("web/app/services/admin_order_workspace_meta.py")


def test_admin_order_workspace_meta_writes_are_extracted_from_router():
    router_source = ROUTER.read_text(encoding="utf-8")
    service_source = META_SERVICE.read_text(encoding="utf-8")

    assert "from web.app.services.admin_order_workspace_meta import (" in router_source
    assert "save_order_internal_note(" in router_source
    assert "save_order_attention(" in router_source

    assert "INSERT INTO web_admin_order_meta" not in router_source
    assert "INSERT INTO web_admin_order_meta" in service_source


def test_admin_order_workspace_meta_service_owns_shared_meta_write_helpers():
    router_source = ROUTER.read_text(encoding="utf-8")
    service_source = META_SERVICE.read_text(encoding="utf-8")

    assert "_mw4a2r6_ensure_meta_table" not in router_source
    assert "_mw4a2r6_user_name" not in router_source
    assert "_mw4a2r6_ensure_meta_table" in service_source
    assert "_mw4a2r6_user_name" in service_source

    assert "SELECT 1\n            FROM web_orders" in service_source
    assert "ON CONFLICT(order_id)" in service_source
