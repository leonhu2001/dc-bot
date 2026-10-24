import ast
from pathlib import Path


_INSTALLERS = {
    "services/quick_order_v2_select_display.py": "install_quick_order_v2_select_display",
    "services/quick_order_v2_fixes.py": "install_quick_order_v2_fixes",
    "services/quick_order_v2_production.py": "install_quick_order_v2_production",
}


def _function_source(path: str, function_name: str) -> str:
    source = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"missing installer {function_name} in {path}")


def test_quick_order_installers_do_not_schedule_historical_repairs():
    for path, function_name in _INSTALLERS.items():
        installer_source = _function_source(path, function_name)
        assert "repair_existing_" not in installer_source
        assert "create_task" not in installer_source


def test_quick_order_historical_repairs_remain_explicitly_callable():
    expected_repairs = {
        "services/quick_order_v2_select_display.py": "repair_existing_quick_order_selects",
        "services/quick_order_v2_fixes.py": "repair_existing_quick_order_v2_tickets",
        "services/quick_order_v2_production.py": "repair_existing_quick_order_v2_copy",
    }

    for path, repair_name in expected_repairs.items():
        source = Path(path).read_text(encoding="utf-8")
        assert f"async def {repair_name}" in source
