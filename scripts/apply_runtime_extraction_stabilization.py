from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bot.py"


WALLET_ANCHOR = "from services.payment_review_runtime import ensure_payment_review_worker_started\n"
WALLET_IMPORT = """from services.wallet_service import (\n    ensure_wallet_tables as _wallet_ensure_tables,\n    get_wallet_balance as _wallet_get_balance,\n    adjust_wallet_balance as _wallet_adjust_balance,\n    get_wallet_transactions as _wallet_get_transactions,\n)\n"""

OLD_SELF_SERVICE_IMPORT = """from services.self_service_runtime import (\n    configure_self_service_runtime,\n    _format_plain_amount,\n    _extract_discord_ids_from_text,\n    _get_rule_from_self_service_data,\n    _is_specify_preference,\n    _role_key_for_member,\n    _resolve_specified_roles_for_price,\n    _defer_and_refresh_self_service_panel,\n    SelfServicePlayerCountModal,\n    _price_int,\n    _price_rate,\n    _price_snapshot,\n    add_self_service_financial_breakdown_fields,\n    create_waiting_acceptance_order_from_self_service,\n    _format_percent_value,\n    _parse_discount_percent_text,\n    _parse_cash_amount_text,\n    _resolve_manual_discount_rate_percent,\n    _resolve_self_service_discount_rate,\n    calculate_manual_price_adjustment,\n    apply_manual_price_adjustment_to_order_data,\n    _quote_preview_lines_for_self_service,\n    add_self_service_quote_preview,\n    build_self_service_panel_embed,\n    _truncate_select_text,\n    get_specified_staff_entries_for_rule,\n    _acknowledge_component_interaction,\n    _edit_component_message,\n    SelfServiceSpecifiedStaffDropdown,\n    SelfServiceSpecifiedStaffPageButton,\n    SelfServiceSpecifiedStaffClearButton,\n    SelfServiceSpecifiedStaffDoneButton,\n    _format_point_hours,\n    get_order_point_item,\n    get_customer_point_balance_for_order,\n    is_order_point_benefit_allowed_for_rule,\n    _adapt_order_point_benefit_for_rule,\n    get_selected_order_point_benefit,\n    calculate_self_service_financials,\n    apply_self_service_financials_to_order_data,\n    SelfServicePointBenefitSelect,\n    SelfServicePointBenefitView,\n    SelfServiceSpecifiedStaffDropdownView,\n    is_self_service_staff_price_required,\n    get_self_service_staff_price,\n    SelfServiceStaffPriceModal,\n    SelfServiceStaffDiscountCouponModal,\n    SelfServiceSubmitNoteModal,\n    SelfServiceOrderView,\n    _reorder_order_value,\n    _reorder_json_dict,\n    build_reorder_self_service_draft,\n    _reorder_message_has_component,\n    _find_reorder_panel_message,\n    ensure_reorder_ticket_panels,\n    create_reorder_ticket_from_closed_order,\n)\n"""

NEW_SELF_SERVICE_IMPORTS = """from services.self_service_selection_runtime import (\n    _truncate_select_text,\n    get_specified_staff_entries_for_rule,\n    _acknowledge_component_interaction,\n    _edit_component_message,\n    SelfServiceSpecifiedStaffDropdown,\n    SelfServiceSpecifiedStaffPageButton,\n    SelfServiceSpecifiedStaffClearButton,\n    SelfServiceSpecifiedStaffDoneButton,\n    SelfServicePointBenefitSelect,\n    SelfServicePointBenefitView,\n    SelfServiceSpecifiedStaffDropdownView,\n)\nfrom services.self_service_runtime import (\n    configure_self_service_runtime,\n    _format_plain_amount,\n    _extract_discord_ids_from_text,\n    _get_rule_from_self_service_data,\n    _is_specify_preference,\n    _role_key_for_member,\n    _resolve_specified_roles_for_price,\n    _defer_and_refresh_self_service_panel,\n    SelfServicePlayerCountModal,\n    _price_int,\n    _price_rate,\n    _price_snapshot,\n    add_self_service_financial_breakdown_fields,\n    create_waiting_acceptance_order_from_self_service,\n    _format_percent_value,\n    _parse_discount_percent_text,\n    _parse_cash_amount_text,\n    _resolve_manual_discount_rate_percent,\n    _resolve_self_service_discount_rate,\n    calculate_manual_price_adjustment,\n    apply_manual_price_adjustment_to_order_data,\n    _quote_preview_lines_for_self_service,\n    add_self_service_quote_preview,\n    build_self_service_panel_embed,\n    _format_point_hours,\n    get_order_point_item,\n    get_customer_point_balance_for_order,\n    is_order_point_benefit_allowed_for_rule,\n    _adapt_order_point_benefit_for_rule,\n    get_selected_order_point_benefit,\n    calculate_self_service_financials,\n    apply_self_service_financials_to_order_data,\n    is_self_service_staff_price_required,\n    get_self_service_staff_price,\n    SelfServiceStaffPriceModal,\n    SelfServiceStaffDiscountCouponModal,\n    SelfServiceSubmitNoteModal,\n    SelfServiceOrderView,\n    _reorder_order_value,\n    _reorder_json_dict,\n    build_reorder_self_service_draft,\n    _reorder_message_has_component,\n    _find_reorder_panel_message,\n    ensure_reorder_ticket_panels,\n    create_reorder_ticket_from_closed_order,\n)\n"""


def main() -> None:
    source = BOT.read_text(encoding="utf-8")
    changed = False

    if WALLET_IMPORT not in source:
        count = source.count(WALLET_ANCHOR)
        if count != 1:
            raise RuntimeError(
                f"wallet import anchor count must be 1, got {count}"
            )
        source = source.replace(
            WALLET_ANCHOR,
            WALLET_ANCHOR + WALLET_IMPORT,
            1,
        )
        changed = True

    if NEW_SELF_SERVICE_IMPORTS not in source:
        count = source.count(OLD_SELF_SERVICE_IMPORT)
        if count != 1:
            raise RuntimeError(
                "legacy self-service import block count must be 1, "
                f"got {count}"
            )
        source = source.replace(
            OLD_SELF_SERVICE_IMPORT,
            NEW_SELF_SERVICE_IMPORTS,
            1,
        )
        changed = True

    if not changed:
        print("runtime import stabilization already applied")
        return

    BOT.write_text(source, encoding="utf-8")
    print("runtime import stabilization applied")


if __name__ == "__main__":
    main()
