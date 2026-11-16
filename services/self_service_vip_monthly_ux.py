from __future__ import annotations

import re
from typing import Any


_INSTALLED = False
_VIP_MONTHLY_FUNDING_COPY = "店家全額吸收，不影響陪玩／打手應得款項"


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


def _vip_monthly_detail_segment(*, title: str, amount_text: str) -> str:
    return (
        f"VIP 月券 -{amount_text}（{title}；"
        f"{_VIP_MONTHLY_FUNDING_COPY}）"
    )


def _insert_vip_monthly_into_detail(value: str, *, title: str, amount_text: str) -> str:
    text = str(value or "")
    segment = _vip_monthly_detail_segment(title=title, amount_text=amount_text)
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
        merged.append(
            (
                "金額明細",
                _vip_monthly_detail_segment(title=title, amount_text=amount_text),
            )
        )
    return merged


def install_self_service_vip_monthly_ux() -> None:
    """Compatibility hook; native finance and UI enforce voucher policies."""
    global _INSTALLED
    _INSTALLED = True


def apply_vip_monthly_option_descriptions(select, parent_view) -> None:
    from services import self_service_selection_runtime as selection

    data = selection.SELF_SERVICE_ORDER_SELECTIONS.get(parent_view.channel_id, {})
    original = _current_original_service_amount(parent_view.rule, data)
    for option in select.options:
        value = str(getattr(option, "value", "") or "")
        if not value.startswith("vip_monthly:"):
            continue
        benefit = _monthly_benefit_by_id(
            parent_view.available_vip_monthly_benefits, value.split(":", 1)[1],
        )
        if benefit is not None:
            option.description = selection._truncate_select_text(
                _option_description(_monthly_status(benefit, original_amount=original))
            )


def monthly_selection_error(view, selected: str, data: dict, guild) -> str | None:
    if not selected.startswith("vip_monthly:"):
        return None
    from services.vip_monthly_benefits import list_available_cash_benefits

    benefit = _monthly_benefit_by_id(
        list_available_cash_benefits(view.customer_id), selected.split(":", 1)[1],
    )
    if benefit is None:
        return "這張 VIP 每月折現券已使用、已保留或已失效，請重新開啟福利選單。"

    original = _current_original_service_amount(view.rule, data, guild=guild)
    status = _monthly_status(benefit, original_amount=original)
    if not bool(status.get("eligible")):
        return _monthly_requirement_text(status)
    return None


def render_vip_monthly_message(view, data: dict, selected_text: str) -> str:
    message = (
        f"請選擇這張單要使用的點數福利或會員福利券。\n"
        f"目前可用點數：{view.point_balance} 點\n"
        f"可用福利券：{len(view.available_vip_monthly_benefits) + len(view.available_coupons) + (1 if view.available_same_order_benefit else 0)} 張\n"
        f"目前選擇：{selected_text}\n\n"
        "同張訂單只能擇一；福利券會在訂單建立時先保留，結單後正式核銷。"
    )
    if not view.available_vip_monthly_benefits:
        return message
    original = _current_original_service_amount(view.rule, data)
    statuses = [
        _monthly_status(item, original_amount=original)
        for item in view.available_vip_monthly_benefits
    ]
    other = len(view.available_coupons) + (
        1 if view.available_same_order_benefit else 0
    )
    eligible = sum(bool(status.get("eligible")) for status in statuses)
    message = re.sub(
        r"可用福利券[:：]\d+ 張",
        f"本單可用福利券：{eligible + other} 張\n持有福利券：{len(statuses) + other} 張",
        message, count=1,
    )
    requirements = "\n".join(
        f"・{_monthly_requirement_text(status)}" for status in statuses
    )
    return f"{message}\n\nVIP 月券使用門檻：\n{requirements}"
