from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICES_INIT = ROOT / "services/__init__.py"


def _module_level_installer_calls() -> list[str]:
    tree = ast.parse(SERVICES_INIT.read_text(encoding="utf-8"))
    calls: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        fn = node.value.func
        if isinstance(fn, ast.Name) and fn.id.startswith("_install"):
            calls.append(fn.id)
    return calls


def test_services_startup_installers_are_not_called_twice():
    counts = Counter(_module_level_installer_calls())
    duplicates = {name: count for name, count in counts.items() if count > 1}
    assert duplicates == {}, f"duplicate services startup installers: {duplicates}"


def test_financial_copy_policy_has_one_owner():
    source = SERVICES_INIT.read_text(encoding="utf-8")
    # benefit_runtime_integration owns this integration. Importing/calling the same
    # installer again from services.__init__ makes behavior depend on startup order.
    assert "install_self_service_financial_copy_policy" not in source
