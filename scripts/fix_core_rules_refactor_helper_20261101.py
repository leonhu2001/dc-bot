from __future__ import annotations

from pathlib import Path
import re

path = Path("scripts/aw_business_core_refactor_20261101.py")
text = path.read_text(encoding="utf-8")

pattern = r'''# ---------------------------------------------------------------------------\n# Financial behavior belongs in the financial calculator itself\.\n# ---------------------------------------------------------------------------\n.*?write\(path, text\)\n\n# ---------------------------------------------------------------------------\n# Checkout controls belong in the normal SelfServiceOrderView implementation\.\n'''

replacement = r'''# ---------------------------------------------------------------------------
# AW finance is a normal core domain module. The generic financial service
# calls it directly; nothing is replaced at runtime.
# ---------------------------------------------------------------------------
write(
    "services/aw_collision_financials.py",
    """from __future__ import annotations


def is_aw_collision_rule(rule_or_key) -> bool:
    key = str(getattr(rule_or_key, "key", rule_or_key) or "").strip()
    return key.startswith("farm_aw_collision_")


def _manual_staff_price(data: dict) -> int | None:
    raw_amount = data.get("manual_staff_amount")
    if raw_amount is None or str(raw_amount).strip() == "":
        return None
    try:
        amount = int(float(str(raw_amount).strip().replace(",", "")))
    except (TypeError, ValueError):
        return None
    return max(0, amount)


def calculate_aw_collision_financials(price_result, data: dict) -> dict:
    manual_price = _manual_staff_price(data)
    if manual_price is None:
        service_original = max(
            0,
            int(getattr(price_result, "base_amount", 0) or 0)
            + int(getattr(price_result, "staff_adjustment_amount", 0) or 0),
        )
    else:
        service_original = max(0, int(manual_price))

    service_quantity = max(1, int(getattr(price_result, "service_quantity", 1) or 1))
    return {
        "price_formula_version": 2,
        "manual_discount_mode": "pay_rate",
        "manual_price_missing": False,
        "manual_staff_amount": manual_price,
        "manual_staff_price_reason": str(data.get("manual_staff_price_reason") or "").strip(),
        "rule_original_amount": service_original,
        "service_original_amount": service_original,
        "original_amount": service_original,
        "priced_amount": service_original,
        "manual_discount_percent": 100.0,
        "discount_rate_percent": 100.0,
        "manual_discount_amount": 0,
        "percent_discount_amount": 0,
        "manual_discount_reason": "",
        "discount_source": "none",
        "vip_level_name": "",
        "cash_coupon_amount": 0,
        "fixed_discount_amount": 0,
        "cash_coupon_reason": "",
        "point_discount_coupon_amount": 0,
        "selected_vip_monthly_benefit_id": None,
        "vip_monthly_benefit_id": None,
        "vip_monthly_benefit_key": None,
        "vip_monthly_benefit_title": "",
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
        "service_quantity": service_quantity,
        "service_bonus_quantity": 0,
        "service_promotion_text": "",
        "payout_base_amount": service_original,
        "benefit_coupon_id": None,
        "benefit_coupon_title": "",
        "benefit_coupon": None,
        "benefit_service_note": "",
        "benefit_service_value": 0,
        "benefit_discount_amount": 0,
        "point_service_value": 0,
        "store_absorbed_amount": 0,
        "customer_pay_amount": service_original,
    }


__all__ = ["calculate_aw_collision_financials", "is_aw_collision_rule"]
""",
)

path = "services/self_service_financials.py"
text = read(path)
text = replace_once(
    text,
    "from typing import Any, Callable\n",
    "from typing import Any, Callable\n\nfrom services.aw_collision_financials import calculate_aw_collision_financials, is_aw_collision_rule\n",
    "import direct AW financial core",
)
text = replace_once(
    text,
    '\n\ndef calculate_self_service_financials(rule, price_result, data: dict) -> dict:\n    manual_price = get_self_service_staff_price(data)\n',
    '\n\ndef calculate_self_service_financials(rule, price_result, data: dict) -> dict:\n    if is_aw_collision_rule(rule):\n        return calculate_aw_collision_financials(price_result, data)\n\n    manual_price = get_self_service_staff_price(data)\n',
    "direct AW financial branch",
)
write(path, text)

# ---------------------------------------------------------------------------
# Checkout controls belong in the normal SelfServiceOrderView implementation.
'''

patched, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.S)
if count != 1:
    raise RuntimeError(f"AW finance section patch count={count}")

path.write_text(patched, encoding="utf-8")
print("AW_FINANCE_EXTRACTION_PATCHED")
