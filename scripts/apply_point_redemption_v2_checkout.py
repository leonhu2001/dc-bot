from pathlib import Path


SOURCE = Path("web/app/services/checkout_preview_core.py")
TARGET = Path("web/app/services/checkout_preview.py")

text = SOURCE.read_text(encoding="utf-8")

import_anchor = '''from services.order_flow import (
    get_payment_method_info,
)
'''
shared_import = '''from services.order_flow import (
    get_payment_method_info,
)
from services.point_benefit_catalog import (
    LEGACY_POINT_REDEEM_ITEMS,
    POINT_REDEEM_ITEMS,
    adapt_point_benefit_for_rule,
    get_point_benefit_item,
    is_service_bonus_allowed_for_rule,
)
'''
if import_anchor not in text:
    raise RuntimeError("checkout import anchor not found")
text = text.replace(import_anchor, shared_import, 1)

points_start = text.index("# ============================================================\n# Points\n")
payment_start = text.index("PAYMENT_METHODS = [", points_start)
new_points = '''# ============================================================
# Points
# ============================================================

def _materialize_point_item(key: str) -> dict | None:
    item = get_point_benefit_item(key)
    return dict(item) if item is not None else None


POINT_ITEMS = [
    item
    for item in (
        _materialize_point_item(str(source.get("key") or ""))
        for source in POINT_REDEEM_ITEMS
    )
    if item is not None
]


# Legacy benefits remain lookup-only for orders created before this migration.
POINT_ITEM_MAP = {
    item["key"]: item
    for item in [
        *POINT_ITEMS,
        *[
            benefit
            for benefit in (
                _materialize_point_item(str(source.get("key") or ""))
                for source in LEGACY_POINT_REDEEM_ITEMS
            )
            if benefit is not None
        ],
    ]
}


'''
text = text[:points_start] + new_points + text[payment_start:]

rules_start = text.index("# ============================================================\n# Point benefit rules\n")
financial_start = text.index("# ============================================================\n# Financial calculation\n", rules_start)
new_rules = '''# ============================================================
# Point benefit rules
# ============================================================

def _point_item_for_rule(rule, item: dict) -> dict:
    return adapt_point_benefit_for_rule(rule, item)


def point_item_status(
    *,
    rule_key: str,
    point_item_key: str,
    point_balance: int,
    quantity: int,
    has_specified_staff: bool,
) -> dict:
    rule = ORDER_RULES.get(str(rule_key))
    item = POINT_ITEM_MAP.get(str(point_item_key))

    if rule is None or item is None:
        return {"allowed": False, "reason": "不支援這個點數福利。"}

    if point_balance < int(item["cost"]):
        return {"allowed": False, "reason": "點數不足。"}

    if not bool(rule.point_benefits_allowed):
        return {"allowed": False, "reason": "此方案不可使用點數福利。"}

    category = str(rule.category)
    if category == "steam":
        return {"allowed": False, "reason": "Steam遊戲目前不可使用點數福利。"}

    if category in {"fun", "delta_desktop_fun", "title"}:
        return {"allowed": False, "reason": "趣味單不可使用點數福利。"}

    if str(rule_key).startswith("basic_trial_"):
        return {"allowed": False, "reason": "體驗單不可使用點數福利。"}

    pricing_type = str(rule.pricing_type)
    kind = str(item.get("kind") or "")

    if kind == "service_bonus":
        if pricing_type not in {"hourly", "game"}:
            return {"allowed": False, "reason": "服務加贈只適用計時或計局方案。"}
        if not is_service_bonus_allowed_for_rule(rule, item):
            return {"allowed": False, "reason": "這張服務加贈券不適用此陪玩類型。"}

    pricing_types = tuple(item.get("pricing_types") or ())
    if pricing_types and pricing_type not in pricing_types:
        label = "計時" if "hourly" in pricing_types else "計局"
        return {"allowed": False, "reason": f"此點數福利只適用{label}方案。"}

    if kind == "free_specify_fee":
        if not rule.allow_specify:
            return {"allowed": False, "reason": "此方案不開放指定。"}
        if pricing_type == "hourly" and int(quantity) >= 2:
            return {"allowed": False, "reason": "2 小時以上本來就免指定費。"}
        if not has_specified_staff:
            return {
                "allowed": False,
                "requires_specified": True,
                "reason": "需先指定人員。",
            }

    if kind == "extra_hours" and pricing_type != "hourly":
        return {"allowed": False, "reason": "加時只適用計時方案。"}

    if kind == "extra_games" and pricing_type != "game":
        return {"allowed": False, "reason": "加局只適用計局方案。"}

    return {"allowed": True, "reason": ""}


def list_point_options(
    *,
    rule_key: str,
    point_balance: int,
    quantity: int,
    has_specified_staff: bool = False,
) -> list[dict]:
    rule = ORDER_RULES.get(str(rule_key))
    if rule is None:
        return []

    result = []
    for item in POINT_ITEMS:
        status = point_item_status(
            rule_key=rule_key,
            point_item_key=item["key"],
            point_balance=point_balance,
            quantity=quantity,
            has_specified_staff=has_specified_staff,
        )
        data = _point_item_for_rule(rule, item)
        data.update(status)
        result.append(data)

    return result


'''
text = text[:rules_start] + new_rules + text[financial_start:]

calc_start = text.index("def calculate_point_service_value(")
calc_end = text.index("\ndef calculate_checkout_financials(", calc_start)
new_calc = '''def calculate_point_service_value(
    *,
    quote: dict,
    vip_pay_rate: int,
    point_item: dict | None,
) -> int:
    """Compute store-funded payout value for one companion seat only."""
    if not point_item:
        return 0

    kind = str(point_item.get("kind") or "")
    if kind == "extra_hours":
        units = float(point_item.get("hours") or 0)
    elif kind == "extra_games":
        units = float(point_item.get("games") or 0)
    else:
        return 0

    if units <= 0:
        return 0

    quantity = max(1, int(quote.get("quantity") or 1))
    staff_count = max(1, int(quote.get("required_staff_count") or 1))
    service_amount = max(0, int(quote.get("customer_pay_amount") or 0))
    gross_extra_value = int(round((service_amount / quantity / staff_count) * units))

    # VIP only changes the customer's charge; the extra service is funded at its
    # normal one-seat value so the selected companion's payout is not reduced.
    return max(0, gross_extra_value)

'''
text = text[:calc_start] + new_calc + text[calc_end + 1:]

text = text.replace(
    '''point_service_note = (
                "服務時間 +30 分鐘"
                if hours == 0.5
                else f"服務時間 +{hours:g} 小時"
            )''',
    '''point_service_note = (
                "服務時間 +30 分鐘（1 位陪玩）"
                if hours == 0.5
                else f"服務時間 +{hours:g} 小時（1 位陪玩）"
            )''',
    1,
)
text = text.replace(
    'point_service_note = f"服務局數 +{games} 局"',
    'point_service_note = f"服務局數 +{games} 局（1 位陪玩）"',
    1,
)

TARGET.write_text(text, encoding="utf-8")
