from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "web" / "app" / "routers" / "admin_order_workspace.py"
SOURCE = PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
LINES = SOURCE.splitlines()


def loaded_names(node: ast.AST) -> set[str]:
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    }


def main() -> None:
    print(f"file bytes={PATH.stat().st_size} lines={len(LINES)}")
    defs = []
    defined_names = {
        node.name
        for node in TREE.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assigned_names = {
        target.id
        for node in TREE.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name)
    }

    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            end = getattr(node, "end_lineno", node.lineno)
            defs.append((end - node.lineno + 1, node.lineno, end, type(node).__name__, node.name, node))

    print("\n=== TOP DEFINITIONS ===")
    for length, start, end, kind, name, _ in sorted(defs, reverse=True):
        print(f"{start:5d}-{end:5d} {length:5d} {kind:16s} {name}")

    candidates = [item for item in defs if item[4].startswith("_mw4a2r6_")]
    print("\n=== PREFIX CLUSTER DEPENDENCIES ===")
    counts = Counter()
    for _, _, _, _, name, node in candidates:
        args = {arg.arg for arg in ast.walk(node) if isinstance(arg, ast.arg)}
        for dep in loaded_names(node) - args:
            if dep in defined_names or dep in assigned_names:
                counts[dep] += 1
    for dep, count in counts.most_common():
        print(f"{count:2d} {dep}")

    print("\n=== ROUTE REFERENCES TO PREFIX HELPERS ===")
    candidate_names = {item[4] for item in candidates}
    candidate_ranges = [(item[1], item[2]) for item in candidates]
    for name in sorted(candidate_names):
        refs = []
        for idx, line in enumerate(LINES, 1):
            if name not in line:
                continue
            if any(start <= idx <= end for start, end in candidate_ranges):
                continue
            refs.append((idx, line.strip()))
        if refs:
            print(name)
            for idx, line in refs:
                print(f"  {idx}: {line[:220]}")


if __name__ == "__main__":
    main()
