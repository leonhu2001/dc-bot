from __future__ import annotations

import ast
import inspect
from pathlib import Path

from services.payment_methods import PAYMENT_METHOD_OPTIONS, WALLET_PAYMENT_METHOD
from services import order_lifecycle_runtime
from services import order_runtime
from services import order_payment_runtime


ROOT = Path(__file__).resolve().parents[1]


def test_wallet_payment_method_is_canonical_and_available_in_every_payment_runtime():
    assert WALLET_PAYMENT_METHOD == "我的錢包"
    assert WALLET_PAYMENT_METHOD in PAYMENT_METHOD_OPTIONS
    assert order_runtime.WALLET_PAYMENT_METHOD == WALLET_PAYMENT_METHOD
    assert order_payment_runtime.WALLET_PAYMENT_METHOD == WALLET_PAYMENT_METHOD
    assert order_lifecycle_runtime.WALLET_PAYMENT_METHOD == WALLET_PAYMENT_METHOD


def test_receipt_finalizer_has_wallet_method_in_its_defining_global_scope():
    # Regression for the live failure where wallet debit succeeded, then
    # ensure_payment_submit_receipt crashed with NameError while building receipt status.
    assert (
        order_lifecycle_runtime.ensure_payment_submit_receipt.__globals__["WALLET_PAYMENT_METHOD"]
        == WALLET_PAYMENT_METHOD
    )


def test_payment_runtime_configuration_no_longer_requires_wallet_label_injection():
    parameters = inspect.signature(order_payment_runtime.configure_order_payment_runtime).parameters
    assert "wallet_payment_method" not in parameters


def test_order_runtime_uses_canonical_payment_constants():
    source = inspect.getsource(order_runtime)
    assert "from services.payment_methods import PAYMENT_METHOD_OPTIONS, WALLET_PAYMENT_METHOD" in source
    assert 'wallet_payment_method=namespace["WALLET_PAYMENT_METHOD"]' not in source


def _module_level_bindings(tree: ast.Module) -> set[str]:
    bindings: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bindings.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bindings.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    bindings.add(target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings.add(node.name)
    return bindings


def test_every_module_loading_wallet_payment_method_binds_it_locally():
    missing: list[str] = []
    for path in ROOT.rglob("*.py"):
        if any(part.startswith(".") for part in path.relative_to(ROOT).parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        loads_symbol = any(
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id == "WALLET_PAYMENT_METHOD"
            for node in ast.walk(tree)
        )
        if loads_symbol and "WALLET_PAYMENT_METHOD" not in _module_level_bindings(tree):
            missing.append(str(path.relative_to(ROOT)))

    assert not missing, (
        "WALLET_PAYMENT_METHOD is loaded without a module-level import/definition in: "
        + ", ".join(sorted(missing))
    )
