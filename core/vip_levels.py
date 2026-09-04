from __future__ import annotations

from typing import Any

VIP_BENEFIT_ITEMS: dict[str, str] = {
    "vip_room": "・專屬 VIP 身分組，可使用VIP專屬包廂",
    "priority_cs": "・優先客服回覆",
    "discount_98": "・體驗單、趣味單及高難度稱號單外全館98折",
    "rebate_2": "・儲值返利2%",
    "monthly_coupon_200": "・每月一張折現券200T",
    "priority_order": "・優先排單",
    "familiar_worker": "・優先安排熟悉打手",
    "rebate_3": "・儲值返利3%",
    "discount_96": "・體驗單、趣味單及高難度稱號單外全館96折",
    "rebate_4": "・儲值返利4%",
    "monthly_coupon_500": "・每月額外一張折現券500T",
    "free_secret_space": "・每月一次免費「機密航天保底1000w」",
    "rebate_5": "・儲值返利5%",
    "discount_94": "・體驗單、趣味單及高難度稱號單外全館94折",
    "custom_order": "・可根據闆闆要求製作「自訂單」",
}

VIP_LEVELS: list[dict[str, Any]] = [
    {
        "name": "銀級魔丸",
        "threshold": 2000,
        "role_id": 1516575040206929920,
        "benefit_keys": ["vip_room"],
    },
    {
        "name": "金級魔丸",
        "threshold": 6000,
        "role_id": 1516575036973256738,
        "benefit_keys": [
            "vip_room",
            "priority_cs",
            "discount_98",
            "custom_order",
        ],
    },
    {
        "name": "白金魔丸",
        "threshold": 12000,
        "role_id": 1516575034670583929,
        "benefit_keys": [
            "vip_room",
            "priority_cs",
            "discount_98",
            "rebate_2",
            "monthly_coupon_200",
            "priority_order",
            "custom_order",
        ],
    },
    {
        "name": "鑽石魔丸",
        "threshold": 25000,
        "role_id": 1516575030648115200,
        "benefit_keys": [
            "vip_room",
            "priority_cs",
            "monthly_coupon_200",
            "priority_order",
            "familiar_worker",
            "rebate_3",
            "discount_96",
            "custom_order",
        ],
    },
    {
        "name": "白鑽魔丸",
        "threshold": 50000,
        "role_id": 1516575026583961711,
        "benefit_keys": [
            "vip_room",
            "priority_cs",
            "monthly_coupon_200",
            "priority_order",
            "familiar_worker",
            "discount_96",
            "rebate_4",
            "monthly_coupon_500",
            "custom_order",
        ],
    },
    {
        "name": "黑鑽魔丸",
        "threshold": 88888,
        "role_id": 1516575018807726150,
        "benefit_keys": [
            "vip_room",
            "priority_cs",
            "monthly_coupon_200",
            "priority_order",
            "familiar_worker",
            "monthly_coupon_500",
            "free_secret_space",
            "rebate_5",
            "discount_94",
            "custom_order",
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

# 儲值回饋依「本次儲值完成後」的有效 VIP 等級計算。
# 銀級 / 金級尚未有儲值返利，因此為 0%。
VIP_TOPUP_REBATE_PERCENT: dict[str, int] = {
    "普通魔丸": 0,
    "銀級魔丸": 0,
    "金級魔丸": 0,
    "白金魔丸": 2,
    "鑽石魔丸": 3,
    "白鑽魔丸": 4,
    "黑鑽魔丸": 5,
}


def get_topup_rebate_percent(level_name: str | None) -> int:
    return int(VIP_TOPUP_REBATE_PERCENT.get(str(level_name or "普通魔丸"), 0))


def has_active_vip_progress_reset(data: dict) -> bool:
    """判斷會員是否真的處於降級 / 手動調整後的重新累積區間。

    舊版曾在「正常升級」時誤寫 vip_progress_base_total_spent，
    因此不能只看 base_total 是否存在。
    """
    if not isinstance(data, dict):
        return False

    try:
        base_total = int(data.get("vip_progress_base_total_spent"))
    except (TypeError, ValueError):
        return False

    logs = data.get("vip_downgrade_logs")
    if isinstance(logs, list) and bool(logs):
        return True

    if (
        data.get("last_level_manual_fixed_at")
        or data.get("last_level_manual_fixed_by")
        or data.get("last_level_manual_fixed_reason")
    ):
        return True

    # 舊資料若缺少手動調整 metadata，普通魔丸且基準正好等於
    # 當前累積金額，仍視為剛被重置到普通等級，避免誤拉回歷史 VIP。
    try:
        stored_index = int(data.get("vip_level_index"))
    except (TypeError, ValueError):
        stored_index = None

    try:
        total_spent = int(data.get("total_spent", 0) or 0)
    except (TypeError, ValueError):
        total_spent = 0

    return (
        stored_index == 0
        and base_total > 0
        and base_total <= total_spent
    )


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
