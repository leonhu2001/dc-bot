from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"

BLOCK_RE = re.compile(r"<(style|script)(?:\s[^>]*)?>(.*?)</\1>", re.I | re.S)
STYLE_ATTR_RE = re.compile(r"\sstyle\s*=", re.I)
EVENT_ATTR_RE = re.compile(r"\son[a-z0-9_-]+\s*=", re.I)
EVENT_FULL_RE = re.compile(r"\s(on[a-z0-9_-]+)\s*=\s*([\"'])(.*?)\2", re.I | re.S)
STYLE_FULL_RE = re.compile(r"\sstyle\s*=\s*([\"'])(.*?)\1", re.I | re.S)


def line_for(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def audit_inline_blocks() -> None:
    print("=== INLINE TEMPLATE BLOCKS ===")
    totals = {"style": 0, "script": 0}
    style_attrs = 0
    event_attrs = 0
    for path in sorted(TEMPLATES.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        matches = list(BLOCK_RE.finditer(text))
        current_style_attrs = len(STYLE_ATTR_RE.findall(text))
        current_event_attrs = len(EVENT_ATTR_RE.findall(text))
        style_attrs += current_style_attrs
        event_attrs += current_event_attrs
        if matches or current_style_attrs or current_event_attrs:
            print(f"\n{path.relative_to(ROOT)} style_attrs={current_style_attrs} event_attrs={current_event_attrs}")
        for match in EVENT_FULL_RE.finditer(text):
            value = " ".join(match.group(3).split())[:220]
            print(f"  EVENT line={line_for(text, match.start())} {match.group(1)}={value!r}")
        for match in STYLE_FULL_RE.finditer(text):
            value = " ".join(match.group(2).split())[:180]
            print(f"  STYLE_ATTR line={line_for(text, match.start())} value={value!r}")
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
    print(
        f"\nTOTAL style={totals['style']} script={totals['script']} "
        f"style_attrs={style_attrs} event_attrs={event_attrs}"
    )


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


def audit_growth_budget() -> None:
    print("\n=== ARCHITECTURE GROWTH BUDGET ===")
    namespace: dict[str, object] = {
        "__file__": str(ROOT / "tests" / "test_architecture_growth_budget.py"),
        "__name__": "phase3_budget_audit",
    }
    budget_path = ROOT / "tests" / "test_architecture_growth_budget.py"
    exec(compile(budget_path.read_text(encoding="utf-8"), str(budget_path), "exec"), namespace)
    max_bytes = namespace.get("MAX_BYTES", {})
    for rel_path, limit in max_bytes.items():
        path = ROOT / rel_path
        if not path.exists():
            print(f"MISSING {rel_path} limit={limit}")
            continue
        size = path.stat().st_size
        state = "PASS" if size <= limit else "FAIL"
        print(f"{state} {rel_path} size={size} limit={limit} delta={size-limit}")


def main() -> None:
    audit_inline_blocks()
    audit_growth_budget()
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
