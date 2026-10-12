from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    "bot.py",
    "services/order_runtime.py",
    "services/self_service_runtime.py",
    "web/app/routers/admin.py",
)


def _node_kind(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    if isinstance(node, ast.ClassDef):
        return "class"
    return type(node).__name__


def main() -> None:
    for relative in TARGETS:
        path = ROOT / relative
        source = path.read_text(encoding="utf-8-sig")
        lines = source.splitlines()
        tree = ast.parse(source, filename=str(path))

        print("=" * 100)
        print(f"MODULE {relative} bytes={path.stat().st_size} lines={len(lines)}")
        print("=" * 100)

        for node in tree.body:
            if not isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            ):
                continue
            start = int(node.lineno)
            end = int(getattr(node, "end_lineno", start) or start)
            name = getattr(node, "name", "<unknown>")
            print(f"{start:5d}-{end:5d}  {_node_kind(node):9s}  {name}")


if __name__ == "__main__":
    main()
