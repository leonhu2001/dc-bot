from __future__ import annotations

import ast
from pathlib import Path


TARGETS = (
    Path("services/quick_order_v2_select_display.py"),
    Path("services/quick_order_v2_production.py"),
    Path("services/quick_order_v2_fixes.py"),
    Path("services/order_ticket_ui_policy.py"),
)


def test_quick_order_runtime_has_no_silent_broad_exception_handlers() -> None:
    failures: list[str] = []

    for path in TARGETS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if not isinstance(node.type, ast.Name) or node.type.id != "Exception":
                continue
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                failures.append(f"{path}:{node.lineno}")

    assert not failures, (
        "Quick Order runtime must not silently swallow broad exceptions; "
        f"found: {', '.join(failures)}"
    )


def test_quick_order_select_marker_failures_are_logged() -> None:
    source = Path("services/quick_order_v2_select_display.py").read_text(encoding="utf-8")

    assert "[quick-order-v2-select] marker update failed" in source
    for action in ("quantity", "detail", "item", "category"):
        assert f'_warn_marker_failure("{action}"' in source
