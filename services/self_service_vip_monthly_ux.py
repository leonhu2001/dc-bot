from __future__ import annotations

import re
import sys
from typing import Any


_INSTALLED = False


def _current_original_service_amount(
    rule,
    data: dict[str, Any],
    *,
    guild=None,
    price_result=None,
) -> int:
    """Recalculate the current order's original service amount before discounts."""
    try:
        from services.self_service_financials import (
            get_self_service_staff_price,
            is_self_service_staff_price_required,
        )

        if is_self_service_staff_price_required(rule):
            manual = get_self_service_staff_price(data)
            return max(0, int(manual or 0))
    except Exception:
        pass

    if price_result is None:
        try:
            from services import self_service_selection_runtime as selection
            from services.order_rules import calculate_price

            specified_roles: list[str] = []
            if guild is not None:
                for staff_id in data.get("specified_staff_ids") or []:
                    try:
                        member = guild.get_member(int(staff_id))
                    except Exception:
                        member = None
                    if member is None:
                        continue
                    try:
                        role_key = selection._role_key_for_member(rule, member)
                    except Exception:
                        role_key = None
                    if role_key:
                        specified_roles.append(str(role_key))

            price_result = calculate_price(
                rule,
                quantity=max(1, int(data.get("quantity") or 1)),
                player_count=max(1, int(data.get("player_count") or 1)),
                specified_roles=specified_roles,
            )
        except Exception:
            price_result = None

    if price_result is not None:
        return max(
            0,
            int(getattr(price_result, "base_amount", 0) or 0)
            + int(getattr(price_result, "staff_adjustment_amount", 0) or 0),
        )

    for key in (
        "service_original_amount",
        "original_amount",
        "manual_staff_amount",
    ):
        try:
            amount = int(data.get(key) or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount > 0:
            return amount
    return 0


def _monthly_status(benefit: dict[str, Any], *, original_amount: int) -> dict[str, Any]:
    from services.vip_monthly_order_discount import get_vip_monthly_cash_order_status

    return get_vip_monthly_cash_order_status(
        benefit,
        original_service_amount=original_amount,
    )


def _monthly_requirement_text(status: dict[str, Any]) -> str:
    from services.vip_monthly_order_discount import format_vip_monthly_cash_order_requirement

    return format_vip_monthly_cash_order_requirement(status)


def _monthly_benefit_by_id(items: list[dict], benefit_id) -> dict | None:
    target = str(benefit_id or "").strip()
    if not target:
        return None
    return next(
        (item for item in items if str(item.get("id") or "").strip() == target),
        None,
    )


def _option_description(status: dict[str, Any]) -> str:
    minimum = max(0, int(status.get("minimum") or 0))
    current = max(0, int(status.get("current") or 0))
    shortfall = max(0, int(status.get("shortfall") or 0))
    amount = max(0, int(status.get("amount") or 0))
    if bool(status.get("eligible")):
        if minimum > 0:
            return f"折抵 {amount}T；低消 {minimum:,}T；目前可使用"
        return f"折抵 {amount}T；目前可使用"
    return f"未達低消：需 {minimum:,}T，目前 {current:,}T，尚差 {shortfall:,}T"


def _insert_vip_monthly_into_detail(value: str, *, title: str, amount_text: str) -> str:
    text = str(value or "")
    segment = f"VIP 月券 -{amount_text}（{title}）"
    if segment in text:
        return text
    marker = "｜打手分潤基準"
    if marker in text:
        return text.replace(marker, f"｜{segment}{marker}", 1)
    return f"{text}｜{segment}" if text else segment


def merge_vip_monthly_into_quote_rows(
    rows: list[tuple[str, str]],
    *,
    title: str,
    amount_text: str,
) -> list[tuple[str, str]]:
    """Put VIP monthly cash discount inside 金額明細 and remove the extra row."""
    merged: list[tuple[str, str]] = []
    detail_found = False
    for name, value in rows:
        if name == "VIP 月券":
            continue
        if name == "金額明細":
            value = _insert_vip_monthly_into_detail(
                str(value or ""),
                title=title,
                amount_text=amount_text,
            )
            detail_found = True
        merged.append((name, value))
    if not detail_found:
        merged.append(("金額明細", f"VIP 月券 -{amount_text}（{title}）"))
    return merged


def _bind_runtime_alias(name: str, value) -> None:
    runtime = sys.modules.get("services.self_service_runtime")
    if runtime is not None:
        setattr(runtime, name, value)


def install_self_service_vip_monthly_ux() -> None:
    """Align VIP monthly coupon eligibility UX and financial presentation."""
    global _INSTALLED
    if _INSTALLED:
        return

    import discord

    from services import self_service_financial_copy as copy_policy
    from services import self_service_financials as financials
    from services import self_service_selection_runtime as selection
    from services.vip_monthly_benefits import list_available_cash_benefits

    # The finance engine is the authoritative last gate. Feed it the current
    # pre-discount service amount explicitly so 1,500 / 4,000 thresholds are
    # evaluated against the order's original service amount, not a post-VIP rate.
    if not hasattr(financials, "_vip_monthly_ux_original_calculate"):
        financials._vip_monthly_ux_original_calculate = financials.calculate_self_service_financials

        def calculate_self_service_financials(rule, price_result, data: dict):
            if data.get("selected_vip_monthly_benefit_id") not in (None, "") and not bool(
                data.get("website_finance_settled")
            ):
                prepared = dict(data)
                prepared["service_original_amount"] = _current_original_service_amount(
                    rule,
                    prepared,
                    price_result=price_result,
                )
                return financials._vip_monthly_ux_original_calculate(
                    rule,
                    price_result,
                    prepared,
                )
            return financials._vip_monthly_ux_original_calculate(rule, price_result, data)

        financials.calculate_self_service_financials = calculate_self_service_financials
        _bind_runtime_alias("calculate_self_service_financials", calculate_self_service_financials)

    # The compact self-service quote already has a single 金額明細 line. Keep the
    # VIP coupon there instead of creating a second standalone VIP 月券 line.
    if not hasattr(financials, "_vip_monthly_ux_original_quote_lines"):
        financials._vip_monthly_ux_original_quote_lines = financials._quote_preview_lines_for_self_service

        def quote_preview_lines(data: dict, guild=None):
            rows = financials._vip_monthly_ux_original_quote_lines(data, guild)
            display = copy_policy._vip_monthly_display(data)
            if not display:
                return rows
            title, amount = display
            return merge_vip_monthly_into_quote_rows(
                rows,
                title=title,
                amount_text=financials._format_plain_amount(amount),
            )

        financials._quote_preview_lines_for_self_service = quote_preview_lines
        _bind_runtime_alias("_quote_preview_lines_for_self_service", quote_preview_lines)

    if not hasattr(selection.SelfServicePointBenefitSelect, "_vip_monthly_ux_original_init"):
        selection.SelfServicePointBenefitSelect._vip_monthly_ux_original_init = (
            selection.SelfServicePointBenefitSelect.__init__
        )

        def select_init(self, parent_view):
            selection.SelfServicePointBenefitSelect._vip_monthly_ux_original_init(self, parent_view)
            data = selection.SELF_SERVICE_ORDER_SELECTIONS.get(parent_view.channel_id, {})
            original_amount = _current_original_service_amount(parent_view.rule, data)
            for option in self.options:
                value = str(getattr(option, "value", "") or "")
                if not value.startswith("vip_monthly:"):
                    continue
                benefit_id = value.split(":", 1)[1]
                benefit = _monthly_benefit_by_id(
                    parent_view.available_vip_monthly_benefits,
                    benefit_id,
                )
                if benefit is None:
                    continue
                status = _monthly_status(benefit, original_amount=original_amount)
                option.description = selection._truncate_select_text(_option_description(status))

        selection.SelfServicePointBenefitSelect.__init__ = select_init

    if not hasattr(selection.SelfServicePointBenefitSelect, "_vip_monthly_ux_original_callback"):
        selection.SelfServicePointBenefitSelect._vip_monthly_ux_original_callback = (
            selection.SelfServicePointBenefitSelect.callback
        )

        async def select_callback(self, interaction: discord.Interaction):
            view = self.view
            selected_value = str(self.values[0] if self.values else "")
            if isinstance(view, selection.SelfServicePointBenefitView) and selected_value.startswith(
                "vip_monthly:"
            ):
                benefit_id = selected_value.split(":", 1)[1]
                available = list_available_cash_benefits(view.customer_id)
                benefit = _monthly_benefit_by_id(available, benefit_id)
                if benefit is None:
                    await interaction.response.send_message(
                        "這張 VIP 每月折現券已使用、已保留或已失效，請重新開啟福利選單。",
                        ephemeral=True,
                    )
                    return

                data = selection.SELF_SERVICE_ORDER_SELECTIONS.get(view.channel_id, {})
                original_amount = _current_original_service_amount(
                    view.rule,
                    data,
                    guild=interaction.guild,
                )
                status = _monthly_status(benefit, original_amount=original_amount)
                if not bool(status.get("eligible")):
                    await interaction.response.send_message(
                        _monthly_requirement_text(status),
                        ephemeral=True,
                    )
                    return

            return await selection.SelfServicePointBenefitSelect._vip_monthly_ux_original_callback(
                self,
                interaction,
            )

        selection.SelfServicePointBenefitSelect.callback = select_callback

    if not hasattr(selection.SelfServicePointBenefitView, "_vip_monthly_ux_original_message"):
        selection.SelfServicePointBenefitView._vip_monthly_ux_original_message = (
            selection.SelfServicePointBenefitView.build_message_content
        )

        def build_message_content(self, data: dict | None = None) -> str:
            draft = data or selection.SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})
            text = selection.SelfServicePointBenefitView._vip_monthly_ux_original_message(
                self,
                draft,
            )
            original_amount = _current_original_service_amount(self.rule, draft)
            statuses = [
                _monthly_status(item, original_amount=original_amount)
                for item in self.available_vip_monthly_benefits
            ]
            if not statuses:
                return text

            eligible_monthly = sum(1 for status in statuses if bool(status.get("eligible")))
            other_available = len(self.available_coupons) + (
                1 if self.available_same_order_benefit else 0
            )
            eligible_total = eligible_monthly + other_available
            held_total = len(statuses) + other_available
            text = re.sub(
                r"可用福利券：\d+ 張",
                f"本單可用福利券：{eligible_total} 張\n持有福利券：{held_total} 張",
                text,
                count=1,
            )
            requirement_lines = "\n".join(
                f"・{_monthly_requirement_text(status)}"
                for status in statuses
            )
            return f"{text}\n\nVIP 月券使用門檻：\n{requirement_lines}"

        selection.SelfServicePointBenefitView.build_message_content = build_message_content

    _INSTALLED = True
