from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = ROOT / "services" / "order_lifecycle_runtime.py"
TEST = ROOT / "tests" / "test_payment_method_runtime_contract.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one match in {path}, found {count}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    LIFECYCLE,
    "import asyncio\nimport discord\n\n\n_REQUIRED_DEPENDENCIES = (",
    "import asyncio\nimport discord\n\nfrom services.payment_methods import WALLET_PAYMENT_METHOD\n\n\n_REQUIRED_DEPENDENCIES = (",
)

TEST.write_text(
    '''from __future__ import annotations\n\nimport ast\nimport inspect\nfrom pathlib import Path\n\nfrom services.payment_methods import PAYMENT_METHOD_OPTIONS, WALLET_PAYMENT_METHOD\nfrom services import order_lifecycle_runtime\nfrom services import order_runtime\nfrom services import order_payment_runtime\n\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef test_wallet_payment_method_is_canonical_and_available_in_every_payment_runtime():\n    assert WALLET_PAYMENT_METHOD == "我的錢包"\n    assert WALLET_PAYMENT_METHOD in PAYMENT_METHOD_OPTIONS\n    assert order_runtime.WALLET_PAYMENT_METHOD == WALLET_PAYMENT_METHOD\n    assert order_payment_runtime.WALLET_PAYMENT_METHOD == WALLET_PAYMENT_METHOD\n    assert order_lifecycle_runtime.WALLET_PAYMENT_METHOD == WALLET_PAYMENT_METHOD\n\n\ndef test_receipt_finalizer_has_wallet_method_in_its_defining_global_scope():\n    # Regression for the live failure where wallet debit succeeded, then\n    # ensure_payment_submit_receipt crashed with NameError while building receipt status.\n    assert (\n        order_lifecycle_runtime.ensure_payment_submit_receipt.__globals__["WALLET_PAYMENT_METHOD"]\n        == WALLET_PAYMENT_METHOD\n    )\n\n\ndef test_payment_runtime_configuration_no_longer_requires_wallet_label_injection():\n    parameters = inspect.signature(order_payment_runtime.configure_order_payment_runtime).parameters\n    assert "wallet_payment_method" not in parameters\n\n\ndef test_order_runtime_uses_canonical_payment_constants():\n    source = inspect.getsource(order_runtime)\n    assert "from services.payment_methods import PAYMENT_METHOD_OPTIONS, WALLET_PAYMENT_METHOD" in source\n    assert 'wallet_payment_method=namespace["WALLET_PAYMENT_METHOD"]' not in source\n\n\ndef _module_level_bindings(tree: ast.Module) -> set[str]:\n    bindings: set[str] = set()\n    for node in tree.body:\n        if isinstance(node, ast.ImportFrom):\n            for alias in node.names:\n                bindings.add(alias.asname or alias.name)\n        elif isinstance(node, ast.Import):\n            for alias in node.names:\n                bindings.add(alias.asname or alias.name.split(".")[0])\n        elif isinstance(node, (ast.Assign, ast.AnnAssign)):\n            targets = node.targets if isinstance(node, ast.Assign) else [node.target]\n            for target in targets:\n                if isinstance(target, ast.Name):\n                    bindings.add(target.id)\n        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):\n            bindings.add(node.name)\n    return bindings\n\n\ndef test_every_module_loading_wallet_payment_method_binds_it_locally():\n    missing: list[str] = []\n    for path in ROOT.rglob("*.py"):\n        if any(part.startswith(".") for part in path.relative_to(ROOT).parts):\n            continue\n        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))\n        loads_symbol = any(\n            isinstance(node, ast.Name)\n            and isinstance(node.ctx, ast.Load)\n            and node.id == "WALLET_PAYMENT_METHOD"\n            for node in ast.walk(tree)\n        )\n        if loads_symbol and "WALLET_PAYMENT_METHOD" not in _module_level_bindings(tree):\n            missing.append(str(path.relative_to(ROOT)))\n\n    assert not missing, (\n        "WALLET_PAYMENT_METHOD is loaded without a module-level import/definition in: "\n        + ", ".join(sorted(missing))\n    )\n''',
    encoding="utf-8",
)

print("wallet lifecycle constant fix applied")
