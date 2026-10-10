from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import floor
import time
from typing import Any, Literal

from services.game_roles import GAME_ROLE_BY_KEY


RoleKey = Literal[
    "top_protector",
    "female_protector",
    "male_protector",
    "male_companion",
    "female_companion",
]

PricingType = Literal["fixed", "hourly", "game", "unit", "manual"]
RequiredStaffMode = int | Literal["player_count"]
SpecifyFreeBasis = Literal["quantity", "quantity_x_player_count"]


ROLE_LABELS: dict[RoleKey, str] = {
    "top_protector": "魔丸♛頂護",
    "female_protector": "魔丸♝女護",
    "male_protector": "魔丸♜男護",
    "male_companion": "魔丸♞男陪",
    "female_companion": "魔丸♟女陪",
}

ROLE_IDS: dict[RoleKey, str] = {
    "top_protector": "1500234130871550004",
    "female_protector": "1500234170943934544",
    "male_protector": "1500751039060643990",
    "male_companion": "1500751059239440575",
    "female_companion": "1482080315798192210",
}

GAME_ROLE_IDS_BY_KEY: dict[str, str] = {
    key: str(role.role_id)
    for key, role in GAME_ROLE_BY_KEY.items()
}
GAME_ROLE_LABELS_BY_KEY: dict[str, str] = {
    key: str(role.label)
    for key, role in GAME_ROLE_BY_KEY.items()
}
ALL_ROLE_IDS: dict[str, str] = {**ROLE_IDS, **GAME_ROLE_IDS_BY_KEY}
ALL_ROLE_LABELS: dict[str, str] = {**ROLE_LABELS, **GAME_ROLE_LABELS_BY_KEY}

PROTECTOR_ROLES: tuple[RoleKey, ...] = (
    "top_protector",
    "female_protector",
    "male_protector",
)

COMPANION_ROLES: tuple[RoleKey, ...] = (
    "male_companion",
    "female_companion",
)

ALL_RECEIVER_ROLES: tuple[RoleKey, ...] = PROTECTOR_ROLES + COMPANION_ROLES

DELTA_DESKTOP_GAME_ROLE = ("delta_desktop",)
DELTA_MOBILE_GAME_ROLE = ("delta_mobile",)
DELTA_ANY_GAME_ROLE = ("delta_desktop", "delta_mobile")
STEAM_GAME_ROLE = ("steam_game",)
VALORANT_GAME_ROLE = ("valorant_game",)
LOL_GAME_ROLE = ("lol_game",)
APEX_GAME_ROLE = ("apex_game",)


CATEGORY_LABELS: dict[str, str] = {
    # 新下單分類。舊 basic / fun / general 保留供歷史訂單與舊存單回查。
    "delta_desktop_basic": "三角洲 基礎單<端遊>",
    "delta_mobile_basic": "三角洲 基礎單<手遊>",
    "delta_desktop_fun": "三角洲 趣味單<端遊>",
    "farm": "三角洲 代肝代解",
    "basic": "三角洲 基礎單",
    "fun": "三角洲 趣味單",
    "general": "通用單",
    "steam": "STEAM遊戲 陪玩",
    "valorant": "特戰英豪 陪玩",
    "lol": "英雄聯盟 陪玩",
    "apex": "APEX 陪玩",
    "custom": "自訂",
}


@dataclass(frozen=True)
class OrderRule:
    category: str
    key: str
    label: str
    pricing_type: PricingType
    price: int = 0
    unit_label: str = "單"

    allowed_roles: tuple[RoleKey, ...] = ALL_RECEIVER_ROLES
    required_staff_count: RequiredStaffMode = 1

    min_quantity: int = 1
    max_quantity: int | None = 24

    allow_specify: bool = False
    max_specified_count: int | None = None
    specify_fee_default: int = 0
    specify_fee_by_role: dict[str, int] = field(default_factory=dict)
    specify_free_min_units: int | None = None
    specify_free_basis: SpecifyFreeBasis = "quantity"

    player_count_enabled: bool = False
    min_player_count: int = 1
    max_player_count: int | None = None
    price_multiply_player_count: bool = False

    # 後台新增商品可自行決定 Discord 自助下單的第二層分類。
    # 空白代表沿用既有 catalog；舊的後台商品則由 services.orders
    # 相容顯示成「後台新增商品」。
    catalog_group_label: str = ""

    # VIP 與點數必須是兩個獨立商品規則；關閉 VIP 不影響客服手動折扣。
    vip_discount_allowed: bool = True
    point_benefits_allowed: bool = True

    min_protector_count: int = 0
    # Legacy same-order buy/get fields remain for historical/custom-rule snapshots.
    # Current built-in products no longer use them.
    service_bonus_buy: int | None = None
    service_bonus_gift: int = 0
    # Cross-order customer loyalty progress. Zero/None means disabled.
    loyalty_threshold_units: float | None = None
    loyalty_reward_units: float = 0

    staff_adjustments: dict[str, int] = field(default_factory=dict)
    staff_adjustment_labels: dict[str, str] = field(default_factory=dict)

    note: str = ""

    # 遊戲階級與舊服務職位分開保存；只有商品規則明確列出時才可接。
    allowed_game_roles: tuple[str, ...] = ()
    # 必須同時持有其中至少一個遊戲身分組；與 allowed_* 是 AND 關係。
    required_game_roles: tuple[str, ...] = ()
    specify_fee_by_game_role: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class PriceResult:
    base_amount: int
    specify_fee: int
    staff_adjustment_amount: int
    total_amount: int
    service_quantity: int
    required_staff_count: int
    free_specify_fee: bool
    details: tuple[str, ...]


RULE_OVERRIDE_FIELDS = {
    "label",
    "pricing_type",
    "price",
    "unit_label",
    "allowed_roles",
    "required_staff_count",
    "min_quantity",
    "max_quantity",
    "allow_specify",
    "max_specified_count",
    "specify_fee_default",
    "specify_fee_by_role",
    "specify_free_min_units",
    "specify_free_basis",
    "player_count_enabled",
    "min_player_count",
    "max_player_count",
    "price_multiply_player_count",
    "catalog_group_label",
    "vip_discount_allowed",
    "point_benefits_allowed",
    "min_protector_count",
    "service_bonus_buy",
    "service_bonus_gift",
    "loyalty_threshold_units",
    "loyalty_reward_units",
    "staff_adjustments",
    "staff_adjustment_labels",
    "note",
    "allowed_game_roles",
    "required_game_roles",
    "specify_fee_by_game_role",
}

_TUPLE_OVERRIDE_FIELDS = {
    "allowed_roles",
    "allowed_game_roles",
    "required_game_roles",
}
_DICT_OVERRIDE_FIELDS = {
    "specify_fee_by_role",
    "staff_adjustments",
    "staff_adjustment_labels",
    "specify_fee_by_game_role",
}


def rule_to_override_payload(rule: OrderRule) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in RULE_OVERRIDE_FIELDS:
        value = getattr(rule, key)
        if key in _TUPLE_OVERRIDE_FIELDS:
            payload[key] = list(value or ())
        elif key in _DICT_OVERRIDE_FIELDS:
            payload[key] = dict(value or {})
        else:
            payload[key] = value
    return payload


def build_rule_with_override(
    base_rule: OrderRule,
    payload: dict[str, Any] | None,
) -> OrderRule:
    if not payload:
        return base_rule

    changes: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in RULE_OVERRIDE_FIELDS:
            continue
        if key in _TUPLE_OVERRIDE_FIELDS:
            value = tuple(str(item) for item in (value or []) if str(item).strip())
        elif key in _DICT_OVERRIDE_FIELDS:
            if not isinstance(value, dict):
                raise ValueError(f"{key} 必須是物件。")
            value = dict(value)
        elif key == "catalog_group_label":
            value = str(value or "").strip()
        changes[key] = value

    return replace(base_rule, **changes)


def build_custom_rule(
    rule_key: str,
    category: str,
    payload: dict[str, Any],
) -> OrderRule:
    key = str(rule_key or "").strip()
    category_value = str(category or "").strip()

    if not key:
        raise RuntimeError("custom rule key is empty")
    if category_value not in CATEGORY_LABELS:
        raise RuntimeError(
            f"{key}: unknown category {category_value}"
        )
    if not isinstance(payload, dict):
        raise RuntimeError(f"{key}: custom rule payload must be an object")

    label = str(payload.get("label") or "").strip()
    pricing_type = str(payload.get("pricing_type") or "").strip()
    if not label:
        raise RuntimeError(f"{key}: product label is empty")
    if pricing_type not in {"fixed", "hourly", "game", "unit", "manual"}:
        raise RuntimeError(f"{key}: invalid pricing type")

    base = OrderRule(
        category=category_value,
        key=key,
        label=label,
        pricing_type=pricing_type,
        price=int(payload.get("price") or 0),
        unit_label=str(payload.get("unit_label") or "單"),
    )
    rule = build_rule_with_override(base, payload)
    validate_rule_definition(key, rule)
    return rule


def _protectors_fee() -> dict[RoleKey, int]:
    return {
        "top_protector": 100,
        "female_protector": 100,
        "male_protector": 100,
    }


def _all_receiver_fee(amount: int) -> dict[RoleKey, int]:
    return {role: amount for role in ALL_RECEIVER_ROLES}


def _top_fee(amount: int) -> dict[RoleKey, int]:
    return {"top_protector": amount}


def _normalize_quantity(rule: OrderRule, quantity: int | None) -> int:
    value = int(quantity or 1)
    if value < rule.min_quantity:
        raise ValueError(f"{rule.label} 最少需要 {rule.min_quantity}{rule.unit_label}")
    if rule.max_quantity is not None and value > rule.max_quantity:
        raise ValueError(f"{rule.label} 最多只能選 {rule.max_quantity}{rule.unit_label}")
    return value


def _normalize_player_count(rule: OrderRule, player_count: int | None) -> int:
    if not rule.player_count_enabled:
        return 1

    value = int(player_count or 1)
    if value < rule.min_player_count:
        raise ValueError(f"{rule.label} 最少需要 {rule.min_player_count} 位")
    if rule.max_player_count is not None and value > rule.max_player_count:
        raise ValueError(f"{rule.label} 最多只能點 {rule.max_player_count} 位")
    return value


def get_required_staff_count(rule: OrderRule, player_count: int | None = None) -> int:
    if rule.required_staff_count == "player_count":
        return _normalize_player_count(rule, player_count)
    return int(rule.required_staff_count)


def get_service_quantity(rule: OrderRule, quantity: int) -> int:
    if rule.service_bonus_buy and rule.service_bonus_gift:
        return int(quantity) + floor(int(quantity) / int(rule.service_bonus_buy)) * int(rule.service_bonus_gift)
    return int(quantity)


def calculate_price(
    rule: OrderRule,
    *,
    quantity: int | None = None,
    player_count: int | None = None,
    specified_roles: list[str] | tuple[str, ...] | None = None,
    staff_adjustments: list[str] | tuple[str, ...] | None = None,
) -> PriceResult:
    qty = _normalize_quantity(rule, quantity)
    players = _normalize_player_count(rule, player_count)
    required_staff = get_required_staff_count(rule, players)

    if rule.pricing_type == "manual":
        base_amount = 0
    else:
        base_amount = int(rule.price) * qty
        if rule.price_multiply_player_count:
            base_amount *= players

    specified_roles = tuple(specified_roles or ())
    if specified_roles and not rule.allow_specify:
        raise ValueError(f"{rule.label} 不開放指定")

    if rule.max_specified_count is not None and len(specified_roles) > rule.max_specified_count:
        raise ValueError(f"{rule.label} 最多只能指定 {rule.max_specified_count} 位")

    if len(specified_roles) > required_staff:
        raise ValueError("指定人數不能超過需要接單人數")

    allowed_specify_roles = set(rule.allowed_roles) | set(rule.allowed_game_roles)

    for role in specified_roles:
        if role not in allowed_specify_roles:
            raise ValueError(f"{ALL_ROLE_LABELS.get(role, role)} 不能接 {rule.label}")

    free_specify_fee = False
    if specified_roles and rule.specify_free_min_units is not None:
        if rule.specify_free_basis == "quantity_x_player_count":
            free_basis_value = qty * players
        else:
            free_basis_value = qty
        free_specify_fee = free_basis_value >= int(rule.specify_free_min_units)

    specify_fee = 0
    if specified_roles and not free_specify_fee:
        specify_fee_map = {
            **(rule.specify_fee_by_role or {}),
            **(rule.specify_fee_by_game_role or {}),
        }
        for role in specified_roles:
            specify_fee += int(specify_fee_map.get(role, rule.specify_fee_default))

    staff_adjustment_amount = 0
    details: list[str] = []

    for adjustment_key in staff_adjustments or ():
        if adjustment_key not in rule.staff_adjustments:
            raise ValueError(f"{rule.label} 不支援這個加減價選項：{adjustment_key}")
        amount = int(rule.staff_adjustments[adjustment_key])
        staff_adjustment_amount += amount
        label = rule.staff_adjustment_labels.get(adjustment_key, adjustment_key)
        sign = "+" if amount >= 0 else ""
        details.append(f"{label} {sign}{amount}")

    service_quantity = get_service_quantity(rule, qty)

    return PriceResult(
        base_amount=base_amount,
        specify_fee=specify_fee,
        staff_adjustment_amount=staff_adjustment_amount,
        total_amount=base_amount + specify_fee + staff_adjustment_amount,
        service_quantity=service_quantity,
        required_staff_count=required_staff,
        free_specify_fee=free_specify_fee,
        details=tuple(details),
    )


ORDER_RULES: dict[str, OrderRule] = {}


def _add(rule: OrderRule) -> None:
    if rule.key in ORDER_RULES:
        raise RuntimeError(f"duplicated order rule key: {rule.key}")
    ORDER_RULES[rule.key] = rule


# ========= 基礎單 =========

for key, label, price in [
    ("basic_exbar_gamble_zongheng", "絕巴四幻神賭單｜縱橫", 16888),
    ("basic_exbar_gamble_leiguan", "絕巴四幻神賭單｜萬金淚冠", 16888),
    ("basic_exbar_gamble_tianyuan", "絕巴四幻神賭單｜天圓地方", 8888),
    ("basic_exbar_gamble_rangefinder", "絕巴四幻神賭單｜測距儀", 12888),
]:
    _add(OrderRule("delta_desktop_basic", key, label, "fixed", price, allowed_roles=PROTECTOR_ROLES, required_game_roles=DELTA_DESKTOP_GAME_ROLE, required_staff_count=2, min_quantity=1, max_quantity=1, allow_specify=False))

_add(OrderRule(
    "delta_desktop_basic", "basic_exbar_tech", "絕巴技術陪", "hourly", 1000, "H",
    allowed_roles=PROTECTOR_ROLES,
    required_game_roles=DELTA_DESKTOP_GAME_ROLE,
    required_staff_count=2,
    allow_specify=True,
    max_specified_count=2,
    specify_fee_by_role=_protectors_fee(),
    specify_free_min_units=2,
    specify_free_basis="quantity",
    loyalty_threshold_units=10,
    loyalty_reward_units=0.5,
    note="保底三選一：800w / 500w + 2 沙色保險 / 4 沙色保險",
))

for key, label, price, staff_count in [
    ("basic_tech_secret_single", "技術陪〈端遊〉｜機密單陪", 400, 1),
    ("basic_tech_secret_double", "技術陪〈端遊〉｜機密雙陪", 750, 2),
    ("basic_tech_topsecret_single", "技術陪〈端遊〉｜絕密單陪", 450, 1),
    ("basic_tech_topsecret_double", "技術陪〈端遊〉｜絕密雙陪", 850, 2),
]:
    _add(OrderRule(
        "delta_desktop_basic", key, label, "hourly", price, "H",
        allowed_roles=PROTECTOR_ROLES,
        required_game_roles=DELTA_DESKTOP_GAME_ROLE,
        required_staff_count=staff_count,
        allow_specify=True,
        max_specified_count=staff_count,
        specify_fee_by_role=_protectors_fee(),
        specify_free_min_units=2,
        specify_free_basis="quantity",
    ))

# 三角洲手遊技術陪：與端遊使用獨立 rule key，避免歷史訂單與平台價格互相影響。
for key, label, price, staff_count in [
    ("basic_mobile_tech_secret_single", "技術陪〈手遊〉｜機密單陪", 380, 1),
    ("basic_mobile_tech_secret_double", "技術陪〈手遊〉｜機密雙陪", 760, 2),
    ("basic_mobile_tech_topsecret_single", "技術陪〈手遊〉｜絕密單陪", 420, 1),
    ("basic_mobile_tech_topsecret_double", "技術陪〈手遊〉｜絕密雙陪", 840, 2),
]:
    _add(OrderRule(
        "delta_mobile_basic", key, label, "hourly", price, "H",
        allowed_roles=PROTECTOR_ROLES,
        required_game_roles=DELTA_MOBILE_GAME_ROLE,
        required_staff_count=staff_count,
        allow_specify=True,
        max_specified_count=staff_count,
        specify_fee_by_role=_protectors_fee(),
        specify_free_min_units=2,
        specify_free_basis="quantity",
    ))


_add(OrderRule(
    "general",
    "basic_teaching_one",
    "教學單｜1對1",
    "hourly",
    500,
    "H",
    allowed_roles=("top_protector",),
    allowed_game_roles=(
        "lol_elite",
        "apex_predator",
        "valorant_radiant",
    ),
    required_game_roles=(),
    required_staff_count=1,
    min_quantity=3,
    allow_specify=False,
))

# 舊雙導師規則不再加入 ORDER_RULES；
# 已建立訂單仍使用建立當下保存的規則快照，不受影響。

for category, key, label, price, staff_count, required_game_roles in [
    ("delta_desktop_basic", "basic_entertain_single", "娛樂陪〈端遊〉｜單陪", 320, 1, DELTA_DESKTOP_GAME_ROLE),
    ("delta_desktop_basic", "basic_entertain_double", "娛樂陪〈端遊〉｜雙陪", 600, 2, DELTA_DESKTOP_GAME_ROLE),
    ("delta_mobile_basic", "basic_mobile_entertain_single", "娛樂陪〈手遊〉｜單陪", 320, 1, DELTA_MOBILE_GAME_ROLE),
    ("delta_mobile_basic", "basic_mobile_entertain_double", "娛樂陪〈手遊〉｜雙陪", 600, 2, DELTA_MOBILE_GAME_ROLE),
]:
    _add(OrderRule(
        category, key, label, "hourly", price, "H",
        allowed_roles=COMPANION_ROLES,
        required_game_roles=required_game_roles,
        required_staff_count=staff_count,
        allow_specify=True,
        max_specified_count=staff_count,
        specify_fee_by_role={
            role: 100
            for role in COMPANION_ROLES
        },
        specify_free_min_units=2,
        specify_free_basis="quantity",
        loyalty_threshold_units=10,
        loyalty_reward_units=0.5,
    ))

# 舊甜蜜單規則保留給既有訂單／舊快照回查，不再出現在新下單選項。
_add(OrderRule(
    "general", "basic_sweet_single", "甜蜜單｜單陪", "hourly", 520, "H",
    allowed_roles=COMPANION_ROLES,
    allowed_game_roles=(),
    required_game_roles=(),
    required_staff_count=1,
    allow_specify=True,
    max_specified_count=1,
    specify_fee_default=100,
    specify_fee_by_role={
        role: 100
        for role in COMPANION_ROLES
    },
    specify_free_min_units=2,
    specify_free_basis="quantity",
))

_add(OrderRule(
    "general", "basic_sweet_double", "甜蜜單｜雙陪", "hourly", 1314, "H",
    allowed_roles=COMPANION_ROLES,
    allowed_game_roles=(),
    required_game_roles=(),
    required_staff_count=2,
    allow_specify=True,
    max_specified_count=2,
    specify_fee_default=100,
    specify_fee_by_role={
        role: 100
        for role in COMPANION_ROLES
    },
    specify_free_min_units=2,
    specify_free_basis="quantity",
))


def _add_sweet_rule(
    key: str,
    label: str,
    *,
    price: int,
    required_staff_count: int,
    allowed_roles: tuple[RoleKey, ...],
    category: str = "general",
    required_game_roles: tuple[str, ...] = (),
) -> None:
    _add(OrderRule(
        category,
        key,
        label,
        "hourly",
        price,
        "H",
        allowed_roles=allowed_roles,
        allowed_game_roles=(),
        required_game_roles=required_game_roles,
        required_staff_count=required_staff_count,
        allow_specify=True,
        max_specified_count=required_staff_count,
        specify_fee_default=100,
        specify_fee_by_role={
            role: 100
            for role in allowed_roles
        },
        specify_free_min_units=2,
        specify_free_basis="quantity",
    ))


_add_sweet_rule(
    "basic_sweet_female_single",
    "甜蜜單｜女單陪",
    price=520,
    required_staff_count=1,
    allowed_roles=("female_companion",),
)
_add_sweet_rule(
    "basic_sweet_male_single",
    "甜蜜單｜男單陪",
    price=520,
    required_staff_count=1,
    allowed_roles=("male_companion",),
)
_add_sweet_rule(
    "basic_sweet_female_double",
    "甜蜜單｜女雙陪",
    price=1314,
    required_staff_count=2,
    allowed_roles=("female_companion",),
)
_add_sweet_rule(
    "basic_sweet_male_double",
    "甜蜜單｜男雙陪",
    price=1314,
    required_staff_count=2,
    allowed_roles=("male_companion",),
)
_add_sweet_rule(
    "basic_sweet_double_any",
    "甜蜜單｜雙陪(不限)",
    price=1314,
    required_staff_count=2,
    allowed_roles=COMPANION_ROLES,
)


# 新訂單把甜蜜單 / 教學單拆到各遊戲；舊 general 規則只留給歷史資料。
_GAME_SHARED_SERVICE_SPECS = (
    ("delta_desktop", "delta_desktop_basic", "三角洲端遊", DELTA_DESKTOP_GAME_ROLE),
    ("delta_mobile", "delta_mobile_basic", "三角洲手遊", DELTA_MOBILE_GAME_ROLE),
    ("steam", "steam", "Steam", STEAM_GAME_ROLE),
    ("valorant", "valorant", "特戰英豪", VALORANT_GAME_ROLE),
    ("lol", "lol", "英雄聯盟", LOL_GAME_ROLE),
    ("apex", "apex", "APEX", APEX_GAME_ROLE),
)

for _prefix, _category, _game_label, _required_game_roles in _GAME_SHARED_SERVICE_SPECS:
    _add_sweet_rule(
        f"{_prefix}_sweet_female_single",
        f"{_game_label}｜甜蜜單｜女單陪",
        category=_category,
        price=520,
        required_staff_count=1,
        allowed_roles=("female_companion",),
        required_game_roles=_required_game_roles,
    )
    _add_sweet_rule(
        f"{_prefix}_sweet_male_single",
        f"{_game_label}｜甜蜜單｜男單陪",
        category=_category,
        price=520,
        required_staff_count=1,
        allowed_roles=("male_companion",),
        required_game_roles=_required_game_roles,
    )
    _add_sweet_rule(
        f"{_prefix}_sweet_female_double",
        f"{_game_label}｜甜蜜單｜女雙陪",
        category=_category,
        price=1314,
        required_staff_count=2,
        allowed_roles=("female_companion",),
        required_game_roles=_required_game_roles,
    )
    _add_sweet_rule(
        f"{_prefix}_sweet_male_double",
        f"{_game_label}｜甜蜜單｜男雙陪",
        category=_category,
        price=1314,
        required_staff_count=2,
        allowed_roles=("male_companion",),
        required_game_roles=_required_game_roles,
    )
    _add_sweet_rule(
        f"{_prefix}_sweet_double_any",
        f"{_game_label}｜甜蜜單｜雙陪(不限)",
        category=_category,
        price=1314,
        required_staff_count=2,
        allowed_roles=COMPANION_ROLES,
        required_game_roles=_required_game_roles,
    )


_GAME_TEACHING_SPECS = (
    ("delta_desktop", "delta_desktop_basic", "三角洲端遊", ("top_protector",), (), DELTA_DESKTOP_GAME_ROLE),
    ("delta_mobile", "delta_mobile_basic", "三角洲手遊", ("top_protector",), (), DELTA_MOBILE_GAME_ROLE),
    ("valorant", "valorant", "特戰英豪", (), ("valorant_radiant",), VALORANT_GAME_ROLE),
    ("lol", "lol", "英雄聯盟", (), ("lol_elite",), LOL_GAME_ROLE),
    ("apex", "apex", "APEX", (), ("apex_predator",), APEX_GAME_ROLE),
)

for (
    _prefix,
    _category,
    _game_label,
    _allowed_roles,
    _allowed_game_roles,
    _required_game_roles,
) in _GAME_TEACHING_SPECS:
    _add(OrderRule(
        _category,
        f"{_prefix}_teaching_one",
        f"{_game_label}｜教學單｜1對1",
        "hourly",
        500,
        "H",
        allowed_roles=_allowed_roles,
        allowed_game_roles=_allowed_game_roles,
        required_game_roles=_required_game_roles,
        required_staff_count=1,
        min_quantity=3,
        allow_specify=False,
    ))

for key, label, price in [
    ("basic_oil_fuel", "油鍋單｜火箭燃油", 2600),
    ("basic_oil_satellite", "油鍋單｜GTI衛星通訊天線", 1800),
    ("basic_oil_all", "油鍋單｜全包", 4000),
    ("basic_bet_1000", "賭約單｜800w", 800),
    ("basic_bet_1500", "賭約單｜1000w", 1200),
    ("basic_bet_2500", "賭約單｜1200w", 1500),
    ("basic_trial_500", "體驗單｜777w", 450),
    ("basic_trial_1000", "體驗單｜1688w", 900),
]:
    _add(OrderRule("delta_desktop_basic", key, label, "fixed", price, allowed_roles=PROTECTOR_ROLES, required_game_roles=DELTA_DESKTOP_GAME_ROLE, required_staff_count=2, min_quantity=1, max_quantity=1, allow_specify=False))


# ========= 趣味單 =========

_add(OrderRule("delta_desktop_fun", "fun_lovebirds", "比翼雙飛", "fixed", 2000, allowed_roles=ALL_RECEIVER_ROLES, required_game_roles=DELTA_DESKTOP_GAME_ROLE, required_staff_count=2, min_protector_count=1, min_quantity=1, max_quantity=1, allow_specify=False))
_add(OrderRule("delta_desktop_fun", "fun_read_no_reply", "已讀亂回", "fixed", 2000, allowed_roles=ALL_RECEIVER_ROLES, required_game_roles=DELTA_DESKTOP_GAME_ROLE, required_staff_count=2, min_protector_count=1, min_quantity=1, max_quantity=1, allow_specify=False))
_add(OrderRule("delta_desktop_fun", "fun_rich_enough", "豪到你了嗎", "fixed", 2000, allowed_roles=PROTECTOR_ROLES, required_game_roles=DELTA_DESKTOP_GAME_ROLE, required_staff_count=2, min_quantity=1, max_quantity=1, allow_specify=False))
_add(OrderRule("delta_desktop_fun", "fun_eat_yourself", "想吃自己打", "fixed", 3000, allowed_roles=PROTECTOR_ROLES, required_game_roles=DELTA_DESKTOP_GAME_ROLE, required_staff_count=2, min_quantity=1, max_quantity=1, allow_specify=False))

# 魔丸娛樂嘎拉給木
# 固定 1 單 / 2 位 / 只允許女陪或女護
# 可指定女陪 / 女護，指定費 0T；不使用點數福利，客服人工折扣仍走通用折扣功能。
for key, label, price in [
    ("fun_mawan_galagame_basic", "魔丸娛樂嘎拉給木｜基礎", 1688),
    ("fun_mawan_galagame_standard", "魔丸娛樂嘎拉給木｜標準", 2688),
    ("fun_mawan_galagame_hard", "魔丸娛樂嘎拉給木｜困難", 4688),
    ("fun_mawan_galagame_hell", "魔丸娛樂嘎拉給木｜地獄", 6688),
]:
    _add(OrderRule(
        "delta_desktop_fun",
        key,
        label,
        "fixed",
        price,
        "單",
        allowed_roles=(
            "female_companion",
            "female_protector",
        ),
        required_game_roles=DELTA_DESKTOP_GAME_ROLE,
        required_staff_count=2,
        min_quantity=1,
        max_quantity=1,
        allow_specify=True,
        max_specified_count=2,
        specify_fee_default=0,
        specify_fee_by_role={
            "female_companion": 0,
            "female_protector": 0,
        },
        point_benefits_allowed=False,
    ))


# ========= 代解代肝 =========

_add(OrderRule(
    "farm",
    "farm_season_3x3_normal",
    "賽季3x3",
    "fixed",
    4000,
    allowed_roles=ALL_RECEIVER_ROLES,
    required_game_roles=DELTA_ANY_GAME_ROLE,
    required_staff_count=1,
    min_quantity=1,
    max_quantity=1,
    allow_specify=False,
    staff_adjustments={
        "skin": 2500,
        "loss_cover": 500,
    },
    staff_adjustment_labels={
        "skin": "造型",
        "loss_cover": "包損耗",
    },
))

_add(OrderRule("farm", "farm_season_3x3_skin", "賽季3x3｜造型", "fixed", 3000, allowed_roles=ALL_RECEIVER_ROLES, required_game_roles=DELTA_ANY_GAME_ROLE, required_staff_count=1, allow_specify=False))
_add(OrderRule(
    "farm",
    "farm_season_3x3_dc_skin",
    "賽季3x3+造型",
    "fixed",
    6500,
    allowed_roles=ALL_RECEIVER_ROLES,
    required_game_roles=DELTA_ANY_GAME_ROLE,
    required_staff_count=1,
    min_quantity=1,
    max_quantity=1,
    allow_specify=False,
))

_add(OrderRule(
    "farm",
    "farm_season_3x3_dc_loss",
    "賽季3x3包損耗",
    "fixed",
    4500,
    allowed_roles=ALL_RECEIVER_ROLES,
    required_game_roles=DELTA_ANY_GAME_ROLE,
    required_staff_count=1,
    min_quantity=1,
    max_quantity=1,
    allow_specify=False,
))

_add(OrderRule(
    "farm",
    "farm_season_3x3_dc_skin_loss",
    "賽季3x3+造型包損耗",
    "fixed",
    7000,
    allowed_roles=ALL_RECEIVER_ROLES,
    required_game_roles=DELTA_ANY_GAME_ROLE,
    required_staff_count=1,
    min_quantity=1,
    max_quantity=1,
    allow_specify=False,
))

_add(OrderRule(
    "farm",
    "farm_season_3x3_contract",
    "命運契約",
    "unit",
    600,
    "個",
    allowed_roles=PROTECTOR_ROLES,
    required_game_roles=DELTA_ANY_GAME_ROLE,
    required_staff_count=1,
    min_quantity=1,
    max_quantity=7,
    allow_specify=False,
))

_add(OrderRule("farm", "farm_department_task", "部門任務", "manual", 0, allowed_roles=ALL_RECEIVER_ROLES, required_game_roles=DELTA_ANY_GAME_ROLE, required_staff_count=1, min_quantity=1, max_quantity=1, allow_specify=False, note="客服填價格"))

for key, label, price in [
    ("farm_halfcoin_120m", "哈夫幣代洗｜120M", 1250),
    ("farm_halfcoin_360m", "哈夫幣代洗｜360M", 3400),
]:
    _add(OrderRule("farm", key, label, "fixed", price, allowed_roles=ALL_RECEIVER_ROLES, required_game_roles=DELTA_ANY_GAME_ROLE, required_staff_count=1, min_quantity=1, max_quantity=1, allow_specify=False))





# ========= Steam 陪玩 =========

_add(OrderRule(
    "steam", "steam_play", "Steam遊戲｜娛樂陪", "hourly", 320, "H",
    allowed_roles=COMPANION_ROLES,
    allowed_game_roles=(),
    required_game_roles=STEAM_GAME_ROLE,
    required_staff_count="player_count",
    player_count_enabled=True,
    max_player_count=4,
    price_multiply_player_count=True,
    allow_specify=True,
    max_specified_count=4,
    specify_fee_default=100,
    specify_fee_by_role={
        role: 100
        for role in COMPANION_ROLES
    },
    specify_free_min_units=2,
    specify_free_basis="quantity",
    point_benefits_allowed=False,
))


# ========= 特戰英豪舊制 =========
# 舊 valorant_entertain / valorant_tech / valorant_top_tech 已從 active rules 移除。
# 歷史訂單使用建立當下的 rule_snapshot_json / price_snapshot_json 回查。

# ========= 特戰英豪 / 英雄聯盟新制陪玩 =========
# 遊戲階級與舊男陪 / 女陪 / 護航完全分開，只在商品規則中明確列出可接資格。
VALORANT_GAME_ROLES = ("valorant_ascendant", "valorant_immortal", "valorant_radiant")
LOL_GAME_ROLES = ("lol_master", "lol_grandmaster", "lol_elite")


def _add_game_service_rule(
    *,
    category: str,
    key: str,
    label: str,
    pricing_type: PricingType,
    price: int,
    unit_label: str,
    allowed_service_roles: tuple[RoleKey, ...] = (),
    allowed_game_roles: tuple[str, ...] = (),
    required_game_roles: tuple[str, ...] = (),
) -> None:
    _add(OrderRule(
        category, key, label, pricing_type, price, unit_label,
        allowed_roles=allowed_service_roles,
        allowed_game_roles=allowed_game_roles,
        required_game_roles=required_game_roles,
        required_staff_count="player_count",
        player_count_enabled=True,
        min_player_count=1,
        max_player_count=4,
        price_multiply_player_count=True,
        allow_specify=True,
        max_specified_count=4,
        specify_fee_default=100,
        specify_fee_by_role={
            role: 100
            for role in allowed_service_roles
        },
        specify_fee_by_game_role={
            role: 100
            for role in allowed_game_roles
        },
        specify_free_min_units=2,
        specify_free_basis="quantity",
        point_benefits_allowed=True,
        loyalty_threshold_units=(10 if pricing_type == "hourly" else 20),
        loyalty_reward_units=(0.5 if pricing_type == "hourly" else 1),
    ))


_add_game_service_rule(category="valorant", key="valorant_entertain_ng", label="特戰英豪｜娛樂陪｜NG", pricing_type="hourly", price=300, unit_label="H", allowed_service_roles=COMPANION_ROLES, required_game_roles=VALORANT_GAME_ROLE)
_add_game_service_rule(category="valorant", key="valorant_entertain_ranked", label="特戰英豪｜娛樂陪｜積分", pricing_type="game", price=250, unit_label="局", allowed_service_roles=COMPANION_ROLES, required_game_roles=VALORANT_GAME_ROLE)
_add_game_service_rule(category="valorant", key="valorant_ascendant_ng", label="特戰英豪｜超凡陪｜NG", pricing_type="hourly", price=340, unit_label="H", allowed_game_roles=("valorant_ascendant", "valorant_immortal", "valorant_radiant"), required_game_roles=VALORANT_GAME_ROLE)
_add_game_service_rule(category="valorant", key="valorant_ascendant_ranked", label="特戰英豪｜超凡陪｜積分", pricing_type="game", price=300, unit_label="局", allowed_game_roles=("valorant_ascendant", "valorant_immortal", "valorant_radiant"), required_game_roles=VALORANT_GAME_ROLE)
_add_game_service_rule(category="valorant", key="valorant_immortal_ng", label="特戰英豪｜神話陪｜NG", pricing_type="hourly", price=360, unit_label="H", allowed_game_roles=("valorant_immortal", "valorant_radiant"), required_game_roles=VALORANT_GAME_ROLE)
_add_game_service_rule(category="valorant", key="valorant_immortal_ranked", label="特戰英豪｜神話陪｜積分", pricing_type="game", price=350, unit_label="局", allowed_game_roles=("valorant_immortal", "valorant_radiant"), required_game_roles=VALORANT_GAME_ROLE)
_add_game_service_rule(category="valorant", key="valorant_radiant_ng", label="特戰英豪｜輻能陪｜NG", pricing_type="hourly", price=400, unit_label="H", allowed_game_roles=("valorant_radiant",), required_game_roles=VALORANT_GAME_ROLE)
_add_game_service_rule(category="valorant", key="valorant_radiant_ranked", label="特戰英豪｜輻能陪｜積分", pricing_type="game", price=400, unit_label="局", allowed_game_roles=("valorant_radiant",), required_game_roles=VALORANT_GAME_ROLE)

_add_game_service_rule(category="lol", key="lol_entertain_aram", label="英雄聯盟｜娛樂陪｜ARAM", pricing_type="hourly", price=300, unit_label="H", allowed_service_roles=COMPANION_ROLES, required_game_roles=LOL_GAME_ROLE)
_add_game_service_rule(category="lol", key="lol_entertain_ng", label="英雄聯盟｜娛樂陪｜NG", pricing_type="hourly", price=300, unit_label="H", allowed_service_roles=COMPANION_ROLES, required_game_roles=LOL_GAME_ROLE)
_add_game_service_rule(category="lol", key="lol_entertain_ranked", label="英雄聯盟｜娛樂陪｜積分", pricing_type="game", price=250, unit_label="局", allowed_service_roles=COMPANION_ROLES, required_game_roles=LOL_GAME_ROLE)
_add_game_service_rule(category="lol", key="lol_master_ng", label="英雄聯盟｜大師陪｜NG", pricing_type="hourly", price=340, unit_label="H", allowed_game_roles=("lol_master", "lol_grandmaster", "lol_elite"), required_game_roles=LOL_GAME_ROLE)
_add_game_service_rule(category="lol", key="lol_master_ranked", label="英雄聯盟｜大師陪｜積分", pricing_type="game", price=300, unit_label="局", allowed_game_roles=("lol_master", "lol_grandmaster", "lol_elite"), required_game_roles=LOL_GAME_ROLE)
_add_game_service_rule(category="lol", key="lol_grandmaster_ng", label="英雄聯盟｜宗師陪｜NG", pricing_type="hourly", price=360, unit_label="H", allowed_game_roles=("lol_grandmaster", "lol_elite"), required_game_roles=LOL_GAME_ROLE)
_add_game_service_rule(category="lol", key="lol_grandmaster_ranked", label="英雄聯盟｜宗師陪｜積分", pricing_type="game", price=350, unit_label="局", allowed_game_roles=("lol_grandmaster", "lol_elite"), required_game_roles=LOL_GAME_ROLE)
_add_game_service_rule(category="lol", key="lol_elite_ng", label="英雄聯盟｜菁英陪｜NG", pricing_type="hourly", price=400, unit_label="H", allowed_game_roles=("lol_elite",), required_game_roles=LOL_GAME_ROLE)
_add_game_service_rule(category="lol", key="lol_elite_ranked", label="英雄聯盟｜菁英陪｜積分", pricing_type="game", price=400, unit_label="局", allowed_game_roles=("lol_elite",), required_game_roles=LOL_GAME_ROLE)


# ========= APEX Legends 陪玩 =========
# 價格依「陪玩階級 × 老闆目前段位」決定，積分場每人每小時 +50T。
# 網站以前台勾選積分場呈現；Discord 則直接使用獨立的積分 rule。
APEX_GAME_ROLES = ("apex_diamond", "apex_master", "apex_predator")


def _add_apex_service_rule(
    *,
    key: str,
    label: str,
    price: int,
    allowed_service_roles: tuple[RoleKey, ...] = (),
    allowed_game_roles: tuple[str, ...] = (),
) -> None:
    _add(OrderRule(
        "apex",
        key,
        label,
        "hourly",
        price,
        "H",
        allowed_roles=allowed_service_roles,
        allowed_game_roles=allowed_game_roles,
        required_game_roles=APEX_GAME_ROLE,
        required_staff_count="player_count",
        min_quantity=1,
        max_quantity=24,
        player_count_enabled=True,
        min_player_count=1,
        max_player_count=2,
        price_multiply_player_count=True,
        allow_specify=True,
        max_specified_count=2,
        specify_fee_default=100,
        specify_fee_by_role={
            role: 100
            for role in allowed_service_roles
        },
        specify_fee_by_game_role={
            role: 100
            for role in allowed_game_roles
        },
        specify_free_min_units=2,
        specify_free_basis="quantity",
        point_benefits_allowed=True,
        loyalty_threshold_units=10,
        loyalty_reward_units=0.5,
    ))


_APEX_SERVICE_SPECS = (
    # key prefix, display label, allowed service roles, allowed game roles,
    # customer-rank prices: (suffix, label, hourly price)
    (
        "apex_entertain",
        "娛樂陪",
        COMPANION_ROLES,
        (),
        (
            ("platinum", "白金以下", 300),
            ("diamond", "鑽石", 330),
            ("master", "大師/頂獵", 350),
        ),
    ),
    (
        "apex_diamond",
        "鑽石陪",
        (),
        ("apex_diamond", "apex_master", "apex_predator"),
        (
            ("platinum", "白金以下", 360),
            ("diamond", "鑽石", 400),
        ),
    ),
    (
        "apex_master",
        "大師陪",
        (),
        ("apex_master", "apex_predator"),
        (
            ("platinum", "白金以下", 420),
            ("diamond", "鑽石", 460),
            ("master", "大師/頂獵", 500),
        ),
    ),
    (
        "apex_predator",
        "頂獵陪",
        (),
        ("apex_predator",),
        (
            ("platinum", "白金以下", 500),
            ("diamond", "鑽石", 550),
            ("master", "大師/頂獵", 600),
        ),
    ),
)

for (
    _apex_prefix,
    _apex_service_label,
    _apex_service_roles,
    _apex_game_roles,
    _apex_rank_prices,
) in _APEX_SERVICE_SPECS:
    for _rank_suffix, _rank_label, _hourly_price in _apex_rank_prices:
        _add_apex_service_rule(
            key=f"{_apex_prefix}_{_rank_suffix}",
            label=f"APEX｜{_apex_service_label}｜{_rank_label}",
            price=_hourly_price,
            allowed_service_roles=_apex_service_roles,
            allowed_game_roles=_apex_game_roles,
        )
        _add_apex_service_rule(
            key=f"{_apex_prefix}_{_rank_suffix}_ranked",
            label=f"APEX｜{_apex_service_label}｜{_rank_label}｜積分",
            price=_hourly_price + 50,
            allowed_service_roles=_apex_service_roles,
            allowed_game_roles=_apex_game_roles,
        )


# ========= 自訂單 =========
_add(OrderRule(
    "custom",
    "custom_custom_order",
    "自訂｜自訂",
    "manual",
    0,
    "H",
    allowed_roles=ALL_RECEIVER_ROLES,
    required_staff_count="player_count",
    min_quantity=1,
    max_quantity=24,
    allow_specify=True,
    max_specified_count=4,
    specify_fee_default=100,
    specify_fee_by_role=_all_receiver_fee(100),
    specify_free_min_units=2,
    specify_free_basis="quantity",
    player_count_enabled=True,
    min_player_count=1,
    max_player_count=4,
    price_multiply_player_count=False,
    point_benefits_allowed=False,
))


def get_rules_by_category(category: str) -> list[OrderRule]:
    return [rule for rule in ORDER_RULES.values() if rule.category == category]


def get_rule(rule_key: str) -> OrderRule:
    try:
        return ORDER_RULES[rule_key]
    except KeyError as exc:
        raise KeyError(f"unknown order rule: {rule_key}") from exc


def get_allowed_role_keys(rule: OrderRule) -> tuple[str, ...]:
    return tuple(rule.allowed_roles) + tuple(rule.allowed_game_roles)


def _unique_role_keys_by_id(role_keys) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[tuple[str, str]] = set()

    for role_key in role_keys:
        role_id = ALL_ROLE_IDS.get(role_key)
        identity = (
            ("id", str(role_id))
            if role_id is not None
            else ("key", str(role_key))
        )

        if identity in seen:
            continue

        seen.add(identity)
        result.append(str(role_key))

    return tuple(result)


def get_allowed_role_ids(rule: OrderRule) -> list[str]:
    return [
        str(ALL_ROLE_IDS[key])
        for key in _unique_role_keys_by_id(get_allowed_role_keys(rule))
        if key in ALL_ROLE_IDS
    ]


def get_required_game_role_keys(rule: OrderRule) -> tuple[str, ...]:
    return _unique_role_keys_by_id(tuple(rule.required_game_roles))


def get_required_game_role_ids(rule: OrderRule) -> list[str]:
    return [
        str(ALL_ROLE_IDS[key])
        for key in get_required_game_role_keys(rule)
        if key in ALL_ROLE_IDS
    ]


def role_ids_match_requirements(
    member_role_ids,
    allowed_role_ids,
    required_game_role_ids=(),
) -> bool:
    member_roles = {
        str(role_id).strip()
        for role_id in (member_role_ids or [])
        if str(role_id).strip()
    }
    allowed = {
        str(role_id).strip()
        for role_id in (allowed_role_ids or [])
        if str(role_id).strip()
    }
    required_games = {
        str(role_id).strip()
        for role_id in (required_game_role_ids or [])
        if str(role_id).strip()
    }

    if allowed and not (member_roles & allowed):
        return False

    if required_games and not (member_roles & required_games):
        return False

    return True


def get_allowed_role_labels(rule: OrderRule) -> list[str]:
    return [
        str(ALL_ROLE_LABELS.get(key, key))
        for key in _unique_role_keys_by_id(get_allowed_role_keys(rule))
    ]


def role_labels(roles: tuple[str, ...], game_roles: tuple[str, ...] = ()) -> str:
    role_keys = _unique_role_keys_by_id(tuple(roles) + tuple(game_roles))
    return " / ".join(str(ALL_ROLE_LABELS.get(role, role)) for role in role_keys)


def rule_role_labels(rule: OrderRule) -> str:
    qualification = role_labels(rule.allowed_roles, rule.allowed_game_roles)
    required_games = " / ".join(
        str(ALL_ROLE_LABELS.get(key, key))
        for key in get_required_game_role_keys(rule)
    )
    if qualification and required_games:
        return f"{qualification} + {required_games}"
    return qualification or required_games


def validate_rule_definition(key: str, rule: OrderRule) -> None:
    if rule.category not in CATEGORY_LABELS:
        raise RuntimeError(f"{key}: unknown category {rule.category}")

    if rule.pricing_type not in {"fixed", "hourly", "game", "unit", "manual"}:
        raise RuntimeError(f"{key}: invalid pricing type")

    if rule.pricing_type != "manual" and int(rule.price) < 0:
        raise RuntimeError(f"{key}: invalid price")

    if rule.required_staff_count != "player_count" and int(rule.required_staff_count) <= 0:
        raise RuntimeError(f"{key}: invalid required staff count")

    if int(rule.min_quantity) <= 0:
        raise RuntimeError(f"{key}: invalid minimum quantity")
    if rule.max_quantity is not None and int(rule.max_quantity) < int(rule.min_quantity):
        raise RuntimeError(f"{key}: maximum quantity is below minimum quantity")

    if rule.player_count_enabled:
        if int(rule.min_player_count) <= 0:
            raise RuntimeError(f"{key}: invalid minimum player count")
        if (
            rule.max_player_count is not None
            and int(rule.max_player_count) < int(rule.min_player_count)
        ):
            raise RuntimeError(f"{key}: maximum player count is below minimum")

    if len(str(rule.catalog_group_label or "")) > 100:
        raise RuntimeError(f"{key}: catalog group label is too long")

    if rule.allow_specify:
        fee_map = {
            **(rule.specify_fee_by_role or {}),
            **(rule.specify_fee_by_game_role or {}),
        }
        specify_roles = tuple(rule.allowed_roles) + tuple(rule.allowed_game_roles)
        missing_fee_roles = [
            role_key
            for role_key in specify_roles
            if (
                role_key not in fee_map
                and int(rule.specify_fee_default or 0) <= 0
            )
        ]
        if missing_fee_roles:
            raise RuntimeError(
                f"{key}: specify fee missing for roles {missing_fee_roles}"
            )

    if not rule.allowed_roles and not rule.allowed_game_roles:
        raise RuntimeError(f"{key}: no allowed roles")

    unknown_roles = [
        role_key
        for role_key in tuple(rule.allowed_roles) + tuple(rule.allowed_game_roles)
        if role_key not in ALL_ROLE_IDS
    ]
    if unknown_roles:
        raise RuntimeError(f"{key}: unknown allowed roles {unknown_roles}")

    unknown_required_games = [
        role_key
        for role_key in rule.required_game_roles
        if role_key not in ALL_ROLE_IDS
    ]
    if unknown_required_games:
        raise RuntimeError(
            f"{key}: unknown required game roles {unknown_required_games}"
        )

    if (
        rule.min_protector_count > 0
        and rule.min_protector_count
        > get_required_staff_count(rule, rule.max_player_count or 1)
    ):
        raise RuntimeError(f"{key}: min protector count exceeds required staff count")


def validate_rules() -> None:
    for key, rule in dict.items(ORDER_RULES):
        validate_rule_definition(str(key), rule)


validate_rules()

_BASE_ORDER_RULES = dict(ORDER_RULES)


class EffectiveOrderRules(dict):
    """Read-through mapping for code rules + manager-created rules + overrides.

    Code rules remain immutable fallbacks. Custom rules are stored in the same
    SQLite database used by the Web and Bot, so newly created products become
    visible to both processes without another Git deployment.
    """

    def __init__(self, base_rules: dict[str, OrderRule]):
        super().__init__(base_rules)
        self._override_cache: dict[str, dict[str, Any]] = {}
        self._custom_cache: dict[str, OrderRule] = {}
        self._external_cache_at = 0.0

    def invalidate(self) -> None:
        self._external_cache_at = 0.0
        self._override_cache = {}
        self._custom_cache = {}

    def _refresh_external(self) -> None:
        now = time.monotonic()
        if now - self._external_cache_at < 2.0:
            return

        overrides: dict[str, dict[str, Any]] = {}
        custom_rules: dict[str, OrderRule] = {}

        try:
            from services.order_rule_store import (
                load_active_overrides,
                load_custom_rule_definitions,
            )

            overrides = load_active_overrides()
            definitions = load_custom_rule_definitions()

            for key, item in definitions.items():
                # A database-created rule may never shadow a code rule.
                if dict.__contains__(self, str(key)):
                    continue
                try:
                    custom_rules[str(key)] = build_custom_rule(
                        str(key),
                        str(item.get("category") or ""),
                        item.get("payload") or {},
                    )
                except Exception:
                    # Corrupt custom rows are ignored instead of taking down
                    # checkout or the Discord Bot.
                    continue
        except Exception:
            overrides = {}
            custom_rules = {}

        self._override_cache = overrides
        self._custom_cache = custom_rules
        self._external_cache_at = now

    def _base(self, key: str) -> OrderRule:
        key = str(key)
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)

        self._refresh_external()
        if key in self._custom_cache:
            return self._custom_cache[key]

        raise KeyError(key)

    def _effective(self, key: str) -> OrderRule:
        key = str(key)
        base = self._base(key)
        self._refresh_external()
        item = self._override_cache.get(key)
        if not item:
            return base

        try:
            rule = build_rule_with_override(base, item.get("payload") or {})
            validate_rule_definition(key, rule)
            return rule
        except Exception:
            # A corrupted override must never take the storefront or Bot down.
            return base

    def __getitem__(self, key):
        return self._effective(str(key))

    def __contains__(self, key):
        key = str(key)
        if dict.__contains__(self, key):
            return True
        self._refresh_external()
        return key in self._custom_cache

    def __iter__(self):
        return iter(self.keys())

    def __len__(self):
        return len(self.keys())

    def get(self, key, default=None):
        try:
            return self._effective(str(key))
        except KeyError:
            return default

    def keys(self):
        self._refresh_external()
        return list(dict.keys(self)) + [
            key
            for key in self._custom_cache
            if not dict.__contains__(self, key)
        ]

    def values(self):
        return [self._effective(str(key)) for key in self.keys()]

    def items(self):
        return [
            (str(key), self._effective(str(key)))
            for key in self.keys()
        ]

    def copy(self):
        return {
            str(key): self._effective(str(key))
            for key in self.keys()
        }

    def is_custom(self, key: str) -> bool:
        key = str(key)
        self._refresh_external()
        return (
            key in self._custom_cache
            and not dict.__contains__(self, key)
        )


ORDER_RULES = EffectiveOrderRules(_BASE_ORDER_RULES)


def get_base_rule(rule_key: str) -> OrderRule:
    key = str(rule_key)
    try:
        if key in _BASE_ORDER_RULES:
            return _BASE_ORDER_RULES[key]
        if isinstance(ORDER_RULES, EffectiveOrderRules):
            return ORDER_RULES._base(key)
    except KeyError as exc:
        raise KeyError(f"unknown order rule: {rule_key}") from exc
    raise KeyError(f"unknown order rule: {rule_key}")


def get_rule_override_metadata(rule_key: str) -> dict[str, Any] | None:
    try:
        from services.order_rule_store import get_active_override

        return get_active_override(str(rule_key))
    except Exception:
        return None


def preview_rule_override(
    rule_key: str,
    payload: dict[str, Any],
) -> OrderRule:
    base = get_base_rule(rule_key)
    rule = build_rule_with_override(base, payload)
    validate_rule_definition(str(rule_key), rule)
    return rule


def invalidate_rule_override_cache() -> None:
    if isinstance(ORDER_RULES, EffectiveOrderRules):
        ORDER_RULES.invalidate()


__all__ = [
    "ALL_RECEIVER_ROLES",
    "ALL_ROLE_IDS",
    "ALL_ROLE_LABELS",
    "CATEGORY_LABELS",
    "COMPANION_ROLES",
    "ORDER_RULES",
    "PROTECTOR_ROLES",
    "PriceResult",
    "ROLE_IDS",
    "ROLE_LABELS",
    "RoleKey",
    "OrderRule",
    "calculate_price",
    "build_rule_with_override",
    "build_custom_rule",
    "get_allowed_role_ids",
    "get_base_rule",
    "get_allowed_role_keys",
    "get_allowed_role_labels",
    "get_required_game_role_ids",
    "get_required_game_role_keys",
    "role_ids_match_requirements",
    "get_required_staff_count",
    "get_rule",
    "get_rule_override_metadata",
    "get_rules_by_category",
    "get_service_quantity",
    "invalidate_rule_override_cache",
    "preview_rule_override",
    "rule_to_override_payload",
    "validate_rule_definition",
    "role_labels",
    "rule_role_labels",
    "validate_rules",
]

ORDER_RULE_SNAPSHOT_VERSION = 1


def _order_rule_snapshot_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {
            str(key): _order_rule_snapshot_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [_order_rule_snapshot_safe(item) for item in value]

    return str(value)


def build_order_rule_snapshot(
    rule,
    *,
    quantity: int | None = None,
    player_count: int | None = None,
    required_staff_count: int | None = None,
    allowed_role_ids: list[str] | tuple[str, ...] | set[str] | None = None,
    required_game_role_ids: list[str] | tuple[str, ...] | set[str] | None = None,
    specified_staff_ids: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict:
    """保存建立訂單當下的規則快照，避免之後改價/改人數影響既有訂單。"""
    from dataclasses import asdict, is_dataclass

    if is_dataclass(rule):
        raw_rule = asdict(rule)
    else:
        raw_rule = dict(getattr(rule, "__dict__", {}) or {})

    snapshot = {
        "version": ORDER_RULE_SNAPSHOT_VERSION,
        "rule": _order_rule_snapshot_safe(raw_rule),
        "resolved": {
            "quantity": quantity,
            "player_count": player_count,
            "required_staff_count": required_staff_count,
            "min_protector_count": getattr(rule, "min_protector_count", 0),
            "allowed_role_keys": list(getattr(rule, "allowed_roles", []) or []),
            "allowed_game_role_keys": list(getattr(rule, "allowed_game_roles", []) or []),
            "required_game_role_keys": list(getattr(rule, "required_game_roles", []) or []),
            "allowed_role_ids": [str(item) for item in (allowed_role_ids or [])],
            "required_game_role_ids": [
                str(item)
                for item in (
                    required_game_role_ids
                    if required_game_role_ids is not None
                    else get_required_game_role_ids(rule)
                )
            ],
            "specified_staff_ids": [str(item) for item in (specified_staff_ids or [])],
            "catalog_group_label": str(getattr(rule, "catalog_group_label", "") or ""),
            "vip_discount_allowed": bool(getattr(rule, "vip_discount_allowed", True)),
            "point_benefits_allowed": bool(getattr(rule, "point_benefits_allowed", True)),
        },
    }

    return _order_rule_snapshot_safe(snapshot)
