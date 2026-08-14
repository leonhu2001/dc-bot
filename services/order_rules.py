from __future__ import annotations

from dataclasses import dataclass, field
from math import floor
from typing import Literal


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


CATEGORY_LABELS: dict[str, str] = {
    "basic": "基礎單",
    "fun": "趣味單",
    "farm": "代解代肝",
    "title": "高難度稱號",
    "steam": "Steam 陪玩",
    "valorant": "Valorant 陪玩",
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
    specify_fee_by_role: dict[RoleKey, int] = field(default_factory=dict)
    specify_free_min_units: int | None = None
    specify_free_basis: SpecifyFreeBasis = "quantity"

    player_count_enabled: bool = False
    min_player_count: int = 1
    max_player_count: int | None = None
    price_multiply_player_count: bool = False

    point_benefits_allowed: bool = True

    min_protector_count: int = 0
    service_bonus_buy: int | None = None
    service_bonus_gift: int = 0

    staff_adjustments: dict[str, int] = field(default_factory=dict)
    staff_adjustment_labels: dict[str, str] = field(default_factory=dict)

    note: str = ""


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


def _protectors_fee() -> dict[RoleKey, int]:
    return {
        "top_protector": 250,
        "female_protector": 200,
        "male_protector": 200,
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
    specified_roles: list[RoleKey] | tuple[RoleKey, ...] | None = None,
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

    for role in specified_roles:
        if role not in rule.allowed_roles:
            raise ValueError(f"{ROLE_LABELS.get(role, role)} 不能接 {rule.label}")

    free_specify_fee = False
    if specified_roles and rule.specify_free_min_units is not None:
        if rule.specify_free_basis == "quantity_x_player_count":
            free_basis_value = qty * players
        else:
            free_basis_value = qty
        free_specify_fee = free_basis_value >= int(rule.specify_free_min_units)

    specify_fee = 0
    if specified_roles and not free_specify_fee:
        for role in specified_roles:
            specify_fee += int(rule.specify_fee_by_role.get(role, rule.specify_fee_default))

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
    ("basic_exbar_gamble_zongheng", "絕巴四幻神賭單｜賭縱橫", 16888),
    ("basic_exbar_gamble_leiguan", "絕巴四幻神賭單｜賭淚冠", 16888),
    ("basic_exbar_gamble_tianyuan", "絕巴四幻神賭單｜賭天圓地方", 8888),
    ("basic_exbar_gamble_rangefinder", "絕巴四幻神賭單｜賭測距儀", 12888),
]:
    _add(OrderRule("basic", key, label, "fixed", price, allowed_roles=PROTECTOR_ROLES, required_staff_count=2, allow_specify=False))

_add(OrderRule(
    "basic", "basic_exbar_tech", "絕巴技術陪", "hourly", 1200, "H",
    allowed_roles=PROTECTOR_ROLES,
    required_staff_count=2,
    allow_specify=True,
    max_specified_count=2,
    specify_fee_by_role=_protectors_fee(),
    specify_free_min_units=2,
    specify_free_basis="quantity",
    service_bonus_buy=5,
    service_bonus_gift=1,
))

for key, label, price, staff_count in [
    ("basic_tech_secret_single", "技術陪｜機密單護", 400, 1),
    ("basic_tech_secret_double", "技術陪｜機密雙護", 800, 2),
    ("basic_tech_topsecret_single", "技術陪｜絕密單護", 450, 1),
    ("basic_tech_topsecret_double", "技術陪｜絕密雙護", 900, 2),
]:
    _add(OrderRule(
        "basic", key, label, "hourly", price, "H",
        allowed_roles=PROTECTOR_ROLES,
        required_staff_count=staff_count,
        allow_specify=True,
        max_specified_count=staff_count,
        specify_fee_by_role=_protectors_fee(),
        specify_free_min_units=2,
        specify_free_basis="quantity",
    ))

for key, label, price, staff_count in [
    ("basic_teaching_one", "教學單｜導師一名", 500, 1),
    ("basic_teaching_two", "教學單｜導師兩名", 900, 2),
]:
    _add(OrderRule(
        "basic", key, label, "hourly", price, "H",
        allowed_roles=("top_protector",),
        required_staff_count=staff_count,
        min_quantity=3,
        allow_specify=False,
    ))

for key, label, price, staff_count in [
    ("basic_entertain_single", "娛樂陪｜單陪", 350, 1),
    ("basic_entertain_double", "娛樂陪｜雙陪", 650, 2),
]:
    _add(OrderRule(
        "basic", key, label, "hourly", price, "H",
        allowed_roles=ALL_RECEIVER_ROLES,
        required_staff_count=staff_count,
        allow_specify=True,
        max_specified_count=staff_count,
        specify_fee_by_role=_all_receiver_fee(150),
        specify_free_min_units=2,
        specify_free_basis="quantity",
    ))

_add(OrderRule(
    "basic", "basic_sweet_single", "甜蜜單｜單陪", "hourly", 520, "H",
    allowed_roles=ALL_RECEIVER_ROLES,
    required_staff_count=1,
    allow_specify=True,
    max_specified_count=1,
    specify_fee_by_role=_all_receiver_fee(150),
    specify_free_min_units=2,
    specify_free_basis="quantity",
))

for key, label, price in [
    ("basic_oil_fuel", "油鍋單｜火箭燃油", 3000),
    ("basic_oil_satellite", "油鍋單｜GTI衛星通訊天線", 2000),
    ("basic_oil_all", "油鍋單｜全包", 4500),
    ("basic_bet_1000", "賭約單 1000", 1000),
    ("basic_bet_1500", "賭約單 1500", 1500),
    ("basic_bet_2500", "賭約單 2500", 2500),
    ("basic_trial_500", "體驗單 500", 500),
    ("basic_trial_1000", "體驗單 1000", 1000),
]:
    _add(OrderRule("basic", key, label, "fixed", price, allowed_roles=PROTECTOR_ROLES, required_staff_count=2, allow_specify=False))


# ========= 趣味單 =========

_add(OrderRule("fun", "fun_lovebirds", "比翼雙飛", "fixed", 2000, allowed_roles=ALL_RECEIVER_ROLES, required_staff_count=2, min_protector_count=1, allow_specify=False))
_add(OrderRule("fun", "fun_read_no_reply", "已讀亂回", "fixed", 2000, allowed_roles=ALL_RECEIVER_ROLES, required_staff_count=2, min_protector_count=1, allow_specify=False))
_add(OrderRule("fun", "fun_rich_enough", "豪到你了嗎", "fixed", 2000, allowed_roles=PROTECTOR_ROLES, required_staff_count=2, allow_specify=False))
_add(OrderRule("fun", "fun_eat_yourself", "想吃自己打", "fixed", 3000, allowed_roles=PROTECTOR_ROLES, required_staff_count=2, allow_specify=False))


# ========= 代解代肝 =========

_add(OrderRule(
    "farm", "farm_season_3x3_normal", "賽季3x3｜普通", "fixed", 5500,
    allowed_roles=PROTECTOR_ROLES,
    required_staff_count=1,
    allow_specify=False,
    staff_adjustments={
        "rush": 1500,
        "loss_cover": 500,
        "early_booking": -500,
    },
    staff_adjustment_labels={
        "rush": "急單",
        "loss_cover": "包損耗",
        "early_booking": "賽季前一周預約",
    },
))

_add(OrderRule("farm", "farm_season_3x3_skin", "賽季3x3｜造型", "fixed", 3000, allowed_roles=PROTECTOR_ROLES, required_staff_count=1, allow_specify=False))
_add(OrderRule("farm", "farm_season_3x3_contract", "賽季3x3｜命運契約", "unit", 700, "個", allowed_roles=PROTECTOR_ROLES, required_staff_count=1, allow_specify=False, max_quantity=99))

_add(OrderRule("farm", "farm_department_task", "代解部門任務", "manual", 0, allowed_roles=ALL_RECEIVER_ROLES, required_staff_count=1, allow_specify=False, note="客服填價格"))

for key, label, price in [
    ("farm_halfcoin_120m", "哈夫幣代洗｜120M", 1250),
    ("farm_halfcoin_360m", "哈夫幣代洗｜360M", 3400),
    ("farm_halfcoin_600m", "哈夫幣代洗｜600M", 5300),
]:
    _add(OrderRule("farm", key, label, "fixed", price, allowed_roles=ALL_RECEIVER_ROLES, required_staff_count=1, allow_specify=False))


# ========= 高難度稱號 =========

_add(OrderRule("title", "title_color_brave_carry", "炫彩勇敢者｜代做", "fixed", 6500, allowed_roles=PROTECTOR_ROLES, required_staff_count=3, allow_specify=False))
_add(OrderRule("title", "title_color_brave_play", "炫彩勇敢者｜陪做", "fixed", 20000, allowed_roles=PROTECTOR_ROLES, required_staff_count=2, allow_specify=False))
_add(OrderRule("title", "title_brave_play", "勇敢者｜陪做", "fixed", 4500, allowed_roles=PROTECTOR_ROLES, required_staff_count=2, allow_specify=False))


# ========= Steam 陪玩 =========

_add(OrderRule(
    "steam", "steam_play", "Steam 陪玩", "hourly", 350, "H",
    allowed_roles=ALL_RECEIVER_ROLES,
    required_staff_count="player_count",
    player_count_enabled=True,
    max_player_count=None,
    price_multiply_player_count=True,
    allow_specify=True,
    max_specified_count=None,
    specify_fee_by_role=_all_receiver_fee(150),
    specify_free_min_units=2,
    specify_free_basis="quantity_x_player_count",
    point_benefits_allowed=False,
))


# ========= Valorant 陪玩 =========

_add(OrderRule(
    "valorant", "valorant_entertain", "Valorant 陪玩｜娛樂陪", "hourly", 350, "H",
    allowed_roles=ALL_RECEIVER_ROLES,
    required_staff_count="player_count",
    player_count_enabled=True,
    max_player_count=4,
    price_multiply_player_count=True,
    allow_specify=True,
    max_specified_count=4,
    specify_fee_by_role=_all_receiver_fee(150),
    specify_free_min_units=2,
    specify_free_basis="quantity_x_player_count",
    point_benefits_allowed=False,
))

_add(OrderRule(
    "valorant", "valorant_tech", "Valorant 陪玩｜技術陪", "game", 200, "局",
    allowed_roles=PROTECTOR_ROLES,
    required_staff_count="player_count",
    player_count_enabled=True,
    max_player_count=4,
    price_multiply_player_count=True,
    allow_specify=True,
    max_specified_count=4,
    specify_fee_by_role={
        "top_protector": 200,
        "female_protector": 200,
        "male_protector": 200,
    },
    specify_free_min_units=2,
    specify_free_basis="quantity_x_player_count",
    point_benefits_allowed=False,
))

_add(OrderRule(
    "valorant", "valorant_top_tech", "Valorant 陪玩｜頂級技術陪", "game", 350, "局",
    allowed_roles=("top_protector",),
    required_staff_count="player_count",
    player_count_enabled=True,
    max_player_count=4,
    price_multiply_player_count=True,
    allow_specify=True,
    max_specified_count=4,
    specify_fee_by_role=_top_fee(250),
    specify_free_min_units=2,
    specify_free_basis="quantity_x_player_count",
    point_benefits_allowed=False,
))


def get_rules_by_category(category: str) -> list[OrderRule]:
    return [rule for rule in ORDER_RULES.values() if rule.category == category]


def get_rule(rule_key: str) -> OrderRule:
    try:
        return ORDER_RULES[rule_key]
    except KeyError as exc:
        raise KeyError(f"unknown order rule: {rule_key}") from exc


def role_labels(roles: tuple[RoleKey, ...]) -> str:
    return " / ".join(ROLE_LABELS[role] for role in roles)


def validate_rules() -> None:
    for key, rule in ORDER_RULES.items():
        if rule.category not in CATEGORY_LABELS:
            raise RuntimeError(f"{key}: unknown category {rule.category}")

        if rule.pricing_type != "manual" and int(rule.price) < 0:
            raise RuntimeError(f"{key}: invalid price")

        if rule.required_staff_count != "player_count" and int(rule.required_staff_count) <= 0:
            raise RuntimeError(f"{key}: invalid required staff count")

        if rule.allow_specify:
            if not rule.specify_fee_by_role and rule.specify_fee_default <= 0:
                raise RuntimeError(f"{key}: specify enabled but no fee configured")

        if not rule.allowed_roles:
            raise RuntimeError(f"{key}: no allowed roles")

        if rule.min_protector_count > 0 and rule.min_protector_count > get_required_staff_count(rule, rule.max_player_count or 1):
            raise RuntimeError(f"{key}: min protector count exceeds required staff count")


validate_rules()


__all__ = [
    "ALL_RECEIVER_ROLES",
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
    "get_required_staff_count",
    "get_rule",
    "get_rules_by_category",
    "get_service_quantity",
    "role_labels",
    "validate_rules",
]

# ===== 魔丸 runtime rule overrides start =====
# 這段放在 ORDER_RULES 建立完成後，用 runtime key / label 直接覆蓋顯示名稱、數量限制與自訂單。

from dataclasses import fields as _mm_dataclass_fields
from dataclasses import is_dataclass as _mm_is_dataclass
from dataclasses import replace as _mm_dataclass_replace

def _mm_order_rule_field_names(_rule):
    if _mm_is_dataclass(_rule):
        return {field.name for field in _mm_dataclass_fields(_rule)}
    return set(getattr(_rule, "__dict__", {}).keys())

def _mm_filter_rule_changes(_rule, _changes):
    _fields = _mm_order_rule_field_names(_rule)
    return {key: value for key, value in _changes.items() if key in _fields}

def _mm_replace_order_rule(_rule, **_changes):
    _filtered = _mm_filter_rule_changes(_rule, _changes)

    if not _filtered:
        return _rule

    if _mm_is_dataclass(_rule):
        try:
            return _mm_dataclass_replace(_rule, **_filtered)
        except Exception:
            pass

    try:
        for _field, _value in _filtered.items():
            setattr(_rule, _field, _value)
        return _rule
    except Exception:
        pass

    try:
        for _field, _value in _filtered.items():
            object.__setattr__(_rule, _field, _value)
    except Exception:
        pass

    return _rule

def _mm_override_order_rule(_key: str, **_changes):
    _rule = ORDER_RULES.get(_key)

    if _rule is None:
        return False

    ORDER_RULES[_key] = _mm_replace_order_rule(_rule, **_changes)
    return True

def _mm_override_order_rule_by_label(_label: str, **_changes):
    _patched = 0

    for _key, _rule in list(ORDER_RULES.items()):
        if str(getattr(_rule, "label", "")) == str(_label):
            ORDER_RULES[_key] = _mm_replace_order_rule(_rule, **_changes)
            _patched += 1

    return _patched

def _mm_override_title_color_brave_carry():
    _patched = 0

    for _key, _rule in list(ORDER_RULES.items()):
        _label = str(getattr(_rule, "label", ""))

        if _key == "title_color_brave_carry" or ("炫彩勇敢者" in _label and "代做" in _label):
            ORDER_RULES[_key] = _mm_replace_order_rule(_rule, max_quantity=3)
            _patched += 1

    return _patched

def _mm_add_custom_order_rule():
    try:
        CATEGORY_LABELS["custom"] = "自訂單"
    except Exception:
        pass

    try:
        ORDER_CATEGORY_LABELS["custom"] = "自訂單"
    except Exception:
        pass

    _template = (
        ORDER_RULES.get("farm_department_task")
        or ORDER_RULES.get("basic_entertain_single")
        or next(iter(ORDER_RULES.values()))
    )

    _allowed_roles = tuple(
        role for role in (
            "top_protector",
            "female_protector",
            "male_protector",
            "male_companion",
            "female_companion",
        )
    )

    _changes = {
        "key": "custom_custom_order",
        "category": "custom",
        "label": "自訂單",
        "pricing_type": "manual",
        "quantity_unit": "單",
        "min_quantity": 1,
        "max_quantity": 24,
        "allow_specify": True,
        "max_specified_count": 24,
        "allowed_roles": _allowed_roles,
        "required_staff_count": 1,
        "min_protector_count": 0,
        "point_benefits_allowed": False,
        "base_amount": 0,
        "base_price": 0,
        "price": 0,
        "unit_price": 0,
        "hourly_price": 0,
        "specify_fee": 0,
    }

    ORDER_RULES["custom_custom_order"] = _mm_replace_order_rule(_template, **_changes)

_mm_override_order_rule("farm_season_3x3_contract", max_quantity=4)

# 炫彩勇敢者｜代做用 key + label 雙保險，避免 key 或 label 寫法不同。
_mm_override_order_rule("title_color_brave_carry", max_quantity=3)
_mm_override_order_rule_by_label("炫彩勇敢者｜代做", max_quantity=3)
_mm_override_title_color_brave_carry()

# 炫彩勇敢者｜陪做只能 1 單
_mm_override_order_rule("title_color_brave_play", max_quantity=1)
_mm_override_order_rule_by_label("炫彩勇敢者｜陪做", max_quantity=1)

# 勇敢者｜陪做只能 1 單
_mm_override_order_rule("title_brave_play", max_quantity=1)
_mm_override_order_rule_by_label("勇敢者｜陪做", max_quantity=1)

_mm_override_order_rule("basic_bet_1000", label="賭約單 800w")
_mm_override_order_rule("basic_bet_1500", label="賭約單 1000w")
_mm_override_order_rule("basic_bet_2500", label="賭約單 1200w")

_mm_override_order_rule("basic_trial_500", label="體驗單 777w")
_mm_override_order_rule("basic_trial_1000", label="體驗單 1688w")

_mm_add_custom_order_rule()
# ===== 魔丸 runtime rule overrides end =====
