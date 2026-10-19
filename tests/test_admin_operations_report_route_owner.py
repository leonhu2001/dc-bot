from __future__ import annotations

from pathlib import Path

from fastapi.routing import APIRoute

from web.app.routers import admin_operations_report, admin_payout_summary


ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "web/app/main.py"
REPORT_PATH = "/admin/payouts/report"


def _get_report_routes(routes) -> list[APIRoute]:
    return [
        route
        for route in routes
        if isinstance(route, APIRoute)
        and route.path == REPORT_PATH
        and "GET" in route.methods
    ]


def test_payout_summary_no_longer_owns_operations_report_route() -> None:
    assert _get_report_routes(admin_payout_summary.router.routes) == []


def test_operations_report_has_one_canonical_route_owner() -> None:
    owner_routes = _get_report_routes(admin_operations_report.router.routes)

    assert len(owner_routes) == 1
    assert owner_routes[0].endpoint.__module__ == "web.app.routers.admin_operations_report"


def test_main_registers_canonical_operations_report_router_without_mutation() -> None:
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert (
        "from web.app.routers.admin_operations_report import router as "
        "admin_operations_report_router"
    ) in source
    assert "app.include_router(admin_operations_report_router)" in source
    assert "admin_payout_summary_router.routes" not in source
