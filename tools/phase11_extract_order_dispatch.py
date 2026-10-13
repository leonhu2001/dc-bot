from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORDER_RUNTIME = ROOT / "services" / "order_runtime.py"
DISPATCH_RUNTIME = ROOT / "services" / "order_dispatch_runtime.py"
ARCH_TEST = ROOT / "tests" / "test_architecture_growth_budget.py"
BOUNDARY_TEST = ROOT / "tests" / "test_order_dispatch_runtime_boundary.py"

TARGETS = (
    "DispatchCancelClaimButton",
    "sync_single_discord_claim_event_to_web",
    "maybe_handle_prepay_acceptance_claim",
    "maybe_handle_prepay_acceptance_unclaim",
    "DispatchClaimView",
    "delete_dispatch_claim_panel_for_order",
    "sync_web_order_status_from_bot",
)

DEPENDENCY_NAMES = (
    "BOOSTER_RECEIVER_ROLE_ID",
    "DISPATCH_CHANNEL_ID",
    "ORDER_CLAIMS",
    "SELF_SERVICE_ORDER_SELECTIONS",
    "_apply_acceptance_state_to_claim_data",
    "_member_display_name",
    "_member_role_id_texts",
    "_order_requires_credentials",
    "_to_int",
    "build_self_service_order_embed",
    "delete_claim_row_from_db",
    "delete_order_row_from_db",
    "grant_order_ticket_access",
    "remember_claim_data",
    "revoke_order_credential_messages",
    "revoke_order_ticket_access",
    "save_bot_data",
    "send_acceptance_payment_panel_if_ready",
    "send_order_log",
)


def main() -> None:
    source = ORDER_RUNTIME.read_text(encoding="utf-8")
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)

    nodes = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name in TARGETS
    }
    missing = [name for name in TARGETS if name not in nodes]
    if missing:
        raise RuntimeError(f"dispatch extraction targets missing: {missing}")

    spans = sorted((nodes[name].lineno, nodes[name].end_lineno, name) for name in TARGETS)
    extracted = []
    for start, end, name in spans:
        extracted.append("".join(lines[start - 1 : end]).rstrip() + "\n\n")

    header = '''from __future__ import annotations

from typing import Any, Mapping

import discord


_CONFIGURED = False
_DEPENDENCY_NAMES = (
'''
    header += "".join(f'    "{name}",\n' for name in DEPENDENCY_NAMES)
    header += ''')


def configure_order_dispatch_runtime(namespace: Mapping[str, Any]) -> None:
    """Bind the bot-owned adapters needed by the Discord dispatch lifecycle."""
    global _CONFIGURED

    for name in _DEPENDENCY_NAMES:
        if name in namespace:
            globals()[name] = namespace[name]

    _CONFIGURED = True


'''
    DISPATCH_RUNTIME.write_text(header + "".join(extracted), encoding="utf-8")

    remove_lines: set[int] = set()
    for start, end, _ in spans:
        remove_lines.update(range(start, end + 1))

    remaining = "".join(
        line for index, line in enumerate(lines, start=1)
        if index not in remove_lines
    )

    import_node = next(
        node for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "services.order_storage_runtime"
    )
    remaining_lines = remaining.splitlines(keepends=True)

    # Removing later nodes does not change the storage import line numbers.
    insert_at = import_node.end_lineno
    dispatch_import = '''from services.order_dispatch_runtime import (
    configure_order_dispatch_runtime,
    DispatchCancelClaimButton,
    sync_single_discord_claim_event_to_web,
    maybe_handle_prepay_acceptance_claim,
    maybe_handle_prepay_acceptance_unclaim,
    DispatchClaimView,
    delete_dispatch_claim_panel_for_order,
    sync_web_order_status_from_bot,
)
'''
    remaining_lines.insert(insert_at, dispatch_import)
    remaining = "".join(remaining_lines)

    configure_anchor = "    credential_keys = {\n"
    if configure_anchor not in remaining:
        raise RuntimeError("configure_order_runtime insertion anchor missing")
    remaining = remaining.replace(
        configure_anchor,
        "    configure_order_dispatch_runtime(namespace)\n\n" + configure_anchor,
        1,
    )
    ORDER_RUNTIME.write_text(remaining, encoding="utf-8")

    arch = ARCH_TEST.read_text(encoding="utf-8")
    old_budget = '    "services/order_runtime.py": 62_000,\n'
    if old_budget not in arch:
        raise RuntimeError("order_runtime architecture budget marker missing")
    arch = arch.replace(
        old_budget,
        '    "services/order_runtime.py": 45_000,\n'
        '    "services/order_dispatch_runtime.py": 30_000,\n',
        1,
    )
    ARCH_TEST.write_text(arch, encoding="utf-8")

    BOUNDARY_TEST.write_text(
        '''from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "DispatchCancelClaimButton",
    "sync_single_discord_claim_event_to_web",
    "maybe_handle_prepay_acceptance_claim",
    "maybe_handle_prepay_acceptance_unclaim",
    "DispatchClaimView",
    "delete_dispatch_claim_panel_for_order",
    "sync_web_order_status_from_bot",
}


def _top_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def test_dispatch_implementation_has_single_canonical_owner():
    legacy = _top_level_names(ROOT / "services/order_runtime.py")
    dispatch = _top_level_names(ROOT / "services/order_dispatch_runtime.py")
    assert TARGETS.isdisjoint(legacy)
    assert TARGETS.issubset(dispatch)


def test_order_runtime_reexports_dispatch_public_surface():
    import services.order_dispatch_runtime as dispatch
    import services.order_runtime as order_runtime

    for name in TARGETS:
        assert getattr(order_runtime, name) is getattr(dispatch, name)


def test_dispatch_runtime_has_no_bot_entrypoint_dependency():
    source = (ROOT / "services/order_dispatch_runtime.py").read_text(encoding="utf-8")
    assert "import bot" not in source
    assert "from bot import" not in source


def test_dispatch_runtime_configuration_is_explicitly_scoped():
    import services.order_dispatch_runtime as dispatch

    marker = object()
    dispatch.configure_order_dispatch_runtime({
        "DISPATCH_CHANNEL_ID": 123,
        "ORDER_CLAIMS": marker,
        "UNRELATED_SENTINEL": object(),
    })
    assert dispatch.DISPATCH_CHANNEL_ID == 123
    assert dispatch.ORDER_CLAIMS is marker
    assert not hasattr(dispatch, "UNRELATED_SENTINEL")
''',
        encoding="utf-8",
    )

    for relative in (
        "tools/phase11_dispatch_inventory.py",
        ".github/workflows/phase11-dispatch-inventory.yml",
        "tools/phase11_extract_order_dispatch.py",
        ".github/workflows/phase11-extract-order-dispatch.yml",
    ):
        (ROOT / relative).unlink(missing_ok=True)

    # Fail early if the generated files cannot even be parsed.
    ast.parse(ORDER_RUNTIME.read_text(encoding="utf-8"))
    ast.parse(DISPATCH_RUNTIME.read_text(encoding="utf-8"))

    print(f"order_runtime_bytes={ORDER_RUNTIME.stat().st_size}")
    print(f"order_dispatch_runtime_bytes={DISPATCH_RUNTIME.stat().st_size}")


if __name__ == "__main__":
    main()
