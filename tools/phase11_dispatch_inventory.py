from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "services" / "order_runtime.py"
source = PATH.read_text(encoding="utf-8")
tree = ast.parse(source)

targets = {
    "DispatchCancelClaimButton",
    "sync_single_discord_claim_event_to_web",
    "maybe_handle_prepay_acceptance_claim",
    "maybe_handle_prepay_acceptance_unclaim",
    "DispatchClaimView",
    "delete_dispatch_claim_panel_for_order",
    "sync_web_order_status_from_bot",
}

print("TOP_LEVEL_DEFINITIONS")
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        print(f"{node.name}\t{node.lineno}-{node.end_lineno}")

print("\nTARGET_GLOBAL_LOADS")
target_nodes = [
    node for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    and node.name in targets
]
for node in target_nodes:
    loads = sorted({
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    })
    print(f"{node.name}: {', '.join(loads)}")

print("\nREFERENCES_TO_TARGETS_OUTSIDE_TARGETS")
for node in tree.body:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        continue
    if node.name in targets:
        continue
    refs = sorted({
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name)
        and isinstance(child.ctx, ast.Load)
        and child.id in targets
    })
    if refs:
        print(f"{node.name}: {', '.join(refs)}")
