from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "services/order_runtime.py"

LEGACY_RUNTIME_NAMES = {
    "DB_FILE",
    "DISPATCH_CHANNEL_ID",
    "ORDER_CONTROL_SELECTIONS",
    "SELF_SERVICE_ORDER_SELECTIONS",
    "SelfServiceOrderView",
    "_defer_and_refresh_self_service_panel",
    "_get_rule_from_self_service_data",
    "build_payment_method_embed",
    "build_self_service_panel_embed",
    "can_operate_self_service_order",
    "format_t_amount",
    "get_order_customer_id_from_channel",
    "get_wallet_balance",
    "is_customer_staff",
    "remember_order_data",
    "rename_ticket_channel",
    "send_order_log",
}


def _source() -> str:
    return SOURCE_PATH.read_text(encoding="utf-8")


def _tree() -> ast.Module:
    return ast.parse(_source())


def _module_level_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.rsplit(".", 1)[-1])
    return names


def test_order_runtime_does_not_bind_dependencies_through_globals() -> None:
    tree = _tree()
    globals_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "globals"
    ]
    assert not globals_calls


def test_order_runtime_uses_immutable_runtime_state() -> None:
    source = _source()
    assert "@dataclass(frozen=True)\nclass _OrderRuntimeState:" in source
    assert "_RUNTIME_STATE: _OrderRuntimeState | None = None" in source
    assert "def _require_runtime_state() -> _OrderRuntimeState:" in source
    assert "_RUNTIME_STATE = _OrderRuntimeState(" in source


def test_order_runtime_has_no_module_level_legacy_runtime_aliases() -> None:
    assert LEGACY_RUNTIME_NAMES.isdisjoint(_module_level_names(_tree()))


def test_order_runtime_configure_signature_stays_explicit() -> None:
    configure = next(
        node
        for node in _tree().body
        if isinstance(node, ast.FunctionDef)
        and node.name == "configure_order_runtime_explicit"
    )
    assert [arg.arg for arg in configure.args.kwonlyargs] == [
        "db_file",
        "dispatch_channel_id",
        "order_control_selections",
        "order_selections",
        "self_service_order_view_type",
        "defer_and_refresh_self_service_panel",
        "self_service_rule_getter",
        "payment_method_embed_builder",
        "self_service_panel_embed_builder",
        "can_operate_self_service_order_func",
        "amount_formatter",
        "order_customer_id_getter",
        "wallet_balance_getter",
        "customer_staff_checker",
        "remember_order",
        "ticket_channel_renamer",
        "order_log_sender",
    ]
