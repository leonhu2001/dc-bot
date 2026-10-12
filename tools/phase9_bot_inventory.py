from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "bot.py"
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
    print(f"bot.py bytes={PATH.stat().st_size} lines={len(LINES)}")
    defs = []
    top_names = {
        node.name
        for node in TREE.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assigned = {
        target.id
        for node in TREE.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name)
    }

    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            end = getattr(node, "end_lineno", node.lineno)
            length = end - node.lineno + 1
            defs.append((length, node.lineno, end, type(node).__name__, node.name, node))

    print("\n=== TOP 80 DEFINITIONS BY SIZE ===")
    for length, start, end, kind, name, _ in sorted(defs, reverse=True)[:80]:
        print(f"{start:5d}-{end:5d} {length:5d} {kind:16s} {name}")

    print("\n=== NAME CLUSTERS ===")
    prefixes = ["voice", "vip", "receipt", "payment", "dispatch", "admin", "order", "ticket", "wallet", "staff"]
    for prefix in prefixes:
        rows = [item for item in defs if prefix in item[4].lower()]
        if not rows:
            continue
        print(f"\n[{prefix}] count={len(rows)} lines={sum(item[0] for item in rows)}")
        for length, start, end, kind, name, _ in sorted(rows, key=lambda item: item[1]):
            print(f"  {start:5d}-{end:5d} {length:4d} {kind:16s} {name}")

    print("\n=== LARGE DEF DEPENDENCIES (>=60 lines) ===")
    for length, start, end, kind, name, node in sorted(defs, key=lambda item: item[1]):
        if length < 60:
            continue
        args = {arg.arg for arg in ast.walk(node) if isinstance(arg, ast.arg)}
        deps = Counter(
            dep for dep in loaded_names(node) - args
            if dep in top_names or dep in assigned
        )
        print(f"\n{name} [{start}-{end}] {length} lines")
        print("  " + ", ".join(f"{dep}:{count}" for dep, count in deps.most_common(30)))


if __name__ == "__main__":
    main()
