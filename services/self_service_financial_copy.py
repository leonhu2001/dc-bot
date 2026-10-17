from __future__ import annotations

import re


_INSTALLED = False
_SHARED_COPY = "共同分攤，折後金額計入分潤基準"
_STORE_COPY = "店家吸收，不降低打手／客服分潤基準"


def _promotion_funding(data: dict) -> str | None:
    try:
        from services import promotion_benefits as promotion

        selection_id = data.get("selected_benefit_coupon_id")
        issued_id = promotion.decode_selection_id(selection_id)
        if issued_id is None:
            return None
        customer_id = str(data.get("customer_id") or "").strip()
        if not customer_id:
            return None
        for item in promotion.list_issued_benefits(
            customer_discord_id=customer_id,
            limit=1000,
        ):
            if int(item.get("id") or 0) != int(issued_id):
                continue
            rules = item.get("rules") if isinstance(item.get("rules"), dict) else {}
            return str(rules.get("funding") or promotion.FUNDING_STORE)
    except Exception:
        return None
    return None


def _rewrite_standard_discount_text(value: str) -> str:
    text = str(value or "")
    text = text.replace("店內吸收，不影響打手分潤", _SHARED_COPY)
    text = text.replace("店內吸收，不扣打手分潤", _SHARED_COPY)
    text = text.replace("（店內吸收）", f"（{_SHARED_COPY}）")
    return text


def _rewrite_quote_text(value: str, *, promotion_funding: str | None) -> str:
    text = str(value or "")

    # Protect the generic-benefit clause first. Loyalty benefits remain
    # store-funded; web-issued promotions can explicitly be shared.
    benefit_copy = _SHARED_COPY if promotion_funding == "shared" else _STORE_COPY
    text = re.sub(
        r"(累積福利\s+-[0-9,]+)(?:（店內吸收，不影響打手分潤）)",
        lambda match: f"{match.group(1)}（{benefit_copy}）",
        text,
    )

    # Ordinary manual fixed / point-cash discounts are shared under the current
    # funding policy. Any untouched store-funded generic clause is no longer an
    # exact match after the replacement above, so these replacements are safe.
    return _rewrite_standard_discount_text(text)


def install_self_service_financial_copy_policy() -> None:
    """Keep checkout copy consistent with the centralized funding rules."""
    global _INSTALLED
    if _INSTALLED:
        return

    from services import self_service_financials as financials

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
            return result

        financials.add_self_service_financial_breakdown_fields = (
            add_self_service_financial_breakdown_fields
        )

    if not hasattr(financials, "_funding_copy_original_quote_lines"):
        financials._funding_copy_original_quote_lines = (
            financials._quote_preview_lines_for_self_service
        )

        def quote_preview_lines(data: dict, guild=None):
            rows = financials._funding_copy_original_quote_lines(data, guild)
            promotion_funding = _promotion_funding(data)
            return [
                (
                    name,
                    _rewrite_quote_text(
                        str(value or ""),
                        promotion_funding=promotion_funding,
                    ),
                )
                for name, value in rows
            ]

        financials._quote_preview_lines_for_self_service = quote_preview_lines

    _INSTALLED = True
