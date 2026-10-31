from __future__ import annotations

from pathlib import Path
import re


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 match, got {count}")
    return text.replace(old, new, 1)


def sub_once(text: str, pattern: str, repl: str, label: str) -> str:
    result, count = re.subn(pattern, repl, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 regex match, got {count}")
    return result


path = "services/order_rules.py"
text = read(path)

role_block = '''ROLE_LABELS: dict[RoleKey, str] = {
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

AW_COLLISION_RECEIVER_ROLE_KEY = "aw_collision_receiver"
AW_COLLISION_RECEIVER_ROLE_ID = "1565369029005287595"
HALFCOIN_RECEIVER_ROLE_KEY = "halfcoin_receiver"
HALFCOIN_RECEIVER_ROLE_ID = "1565369317929918554"

SPECIAL_RECEIVER_ROLE_IDS_BY_KEY: dict[str, str] = {
    AW_COLLISION_RECEIVER_ROLE_KEY: AW_COLLISION_RECEIVER_ROLE_ID,
    HALFCOIN_RECEIVER_ROLE_KEY: HALFCOIN_RECEIVER_ROLE_ID,
}
SPECIAL_RECEIVER_ROLE_LABELS_BY_KEY: dict[str, str] = {
    AW_COLLISION_RECEIVER_ROLE_KEY: "AW代撞接單",
    HALFCOIN_RECEIVER_ROLE_KEY: "哈夫幣代洗接單",
}

GAME_ROLE_IDS_BY_KEY: dict[str, str] = {
    key: str(role.role_id)
    for key, role in GAME_ROLE_BY_KEY.items()
}
GAME_ROLE_LABELS_BY_KEY: dict[str, str] = {
    key: str(role.label)
    for key, role in GAME_ROLE_BY_KEY.items()
}

SWEET_COMPANION_ROLE_KEY = "sweet_companion"
SWEET_COMPANION_ROLE_ID = "1564966706407940248"
SWEET_COMPANION_ROLE_LABEL = "甜蜜陪"
EXTRA_REQUIRED_ROLE_IDS_BY_KEY: dict[str, str] = {
    SWEET_COMPANION_ROLE_KEY: SWEET_COMPANION_ROLE_ID,
}
EXTRA_REQUIRED_ROLE_LABELS_BY_KEY: dict[str, str] = {
    SWEET_COMPANION_ROLE_KEY: SWEET_COMPANION_ROLE_LABEL,
}

ALL_ROLE_IDS: dict[str, str] = {
    **ROLE_IDS,
    **SPECIAL_RECEIVER_ROLE_IDS_BY_KEY,
    **GAME_ROLE_IDS_BY_KEY,
    **EXTRA_REQUIRED_ROLE_IDS_BY_KEY,
}
ALL_ROLE_LABELS: dict[str, str] = {
    **ROLE_LABELS,
    **SPECIAL_RECEIVER_ROLE_LABELS_BY_KEY,
    **GAME_ROLE_LABELS_BY_KEY,
    **EXTRA_REQUIRED_ROLE_LABELS_BY_KEY,
}
'''
text = sub_once(
    text,
    r"ROLE_LABELS: dict\[RoleKey, str\] = \{.*?ALL_ROLE_LABELS: dict\[str, str\] = \{\*\*ROLE_LABELS, \*\*GAME_ROLE_LABELS_BY_KEY\}\n",
    role_block,
    "role maps",
)
text = replace_once(
    text,
    'ALL_RECEIVER_ROLES: tuple[RoleKey, ...] = PROTECTOR_ROLES + COMPANION_ROLES\nAW_COLLISION_RECEIVER_ROLES: tuple[RoleKey, ...] = ("aw_collision_receiver",)\nHALFCOIN_RECEIVER_ROLES: tuple[RoleKey, ...] = ("halfcoin_receiver",)\n',
    'ALL_RECEIVER_ROLES: tuple[RoleKey, ...] = PROTECTOR_ROLES + COMPANION_ROLES\nAW_COLLISION_RECEIVER_ROLES: tuple[RoleKey, ...] = ("aw_collision_receiver",)\nHALFCOIN_RECEIVER_ROLES: tuple[RoleKey, ...] = ("halfcoin_receiver",)\nSPECIAL_RECEIVER_ROLES: tuple[RoleKey, ...] = AW_COLLISION_RECEIVER_ROLES + HALFCOIN_RECEIVER_ROLES\nALL_CLAIM_ROLES: tuple[RoleKey, ...] = ALL_RECEIVER_ROLES + SPECIAL_RECEIVER_ROLES\n',
    "claim role sets",
)
text = replace_once(
    text,
    'APEX_GAME_ROLE = ("apex_game",)\n',
    '''APEX_GAME_ROLE = ("apex_game",)\n\nAW_COLLISION_PRICING_BY_RULE: dict[str, dict[str, Any]] = {\n    "farm_aw_collision_1_100": {"label": "1～100發｜5T/發", "short_label": "1～100發", "min": 1, "max": 100, "rate_x2": 10, "rate_text": "5"},\n    "farm_aw_collision_101_500": {"label": "101～500發｜4.5T/發", "short_label": "101～500發", "min": 101, "max": 500, "rate_x2": 9, "rate_text": "4.5"},\n    "farm_aw_collision_501_plus": {"label": "501發以上｜4T/發", "short_label": "501發以上", "min": 501, "max": 999999, "rate_x2": 8, "rate_text": "4"},\n}\n''',
    "AW pricing table",
)
text = replace_once(text, '    "farm": "三角洲 代肝代解",', '    "farm": "台服代肝代解",', "farm label")
text = replace_once(
    text,
    '    # 必須同時持有其中至少一個遊戲身分組；與 allowed_* 是 AND 關係。\n    required_game_roles: tuple[str, ...] = ()\n    specify_fee_by_game_role: dict[str, int] = field(default_factory=dict)\n',
    '    # 必須同時持有其中至少一個遊戲身分組；與 allowed_* 是 AND 關係。\n    required_game_roles: tuple[str, ...] = ()\n    # 非遊戲身分的額外資格；每一個都必須持有（ALL / AND）。\n    required_roles: tuple[str, ...] = ()\n    specify_fee_by_game_role: dict[str, int] = field(default_factory=dict)\n',
    "required_roles field",
)
text = replace_once(text, '    "required_game_roles",\n    "specify_fee_by_game_role",', '    "required_game_roles",\n    "required_roles",\n    "specify_fee_by_game_role",', "override field")
text = replace_once(text, '    "required_game_roles",\n}\n_DICT_OVERRIDE_FIELDS', '    "required_game_roles",\n    "required_roles",\n}\n_DICT_OVERRIDE_FIELDS', "tuple override")

if text.count('required_game_roles=(SWEET_COMPANION_ROLE_KEY,),') != 2:
    raise RuntimeError("expected two legacy sweet direct requirements")
text = text.replace('required_game_roles=(SWEET_COMPANION_ROLE_KEY,),', 'required_game_roles=(),')
text = replace_once(text, '        required_game_roles=(*required_game_roles, SWEET_COMPANION_ROLE_KEY),\n', '        required_game_roles=required_game_roles,\n', "legacy sweet helper")
text = replace_once(text, '        required_game_roles=(*required_game_roles, SWEET_COMPANION_ROLE_KEY),\n', '        required_game_roles=required_game_roles,\n        required_roles=(SWEET_COMPANION_ROLE_KEY,),\n', "canonical sweet helper")

halfcoin = '''for key, label, price in [\n    ("farm_halfcoin_120m", "哈夫幣代洗｜120M", 1250),\n    ("farm_halfcoin_360m", "哈夫幣代洗｜360M", 3400),\n]:\n    _add(OrderRule("farm", key, label, "fixed", price, allowed_roles=HALFCOIN_RECEIVER_ROLES, required_game_roles=(), required_staff_count=1, min_quantity=1, max_quantity=1, allow_specify=False))\n'''
text = replace_once(
    text,
    halfcoin,
    halfcoin + '''\nfor key, plan in AW_COLLISION_PRICING_BY_RULE.items():\n    _add(OrderRule(\n        category="farm", key=key, label=f"AW代撞｜{plan['short_label']}",\n        pricing_type="unit", price=max(1, int(plan["rate_x2"]) // 2), unit_label="發",\n        allowed_roles=AW_COLLISION_RECEIVER_ROLES, required_staff_count=1,\n        min_quantity=int(plan["min"]), max_quantity=int(plan["max"]), allow_specify=False,\n        max_specified_count=None, specify_fee_default=0, vip_discount_allowed=False,\n        point_benefits_allowed=False, loyalty_benefits_enabled=False, required_game_roles=(),\n        note="AW代撞依方案發數動態計價；101～500發為4.5T/發。系統帳務只存整數T，半T總額向上進位。",\n    ))\n''',
    "base AW rules",
)
text = replace_once(
    text,
    '    qty = _normalize_quantity(rule, quantity)\n    players = _normalize_player_count(rule, player_count)\n    required_staff = get_required_staff_count(rule, players)\n\n    if rule.pricing_type == "manual":\n',
    '''    aw_plan = AW_COLLISION_PRICING_BY_RULE.get(str(getattr(rule, "key", "") or ""))\n    if aw_plan is not None and quantity is None:\n        quantity = int(getattr(rule, "min_quantity", 1) or 1)\n    qty = _normalize_quantity(rule, quantity)\n    players = _normalize_player_count(rule, player_count)\n    required_staff = get_required_staff_count(rule, players)\n\n    if aw_plan is not None:\n        if specified_roles:\n            raise ValueError("AW代撞不開放指定")\n        if staff_adjustments:\n            raise ValueError("AW代撞不支援額外加減價選項")\n        base_amount = (qty * int(aw_plan["rate_x2"]) + 1) // 2\n        return PriceResult(base_amount, 0, 0, base_amount, qty, 1, False, (f"AW代撞｜{aw_plan['short_label']}｜{aw_plan['rate_text']}T/發",))\n\n    if rule.pricing_type == "manual":\n''',
    "direct AW pricing",
)

text = sub_once(
    text,
    r"def get_required_game_role_keys\(rule: OrderRule\) -> tuple\[str, \.\.\.\]:.*?\n\ndef get_allowed_role_labels\(rule: OrderRule\) -> list\[str\]:",
    '''def get_required_game_role_keys(rule: OrderRule) -> tuple[str, ...]:\n    return _unique_role_keys_by_id(tuple(rule.required_game_roles))\n\n\ndef get_required_role_keys(rule: OrderRule) -> tuple[str, ...]:\n    return _unique_role_keys_by_id(tuple(rule.required_roles))\n\n\ndef get_required_role_ids(rule: OrderRule) -> list[str]:\n    return [str(ALL_ROLE_IDS[key]) for key in get_required_role_keys(rule) if key in ALL_ROLE_IDS]\n\n\ndef get_required_qualification_role_ids(rule: OrderRule) -> list[str]:\n    keys = _unique_role_keys_by_id(tuple(get_required_game_role_keys(rule)) + tuple(get_required_role_keys(rule)))\n    return [str(ALL_ROLE_IDS[key]) for key in keys if key in ALL_ROLE_IDS]\n\n\ndef get_required_game_role_ids(rule: OrderRule) -> list[str]:\n    # Legacy persistence/caller API. The stored column is still named game roles,\n    # so return all required qualification IDs while the canonical keys stay split.\n    return get_required_qualification_role_ids(rule)\n\n\ndef role_ids_match_requirements(member_role_ids, allowed_role_ids, required_game_role_ids=(), required_role_ids=()) -> bool:\n    member_roles = {str(x).strip() for x in (member_role_ids or []) if str(x).strip()}\n    allowed = {str(x).strip() for x in (allowed_role_ids or []) if str(x).strip()}\n    required_games = {str(x).strip() for x in (required_game_role_ids or []) if str(x).strip()}\n    required_all = {str(x).strip() for x in (required_role_ids or []) if str(x).strip()}\n    extra_ids = set(EXTRA_REQUIRED_ROLE_IDS_BY_KEY.values())\n    required_all.update(required_games & extra_ids)\n    required_games.difference_update(extra_ids)\n    if allowed and not (member_roles & allowed):\n        return False\n    if required_games and not (member_roles & required_games):\n        return False\n    if required_all and not required_all.issubset(member_roles):\n        return False\n    return True\n\n\ndef get_allowed_role_labels(rule: OrderRule) -> list[str]:''',
    "qualification helpers",
)
text = sub_once(
    text,
    r"def rule_role_labels\(rule: OrderRule\) -> str:\n.*?\n\ndef validate_rule_definition",
    '''def rule_role_labels(rule: OrderRule) -> str:\n    qualification = role_labels(rule.allowed_roles, rule.allowed_game_roles)\n    required_keys = _unique_role_keys_by_id(tuple(get_required_game_role_keys(rule)) + tuple(get_required_role_keys(rule)))\n    required = " / ".join(str(ALL_ROLE_LABELS.get(key, key)) for key in required_keys)\n    if qualification and required:\n        return f"{qualification} + {required}"\n    return qualification or required\n\n\ndef validate_rule_definition''',
    "role labels",
)
text = replace_once(
    text,
    '''    unknown_required_games = [\n        role_key\n        for role_key in rule.required_game_roles\n        if role_key not in ALL_ROLE_IDS\n    ]\n    if unknown_required_games:\n        raise RuntimeError(\n            f"{key}: unknown required game roles {unknown_required_games}"\n        )\n''',
    '''    unknown_required_games = [role_key for role_key in rule.required_game_roles if role_key not in GAME_ROLE_IDS_BY_KEY]\n    if unknown_required_games:\n        raise RuntimeError(f"{key}: unknown required game roles {unknown_required_games}")\n    unknown_required_roles = [role_key for role_key in rule.required_roles if role_key not in EXTRA_REQUIRED_ROLE_IDS_BY_KEY]\n    if unknown_required_roles:\n        raise RuntimeError(f"{key}: unknown required roles {unknown_required_roles}")\n''',
    "required validation",
)
text = replace_once(text, '                    required_game_roles=base.required_game_roles,\n                    required_staff_count=base.required_staff_count,', '                    required_game_roles=base.required_game_roles,\n                    required_roles=base.required_roles,\n                    required_staff_count=base.required_staff_count,', "source authority")
text = replace_once(text, '                    required_game_roles=base.required_game_roles,\n                    allow_specify=base.allow_specify,', '                    required_game_roles=base.required_game_roles,\n                    required_roles=base.required_roles,\n                    allow_specify=base.allow_specify,', "qualification authority")
text = replace_once(text, '            if SWEET_COMPANION_ROLE_KEY in tuple(base.required_game_roles):\n                rule = replace(rule, required_game_roles=base.required_game_roles)\n', '            if SWEET_COMPANION_ROLE_KEY in tuple(base.required_roles):\n                rule = replace(rule, required_roles=base.required_roles)\n', "sweet authority")
text = replace_once(text, '    "ALL_RECEIVER_ROLES",\n', '    "ALL_RECEIVER_ROLES",\n    "ALL_CLAIM_ROLES",\n    "SPECIAL_RECEIVER_ROLES",\n', "exports claim")
text = replace_once(text, '    "AW_COLLISION_RECEIVER_ROLES",\n', '    "AW_COLLISION_RECEIVER_ROLES",\n    "AW_COLLISION_RECEIVER_ROLE_ID",\n    "AW_COLLISION_PRICING_BY_RULE",\n', "exports AW")
text = replace_once(text, '    "HALFCOIN_RECEIVER_ROLES",\n', '    "HALFCOIN_RECEIVER_ROLES",\n    "HALFCOIN_RECEIVER_ROLE_ID",\n', "exports half")
text = replace_once(text, '    "get_required_game_role_ids",\n    "get_required_game_role_keys",\n', '    "get_required_game_role_ids",\n    "get_required_game_role_keys",\n    "get_required_role_ids",\n    "get_required_role_keys",\n    "get_required_qualification_role_ids",\n', "exports helpers")
text = replace_once(text, 'ORDER_RULE_SNAPSHOT_VERSION = 1', 'ORDER_RULE_SNAPSHOT_VERSION = 2', "snapshot version")
text = replace_once(text, '            "required_game_role_keys": list(getattr(rule, "required_game_roles", []) or []),\n            "allowed_role_ids":', '            "required_game_role_keys": list(getattr(rule, "required_game_roles", []) or []),\n            "required_role_keys": list(getattr(rule, "required_roles", []) or []),\n            "required_role_ids": get_required_role_ids(rule),\n            "allowed_role_ids":', "snapshot roles")
write(path, text)

# Direct AW catalog data.
path = "services/orders.py"
text = read(path)
needle = '''        {\n            "label": "哈夫幣代洗",\n            "details": [\n                {"label": "120M", "value": "120m", "rule_key": "farm_halfcoin_120m", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1},\n                {"label": "360M", "value": "360m", "rule_key": "farm_halfcoin_360m", "quantity_unit": "單", "min_quantity": 1, "max_quantity": 1},\n            ],\n        },\n'''
text = replace_once(text, needle, needle + '''        {\n            "label": "AW代撞",\n            "details": [\n                {"label": "1～100發｜5T/發", "value": "1_100", "rule_key": "farm_aw_collision_1_100", "quantity_unit": "發", "min_quantity": 1, "max_quantity": 100, "quantity_input_mode": "modal"},\n                {"label": "101～500發｜4.5T/發", "value": "101_500", "rule_key": "farm_aw_collision_101_500", "quantity_unit": "發", "min_quantity": 101, "max_quantity": 500, "quantity_input_mode": "modal"},\n                {"label": "501發以上｜4T/發", "value": "501_plus", "rule_key": "farm_aw_collision_501_plus", "quantity_unit": "發", "min_quantity": 501, "max_quantity": 999999, "quantity_input_mode": "modal"},\n            ],\n        },\n''', "orders AW catalog")
write(path, text)

# AW module retains UI/modal adapters only; no rule or price mutation.
path = "services/aw_collision_catalog.py"
text = read(path)
text = sub_once(text, r"from services\.order_rules import \(.*?\)\n", "from services.order_rules import AW_COLLISION_PRICING_BY_RULE\n", "AW imports")
text = sub_once(text, r"AW_RULE_KEYS = \(.*?AW_COLLISION_PLANS: dict\[str, dict\[str, Any\]\] = \{.*?\n\}\n", 'AW_RULE_KEYS = tuple(AW_COLLISION_PRICING_BY_RULE)\nAW_COLLISION_PLANS: dict[str, dict[str, Any]] = {key: dict(plan) for key, plan in AW_COLLISION_PRICING_BY_RULE.items()}\n', "AW plans")
text = text.replace("_ORIGINAL_CALCULATE_PRICE = None\n", "")
text = sub_once(text, r"def _install_rules_and_catalog\(\) -> None:.*?\n\ndef _extend_product_dependent_state\(\) -> None:", "def _extend_product_dependent_state() -> None:", "remove AW mutations")
text = replace_once(text, "    _install_rules_and_catalog()\n    _install_price_patch()\n    _extend_product_dependent_state()\n", "    _extend_product_dependent_state()\n", "AW install")
write(path, text)

# Audit special claim roles through ALL_ROLE_IDS without expanding ordinary products.
path = "tools/audit_order_rules.py"
text = read(path)
text = replace_once(text, '    all_receiver_roles = set(getattr(order_rules, "ALL_RECEIVER_ROLES", set()) or set())\n', '    all_receiver_roles = set(getattr(order_rules, "ALL_CLAIM_ROLES", getattr(order_rules, "ALL_RECEIVER_ROLES", set())) or set())\n', "audit claim set")
text = replace_once(text, '            role_id = ROLE_IDS.get(role_key)\n', '            role_id = all_role_ids.get(role_key)\n', "audit map")
text = replace_once(text, '            if role_key not in ROLE_IDS:\n                errors.append(f"{key}: allowed role missing ROLE_IDS mapping: {role_key}")\n', '            if role_key not in all_role_ids:\n                errors.append(f"{key}: allowed role missing ALL_ROLE_IDS mapping: {role_key}")\n', "audit allowed map")
write(path, text)

# Tests: remove old assumptions that every farm product is a generic Delta worker product.
path = "tests/test_aw_collision_catalog.py"
text = read(path)
text = replace_once(text, 'def test_aw_rules_require_one_delta_worker_and_no_specify():\n    for key in AW_RULE_KEYS:\n        rule = ORDER_RULES[key]\n        assert rule.category == "farm"\n        assert rule.required_staff_count == 1\n        assert rule.required_game_roles == ("delta_desktop", "delta_mobile")\n        assert rule.allow_specify is False\n', 'def test_aw_rules_require_only_dedicated_receiver_and_no_specify():\n    for key in AW_RULE_KEYS:\n        rule = ORDER_RULES[key]\n        assert rule.category == "farm"\n        assert rule.required_staff_count == 1\n        assert rule.allowed_roles == ("aw_collision_receiver",)\n        assert rule.required_game_roles == ()\n        assert rule.allow_specify is False\n', "AW test")
write(path, text)

path = "tests/test_game_service_rules.py"
text = read(path)
text = replace_once(text, '        if rule.category != "farm":\n            continue\n\n        assert get_required_game_role_keys(rule) == (\n', '        if rule.category != "farm":\n            continue\n        if rule_key.startswith(("farm_aw_collision_", "farm_halfcoin_")):\n            continue\n\n        assert get_required_game_role_keys(rule) == (\n', "farm generic test")
marker = '\n\ndef test_all_season_3x3_variants_allow_all_five_store_roles():\n'
dedicated = '''\n\ndef test_dedicated_farm_products_use_only_their_receiver_role():\n    expected = {\n        "farm_halfcoin_120m": ("halfcoin_receiver", "1565369317929918554"),\n        "farm_halfcoin_360m": ("halfcoin_receiver", "1565369317929918554"),\n        "farm_aw_collision_1_100": ("aw_collision_receiver", "1565369029005287595"),\n        "farm_aw_collision_101_500": ("aw_collision_receiver", "1565369029005287595"),\n        "farm_aw_collision_501_plus": ("aw_collision_receiver", "1565369029005287595"),\n    }\n    for rule_key, (role_key, role_id) in expected.items():\n        rule = ORDER_RULES[rule_key]\n        assert rule.allowed_roles == (role_key,)\n        assert get_allowed_role_ids(rule) == [role_id]\n        assert get_required_game_role_keys(rule) == ()\n        assert role_ids_match_requirements([role_id], [role_id], ()) is True\n\n'''
text = replace_once(text, marker, dedicated + 'def test_all_season_3x3_variants_allow_all_five_store_roles():\n', "dedicated tests")
write(path, text)

path = "tests/test_companion_count_finish_20261028.py"
text = read(path)
text = replace_once(text, '    assert SWEET_COMPANION_ROLE_ID in required\n    assert game_ids\n', '    assert order_rules.get_required_role_keys(rule) == ("sweet_companion",)\n    assert order_rules.get_required_game_role_keys(rule) == ("valorant_game",)\n    assert SWEET_COMPANION_ROLE_ID in required\n    assert game_ids\n', "sweet field test")
write(path, text)

# Safety assertions.
canonical = read("services/order_rules.py")
for token in (
    'AW_COLLISION_RECEIVER_ROLE_ID = "1565369029005287595"',
    'HALFCOIN_RECEIVER_ROLE_ID = "1565369317929918554"',
    'SWEET_COMPANION_ROLE_ID = "1564966706407940248"',
    'required_roles=(SWEET_COMPANION_ROLE_KEY,)',
    'AW_COLLISION_PRICING_BY_RULE',
):
    assert token in canonical, token
print("CORE_RULE_REFACTOR_APPLIED")
