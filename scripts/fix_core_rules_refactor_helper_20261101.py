from pathlib import Path

path = Path("scripts/core_rules_refactor_20261101.py")
text = path.read_text(encoding="utf-8")

# Two sweet builders contain the same old line: the first is legacy/history,
# the second is the canonical selectable sweet builder.
old = '''text = replace_once(text, '        required_game_roles=(*required_game_roles, SWEET_COMPANION_ROLE_KEY),\\n', '        required_game_roles=required_game_roles,\\n', "legacy sweet helper")
text = replace_once(text, '        required_game_roles=(*required_game_roles, SWEET_COMPANION_ROLE_KEY),\\n', '        required_game_roles=required_game_roles,\\n        required_roles=(SWEET_COMPANION_ROLE_KEY,),\\n', "canonical sweet helper")
'''
new = '''sweet_helper = '        required_game_roles=(*required_game_roles, SWEET_COMPANION_ROLE_KEY),\\n'
if text.count(sweet_helper) != 2:
    raise RuntimeError(f"sweet helpers: expected 2 matches, got {text.count(sweet_helper)}")
text = text.replace(sweet_helper, '        required_game_roles=required_game_roles,\\n', 1)
text = text.replace(sweet_helper, '        required_game_roles=required_game_roles,\\n        required_roles=(SWEET_COMPANION_ROLE_KEY,),\\n', 1)
'''
assert text.count(old) == 1
text = text.replace(old, new, 1)

# Keep PriceResult keyword-based so the refactor is resilient to dataclass order.
old = '        return PriceResult(base_amount, 0, 0, base_amount, qty, 1, False, (f"AW代撞｜{aw_plan[\'short_label\']}｜{aw_plan[\'rate_text\']}T/發",))\\n'
new = '''        return PriceResult(\\n            base_amount=base_amount,\\n            specify_fee=0,\\n            staff_adjustment_amount=0,\\n            total_amount=base_amount,\\n            service_quantity=qty,\\n            required_staff_count=1,\\n            free_specify_fee=False,\\n            details=(f"AW代撞｜{aw_plan['short_label']}｜{aw_plan['rate_text']}T/發",),\\n        )\\n'''
assert text.count(old) == 1
text = text.replace(old, new, 1)

# Current audit source uses eight spaces here, not twelve.
old = '''text = replace_once(text, '            role_id = ROLE_IDS.get(role_key)\\n', '            role_id = all_role_ids.get(role_key)\\n', "audit map")'''
new = '''text = replace_once(text, '        role_id = ROLE_IDS.get(role_key)\\n', '        role_id = all_role_ids.get(role_key)\\n', "audit map")'''
assert text.count(old) == 1
text = text.replace(old, new, 1)

# The AW plan regex consumes the local credential placeholder; explicitly put
# that UI-only constant back into the replacement text.
old = '''text = sub_once(text, r"AW_RULE_KEYS = \\(.*?AW_COLLISION_PLANS: dict\\[str, dict\\[str, Any\\]\\] = \\{.*?\\n\\}\\n", 'AW_RULE_KEYS = tuple(AW_COLLISION_PRICING_BY_RULE)\\nAW_COLLISION_PLANS: dict[str, dict[str, Any]] = {key: dict(plan) for key, plan in AW_COLLISION_PRICING_BY_RULE.items()}\\n', "AW plans")'''
new = '''text = sub_once(text, r"AW_RULE_KEYS = \\(.*?AW_COLLISION_PLANS: dict\\[str, dict\\[str, Any\\]\\] = \\{.*?\\n\\}\\n", 'AW_RULE_KEYS = tuple(AW_COLLISION_PRICING_BY_RULE)\\nCREDENTIAL_NOTE_PLACEHOLDER = (\\n    "例如 Steam、Garena、Google 登入、其他登入注意事項；請補充安全箱格數"\\n)\\nAW_COLLISION_PLANS: dict[str, dict[str, Any]] = {key: dict(plan) for key, plan in AW_COLLISION_PRICING_BY_RULE.items()}\\n', "AW plans")'''
assert text.count(old) == 1, "AW plan replacement statement changed"
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("HELPER_PATCHED")
