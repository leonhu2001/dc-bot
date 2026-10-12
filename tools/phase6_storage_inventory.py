from __future__ import annotations

import ast
import builtins
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "services/order_runtime.py"
SOURCE = PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
TARGETS = {
    "store_dispatch_claim_panel",
    "lock_dispatch_claim_panel",
    "resume_stored_order",
}

module_defs = {
    item.name: item
    for item in TREE.body
    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
}

print("large module nodes:")
for name, node in sorted(
    module_defs.items(),
    key=lambda pair: getattr(pair[1], "end_lineno", pair[1].lineno) - pair[1].lineno,
    reverse=True,
):
    span = getattr(node, "end_lineno", node.lineno) - node.lineno + 1
    if span >= 50:
        print(f"  {type(node).__name__} {name}: {node.lineno}-{node.end_lineno} ({span})")

builtin_names = set(dir(builtins))
for target in TARGETS:
    node = module_defs.get(target)
    if node is None:
        print(f"\n{target}: MISSING")
        continue
    params = {
        arg.arg for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    } if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else set()
    stored = {
        child.id for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Param))
    }
    loaded = {
        child.id for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    }
    free = sorted(loaded - params - stored - builtin_names - TARGETS)
    print(f"\n{target}: {node.lineno}-{node.end_lineno}")
    print("  free:", ", ".join(free))
    print("  module defs:", ", ".join(sorted(set(free) & module_defs.keys())))
    imports = [ast.unparse(child) for child in ast.walk(node) if isinstance(child, (ast.Import, ast.ImportFrom))]
    if imports:
        print("  local imports:")
        for item in imports:
            print("   ", item)
