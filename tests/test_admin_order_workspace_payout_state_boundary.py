from pathlib import Path


ROUTER = Path("web/app/routers/admin_order_workspace.py")
PAYOUT_STATE = Path("web/app/services/admin_order_workspace_payout_state.py")


def test_admin_order_workspace_payout_state_is_extracted_from_router():
    router_source = ROUTER.read_text(encoding="utf-8")
    service_source = PAYOUT_STATE.read_text(encoding="utf-8")

    assert "from web.app.services.admin_order_workspace_payout_state import (" in router_source

    for helper in (
        "_mw_r8_jsonable_row",
        "_mw_r8_snapshot_payout_status",
        "_mw_r8_restore_payout_status",
        "_mw_r8_cs_payout_rows",
    ):
        assert f"def {helper}(" not in router_source
        assert f"def {helper}(" in service_source


def test_admin_order_workspace_payout_state_owns_payout_status_sql():
    router_source = ROUTER.read_text(encoding="utf-8")
    service_source = PAYOUT_STATE.read_text(encoding="utf-8")

    assert "UPDATE worker_payouts\n                SET payout_status" not in router_source
    assert "UPDATE customer_service_payouts\n                SET payout_status" not in router_source
    assert "FROM customer_service_payouts\n            WHERE order_id" not in router_source

    assert "UPDATE worker_payouts" in service_source
    assert "UPDATE customer_service_payouts" in service_source
    assert "FROM customer_service_payouts" in service_source
