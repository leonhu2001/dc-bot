from __future__ import annotations

from typing import Any

VIP_BENEFIT_ITEMS: dict[str, str] = {
    "vip_room": "・專屬 VIP 身分組，可使用VIP專屬包廂",
    "priority_cs": "・優先客服回覆",
    "discount_98": "・體驗單、趣味單外全館98折",
    "rebate_1": "・儲值返利1%",
    "rebate_2": "・儲值返利2%",
    "monthly_coupon_200": "・每月一張折現券200T",
    "priority_order": "・優先排單",
    "familiar_worker": "・優先安排熟悉／收藏陪玩",
    "rebate_3": "・儲值返利3%",
    "discount_96": "・體驗單、趣味單外全館96折",
    "monthly_coupon_500": "・每月額外一張折現券500T",
    "free_secret_space": "・每月一次免費「機密航天保底1000w」或娛樂陪 2H",
    "discount_94": "・體驗單、趣味單外全館94折",
    "custom_order": "・可根據闆闆要求製作\"自訂單\"",
}

VIP_LEVELS: list[dict[str, Any]] = [
    {
        "name": "銀級魔丸",
        "threshold": 2000,
        "role_id": 1516575040206929920,
        "benefit_keys": ["vip_room", "priority_cs"],
    },
    {
        "name": "金級魔丸",
        "threshold": 6000,
        "role_id": 1516575036973256738,
        "benefit_keys": ["vip_room", "priority_cs", "discount_98", "custom_order"],
    },
    {
        "name": "白金魔丸",
        "threshold": 12000,
        "role_id": 1516575034670583929,
        "benefit_keys": [
            "vip_room", "priority_cs", "discount_98", "rebate_1",
            "monthly_coupon_200", "priority_order", "custom_order",
        ],
    },
    {
        "name": "鑽石魔丸",
        "threshold": 25000,
        "role_id": 1516575030648115200,
        "benefit_keys": [
            "vip_room", "priority_cs", "monthly_coupon_200", "priority_order",
            "familiar_worker", "rebate_2", "discount_96", "custom_order",
        ],
    },
    {
        "name": "白鑽魔丸",
        "threshold": 50000,
        "role_id": 1516575026583961711,
        "benefit_keys": [
            "vip_room", "priority_cs", "monthly_coupon_200", "priority_order",
            "familiar_worker", "discount_96", "rebate_3", "monthly_coupon_500",
            "custom_order",
        ],
    },
    {
        "name": "黑鑽魔丸",
        "threshold": 88888,
        "role_id": 1516575018807726150,
        "benefit_keys": [
            "vip_room", "priority_cs", "monthly_coupon_200", "priority_order",
            "familiar_worker", "monthly_coupon_500", "free_secret_space",
            "rebate_3", "discount_94", "custom_order",
        ],
    },
]

BASE_MEMBER_LEVELS: list[dict[str, int | str]] = [
    {"name": "普通魔丸", "threshold": 0},
    *[
        {"name": str(level["name"]), "threshold": int(level["threshold"])}
        for level in VIP_LEVELS
    ],
]

VIP_ROLE_TIERS: list[dict[str, int | str]] = [
    {
        "name": str(level["name"]),
        "threshold": int(level["threshold"]),
        "role_id": int(level["role_id"]),
    }
    for level in VIP_LEVELS
]
VIP_ROLE_IDS: list[int] = [int(level["role_id"]) for level in VIP_LEVELS]
SILVER_MEMBER_ROLE_ID: int = int(VIP_LEVELS[0]["role_id"])

VIP_RETENTION_DAYS: dict[str, int] = {
    "普通魔丸": 0,
    "銀級魔丸": 30,
    "金級魔丸": 45,
    "白金魔丸": 60,
    "鑽石魔丸": 90,
    "白鑽魔丸": 120,
    "黑鑽魔丸": 180,
}

# 2026-10-14 起的新制。既有儲值單會在 topup_orders.policy_version 保留 legacy。
VIP_TOPUP_REBATE_POLICY_CURRENT = "2026-10-14"
VIP_TOPUP_REBATE_POLICY_LEGACY = "legacy"
VIP_TOPUP_REBATE_PERCENT: dict[str, int] = {
    "普通魔丸": 0,
    "銀級魔丸": 0,
    "金級魔丸": 0,
    "白金魔丸": 1,
    "鑽石魔丸": 2,
    "白鑽魔丸": 3,
    "黑鑽魔丸": 3,
}
VIP_TOPUP_REBATE_PERCENT_LEGACY: dict[str, int] = {
    "普通魔丸": 0,
    "銀級魔丸": 0,
    "金級魔丸": 0,
    "白金魔丸": 2,
    "鑽石魔丸": 3,
    "白鑽魔丸": 4,
    "黑鑽魔丸": 5,
}

VIP_DISCOUNT_PAY_RATES: dict[str, int] = {
    "普通魔丸": 100,
    "銀級魔丸": 100,
    "金級魔丸": 98,
    "白金魔丸": 98,
    "鑽石魔丸": 96,
    "白鑽魔丸": 96,
    "黑鑽魔丸": 94,
}

VIP_DISCOUNT_EXCLUDED_CATEGORIES: frozenset[str] = frozenset({"fun", "title"})


class _VipDiscountExcludedRuleKeys(frozenset):
    """Static exclusions plus each product's live VIP eligibility setting."""

    def __contains__(self, value) -> bool:
        key = str(value or "").strip()
        if super().__contains__(key):
            return True
        if not key:
            return False
        try:
            from services.order_rules import ORDER_RULES

            rule = ORDER_RULES.get(key)
            if rule is not None:
                return not bool(getattr(rule, "vip_discount_allowed", True))
        except Exception:
            pass
        return False


VIP_DISCOUNT_EXCLUDED_RULE_KEYS: frozenset[str] = _VipDiscountExcludedRuleKeys({
    "basic_trial_500",
    "basic_trial_1000",
    "farm_season_3x3_normal",
    "farm_season_3x3_contract",
    "farm_season_3x3_dc_skin",
    "farm_season_3x3_dc_loss",
    "farm_season_3x3_dc_skin_loss",
})


def get_vip_discount_pay_rate(
    level_name: str | None,
    *,
    category: str | None = None,
    rule_key: str | None = None,
) -> int:
    rate = int(VIP_DISCOUNT_PAY_RATES.get(str(level_name or "普通魔丸"), 100))
    if rate >= 100:
        return 100
    if str(category or "").strip() in VIP_DISCOUNT_EXCLUDED_CATEGORIES:
        return 100
    if str(rule_key or "").strip() in VIP_DISCOUNT_EXCLUDED_RULE_KEYS:
        return 100
    return max(0, min(100, rate))


def get_topup_rebate_percent(
    level_name: str | None,
    *,
    policy_version: str | None = None,
) -> int:
    policy = str(policy_version or VIP_TOPUP_REBATE_POLICY_CURRENT).strip()
    rates = (
        VIP_TOPUP_REBATE_PERCENT_LEGACY
        if policy == VIP_TOPUP_REBATE_POLICY_LEGACY
        else VIP_TOPUP_REBATE_PERCENT
    )
    return int(rates.get(str(level_name or "普通魔丸"), 0))


def get_vip_retention_days(level_name: str | None) -> int:
    return int(VIP_RETENTION_DAYS.get(str(level_name or "普通魔丸"), 0))


def has_active_vip_progress_reset(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    try:
        base_total = int(data.get("vip_progress_base_total_spent"))
    except (TypeError, ValueError):
        return False
    if data.get("vip_progress_reset_active") is True:
        return True
    logs = data.get("vip_downgrade_logs")
    if isinstance(logs, list) and bool(logs):
        return True
    if (
        data.get("last_level_manual_fixed_at")
        or data.get("last_level_manual_fixed_by")
        or data.get("last_level_manual_fixed_reason")
    ):
        return True
    try:
        stored_index = int(data.get("vip_level_index"))
    except (TypeError, ValueError):
        stored_index = None
    try:
        total_spent = int(data.get("total_spent", 0) or 0)
    except (TypeError, ValueError):
        total_spent = 0
    return stored_index == 0 and base_total > 0 and base_total <= total_spent


def build_vip_level_benefits() -> dict[str, str]:
    benefits: dict[str, str] = {"普通魔丸": "尚未解鎖 VIP 福利。"}
    for level in VIP_LEVELS:
        lines = [f"累積消費 {int(level['threshold'])}⤴️"]
        lines.extend(
            VIP_BENEFIT_ITEMS[key]
            for key in level.get("benefit_keys", [])
            if key in VIP_BENEFIT_ITEMS
        )
        benefits[str(level["name"])] = "\n".join(lines)
    return benefits


VIP_LEVEL_BENEFITS: dict[str, str] = build_vip_level_benefits()
