from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "views" / "review.py"
SOURCE = PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
LINES = SOURCE.splitlines()

TARGET_NAMES = {
    "_worker_tip_row",
    "create_worker_tip",
    "set_worker_tip_confirmation_message",
    "mark_worker_tip_paid",
    "mark_worker_tip_cancelled",
    "has_pending_worker_tips",
    "get_pending_worker_tip_confirmations",
    "_log_worker_tip",
    "_notify_worker_tip_paid",
    "_worker_tip_preview_text",
    "WorkerTipAmountEditModal",
    "WorkerTipAmountModal",
    "WorkerTipMemberSelect",
    "WorkerTipMemberSelectView",
    "WorkerTipPaymentMethodSelect",
    "WorkerTipPaymentMethodView",
    "WorkerTipPaymentConfirmView",
}

MODULE_DEFINED = {
    node.name
    for node in TREE.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
}
MODULE_ASSIGNED = {
    target.id
    for node in TREE.body
    if isinstance(node, (ast.Assign, ast.AnnAssign))
    for target in (
        node.targets if isinstance(node, ast.Assign) else [node.target]
    )
    if isinstance(target, ast.Name)
}


def names_loaded(node: ast.AST) -> set[str]:
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    }


def main() -> None:
    print(f"review.py bytes={PATH.stat().st_size} lines={len(LINES)}")
    found = {}
    for node in TREE.body:
        name = getattr(node, "name", None)
        if name in TARGET_NAMES:
            found[name] = node
            print(
                f"TARGET {name} lines={node.lineno}-{getattr(node, 'end_lineno', node.lineno)} "
                f"size={getattr(node, 'end_lineno', node.lineno)-node.lineno+1}"
            )
    print("missing:", sorted(TARGET_NAMES - found.keys()))

    deps = Counter()
    for name, node in found.items():
        loaded = names_loaded(node)
        local_defs = {
            child.arg
            for child in ast.walk(node)
            if isinstance(child, ast.arg)
        }
        for dep in sorted(loaded - local_defs - TARGET_NAMES):
            if dep in MODULE_DEFINED or dep in MODULE_ASSIGNED or dep.startswith("_"):
                deps[dep] += 1
    print("\n=== CANDIDATE MODULE DEPS ===")
    for dep, count in deps.most_common():
        print(f"{count:2d} {dep}")

    print("\n=== REFERENCES OUTSIDE TARGET CLUSTER ===")
    target_ranges = [
        (node.lineno, getattr(node, "end_lineno", node.lineno))
        for node in found.values()
    ]
    for name in sorted(TARGET_NAMES):
        refs = []
        for idx, line in enumerate(LINES, 1):
            if name not in line:
                continue
            if any(start <= idx <= end for start, end in target_ranges):
                continue
            refs.append((idx, line.strip()))
        if refs:
            print(name)
            for idx, line in refs:
                print(f"  {idx}: {line[:220]}")

    print("\n=== WORKER TIP DDL RANGE ===")
    for idx, line in enumerate(LINES, 1):
        if "CREATE TABLE IF NOT EXISTS worker_tips" in line:
            for j in range(max(1, idx - 3), min(len(LINES), idx + 60) + 1):
                print(f"{j}: {LINES[j-1]}")
            break


if __name__ == "__main__":
    main()
