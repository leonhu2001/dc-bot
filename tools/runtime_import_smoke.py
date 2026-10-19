from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


BOT_PATH = ROOT / "bot.py"
CRITICAL_RUNTIME_MODULES = (
    "cogs.wallet_commands",
    "cogs.staff_profile_commands",
    "services.payment_review_runtime",
    "services.vip_voice_runtime",
    "services.order_runtime",
    "services.order_lifecycle_runtime",
    "services.order_storage_runtime",
    "services.order_payment_runtime",
    "services.order_payment_composition",
    "services.wallet_discord_runtime",
    "services.order_credential_runtime",
    "services.order_point_redemption",
    "services.self_service_runtime",
    "services.self_service_selection_runtime",
    "services.self_service_reorder",
    "services.self_service_financials",
    "services.worker_tips",
    "services.review_storage",
    "views.review",
)

BOT_IMPORT_PREFIXES = (
    "services.",
    "views.",
)

# Extraction boundaries that must remain explicit in bot.py. This catches both
# missing imports and accidental compatibility re-exports from the old runtime.
REQUIRED_BOT_IMPORT_ALIASES = {
    "_wallet_ensure_tables": (
        "services.wallet_service",
        "ensure_wallet_tables",
    ),
    "_wallet_get_balance": (
        "services.wallet_service",
        "get_wallet_balance",
    ),
    "adjust_customer_wallet_balance": (
        "services.wallet_discord_runtime",
        "adjust_customer_wallet_balance",
    ),
    "send_wallet_log": (
        "services.wallet_discord_runtime",
        "send_wallet_log",
    ),
    "_truncate_select_text": (
        "services.self_service_selection_runtime",
        "_truncate_select_text",
    ),
    "get_specified_staff_entries_for_rule": (
        "services.self_service_selection_runtime",
        "get_specified_staff_entries_for_rule",
    ),
    "_acknowledge_component_interaction": (
        "services.self_service_selection_runtime",
        "_acknowledge_component_interaction",
    ),
    "_edit_component_message": (
        "services.self_service_selection_runtime",
        "_edit_component_message",
    ),
    "SelfServiceSpecifiedStaffDropdown": (
        "services.self_service_selection_runtime",
        "SelfServiceSpecifiedStaffDropdown",
    ),
    "SelfServiceSpecifiedStaffPageButton": (
        "services.self_service_selection_runtime",
        "SelfServiceSpecifiedStaffPageButton",
    ),
    "SelfServiceSpecifiedStaffClearButton": (
        "services.self_service_selection_runtime",
        "SelfServiceSpecifiedStaffClearButton",
    ),
    "SelfServiceSpecifiedStaffDoneButton": (
        "services.self_service_selection_runtime",
        "SelfServiceSpecifiedStaffDoneButton",
    ),
    "SelfServicePointBenefitSelect": (
        "services.self_service_selection_runtime",
        "SelfServicePointBenefitSelect",
    ),
    "SelfServicePointBenefitView": (
        "services.self_service_selection_runtime",
        "SelfServicePointBenefitView",
    ),
    "SelfServiceSpecifiedStaffDropdownView": (
        "services.self_service_selection_runtime",
        "SelfServiceSpecifiedStaffDropdownView",
    ),
}


def _validate_bot_import_contracts() -> int:
    tree = ast.parse(BOT_PATH.read_text(encoding="utf-8"), filename=str(BOT_PATH))
    imported_aliases: dict[str, tuple[str, str]] = {}
    validated = 0

    # Only top-level imports are part of the process startup boundary. Local
    # imports are intentionally lazy and should not turn preflight into a full
    # application dependency walk.
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not node.module.startswith(BOT_IMPORT_PREFIXES):
            continue

        module = importlib.import_module(node.module)

        for alias in node.names:
            if alias.name == "*":
                continue

            if not hasattr(module, alias.name):
                raise ImportError(
                    "bot.py imports missing symbol "
                    f"{alias.name!r} from {node.module!r} "
                    f"at line {node.lineno}"
                )

            imported_name = alias.asname or alias.name
            imported_aliases[imported_name] = (node.module, alias.name)
            validated += 1

    for alias_name, expected in REQUIRED_BOT_IMPORT_ALIASES.items():
        actual = imported_aliases.get(alias_name)
        if actual != expected:
            expected_module, expected_symbol = expected
            actual_text = (
                f"{actual[0]}.{actual[1]}"
                if actual is not None
                else "not imported"
            )
            raise ImportError(
                f"bot.py must import {alias_name} as "
                f"{expected_module}.{expected_symbol}; got {actual_text}"
            )

    return validated


def main() -> None:
    for module_name in CRITICAL_RUNTIME_MODULES:
        importlib.import_module(module_name)

    bot_symbol_count = _validate_bot_import_contracts()
    print(
        "PASS: imported "
        f"{len(CRITICAL_RUNTIME_MODULES)} critical runtime modules; "
        f"validated {bot_symbol_count} bot import contracts"
    )


if __name__ == "__main__":
    main()
