from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MULTI_SEAT_POLICY = ROOT / "services/multi_seat_order_policy_20261028.py"
DYNAMIC_POINT_POLICY = ROOT / "services/dynamic_game_point_policy.py"
WEB_SERVICES_INIT = ROOT / "web/app/services/__init__.py"


def _assigned_attribute_paths(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = str(node.module or "")
            for item in node.names:
                aliases[item.asname or item.name] = f"{module}.{item.name}"
        elif isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name] = item.name

    result: set[str] = set()
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            else:
                targets = [node.target]
        for target in targets:
            if not isinstance(target, ast.Attribute) or not isinstance(target.value, ast.Name):
                continue
            owner = aliases.get(target.value.id, target.value.id)
            result.add(f"{owner}.{target.attr}")
    return result


def test_multi_seat_policy_does_not_replace_canonical_calculators():
    assigned = _assigned_attribute_paths(MULTI_SEAT_POLICY)
    forbidden_suffixes = {
        ".calculate_price",
        ".is_service_bonus_allowed_for_rule",
        ".calculate_service_bonus_point_cost",
        ".check_order_point_benefit_allowed",
    }
    offenders = {
        path
        for path in assigned
        if any(path.endswith(suffix) for suffix in forbidden_suffixes)
    }
    assert offenders == set(), f"multi-seat runtime rebinds canonical rules: {sorted(offenders)}"


def test_dynamic_point_policy_cannot_grow_new_cross_module_rule_overrides():
    assigned = _assigned_attribute_paths(DYNAMIC_POINT_POLICY)
    forbidden_suffixes = {
        ".is_service_bonus_allowed_for_rule",
        ".uses_dynamic_service_point_cost",
        ".calculate_service_bonus_point_cost",
        ".check_order_point_benefit_allowed",
        ".is_service_point_benefit_enabled",
    }
    offenders = {
        path
        for path in assigned
        if any(path.endswith(suffix) for suffix in forbidden_suffixes)
    }
    assert offenders == set(), f"dynamic point policy restored retired rule overrides: {sorted(offenders)}"


def test_web_services_init_does_not_rewrite_group_specs_at_import_time():
    source = WEB_SERVICES_INIT.read_text(encoding="utf-8")
    assert "GROUP_SPECS" not in source
    assert "_spec[" not in source
