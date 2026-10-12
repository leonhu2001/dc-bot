from __future__ import annotations

import ast
from pathlib import Path

from optimize_web_assets import optimize_assets


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    source = path.read_text(encoding="utf-8-sig")
    if old not in source:
        raise RuntimeError(f"expected block not found in {path.relative_to(ROOT)}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def switch_optimized_image_references() -> None:
    replacements = {
        "home_hero_mascot_final.png": "home_hero_mascot_final.webp",
        "staff_profile_bg_gothic_hall.png": "staff_profile_bg_gothic_hall.webp",
    }
    changed = []
    for path in (ROOT / "web" / "app").rglob("*"):
        if path.suffix.lower() not in {".html", ".css", ".js"}:
            continue
        source = path.read_text(encoding="utf-8")
        updated = source
        for old, new in replacements.items():
            updated = updated.replace(old, new)
        if updated != source:
            path.write_text(updated, encoding="utf-8")
            changed.append(str(path.relative_to(ROOT)))
    print("IMAGE_REFERENCES", ", ".join(changed) or "none")


def make_child_runtime_binding_partial_namespace_safe() -> None:
    order_path = ROOT / "services" / "order_runtime.py"
    old_order = '''    configure_order_credentials(
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
    )
'''
    new_order = '''    credential_keys = {
        "CREDENTIAL_OWNER_USER_ID",
        "GUILD_ID",
        "SELF_SERVICE_ORDER_SELECTIONS",
        "_to_int",
        "bot",
        "fetch_member_safely",
        "get_taipei_now_iso",
        "remember_order_data",
        "save_bot_data",
    }
    if credential_keys.issubset(namespace):
        configure_order_credentials(
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

    redemption_keys = {
        "CUSTOMER_REWARDS",
        "_to_int",
        "get_current_reward_points",
        "get_customer_reward_data",
        "get_order_point_item",
        "get_taipei_now_iso",
        "remember_order_data",
        "save_bot_data",
        "send_order_log",
    }
    if redemption_keys.issubset(namespace):
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
        )
'''
    replace_once(order_path, old_order, new_order)

    self_path = ROOT / "services" / "self_service_runtime.py"
    old_self = '''    configure_self_service_financials(
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
    )
'''
    new_self = '''    financial_keys = {
        "ORDER_POINT_BENEFIT_SPECS",
        "POINT_REDEEM_ITEMS_BY_KEY",
        "_to_int",
        "allocate_store_absorbed_fixed_discount",
        "get_current_reward_points",
        "get_customer_reward_data",
        "get_effective_member_level",
        "get_self_service_quantity_unit",
        "get_vip_discount_pay_rate",
    }
    if financial_keys.issubset(namespace):
        configure_self_service_financials(
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
        )
'''
    replace_once(self_path, old_self, new_self)


def extract_ticket_helpers_from_bot() -> None:
    path = ROOT / "bot.py"
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    names = {
        "_clean_ticket_channel_part",
        "build_ticket_channel_name",
        "safe_channel_name",
        "rename_ticket_channel",
        "is_agree_answer",
        "get_recruit_info_from_channel",
        "get_recruit_member_id_from_channel",
        "remove_recruit_applicant_role",
        "get_order_customer_id_from_channel",
    }
    nodes = {
        getattr(node, "name", ""): node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = names - set(nodes)
    if missing:
        raise RuntimeError(f"bot ticket helpers not found: {sorted(missing)}")

    lines = source.splitlines(keepends=True)
    removed = set()
    for name in names:
        node = nodes[name]
        removed.update(range(int(node.lineno), int(node.end_lineno) + 1))
    updated = "".join(
        line
        for number, line in enumerate(lines, start=1)
        if number not in removed
    )

    import_block = '''from services.ticket_identity import (
    configure_ticket_identity,
    _clean_ticket_channel_part,
    build_ticket_channel_name,
    safe_channel_name,
    rename_ticket_channel,
    is_agree_answer,
    get_recruit_info_from_channel,
    get_recruit_member_id_from_channel,
    remove_recruit_applicant_role,
    get_order_customer_id_from_channel,
)
'''
    marker = "import discord\n"
    if marker not in updated:
        raise RuntimeError("bot discord import marker not found")
    updated = updated.replace(marker, marker + "\n" + import_block, 1)

    configure_marker = "configure_support_views(\n"
    if configure_marker not in updated:
        raise RuntimeError("support view configure marker not found")
    updated = updated.replace(
        configure_marker,
        "configure_ticket_identity(\n"
        "    recruit_applicant_role_id=RECRUIT_APPLICANT_ROLE_ID,\n"
        ")\n\n\n"
        + configure_marker,
        1,
    )
    path.write_text(updated, encoding="utf-8")


def document_phase2_boundaries() -> None:
    path = ROOT / "ARCHITECTURE.md"
    source = path.read_text(encoding="utf-8")
    note = '''

## Phase 2 extraction boundaries (2026-10-13)

- Discord order credential UI/runtime lives in `services/order_credential_runtime.py`; credential persistence remains in `services/order_credentials.py`.
- Point-benefit payment redemption lives in `services/order_point_redemption.py`.
- Self-service pricing, manual adjustment, VIP discount, and point-benefit financial calculation live in `services/self_service_financials.py`.
- Ticket naming/topic identity helpers live in `services/ticket_identity.py`, not the `bot.py` entrypoint.
- Admin dashboard and order workspace are separate routers; `web/app/routers/admin.py` is a thin action/router composition layer.
- Patch-style frontend assets (`*_fix.js` / `*_fix.css`) have no allow-list. Additions must be implemented in canonical controllers/styles instead.
'''
    if "## Phase 2 extraction boundaries (2026-10-13)" not in source:
        path.write_text(source.rstrip() + note, encoding="utf-8")


def remove_one_shot_tools() -> None:
    paths = (
        ".github/workflows/optimize-web-assets.yml",
        ".github/workflows/phase2-fix-credential-boundary.yml",
        ".github/workflows/phase2-inventory.yml",
        ".github/workflows/phase2-source-cleanup.yml",
        ".github/workflows/phase2-split-admin.yml",
        ".github/workflows/phase2-split-order-runtimes.yml",
        ".github/workflows/phase2-finalize.yml",
        "tools/optimize_web_assets.py",
        "tools/phase2_module_inventory.py",
        "tools/phase2_source_cleanup.py",
        "tools/phase2_split_admin_router.py",
        "tools/phase2_split_order_runtimes.py",
        "tools/phase2_finalize.py",
    )
    for relative in paths:
        path = ROOT / relative
        if path.exists():
            path.unlink()
            print(f"REMOVED_ONE_SHOT {relative}")


def main() -> None:
    optimize_assets()
    switch_optimized_image_references()
    make_child_runtime_binding_partial_namespace_safe()
    extract_ticket_helpers_from_bot()
    document_phase2_boundaries()
    remove_one_shot_tools()
    print("PHASE2_FINALIZE_DONE")


if __name__ == "__main__":
    main()
