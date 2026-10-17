from __future__ import annotations

"""Compatibility facade for Discord self-service financials.

The large runtime implementation is preserved in ``self_service_financials_legacy``.
This facade applies the new fixed-discount policy without duplicating the entire
Discord order calculator, and makes the VIP monthly per-order minimum validate
against the true original service amount.
"""

from services import self_service_financials_legacy as _legacy
from services.self_service_financials_legacy import *  # noqa: F401,F403


FINANCIAL_POLICY_VERSION = "2026-10-17-shared-fixed-cs-margin-v1"

_base_calculate_self_service_financials = _legacy.calculate_self_service_financials
_base_add_financial_breakdown = _legacy.add_self_service_financial_breakdown_fields
_base_quote_preview_lines = _legacy._quote_preview_lines_for_self_service


def _original_service_amount(rule, price_result, data: dict) -> int:
    manual_price = _legacy.get_self_service_staff_price(data)
    if _legacy.is_self_service_staff_price_required(rule):
        return max(0, int(manual_price or 0))
    return max(
        0,
        int(getattr(price_result, "base_amount", 0) or 0)
        + int(getattr(price_result, "staff_adjustment_amount", 0) or 0),
    )


def calculate_self_service_financials(rule, price_result, data: dict) -> dict:
    # VIP monthly cash vouchers validate at the original service amount before
    # VIP percentage/fixed discounts.  The preserved calculator's resolver can
    # read this temporary field, so both Web and Discord enforce 1500/4000T the
    # same way even before the resulting snapshot exists.
    had_original = "service_original_amount" in data
    previous_original = data.get("service_original_amount")
    data["service_original_amount"] = _original_service_amount(rule, price_result, data)
    try:
        result = _base_calculate_self_service_financials(rule, price_result, data)
    finally:
        if had_original:
            data["service_original_amount"] = previous_original
        else:
            data.pop("service_original_amount", None)

    result = dict(result or {})
    result["financial_policy_version"] = FINANCIAL_POLICY_VERSION
    return result


def _shared_funding_copy(value: str) -> str:
    text = str(value or "")
    replacements = {
        "店內吸收，不影響打手分潤": "共同分攤，折後金額計入分潤基準",
        "店內吸收，不扣打手分潤": "共同分攤，折後金額計入分潤基準",
        "（店內吸收）": "（共同分攤）",
        "，店內吸收，不影響打手分潤）": "，共同分攤）",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _quote_preview_lines_for_self_service(data: dict, guild=None):
    return [
        (name, _shared_funding_copy(value))
        for name, value in _base_quote_preview_lines(data, guild)
    ]


def add_self_service_financial_breakdown_fields(embed, src: dict, final_label="顧客應付"):
    result = _base_add_financial_breakdown(embed, src, final_label=final_label)
    # discord.Embed fields are immutable proxies, so rewrite only affected text
    # through the supported set_field_at API.
    for index, field in enumerate(list(result.fields)):
        updated = _shared_funding_copy(field.value)
        if updated != field.value:
            result.set_field_at(
                index,
                name=field.name,
                value=updated,
                inline=field.inline,
            )
    return result


# Functions defined in the preserved module resolve module globals at runtime.
# Patch those globals so internal preview/render calls use the policy wrappers.
_legacy.calculate_self_service_financials = calculate_self_service_financials
_legacy._quote_preview_lines_for_self_service = _quote_preview_lines_for_self_service
_legacy.add_self_service_financial_breakdown_fields = add_self_service_financial_breakdown_fields
