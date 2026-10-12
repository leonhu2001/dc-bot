from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"

BLOCK_RE = re.compile(r"<(style|script)(?:\s[^>]*)?>(.*?)</\1>", re.I | re.S)


def audit_inline_blocks() -> None:
    print("=== INLINE TEMPLATE BLOCKS ===")
    totals = {"style": 0, "script": 0}
    for path in sorted(TEMPLATES.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        matches = list(BLOCK_RE.finditer(text))
        if not matches:
            continue
        print(f"\n{path.relative_to(ROOT)}")
        for index, match in enumerate(matches, 1):
            kind = match.group(1).lower()
            body = match.group(2)
            totals[kind] += 1
            has_jinja = "{{" in body or "{%" in body or "{#" in body
            nonblank = [line for line in body.splitlines() if line.strip()]
            preview = " ".join(line.strip() for line in nonblank[:2])[:180]
            print(
                f"  {kind}#{index}: lines={len(body.splitlines())} chars={len(body)} "
                f"jinja={'yes' if has_jinja else 'no'} preview={preview!r}"
            )
    print(f"\nTOTAL style={totals['style']} script={totals['script']}")


def audit_module(path_text: str) -> None:
    path = ROOT / path_text
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    rows = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            end = getattr(node, "end_lineno", node.lineno)
            rows.append((end - node.lineno + 1, node.lineno, end, type(node).__name__, node.name))
    rows.sort(reverse=True)
    print(f"\n=== {path_text} bytes={path.stat().st_size} lines={len(source.splitlines())} ===")
    for length, start, end, kind, name in rows[:30]:
        print(f"{start:5d}-{end:5d} {length:5d} {kind:16s} {name}")


def main() -> None:
    audit_inline_blocks()
    for name in [
        "bot.py",
        "views/review.py",
        "services/order_runtime.py",
        "services/self_service_runtime.py",
        "web/app/routers/admin_order_workspace.py",
    ]:
        audit_module(name)


if __name__ == "__main__":
    main()
