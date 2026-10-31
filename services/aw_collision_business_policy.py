from __future__ import annotations

from dataclasses import replace

import discord

from services.aw_collision_catalog import is_aw_collision_rule


_INSTALLED = False
_ORIGINAL_FINANCIAL_CALCULATOR = None
_ORIGINAL_DISCOUNT_RESOLVER = None
_ORIGINAL_VIEW_INIT = None


_AW_DISCOUNT_AND_BENEFIT_KEYS = {
    "manual_discount_mode",
    "manual_discount_percent",
    "manual_discount_percent_override",
    "manual_discount_reason",
    "manual_price_adjustment_set_by",
    "manual_price_adjustment_set_at",
    "cash_coupon_amount",
    "fixed_discount_amount",
    "cash_coupon_reason",
    "selected_point_benefit_key",
    "point_benefit_key",
    "point_benefit_name",
    "point_benefit_cost",
    "point_discount_coupon_amount",
    "point_waived_specify_fee",
    "point_free_first_hour_amount",
    "point_extra_hours",
    "point_extra_games",
    "selected_vip_monthly_benefit_id",
    "vip_monthly_benefit_id",
    "vip_monthly_benefit_key",
    "vip_monthly_benefit_title",
    "vip_monthly_cash_amount",
    "selected_benefit_coupon_id",
    "selected_same_order_benefit",
    "benefit_coupon_id",
    "benefit_coupon_title",
    "benefit_coupon",
    "benefit_service_value",
    "benefit_discount_amount",
    "benefit_service_note",
}


def _clean_aw_finance_input(data: dict) -> dict:
    clean = dict(data or {})
    for key in _AW_DISCOUNT_AND_BENEFIT_KEYS:
        clean.pop(key, None)
    clean.pop("specified_staff_ids", None)
    clean["companion_preference"] = "不指定陪玩/打手"
    return clean


def _install_financial_policy() -> None:
    global _ORIGINAL_FINANCIAL_CALCULATOR, _ORIGINAL_DISCOUNT_RESOLVER

    from services import self_service_financials as financials

    if _ORIGINAL_FINANCIAL_CALCULATOR is None:
        _ORIGINAL_FINANCIAL_CALCULATOR = financials.calculate_self_service_financials
    if _ORIGINAL_DISCOUNT_RESOLVER is None:
        _ORIGINAL_DISCOUNT_RESOLVER = financials._resolve_self_service_discount_rate

    original_calculate = _ORIGINAL_FINANCIAL_CALCULATOR
    original_resolve_discount = _ORIGINAL_DISCOUNT_RESOLVER

    def resolve_discount(rule, data: dict):
        if is_aw_collision_rule(getattr(rule, "key", None)):
            # AW 100% goes to the worker. Its internal-price mechanism is the
            # explicit CSR price override, never VIP/point/coupon stacking.
            return 100.0, "", "none", ""
        return original_resolve_discount(rule, data)

    def calculate(rule, price_result, data: dict) -> dict:
        if not is_aw_collision_rule(getattr(rule, "key", None)):
            return original_calculate(rule, price_result, data)

        clean = _clean_aw_finance_input(data)
        manual = financials.get_self_service_staff_price(data)
        if manual is None:
            base = max(
                0,
                int(getattr(price_result, "base_amount", 0) or 0)
                + int(getattr(price_result, "staff_adjustment_amount", 0) or 0),
            )
        else:
            base = max(0, int(manual))

        aw_price = replace(
            price_result,
            base_amount=base,
            specify_fee=0,
            staff_adjustment_amount=0,
            total_amount=base,
        )
        result = dict(original_calculate(rule, aw_price, clean))

        # Freeze every discount/benefit field to zero so stale order-level CSR
        # adjustments from a previously selected product cannot leak into AW.
        result.update(
            {
                "manual_price_missing": False,
                "manual_staff_amount": manual,
                "manual_staff_price_reason": str(data.get("manual_staff_price_reason") or "").strip(),
                "rule_original_amount": base,
                "service_original_amount": base,
                "original_amount": base,
                "priced_amount": base,
                "manual_discount_percent": 100.0,
                "discount_rate_percent": 100.0,
                "manual_discount_amount": 0,
                "percent_discount_amount": 0,
                "manual_discount_reason": "",
                "discount_source": "none",
                "cash_coupon_amount": 0,
                "fixed_discount_amount": 0,
                "cash_coupon_reason": "",
                "point_discount_coupon_amount": 0,
                "selected_vip_monthly_benefit_id": None,
                "vip_monthly_benefit_id": None,
                "vip_monthly_cash_amount": 0,
                "specified_fee_before_waiver": 0,
                "effective_specify_fee": 0,
                "point_waived_specify_fee": 0,
                "point_free_first_hour_amount": 0,
                "point_extra_hours": 0,
                "point_extra_games": 0,
                "point_benefit_key": None,
                "point_benefit_name": "",
                "point_benefit_cost": 0,
                "point_benefit_summary": "",
                "service_bonus_text": "",
                "service_bonus_quantity": 0,
                "service_promotion_text": "",
                "payout_base_amount": base,
                "benefit_coupon_id": None,
                "benefit_coupon_title": "",
                "benefit_coupon": None,
                "benefit_service_note": "",
                "benefit_service_value": 0,
                "benefit_discount_amount": 0,
                "point_service_value": 0,
                "store_absorbed_amount": 0,
                "customer_pay_amount": base,
            }
        )
        return result

    financials._resolve_self_service_discount_rate = resolve_discount
    financials.calculate_self_service_financials = calculate


def _install_checkout_controls() -> None:
    global _ORIGINAL_VIEW_INIT

    from services import self_service_ui_runtime as ui

    if _ORIGINAL_VIEW_INIT is None:
        _ORIGINAL_VIEW_INIT = ui.SelfServiceOrderView.__init__
    original = _ORIGINAL_VIEW_INIT

    def aw_business_view_init(view, customer_id: int, channel_id: int, selected_category: str | None = None):
        original(view, customer_id, channel_id, selected_category)
        data = ui.SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        rule_key = str(data.get("order_rule_key") or "").strip()
        if not is_aw_collision_rule(rule_key):
            return

        for child in list(view.children):
            custom_id = str(getattr(child, "custom_id", "") or "")
            if custom_id == "self_service_order_staff_price_button":
                child.disabled = False

                async def open_aw_staff_price(interaction: discord.Interaction):
                    if not isinstance(interaction.user, discord.Member) or not ui.is_customer_staff(interaction.user):
                        await interaction.response.send_message("只有客服可以填寫 AW 代撞內部價格。", ephemeral=True)
                        return
                    current = ui.SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
                    if not is_aw_collision_rule(current.get("order_rule_key")):
                        await interaction.response.send_message("目前已不是 AW 代撞商品，請重新操作。", ephemeral=True)
                        return
                    panel_message_id = interaction.message.id if interaction.message is not None else None
                    await interaction.response.send_modal(
                        ui.SelfServiceStaffPriceModal(
                            customer_id=customer_id,
                            channel_id=channel_id,
                            panel_message_id=panel_message_id,
                        )
                    )

                child.callback = open_aw_staff_price
            elif custom_id in {
                "self_service_order_specified_staff_button",
                "self_service_order_point_benefit_button",
                "self_service_order_staff_discount_coupon_button",
            }:
                child.disabled = True

    ui.SelfServiceOrderView.__init__ = aw_business_view_init


def install_aw_collision_business_policy() -> None:
    """Install only AW checkout/financial UI behavior. Qualification and payout are canonical rules."""
    global _INSTALLED
    if _INSTALLED:
        return

    _install_financial_policy()
    _install_checkout_controls()
    _INSTALLED = True


__all__ = ["install_aw_collision_business_policy"]
