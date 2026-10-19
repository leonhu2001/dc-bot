from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "web/app/main.py"
EXPECTED_ROUTER_ALIASES = {
    "dispatch_state_router",
    "admin_wallets_router",
    "discord_avatars_router",
}


def _main_tree() -> ast.Module:
    return ast.parse(MAIN_PATH.read_text(encoding="utf-8"))


def test_web_entrypoint_has_no_late_top_level_imports() -> None:
    tree = _main_tree()
    app_assignment_line = next(
        node.lineno
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "app" for target in node.targets)
    )

    late_imports = [
        node.lineno
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and node.lineno > app_assignment_line
    ]

    assert not late_imports, f"web/app/main.py has late top-level imports at {late_imports}"


def test_web_entrypoint_does_not_hide_router_import_failures() -> None:
    tree = _main_tree()
    hidden_router_imports: list[str] = []

    for try_node in (node for node in ast.walk(tree) if isinstance(node, ast.Try)):
        for node in ast.walk(try_node):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = str(node.module or "")
            if module.startswith("web.app.routers"):
                hidden_router_imports.append(module)

    assert not hidden_router_imports, (
        "router imports must fail loudly instead of being swallowed by try/except: "
        + ", ".join(hidden_router_imports)
    )


def test_late_registered_routers_use_explicit_top_level_aliases() -> None:
    tree = _main_tree()
    imported_aliases = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and str(node.module or "").startswith("web.app.routers")
        for alias in node.names
    }
    included_aliases = {
        call.args[0].id
        for call in (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "app"
            and node.func.attr == "include_router"
            and node.args
            and isinstance(node.args[0], ast.Name)
        )
    }

    assert EXPECTED_ROUTER_ALIASES <= imported_aliases
    assert EXPECTED_ROUTER_ALIASES <= included_aliases
