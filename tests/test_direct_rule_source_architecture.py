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


def test_special_receiver_roles_are_defined_directly_not_reinstalled_at_import():
    source = (ROOT / "services/__init__.py").read_text(encoding="utf-8")
    rules = (ROOT / "services/order_rules.py").read_text(encoding="utf-8")

    assert "install_special_receiver_roles_20261103" not in source
    assert 'AW_COLLISION_RECEIVER_ROLE_ID = "1571080769407942787"' in rules
    assert 'COIN_WASH_AW_RECEIVER_ROLE_ID = "1565369317929918554"' in rules
    assert "SPECIAL_RECEIVER_ROLE_IDS_BY_KEY: dict[str, str] = {" in rules


def test_four_delta_buttons_are_owned_by_core_view_not_startup_monkey_patch():
    core = (ROOT / "services/quick_order_v2.py").read_text(encoding="utf-8")
    fixes = (ROOT / "services/quick_order_v2_fixes.py").read_text(encoding="utf-8")

    block = core.split("class QuickDeltaEntryView(", 1)[1].split("class QuickVipGameSelect(", 1)[0]
    assert "for emoji, label, category, style in _DELTA_BUTTONS:" in block
    assert "row=0," in block
    assert "row=0 if index < 3 else 1" not in block
    assert "quick.QuickDeltaEntryView.__init__ =" not in fixes


def test_one_life_clear_does_not_need_runtime_rule_or_database_patch():
    source = (ROOT / "services/__init__.py").read_text(encoding="utf-8")
    rules = (ROOT / "services/order_rules.py").read_text(encoding="utf-8")
    catalog = (ROOT / "services/orders.py").read_text(encoding="utf-8")
    prices = (ROOT / "services/quick_order_v2_price_lists.py").read_text(encoding="utf-8")
    assert "install_delta_fun_one_life_clear_20261102" not in source
    assert 'FULL_SOURCE_AUTHORITY_RULE_KEYS = frozenset({"fun_eat_yourself"})' in rules
    assert '13888' in rules
    assert '"想吃自己打": "fun_eat_yourself"' in catalog
    assert '"label": "一命通關"' in prices
