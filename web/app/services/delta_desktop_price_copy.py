"""Live Delta desktop card copy for the public Web catalog.

Descriptions use the same effective OrderRule objects as the Bot checkout.
No duplicated hard-coded selling prices and no startup patch installation.
"""
from __future__ import annotations

from services.order_rules import ORDER_RULES


VISIBLE_DESKTOP_GROUPS = frozenset({
    "一陪一護", "體驗單", "娛樂陪", "技術陪",
    "絕巴技術陪", "賭約單", "油鍋單",
})


def _black_tide_live_description() -> str:
    lines = []
    for key, title in (
        ("basic_black_tide_entertain", "娛樂陪"),
        ("basic_black_tide_tech", "技術陪"),
    ):
        rule = ORDER_RULES.get(key)
        if rule is None:
            continue
        prices = dict(rule.player_count_prices or {})
        single = int(prices.get(1, rule.price))
        multi = int(prices.get(2, 0)) // 2
        limit = int(rule.max_player_count or 1)
        lines.append(
            f"{title}：單陪 {single}T/H，多陪每人 {multi}T/H（2～{limit} 人）"
        )

    if not lines:
        return ""
    entertainment = ORDER_RULES.get("basic_black_tide_entertain")
    technical = ORDER_RULES.get("basic_black_tide_tech")
    if entertainment is not None and technical is not None and (
        entertainment.loyalty_benefits_enabled
        and technical.loyalty_benefits_enabled
    ):
        lines.append("累積 10H 送 1H 折價券")
    if entertainment is not None and entertainment.allow_specify:
        fee = int(entertainment.specify_fee_default or 0)
        lines.append(f"指定每位 +{fee}T")
        if entertainment.specify_free_min_units:
            lines.append(f"{int(entertainment.specify_free_min_units)}H 以上免指定費")
    return "；".join(lines)


def render_delta_desktop_group_copy(
    *, category: str, label: str, description: str,
    variants: list[dict],
) -> str:
    if category == "delta_desktop_basic" and label == "黑潮爆破":
        return _black_tide_live_description() or description
    if category != "delta_desktop_basic" or label not in VISIBLE_DESKTOP_GROUPS:
        return description

    rows: list[str] = []
    for variant in variants:
        rule_key = str(variant.get("rule_key") or "")
        rule = ORDER_RULES.get(rule_key)
        if rule is None:
            continue
        # All three entertainment receiver choices have the same two prices.
        if label == "娛樂陪" and rows:
            break
        tiers = dict(getattr(rule, "player_count_prices", {}) or {})
        if rule.player_count_enabled and 1 in tiers and 2 in tiers:
            unit = "單護／雙護" if label == "技術陪" else "單陪／雙陪"
            seat_names = unit.split("／")
            rate = (
                f"{seat_names[0]} {tiers[1]:,}T/H、"
                f"{seat_names[1]} {tiers[2]:,}T/H"
            )
        else:
            rate = f"{int(rule.price):,}T/{'H' if rule.pricing_type == 'hourly' else '單'}"
        note = str(rule.note or "").strip()
        line = f"{variant['label']}：{rate}"
        if note:
            line += f"；{note}"
        rows.append(line)

    if not rows:
        return description
    rule = ORDER_RULES.get(str(variants[0].get("rule_key") or ""))
    specify = ""
    if rule is not None and rule.allow_specify:
        fees = [int(v) for v in (rule.specify_fee_by_role or {}).values() if int(v) > 0]
        fee = int(rule.specify_fee_default or 0) or (max(fees) if fees else 0)
        if fee > 0:
            specify = f"指定每人 +{fee}T"
            if int(rule.specify_free_min_units or 0) >= 2:
                specify += f"；{int(rule.specify_free_min_units)}H 以上免指定費"
    final = "；".join(rows + ([specify] if specify else []))
    return f"{description} {final}".strip() if description else final
