from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = ROOT / "web/app/services/operations_report.py"
ROUTER_PATH = ROOT / "web/app/routers/admin_operations_report.py"
AI_PATH = ROOT / "web/app/services/ai_operations.py"


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_operations_report_builder_is_owned_by_service() -> None:
    service_functions = _top_level_functions(SERVICE_PATH)
    router_functions = _top_level_functions(ROUTER_PATH)

    assert "build_operations_report" in service_functions
    assert "build_operations_report" not in router_functions


def test_operations_report_service_does_not_import_router_layer() -> None:
    source = SERVICE_PATH.read_text(encoding="utf-8")
    assert "web.app.routers" not in source


def test_router_and_ai_depend_on_operations_report_service() -> None:
    expected = "from web.app.services.operations_report import build_operations_report"

    router_source = ROUTER_PATH.read_text(encoding="utf-8")
    ai_source = AI_PATH.read_text(encoding="utf-8")

    assert expected in router_source
    assert expected in ai_source
    assert "from web.app.routers.admin_operations_report import build_operations_report" not in ai_source
