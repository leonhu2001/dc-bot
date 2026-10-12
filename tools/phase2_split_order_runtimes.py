from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "services"
ORDER_RUNTIME = SERVICES / "order_runtime.py"
SELF_RUNTIME = SERVICES / "self_service_runtime.py"

ORDER_CREDENTIAL_NAMES = {
    "_order_requires_credentials",
    "_credential_user_for_id",
    "_credential_display_name",
    "_resolve_credential_owner",
    "revoke_order_credential_messages",
    "ensure_order_credential_request",
    "OrderCredentialModal",
    "OrderCredentialEntryView",
}

ORDER_BENEFIT_NAMES = {
    "_get_pending_order_point_benefit_info",
    "precheck_order_point_benefit_for_payment",
    "redeem_order_point_benefit_on_payment",
}

SELF_FINANCIAL_NAMES = {
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
    "_format_point_hours",
    "get_order_point_item",
    "get_customer_point_balance_for_order",
    "is_order_point_benefit_allowed_for_rule",
    "_adapt_order_point_benefit_for_rule",
    "get_selected_order_point_benefit",
    "calculate_self_service_financials",
    "apply_self_service_financials_to_order_data",
}


def _top_level_nodes(source: str) -> dict[str, ast.AST]:
    tree = ast.parse(source)
    return {
        getattr(node, "name", ""): node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def _extract(source: str, names: set[str]) -> tuple[str, str]:
    nodes = _top_level_nodes(source)
    lines = source.splitlines(keepends=True)
    missing = sorted(names - set(nodes))
    if missing:
        raise RuntimeError(f"missing extraction nodes: {missing}")

    ranges = sorted(
        (int(nodes[name].lineno), int(nodes[name].end_lineno), name)
        for name in names
    )
    chunks = ["".join(lines[start - 1 : end]).rstrip() for start, end, _ in ranges]

    remove_lines: set[int] = set()
    for start, end, _ in ranges:
        remove_lines.update(range(start, end + 1))

    remaining = "".join(
        line
        for index, line in enumerate(lines, start=1)
        if index not in remove_lines
    )
    return remaining, "\n\n\n".join(chunks).rstrip() + "\n"


def _insert_after_discord_import(source: str, block: str) -> str:
    marker = "import discord\n"
    if marker not in source:
        raise RuntimeError("discord import marker not found")
    return source.replace(marker, marker + "\n" + block.rstrip() + "\n", 1)


def _insert_before_configured_true(source: str, block: str) -> str:
    marker = "    _CONFIGURED = True"
    if marker not in source:
        raise RuntimeError("runtime configuration marker not found")
    return source.replace(marker, block.rstrip() + "\n\n" + marker, 1)


def _write_order_credentials(body: str) -> None:
    prelude = '''from __future__ import annotations

from typing import Any, Callable

import discord


CREDENTIAL_OWNER_USER_ID: int
GUILD_ID: int
SELF_SERVICE_ORDER_SELECTIONS: dict
_to_int: Callable[..., int]
bot: Any
fetch_member_safely: Callable[..., Any]
get_taipei_now_iso: Callable[..., str]
remember_order_data: Callable[..., Any]
save_bot_data: Callable[..., Any]


def configure_order_credentials(
    *,
    credential_owner_user_id: int,
    guild_id: int,
    self_service_order_selections: dict,
    to_int: Callable[..., int],
    bot_instance: Any,
    fetch_member: Callable[..., Any],
    taipei_now_iso: Callable[..., str],
    remember_data: Callable[..., Any],
    save_data: Callable[..., Any],
) -> None:
    global CREDENTIAL_OWNER_USER_ID
    global GUILD_ID
    global SELF_SERVICE_ORDER_SELECTIONS
    global _to_int
    global bot
    global fetch_member_safely
    global get_taipei_now_iso
    global remember_order_data
    global save_bot_data

    CREDENTIAL_OWNER_USER_ID = int(credential_owner_user_id or 0)
    GUILD_ID = int(guild_id or 0)
    SELF_SERVICE_ORDER_SELECTIONS = self_service_order_selections
    _to_int = to_int
    bot = bot_instance
    fetch_member_safely = fetch_member
    get_taipei_now_iso = taipei_now_iso
    remember_order_data = remember_data
    save_bot_data = save_data


'''
    (SERVICES / "order_credentials.py").write_text(prelude + body, encoding="utf-8")


def _write_order_benefits(body: str) -> None:
    prelude = '''from __future__ import annotations

from typing import Any, Callable

import discord


CUSTOMER_REWARDS: dict
_to_int: Callable[..., int]
get_current_reward_points: Callable[..., int]
get_customer_reward_data: Callable[..., Any]
get_order_point_item: Callable[..., Any]
get_taipei_now_iso: Callable[..., str]
remember_order_data: Callable[..., Any]
save_bot_data: Callable[..., Any]
send_order_log: Callable[..., Any]


def configure_order_point_redemption(
    *,
    customer_rewards: dict,
    to_int: Callable[..., int],
    current_reward_points: Callable[..., int],
    customer_reward_data: Callable[..., Any],
    order_point_item: Callable[..., Any],
    taipei_now_iso: Callable[..., str],
    remember_data: Callable[..., Any],
    save_data: Callable[..., Any],
    order_log_sender: Callable[..., Any],
) -> None:
    global CUSTOMER_REWARDS
    global _to_int
    global get_current_reward_points
    global get_customer_reward_data
    global get_order_point_item
    global get_taipei_now_iso
    global remember_order_data
    global save_bot_data
    global send_order_log

    CUSTOMER_REWARDS = customer_rewards
    _to_int = to_int
    get_current_reward_points = current_reward_points
    get_customer_reward_data = customer_reward_data
    get_order_point_item = order_point_item
    get_taipei_now_iso = taipei_now_iso
    remember_order_data = remember_data
    save_bot_data = save_data
    send_order_log = order_log_sender


'''
    (SERVICES / "order_point_redemption.py").write_text(prelude + body, encoding="utf-8")


def _write_self_financials(body: str) -> None:
    prelude = '''from __future__ import annotations

import json
from typing import Any, Callable

import discord


ORDER_POINT_BENEFIT_SPECS: dict
POINT_REDEEM_ITEMS_BY_KEY: dict
_get_rule_from_self_service_data: Callable[..., Any]
_is_specify_preference: Callable[..., bool]
_role_key_for_member: Callable[..., Any]
_to_int: Callable[..., int]
allocate_store_absorbed_fixed_discount: Callable[..., Any]
get_current_reward_points: Callable[..., int]
get_customer_reward_data: Callable[..., Any]
get_effective_member_level: Callable[..., Any]
get_self_service_quantity_unit: Callable[..., Any]
get_self_service_staff_price: Callable[..., Any]
get_vip_discount_pay_rate: Callable[..., Any]
is_self_service_staff_price_required: Callable[..., bool]


def configure_self_service_financials(
    *,
    order_point_benefit_specs: dict,
    point_redeem_items_by_key: dict,
    get_rule_from_data: Callable[..., Any],
    is_specify_preference: Callable[..., bool],
    role_key_for_member: Callable[..., Any],
    to_int: Callable[..., int],
    store_absorbed_discount_allocator: Callable[..., Any],
    current_reward_points: Callable[..., int],
    customer_reward_data: Callable[..., Any],
    effective_member_level: Callable[..., Any],
    self_service_quantity_unit: Callable[..., Any],
    self_service_staff_price: Callable[..., Any],
    vip_discount_pay_rate: Callable[..., Any],
    staff_price_required: Callable[..., bool],
) -> None:
    global ORDER_POINT_BENEFIT_SPECS
    global POINT_REDEEM_ITEMS_BY_KEY
    global _get_rule_from_self_service_data
    global _is_specify_preference
    global _role_key_for_member
    global _to_int
    global allocate_store_absorbed_fixed_discount
    global get_current_reward_points
    global get_customer_reward_data
    global get_effective_member_level
    global get_self_service_quantity_unit
    global get_self_service_staff_price
    global get_vip_discount_pay_rate
    global is_self_service_staff_price_required

    ORDER_POINT_BENEFIT_SPECS = order_point_benefit_specs
    POINT_REDEEM_ITEMS_BY_KEY = point_redeem_items_by_key
    _get_rule_from_self_service_data = get_rule_from_data
    _is_specify_preference = is_specify_preference
    _role_key_for_member = role_key_for_member
    _to_int = to_int
    allocate_store_absorbed_fixed_discount = store_absorbed_discount_allocator
    get_current_reward_points = current_reward_points
    get_customer_reward_data = customer_reward_data
    get_effective_member_level = effective_member_level
    get_self_service_quantity_unit = self_service_quantity_unit
    get_self_service_staff_price = self_service_staff_price
    get_vip_discount_pay_rate = vip_discount_pay_rate
    is_self_service_staff_price_required = staff_price_required


'''
    (SERVICES / "self_service_financials.py").write_text(prelude + body, encoding="utf-8")


def split_order_runtime() -> None:
    source = ORDER_RUNTIME.read_text(encoding="utf-8-sig")
    source, credential_body = _extract(source, ORDER_CREDENTIAL_NAMES)
    source, benefit_body = _extract(source, ORDER_BENEFIT_NAMES)

    _write_order_credentials(credential_body)
    _write_order_benefits(benefit_body)

    imports = '''from services.order_credentials import (
    configure_order_credentials,
    _order_requires_credentials,
    _credential_user_for_id,
    _credential_display_name,
    _resolve_credential_owner,
    revoke_order_credential_messages,
    ensure_order_credential_request,
    OrderCredentialModal,
    OrderCredentialEntryView,
)
from services.order_point_redemption import (
    configure_order_point_redemption,
    _get_pending_order_point_benefit_info,
    precheck_order_point_benefit_for_payment,
    redeem_order_point_benefit_on_payment,
)
'''
    source = _insert_after_discord_import(source, imports)

    configure_children = '''    configure_order_credentials(
        credential_owner_user_id=namespace["CREDENTIAL_OWNER_USER_ID"],
        guild_id=namespace["GUILD_ID"],
        self_service_order_selections=namespace["SELF_SERVICE_ORDER_SELECTIONS"],
        to_int=namespace["_to_int"],
        bot_instance=namespace["bot"],
        fetch_member=namespace["fetch_member_safely"],
        taipei_now_iso=namespace["get_taipei_now_iso"],
        remember_data=namespace["remember_order_data"],
        save_data=namespace["save_bot_data"],
    )
    configure_order_point_redemption(
        customer_rewards=namespace["CUSTOMER_REWARDS"],
        to_int=namespace["_to_int"],
        current_reward_points=namespace["get_current_reward_points"],
        customer_reward_data=namespace["get_customer_reward_data"],
        order_point_item=namespace["get_order_point_item"],
        taipei_now_iso=namespace["get_taipei_now_iso"],
        remember_data=namespace["remember_order_data"],
        save_data=namespace["save_bot_data"],
        order_log_sender=namespace["send_order_log"],
    )'''
    source = _insert_before_configured_true(source, configure_children)
    ORDER_RUNTIME.write_text(source, encoding="utf-8")


def split_self_runtime() -> None:
    source = SELF_RUNTIME.read_text(encoding="utf-8-sig")
    source, financial_body = _extract(source, SELF_FINANCIAL_NAMES)
    _write_self_financials(financial_body)

    exported = "\n".join(f"    {name}," for name in sorted(SELF_FINANCIAL_NAMES))
    imports = f'''from services.self_service_financials import (
    configure_self_service_financials,
{exported}
)
'''
    source = _insert_after_discord_import(source, imports)

    configure_child = '''    configure_self_service_financials(
        order_point_benefit_specs=namespace["ORDER_POINT_BENEFIT_SPECS"],
        point_redeem_items_by_key=namespace["POINT_REDEEM_ITEMS_BY_KEY"],
        get_rule_from_data=_get_rule_from_self_service_data,
        is_specify_preference=_is_specify_preference,
        role_key_for_member=_role_key_for_member,
        to_int=namespace["_to_int"],
        store_absorbed_discount_allocator=namespace["allocate_store_absorbed_fixed_discount"],
        current_reward_points=namespace["get_current_reward_points"],
        customer_reward_data=namespace["get_customer_reward_data"],
        effective_member_level=namespace["get_effective_member_level"],
        self_service_quantity_unit=namespace["get_self_service_quantity_unit"],
        self_service_staff_price=get_self_service_staff_price,
        vip_discount_pay_rate=namespace["get_vip_discount_pay_rate"],
        staff_price_required=is_self_service_staff_price_required,
    )'''
    source = _insert_before_configured_true(source, configure_child)
    SELF_RUNTIME.write_text(source, encoding="utf-8")


def main() -> None:
    split_order_runtime()
    split_self_runtime()

    for relative in (
        "services/order_runtime.py",
        "services/order_credentials.py",
        "services/order_point_redemption.py",
        "services/self_service_runtime.py",
        "services/self_service_financials.py",
    ):
        path = ROOT / relative
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        print(f"RUNTIME_SPLIT {relative} bytes={path.stat().st_size}")


if __name__ == "__main__":
    main()
