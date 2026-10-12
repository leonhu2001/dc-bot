from __future__ import annotations

import ast
import builtins
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "services/order_runtime.py"
SOURCE = PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
TARGET = "finalize_accepted_pending_payment"

node = next(
    item for item in TREE.body
    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == TARGET
)
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
builtin_names = set(dir(builtins))
free = sorted(loaded - params - stored - builtin_names)
print(f"{TARGET}: {node.lineno}-{node.end_lineno} ({node.end_lineno-node.lineno+1} lines)")
print("free globals:")
for name in free:
    print(" ", name)

print("\nimports inside target:")
for child in ast.walk(node):
    if isinstance(child, (ast.Import, ast.ImportFrom)):
        print(" ", ast.unparse(child))

print("\nmodule defs referenced:")
module_defs = {
    item.name
    for item in TREE.body
    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
}
for name in sorted(set(free) & module_defs):
    print(" ", name)
