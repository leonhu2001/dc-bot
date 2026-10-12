from __future__ import annotations

import ast
import builtins
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "services/self_service_runtime.py"
SOURCE = PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
NAMES = {
    "_reorder_order_value",
    "_reorder_json_dict",
    "build_reorder_self_service_draft",
    "_reorder_message_has_component",
    "_find_reorder_panel_message",
    "ensure_reorder_ticket_panels",
    "create_reorder_ticket_from_closed_order",
}

nodes = {
    node.name: node
    for node in TREE.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in NAMES
}
missing = NAMES - nodes.keys()
if missing:
    raise SystemExit(f"missing reorder definitions: {sorted(missing)}")

builtin_names = set(dir(builtins))
module_defs = {
    node.name
    for node in TREE.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
}

for name in sorted(NAMES, key=lambda item: nodes[item].lineno):
    node = nodes[name]
    params = {
        arg.arg
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    }
    if node.args.vararg:
        params.add(node.args.vararg.arg)
    if node.args.kwarg:
        params.add(node.args.kwarg.arg)
    stored = {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Param))
    }
    loaded = {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    }
    free = sorted(
        loaded
        - params
        - stored
        - builtin_names
        - NAMES
    )
    print(f"{name}: {node.lineno}-{node.end_lineno}")
    print("  free:", ", ".join(free))

print("\nModule-owned callable/class dependencies:")
used = set()
for node in nodes.values():
    loaded = {child.id for child in ast.walk(node) if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)}
    used |= loaded & module_defs
print(", ".join(sorted(used - NAMES)))
