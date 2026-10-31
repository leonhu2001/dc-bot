from pathlib import Path
import re


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, got {count}")
    return text.replace(old, new, 1)


# 1) Canonical qualification rules.
path = "services/order_rules.py"
text = read(path)

text = replace_once(
    text,
    '''RoleKey = Literal[\n    "top_protector",\n    "female_protector",\n    "male_protector",\n    "male_companion",\n    "female_companion",\n]\n''',
    '''RoleKey = Literal[\n    "top_protector",\n    "female_protector",\n    "male_protector",\n    "male_companion",\n    "female_companion",\n    "aw_collision_receiver",\n    "halfcoin_receiver",\n]\n''',
    "RoleKey",
)
text = replace_once(
    text,
    '    "female_companion": "魔丸♟女陪",\n}',
    '    "female_companion": "魔丸♟女陪",\n    "aw_collision_receiver": "AW代撞接單",\n    "halfcoin_receiver": "哈夫幣代洗接單",\n}',
    "ROLE_LABELS",
)
text = replace_once(
    text,
    '    "female_companion": "1482080315798192210",\n}',
    '    "female_companion": "1482080315798192210",\n    "aw_collision_receiver": "1565369029005287595",\n    "halfcoin_receiver": "1565369317929918554",\n}',
    "ROLE_IDS",
)
text = replace_once(
    text,
    'ALL_RECEIVER_ROLES: tuple[RoleKey, ...] = PROTECTOR_ROLES + COMPANION_ROLES\n',
    'ALL_RECEIVER_ROLES: tuple[RoleKey, ...] = PROTECTOR_ROLES + COMPANION_ROLES\nAW_COLLISION_RECEIVER_ROLES: tuple[RoleKey, ...] = ("aw_collision_receiver",)\nHALFCOIN_RECEIVER_ROLES: tuple[RoleKey, ...] = ("halfcoin_receiver",)\n',
    "special receiver tuples",
)

text = replace_once(
    text,
    '''    "general", "basic_sweet_single", "甜蜜單｜單陪", "hourly", 520, "H",\n    allowed_roles=COMPANION_ROLES,\n    allowed_game_roles=(),\n    required_game_roles=(),\n''',
    '''    "general", "basic_sweet_single", "甜蜜單｜單陪", "hourly", 520, "H",\n    allowed_roles=COMPANION_ROLES,\n    allowed_game_roles=(),\n    required_game_roles=(SWEET_COMPANION_ROLE_KEY,),\n''',
    "legacy sweet single",
)
text = replace_once(
    text,
    '''    "general", "basic_sweet_double", "甜蜜單｜雙陪", "hourly", 1314, "H",\n    allowed_roles=COMPANION_ROLES,\n    allowed_game_roles=(),\n    required_game_roles=(),\n''',
    '''    "general", "basic_sweet_double", "甜蜜單｜雙陪", "hourly", 1314, "H",\n    allowed_roles=COMPANION_ROLES,\n    allowed_game_roles=(),\n    required_game_roles=(SWEET_COMPANION_ROLE_KEY,),\n''',
    "legacy sweet double",
)
text = replace_once(
    text,
    '        required_game_roles=required_game_roles,\n        required_staff_count=required_staff_count,',
    '        required_game_roles=(*required_game_roles, SWEET_COMPANION_ROLE_KEY),\n        required_staff_count=required_staff_count,',
    "sweet helper qualification",
)
text = replace_once(
    text,
    '    _add(OrderRule("farm", key, label, "fixed", price, allowed_roles=ALL_RECEIVER_ROLES, required_game_roles=DELTA_ANY_GAME_ROLE, required_staff_count=1, min_quantity=1, max_quantity=1, allow_specify=False))',
    '    _add(OrderRule("farm", key, label, "fixed", price, allowed_roles=HALFCOIN_RECEIVER_ROLES, required_game_roles=(), required_staff_count=1, min_quantity=1, max_quantity=1, allow_specify=False))',
    "halfcoin qualification",
)

source_block = '''SOURCE_AUTHORITY_RULE_KEYS = frozenset(\n    key\n    for key, rule in _BASE_ORDER_RULES.items()\n    if bool(rule.player_count_enabled) and key != "custom_custom_order"\n)\n'''
source_new = source_block + '''\n# Owner-approved structural qualifications. Manager overrides may change ordinary\n# commercial fields but cannot broaden who may claim these system products.\nSOURCE_AUTHORITY_QUALIFICATION_RULE_KEYS = frozenset({\n    "farm_halfcoin_120m",\n    "farm_halfcoin_360m",\n    "farm_aw_collision_1_100",\n    "farm_aw_collision_101_500",\n    "farm_aw_collision_501_plus",\n})\n'''
text = replace_once(text, source_block, source_new, "qualification authority set")

text = replace_once(
    text,
    '''                    max_specified_count=base.max_specified_count,\n                )\n            if SWEET_COMPANION_ROLE_KEY in tuple(base.required_game_roles):\n''',
    '''                    max_specified_count=base.max_specified_count,\n                )\n            if key in SOURCE_AUTHORITY_QUALIFICATION_RULE_KEYS:\n                rule = replace(\n                    rule,\n                    allowed_roles=base.allowed_roles,\n                    allowed_game_roles=base.allowed_game_roles,\n                    required_game_roles=base.required_game_roles,\n                    allow_specify=base.allow_specify,\n                    max_specified_count=base.max_specified_count,\n                    specify_fee_default=base.specify_fee_default,\n                    vip_discount_allowed=base.vip_discount_allowed,\n                    point_benefits_allowed=base.point_benefits_allowed,\n                    loyalty_benefits_enabled=base.loyalty_benefits_enabled,\n                )\n            if SWEET_COMPANION_ROLE_KEY in tuple(base.required_game_roles):\n''',
    "effective qualification authority",
)
text = replace_once(
    text,
    '    "ALL_RECEIVER_ROLES",\n',
    '    "ALL_RECEIVER_ROLES",\n    "AW_COLLISION_RECEIVER_ROLES",\n    "HALFCOIN_RECEIVER_ROLES",\n',
    "receiver exports",
)
text = replace_once(
    text,
    '    "SOURCE_AUTHORITY_RULE_KEYS",\n',
    '    "SOURCE_AUTHORITY_RULE_KEYS",\n    "SOURCE_AUTHORITY_QUALIFICATION_RULE_KEYS",\n',
    "authority export",
)
write(path, text)

# 2) AW rule directly owns qualification and immutable business flags.
path = "services/aw_collision_catalog.py"
text = read(path)
text = replace_once(text, '    ALL_RECEIVER_ROLES,\n    DELTA_ANY_GAME_ROLE,\n', '    AW_COLLISION_RECEIVER_ROLES,\n', "AW imports")
text = replace_once(text, '                allowed_roles=ALL_RECEIVER_ROLES,\n', '                allowed_roles=AW_COLLISION_RECEIVER_ROLES,\n', "AW allowed role")
text = replace_once(
    text,
    '                allow_specify=False,\n                required_game_roles=DELTA_ANY_GAME_ROLE,\n',
    '''                allow_specify=False,\n                max_specified_count=None,\n                specify_fee_default=0,\n                vip_discount_allowed=False,\n                point_benefits_allowed=False,\n                loyalty_benefits_enabled=False,\n                required_game_roles=(),\n''',
    "AW direct business flags",
)
write(path, text)

# 3) 100% worker payout lives in the payout engine.
path = "services/one_companion_one_guard_payout.py"
text = read(path)
payout_anchor = '''ONE_COMPANION_ONE_GUARD_PAYOUT_BASES: dict[str, tuple[int, int]] = {\n    "basic_one_companion_one_guard_secret": (400, 320),\n    "basic_one_companion_one_guard_topsecret": (450, 320),\n    "basic_mobile_one_companion_one_guard_secret": (380, 320),\n    "basic_mobile_one_companion_one_guard_topsecret": (420, 320),\n}\n'''
payout_new = payout_anchor + '''\nFULL_WORKER_PAYOUT_RULE_KEYS = frozenset({\n    "farm_halfcoin_120m",\n    "farm_halfcoin_360m",\n})\nFULL_WORKER_PAYOUT_RULE_PREFIXES = ("farm_aw_collision_",)\n\n\ndef is_full_worker_payout_rule(rule_key: str | None) -> bool:\n    key = str(rule_key or "").strip()\n    return key in FULL_WORKER_PAYOUT_RULE_KEYS or key.startswith(FULL_WORKER_PAYOUT_RULE_PREFIXES)\n'''
text = replace_once(text, payout_anchor, payout_new, "full payout declarations")
text = replace_once(
    text,
    '''    workers = _unique_worker_roles(worker_roles)\n    shares = allocate_integer_gross_shares(rule_key, workers, total_amount)\n''',
    '''    workers = _unique_worker_roles(worker_roles)\n\n    if is_full_worker_payout_rule(rule_key):\n        worker_ids = [worker_id for worker_id, _role_type in workers]\n        customer_service_amount = (\n            max(0, int(total_amount or 0))\n            if customer_service_total_amount is None\n            else max(0, int(customer_service_total_amount or 0))\n        )\n        return calculate_order_payout(\n            total_amount=max(0, int(total_amount or 0)),\n            worker_discord_ids=worker_ids,\n            named_bonus_worker_ids=[],\n            worker_base_rate=1.0,\n            customer_service_rate=0.0,\n            named_bonus_rate=0.0,\n            customer_service_total_amount=customer_service_amount,\n        )\n\n    shares = allocate_integer_gross_shares(rule_key, workers, total_amount)\n''',
    "canonical full payout branch",
)
text = replace_once(
    text,
    '    "ONE_COMPANION_ONE_GUARD_PAYOUT_BASES",\n',
    '    "ONE_COMPANION_ONE_GUARD_PAYOUT_BASES",\n    "FULL_WORKER_PAYOUT_RULE_KEYS",\n    "FULL_WORKER_PAYOUT_RULE_PREFIXES",\n',
    "payout constant exports",
)
text = replace_once(
    text,
    '    "calculate_one_companion_one_guard_order_payout",\n',
    '    "calculate_one_companion_one_guard_order_payout",\n    "is_full_worker_payout_rule",\n',
    "payout helper export",
)
write(path, text)

# 4) Remove the old AW rule/payout monkey-patches.
path = "services/aw_collision_business_policy.py"
text = read(path)
text = replace_once(
    text,
    'from services.aw_collision_catalog import AW_RULE_KEYS, is_aw_collision_rule\n',
    'from services.aw_collision_catalog import is_aw_collision_rule\n',
    "business policy import",
)
text = replace_once(text, '_ORIGINAL_ROLE_AWARE_PAYOUT = None\n', '', "old payout global")
text, count = re.subn(r'\n\ndef _install_rule_policy\(\) -> None:.*?(?=\n\ndef _clean_aw_finance_input)', '', text, count=1, flags=re.S)
if count != 1:
    raise RuntimeError(f"remove AW rule patch: expected 1 match, got {count}")
text, count = re.subn(r'\n\ndef _install_payout_policy\(\) -> None:.*?(?=\n\ndef install_aw_collision_business_policy)', '', text, count=1, flags=re.S)
if count != 1:
    raise RuntimeError(f"remove AW payout patch: expected 1 match, got {count}")
text = replace_once(text, '    _install_rule_policy()\n', '', "remove AW rule installer call")
text = replace_once(text, '    _install_payout_policy()\n', '', "remove AW payout installer call")
text = replace_once(
    text,
    '    """Apply AW-only checkout, finance, and payroll rules."""\n',
    '    """Install only AW checkout/financial UI behavior. Qualification and payout are canonical rules."""\n',
    "business policy docstring",
)
write(path, text)

# 5) Legacy Sweet policy is retained only as a no-op import shim.
write(
    "services/sweet_companion_policy_20261028.py",
    '''from __future__ import annotations\n\nfrom services.order_rules import (\n    SWEET_COMPANION_ROLE_ID,\n    SWEET_COMPANION_ROLE_KEY,\n    SWEET_COMPANION_ROLE_LABEL,\n)\n\n\ndef is_sweet_rule_key(rule_key: str) -> bool:\n    key = str(rule_key or "")\n    return key.endswith(("_sweet_female", "_sweet_male", "_sweet_any"))\n\n\ndef install_sweet_companion_policy_20261028() -> None:\n    """Compatibility no-op: Sweet qualification now lives in services.order_rules."""\n    return None\n\n\n__all__ = [\n    "SWEET_COMPANION_ROLE_ID",\n    "SWEET_COMPANION_ROLE_KEY",\n    "SWEET_COMPANION_ROLE_LABEL",\n    "is_sweet_rule_key",\n    "install_sweet_companion_policy_20261028",\n]\n''',
)

# Static safety checks.
rules = read("services/order_rules.py")
aw = read("services/aw_collision_catalog.py")
payout = read("services/one_companion_one_guard_payout.py")
policy = read("services/aw_collision_business_policy.py")
sweet_policy = read("services/sweet_companion_policy_20261028.py")

assert '"aw_collision_receiver": "1565369029005287595"' in rules
assert '"halfcoin_receiver": "1565369317929918554"' in rules
assert 'allowed_roles=HALFCOIN_RECEIVER_ROLES, required_game_roles=()' in rules
assert 'required_game_roles=(*required_game_roles, SWEET_COMPANION_ROLE_KEY)' in rules
assert 'allowed_roles=AW_COLLISION_RECEIVER_ROLES' in aw
assert 'worker_base_rate=1.0' in payout
assert 'farm_halfcoin_120m' in payout and 'farm_halfcoin_360m' in payout
assert '_install_payout_policy' not in policy
assert '_install_rule_policy' not in policy
assert 'order_rules.role_ids_match_requirements =' not in sweet_policy
