from pathlib import Path


ROUTER = Path("web/app/routers/admin_order_workspace.py")
FIELD_WRITE = Path("web/app/services/admin_order_workspace_field_write.py")


def test_admin_order_workspace_field_sql_is_extracted_from_router():
    router_source = ROUTER.read_text(encoding="utf-8")
    service_source = FIELD_WRITE.read_text(encoding="utf-8")

    assert "from web.app.services.admin_order_workspace_field_write import (" in router_source
    assert "write_order_workspace_fields(" in router_source

    assert "UPDATE web_orders\n            SET" not in router_source
    assert "UPDATE order_acceptance_meta" not in router_source

    assert "UPDATE web_orders" in service_source
    assert "UPDATE order_acceptance_meta" in service_source


def test_admin_order_workspace_field_service_owns_financial_gap_preservation():
    router_source = ROUTER.read_text(encoding="utf-8")
    service_source = FIELD_WRITE.read_text(encoding="utf-8")

    assert "preserve_order_financial_gaps" not in router_source
    assert "preserve_order_financial_gaps" in service_source
    assert "previous_payout_base_amount" in service_source
    assert "new_payout_base_amount" in service_source
