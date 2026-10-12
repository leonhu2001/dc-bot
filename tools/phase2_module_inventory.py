from __future__ import annotations

import ast
import builtins
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    "bot.py",
    "services/order_runtime.py",
    "services/self_service_runtime.py",
    "web/app/routers/admin.py",
)

EXTRACTION_GROUPS = {
    "services/order_runtime.py": {
        "credentials": {
            "_order_requires_credentials",
            "_credential_user_for_id",
            "_credential_display_name",
            "_resolve_credential_owner",
            "revoke_order_credential_messages",
            "ensure_order_credential_request",
            "OrderCredentialModal",
            "OrderCredentialEntryView",
        },
        "benefits": {
            "_get_pending_order_point_benefit_info",
            "precheck_order_point_benefit_for_payment",
            "redeem_order_point_benefit_on_payment",
        },
    },
    "services/self_service_runtime.py": {
        "manual_pricing": {
            "_format_plain_amount",
            "_price_int",
            "_price_rate",
            "_price_snapshot",
            "add_self_service_financial_breakdown_fields",
            "_format_percent_value",
            "_parse_discount_percent_text",
            "_parse_cash_amount_text",
            "_resolve_manual_discount_rate_percent",
            "_resolve_self_service_discount_rate",
            "calculate_manual_price_adjustment",
            "apply_manual_price_adjustment_to_order_data",
            "_quote_preview_lines_for_self_service",
            "add_self_service_quote_preview",
        },
        "point_benefits": {
            "_format_point_hours",
            "get_order_point_item",
            "get_customer_point_balance_for_order",
            "is_order_point_benefit_allowed_for_rule",
            "_adapt_order_point_benefit_for_rule",
            "get_selected_order_point_benefit",
            "calculate_self_service_financials",
            "apply_self_service_financials_to_order_data",
        },
    },
}


def _node_kind(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    if isinstance(node, ast.ClassDef):
        return "class"
    return type(node).__name__


def _bound_names(node: ast.AST) -> set[str]:
    bound: set[str] = set()
    for item in ast.walk(node):
        if isinstance(item, ast.arg):
            bound.add(item.arg)
        elif isinstance(item, ast.Name) and isinstance(item.ctx, (ast.Store, ast.Del)):
            bound.add(item.id)
        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and item is not node:
            bound.add(item.name)
        elif isinstance(item, ast.alias):
            bound.add(item.asname or item.name.split(".")[0])
    return bound


def _loaded_names(node: ast.AST) -> set[str]:
    return {
        item.id
        for item in ast.walk(node)
        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)
    }


def _print_extraction_dependencies(relative: str, tree: ast.Module) -> None:
    groups = EXTRACTION_GROUPS.get(relative, {})
    if not groups:
        return

    by_name = {
        getattr(node, "name", ""): node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    builtin_names = set(dir(builtins))

    for group_name, names in groups.items():
        nodes = [by_name[name] for name in names if name in by_name]
        loaded: set[str] = set()
        bound: set[str] = set(names)
        for node in nodes:
            loaded.update(_loaded_names(node))
            bound.update(_bound_names(node))

        external = sorted(loaded - bound - builtin_names)
        print("-" * 100)
        print(f"EXTRACTION {relative}:{group_name}")
        print("EXTERNAL_NAMES " + ", ".join(external))


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

        _print_extraction_dependencies(relative, tree)


if __name__ == "__main__":
    main()
