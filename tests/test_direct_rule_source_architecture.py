from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

RETIRED_RUNTIME_PATCH_MODULES = (
    "services/dynamic_game_point_policy.py",
    "services/multi_seat_order_policy_20261028.py",
    "services/entertainment_companion_policy_20261028.py",
    "services/loyalty_companion_fix_20261029.py",
)


def _external_attribute_assignments(path: str) -> list[str]:
    source = (ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=path)
    result: list[str] = []

    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]

        for target in targets:
            if isinstance(target, ast.Attribute):
                result.append(ast.unparse(target))

    return result


def test_retired_policy_modules_do_not_monkey_patch_runtime_modules():
    offenders = {
        path: assignments
        for path in RETIRED_RUNTIME_PATCH_MODULES
        if (assignments := _external_attribute_assignments(path))
    }
    assert offenders == {}


def test_startup_does_not_install_retired_rule_override_layers():
    service_init = (ROOT / "services/__init__.py").read_text(encoding="utf-8")
    benefit_runtime = (ROOT / "services/benefit_runtime_integration.py").read_text(encoding="utf-8")

    assert "install_dynamic_game_point_policy" not in service_init
    assert "install_point_service_financial_runtime_20261028" not in service_init
    assert "install_dynamic_game_point_policy" not in benefit_runtime
    assert "install_loyalty_companion_fix_20261029" not in benefit_runtime


def test_direct_business_rules_live_in_canonical_modules():
    catalog = (ROOT / "services/point_benefit_catalog.py").read_text(encoding="utf-8")
    financials = (ROOT / "services/self_service_financials.py").read_text(encoding="utf-8")
    loyalty = (ROOT / "services/loyalty_benefits.py").read_text(encoding="utf-8")

    assert "is_rule_service_bonus_supported(rule)" in catalog
    assert "funded_point_service_seats" in financials
    assert "point_service_value = one_seat_point_service_value * funded_point_service_seats" in financials
    assert "player_count_prices" in loyalty
    assert "def _selected_unit_total" in loyalty
