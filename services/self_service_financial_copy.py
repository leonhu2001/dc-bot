from __future__ import annotations

import re
import sys


_INSTALLED = False
_SHARED_COPY = "共同分攤，折後金額計入分潤基準"
_STORE_COPY = "店家吸收，不降低打手／客服分潤基準"

_SETTLED_FINANCIAL_KEYS = frozenset(
    {
        "price_formula_version",
        "manual_price_missing",
        "manual_staff_amount",
        "manual_staff_price_reason",
        "rule_original_amount",
        "service_original_amount",
        "original_amount",
        "priced_amount",
        "manual_discount_mode",
        "manual_discount_percent",
        "discount_rate_percent",
        "manual_discount_amount",
        "percent_discount_amount",
        "manual_discount_reason",
        "discount_source",
        "vip_level_name",
        "cash_coupon_amount",
        "fixed_discount_amount",
        "cash_coupon_reason",
        "point_discount_coupon_amount",
        "vip_monthly_benefit_id",
        "vip_monthly_benefit_key",
        "vip_monthly_benefit_title",
        "vip_monthly_cash_amount",
        "specified_fee_before_waiver",
        "effective_specify_fee",
        "point_waived_specify_fee",
        "point_free_first_hour_amount",
        "point_extra_hours",
        "point_extra_games",
        "point_benefit_key",
        "point_benefit_name",
        "point_benefit_cost",
        "point_benefit_summary",
        "service_bonus_text",
        "service_quantity",
        "service_bonus_quantity",
        "service_promotion_text",
        "payout_base_amount",
        "benefit_coupon_id",
        "benefit_coupon_title",
        "benefit_coupon",
        "benefit_service_note",
        "benefit_service_value",
        "benefit_discount_amount",
        "point_service_value",
        "promotion_benefit_id",
        "promotion_discount_amount",
        "promotion_funding",
        "promotion_rules_snapshot",
        "store_absorbed_amount",
        "customer_pay_amount",
    }
)


def _promotion_funding(data: dict) -> str | None:
    try:
        from services import promotion_benefits as promotion

        selection_id = data.get("selected_benefit_coupon_id")
        issued_id = promotion.decode_selection_id(selection_id)
        if issued_id is None:
            return str(data.get("promotion_funding") or "").strip() or None
        customer_id = str(data.get("customer_id") or "").strip()
        if not customer_id:
            return str(data.get("promotion_funding") or "").strip() or None
        for item in promotion.list_issued_benefits(
            customer_discord_id=customer_id,
            limit=1000,
        ):
            if int(item.get("id") or 0) != int(issued_id):
                continue
            rules = item.get("rules") if isinstance(item.get("rules"), dict) else {}
            return str(rules.get("funding") or promotion.FUNDING_STORE)
    except Exception:
        return str(data.get("promotion_funding") or "").strip() or None
    return str(data.get("promotion_funding") or "").strip() or None


def _vip_monthly_display(data: dict) -> tuple[str, int] | None:
    title = str(data.get("vip_monthly_benefit_title") or "").strip()
    try:
        amount = max(0, int(data.get("vip_monthly_cash_amount") or 0))
    except (TypeError, ValueError):
        amount = 0

    if title and amount > 0:
        return title, amount

    selection_id = data.get("selected_vip_monthly_benefit_id")
    customer_id = str(data.get("customer_id") or "").strip()
    if selection_id in (None, "") or not customer_id:
        return None

    try:
        from services.vip_monthly_benefits import get_available_cash_benefit

        selected = get_available_cash_benefit(selection_id, customer_id=customer_id)
    except Exception:
        selected = None

    if not selected:
        return None

    title = str(selected.get("title") or "VIP 每月折現券").strip()
    try:
        amount = max(0, int(selected.get("amount") or 0))
    except (TypeError, ValueError):
        amount = 0
    return (title, amount) if amount > 0 else None


def _rewrite_standard_discount_text(value: str) -> str:
    text = str(value or "")
    text = text.replace("店內吸收，不影響打手分潤", _SHARED_COPY)
    text = text.replace("店內吸收，不扣打手分潤", _SHARED_COPY)
    text = text.replace("（店內吸收）", f"（{_SHARED_COPY}）")
    return text


def _rewrite_quote_text(value: str, *, promotion_funding: str | None) -> str:
    text = str(value or "")

    benefit_copy = _SHARED_COPY if promotion_funding == "shared" else _STORE_COPY
    text = re.sub(
        r"(累積福利\s+-[0-9,]+)(?:（店內吸收，不影響打手分潤）)",
        lambda match: f"{match.group(1)}（{benefit_copy}）",
        text,
    )
    return _rewrite_standard_discount_text(text)


def _bind_runtime_alias(name: str, value) -> None:
    runtime = sys.modules.get("services.self_service_runtime")
    if runtime is not None:
        setattr(runtime, name, value)


def install_self_service_financial_copy_policy() -> None:
    """Keep checkout copy and settled Web order snapshots consistent everywhere."""
    global _INSTALLED
    if _INSTALLED:
        return

    from services import self_service_financials as financials

    if not hasattr(financials, "_settled_snapshot_original_calculate"):
        financials._settled_snapshot_original_calculate = (
            financials.calculate_self_service_financials
        )

        def calculate_self_service_financials(rule, price_result, data: dict):
            if not bool(data.get("website_finance_settled")):
                return financials._settled_snapshot_original_calculate(
                    rule,
                    price_result,
                    data,
                )

            # Web checkout already validated/reserved its benefit. Re-querying a
            # now-reserved coupon in Discord can make a valid settled order look
            # unavailable, so calculate structure without redeemable selectors and
            # overlay the authoritative saved checkout snapshot afterwards.
            safe_data = dict(data)
            for key in (
                "selected_point_benefit_key",
                "selected_vip_monthly_benefit_id",
                "selected_benefit_coupon_id",
            ):
                safe_data.pop(key, None)

            result = financials._settled_snapshot_original_calculate(
                rule,
                price_result,
                safe_data,
            )
            for key in _SETTLED_FINANCIAL_KEYS:
                if key in data and data.get(key) is not None:
                    result[key] = data.get(key)
            return result

        financials.calculate_self_service_financials = calculate_self_service_financials
        _bind_runtime_alias(
            "calculate_self_service_financials",
            calculate_self_service_financials,
        )

    if not hasattr(financials, "_funding_copy_original_add_breakdown"):
        financials._funding_copy_original_add_breakdown = (
            financials.add_self_service_financial_breakdown_fields
        )

        def add_self_service_financial_breakdown_fields(embed, src, final_label="顧客應付"):
            result = financials._funding_copy_original_add_breakdown(
                embed,
                src,
                final_label=final_label,
            )
            for index, field in enumerate(list(result.fields)):
                if field.name not in {"固定折扣", "點數折價"}:
                    continue
                rewritten = _rewrite_standard_discount_text(str(field.value or ""))
                if rewritten != str(field.value or ""):
                    result.set_field_at(
                        index,
                        name=field.name,
                        value=rewritten,
                        inline=field.inline,
                    )

            vip_monthly = _vip_monthly_display(dict(src or {}))
            if vip_monthly and not any(field.name == "VIP 月券" for field in result.fields):
                title, amount = vip_monthly
                result.add_field(
                    name="VIP 月券",
                    value=f"{title}\n-{financials._format_plain_amount(amount)}",
                    inline=False,
                )
            return result

        financials.add_self_service_financial_breakdown_fields = (
            add_self_service_financial_breakdown_fields
        )
        _bind_runtime_alias(
            "add_self_service_financial_breakdown_fields",
            add_self_service_financial_breakdown_fields,
        )

    if not hasattr(financials, "_funding_copy_original_quote_lines"):
        financials._funding_copy_original_quote_lines = (
            financials._quote_preview_lines_for_self_service
        )

        def quote_preview_lines(data: dict, guild=None):
            rows = financials._funding_copy_original_quote_lines(data, guild)
            promotion_funding = _promotion_funding(data)
            rewritten_rows = [
                (
                    name,
                    _rewrite_quote_text(
                        str(value or ""),
                        promotion_funding=promotion_funding,
                    ),
                )
                for name, value in rows
            ]

            vip_monthly = _vip_monthly_display(data)
            if vip_monthly and not any(name == "VIP 月券" for name, _ in rewritten_rows):
                title, amount = vip_monthly
                rewritten_rows.append(
                    (
                        "VIP 月券",
                        f"{title}｜-{financials._format_plain_amount(amount)}",
                    )
                )
            return rewritten_rows

        financials._quote_preview_lines_for_self_service = quote_preview_lines
        _bind_runtime_alias(
            "_quote_preview_lines_for_self_service",
            quote_preview_lines,
        )

    _INSTALLED = True
