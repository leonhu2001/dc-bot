from pathlib import Path

path = Path("scripts/core_rules_refactor_20261101.py")
text = path.read_text(encoding="utf-8")

old = '''text = replace_once(text, '        required_game_roles=(*required_game_roles, SWEET_COMPANION_ROLE_KEY),\\n', '        required_game_roles=required_game_roles,\\n', "legacy sweet helper")
text = replace_once(text, '        required_game_roles=(*required_game_roles, SWEET_COMPANION_ROLE_KEY),\\n', '        required_game_roles=required_game_roles,\\n        required_roles=(SWEET_COMPANION_ROLE_KEY,),\\n', "canonical sweet helper")
'''
new = '''sweet_helper = '        required_game_roles=(*required_game_roles, SWEET_COMPANION_ROLE_KEY),\\n'
if text.count(sweet_helper) != 2:
    raise RuntimeError(f"sweet helpers: expected 2 matches, got {text.count(sweet_helper)}")
text = text.replace(sweet_helper, '        required_game_roles=required_game_roles,\\n', 1)
text = text.replace(sweet_helper, '        required_game_roles=required_game_roles,\\n        required_roles=(SWEET_COMPANION_ROLE_KEY,),\\n', 1)
'''
if text.count(old) != 1:
    raise RuntimeError(f"sweet helper patch target count={text.count(old)}")
text = text.replace(old, new, 1)

old_price = '        return PriceResult(base_amount, 0, 0, base_amount, qty, 1, False, (f"AW代撞｜{aw_plan[\'short_label\']}｜{aw_plan[\'rate_text\']}T/發",))\\n'
new_price = '''        return PriceResult(\\n            base_amount=base_amount,\\n            specify_fee=0,\\n            staff_adjustment_amount=0,\\n            total_amount=base_amount,\\n            service_quantity=qty,\\n            required_staff_count=1,\\n            free_specify_fee=False,\\n            details=(f"AW代撞｜{aw_plan['short_label']}｜{aw_plan['rate_text']}T/發",),\\n        )\\n'''
if text.count(old_price) != 1:
    raise RuntimeError(f"AW PriceResult patch target count={text.count(old_price)}")
text = text.replace(old_price, new_price, 1)

old_audit = '''text = replace_once(text, '            role_id = ROLE_IDS.get(role_key)\\n', '            role_id = all_role_ids.get(role_key)\\n', "audit map")'''
new_audit = '''text = replace_once(text, '        role_id = ROLE_IDS.get(role_key)\\n', '        role_id = all_role_ids.get(role_key)\\n', "audit map")'''
if text.count(old_audit) != 1:
    raise RuntimeError(f"audit helper patch target count={text.count(old_audit)}")
text = text.replace(old_audit, new_audit, 1)

old_aw_plans = '''    'AW_RULE_KEYS = tuple(AW_COLLISION_PRICING_BY_RULE)\\nAW_COLLISION_PLANS: dict[str, dict[str, Any]] = {key: dict(plan) for key, plan in AW_COLLISION_PRICING_BY_RULE.items()}\\n',
    "AW plans",
)'''
new_aw_plans = '''    'AW_RULE_KEYS = tuple(AW_COLLISION_PRICING_BY_RULE)\\nCREDENTIAL_NOTE_PLACEHOLDER = (\\n    "例如 Steam、Garena、Google 登入、其他登入注意事項；請補充安全箱格數"\\n)\\nAW_COLLISION_PLANS: dict[str, dict[str, Any]] = {key: dict(plan) for key, plan in AW_COLLISION_PRICING_BY_RULE.items()}\\n',
    "AW plans",
)'''
if text.count(old_aw_plans) != 1:
    raise RuntimeError(f"AW plan replacement patch target count={text.count(old_aw_plans)}")
text = text.replace(old_aw_plans, new_aw_plans, 1)

path.write_text(text, encoding="utf-8")
print("HELPER_PATCHED")
