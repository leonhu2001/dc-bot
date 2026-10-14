from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Customer-facing descriptions: loyalty belongs only to entertainment services.
replace_once(
    "web/app/services/order_groups.py",
    '        "description": "需同時具備男陪／女陪與三角洲<端遊>身分組；以聊天、娛樂與遊戲體驗為主。",\n',
    '        "description": "需同時具備男陪／女陪與三角洲<端遊>身分組；娛樂陪福利累積 10 個服務小時回饋 1 小時，可於達標當單直接折抵。",\n',
)
replace_once(
    "web/app/services/order_groups.py",
    '        "description": "需同時具備男陪／女陪與三角洲<手遊>身分組；價格與端遊相同。",\n',
    '        "description": "需同時具備男陪／女陪與三角洲<手遊>身分組；價格與端遊相同；娛樂陪福利累積 10 個服務小時回饋 1 小時，可於達標當單直接折抵。",\n',
)
replace_once(
    "web/app/services/order_groups.py",
    '        "description": "需男陪／女陪 + Steam 身分組。",\n',
    '        "description": "需男陪／女陪 + Steam 身分組；娛樂陪福利累積 10 個服務小時回饋 1 小時，可於達標當單直接折抵。",\n',
)

for old, new in [
    (
        '{"key":"valorant_entertain","category":"valorant","label":"特戰英豪｜娛樂陪","selector_label":"模式","description":"需男陪／女陪 + 特戰英豪身分組；買 5 送 1；指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("valorant_entertain_ng","NG"),("valorant_entertain_ranked","積分")]},\n',
        '{"key":"valorant_entertain","category":"valorant","label":"特戰英豪｜娛樂陪","selector_label":"模式","description":"需男陪／女陪 + 特戰英豪身分組；娛樂陪福利：NG 累積 10 個服務小時回饋 1 小時、積分累積 10 個服務局回饋 1 局，達標當單可直接折抵；指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("valorant_entertain_ng","NG"),("valorant_entertain_ranked","積分")]},\n',
    ),
    (
        '{"key":"valorant_ascendant","category":"valorant","label":"特戰英豪｜超凡陪","selector_label":"模式","description":"需特戰英豪身分組 + 超凡／神話／輻能階級；買 5 送 1；指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("valorant_ascendant_ng","NG"),("valorant_ascendant_ranked","積分")]},\n',
        '{"key":"valorant_ascendant","category":"valorant","label":"特戰英豪｜超凡陪","selector_label":"模式","description":"需特戰英豪身分組 + 超凡／神話／輻能階級；指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("valorant_ascendant_ng","NG"),("valorant_ascendant_ranked","積分")]},\n',
    ),
    (
        '{"key":"valorant_immortal","category":"valorant","label":"特戰英豪｜神話陪","selector_label":"模式","description":"需特戰英豪身分組 + 神話／輻能階級；買 5 送 1；指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("valorant_immortal_ng","NG"),("valorant_immortal_ranked","積分")]},\n',
        '{"key":"valorant_immortal","category":"valorant","label":"特戰英豪｜神話陪","selector_label":"模式","description":"需特戰英豪身分組 + 神話／輻能階級；指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("valorant_immortal_ng","NG"),("valorant_immortal_ranked","積分")]},\n',
    ),
    (
        '{"key":"valorant_radiant","category":"valorant","label":"特戰英豪｜輻能陪","selector_label":"模式","description":"需特戰英豪身分組 + 輻能階級；買 5 送 1；指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("valorant_radiant_ng","NG"),("valorant_radiant_ranked","積分")]},\n',
        '{"key":"valorant_radiant","category":"valorant","label":"特戰英豪｜輻能陪","selector_label":"模式","description":"需特戰英豪身分組 + 輻能階級；指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("valorant_radiant_ng","NG"),("valorant_radiant_ranked","積分")]},\n',
    ),
    (
        '{"key":"lol_entertain","category":"lol","label":"英雄聯盟｜娛樂陪","selector_label":"模式","description":"需男陪／女陪 + 英雄聯盟身分組；買 5 送 1；指定每位 +100T，ARAM / NG 2 小時、積分 2 局以上免指定費。","variants":[("lol_entertain_aram","ARAM"),("lol_entertain_ng","NG"),("lol_entertain_ranked","積分")]},\n',
        '{"key":"lol_entertain","category":"lol","label":"英雄聯盟｜娛樂陪","selector_label":"模式","description":"需男陪／女陪 + 英雄聯盟身分組；娛樂陪福利：ARAM / NG 累積 10 個服務小時回饋 1 小時、積分累積 10 個服務局回饋 1 局，達標當單可直接折抵；指定每位 +100T，ARAM / NG 2 小時、積分 2 局以上免指定費。","variants":[("lol_entertain_aram","ARAM"),("lol_entertain_ng","NG"),("lol_entertain_ranked","積分")]},\n',
    ),
    (
        '{"key":"lol_master","category":"lol","label":"英雄聯盟｜大師陪","selector_label":"模式","description":"需英雄聯盟身分組 + 大師／宗師／菁英階級；買 5 送 1；指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("lol_master_ng","NG"),("lol_master_ranked","積分")]},\n',
        '{"key":"lol_master","category":"lol","label":"英雄聯盟｜大師陪","selector_label":"模式","description":"需英雄聯盟身分組 + 大師／宗師／菁英階級；指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("lol_master_ng","NG"),("lol_master_ranked","積分")]},\n',
    ),
    (
        '{"key":"lol_grandmaster","category":"lol","label":"英雄聯盟｜宗師陪","selector_label":"模式","description":"需英雄聯盟身分組 + 宗師／菁英階級；買 5 送 1；指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("lol_grandmaster_ng","NG"),("lol_grandmaster_ranked","積分")]},\n',
        '{"key":"lol_grandmaster","category":"lol","label":"英雄聯盟｜宗師陪","selector_label":"模式","description":"需英雄聯盟身分組 + 宗師／菁英階級；指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("lol_grandmaster_ng","NG"),("lol_grandmaster_ranked","積分")]},\n',
    ),
    (
        '{"key":"lol_elite","category":"lol","label":"英雄聯盟｜菁英陪","selector_label":"模式","description":"需英雄聯盟身分組 + 菁英階級；買 5 送 1；指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("lol_elite_ng","NG"),("lol_elite_ranked","積分")]},\n',
        '{"key":"lol_elite","category":"lol","label":"英雄聯盟｜菁英陪","selector_label":"模式","description":"需英雄聯盟身分組 + 菁英階級；指定每位 +100T，NG 2 小時 / 積分 2 局以上免指定費。","variants":[("lol_elite_ng","NG"),("lol_elite_ranked","積分")]},\n',
    ),
]:
    replace_once("web/app/services/order_groups.py", old, new)

replace_once(
    "web/app/services/order_groups.py",
    '        "description": "需男陪／女陪 + APEX身分組；NG 300T/人/H、積分 350T/人/H；指定每位 +100T，2H 以上免指定費；累積 10H 送 30 分鐘券。",\n',
    '        "description": "需男陪／女陪 + APEX身分組；NG 300T/人/H、積分 350T/人/H；指定每位 +100T，2H 以上免指定費；娛樂陪福利累積 10 個服務小時回饋 1 小時，可於達標當單直接折抵。",\n',
)
for old, new in [
    (
        '        "description": "需 APEX身分組 + 鑽石／大師／頂獵階級；NG 400T/人/H、積分 450T/人/H；指定每位 +100T，2H 以上免指定費；累積 10H 送 30 分鐘券。",\n',
        '        "description": "需 APEX身分組 + 鑽石／大師／頂獵階級；NG 400T/人/H、積分 450T/人/H；指定每位 +100T，2H 以上免指定費。",\n',
    ),
    (
        '        "description": "需 APEX身分組 + 大師／頂獵階級；NG 500T/人/H、積分 550T/人/H；指定每位 +100T，2H 以上免指定費；累積 10H 送 30 分鐘券。",\n',
        '        "description": "需 APEX身分組 + 大師／頂獵階級；NG 500T/人/H、積分 550T/人/H；指定每位 +100T，2H 以上免指定費。",\n',
    ),
    (
        '        "description": "需 APEX身分組 + 頂獵階級；NG 600T/人/H、積分 650T/人/H；指定每位 +100T，2H 以上免指定費；累積 10H 送 30 分鐘券。",\n',
        '        "description": "需 APEX身分組 + 頂獵階級；NG 600T/人/H、積分 650T/人/H；指定每位 +100T，2H 以上免指定費。",\n',
    ),
]:
    replace_once("web/app/services/order_groups.py", old, new)

# Update old regression tests to the new entertainment-only policy.
replace_once(
    "tests/test_apex_pricing_20261012.py",
    '        assert rule.loyalty_benefits_enabled is True\n',
    '        assert rule.loyalty_benefits_enabled is rule_key.startswith("apex_entertain_")\n',
)
replace_once(
    "tests/test_apex_pricing_20261012.py",
    '''def test_apex_loyalty_remains_ten_hours_for_thirty_minute_coupon():\n    policy = loyalty_policy_for_rule("apex_predator_ranked")\n    assert policy is not None\n    assert policy["pricing_type"] == "hourly"\n    assert policy["threshold_units"] == 10.0\n    assert policy["benefit_kind"] == "extra_hours"\n    assert policy["benefit_units"] == 0.5\n    assert policy["benefit_label"] == "+30 分鐘"\n''',
    '''def test_apex_loyalty_only_applies_to_entertainment_at_ten_percent():\n    policy = loyalty_policy_for_rule("apex_entertain_ranked")\n    assert policy is not None\n    assert policy["pricing_type"] == "hourly"\n    assert policy["threshold_units"] == 10.0\n    assert policy["benefit_kind"] == "extra_hours"\n    assert policy["benefit_units"] == 1.0\n    assert policy["benefit_label"] == "+1 小時"\n    assert loyalty_policy_for_rule("apex_predator_ranked") is None\n''',
)
replace_once(
    "tests/test_apex_pricing_20261012.py",
    '''        assert "買 5 送 1" not in group["description"]\n        assert "累積 10H 送 30 分鐘券" in group["description"]\n''',
    '''        assert "買 5 送 1" not in group["description"]\n        assert "累積 10H 送 30 分鐘券" not in group["description"]\n        if group_key == "apex_entertain":\n            assert "累積 10 個服務小時回饋 1 小時" in group["description"]\n            assert "達標當單直接折抵" in group["description"]\n        else:\n            assert "回饋" not in group["description"]\n''',
)

replace_once(
    "tests/test_game_service_rules.py",
    '''def test_same_order_buy_get_is_disabled_and_loyalty_is_enabled():\n    rule = ORDER_RULES["valorant_radiant_ranked"]\n    result = calculate_price(rule, quantity=8, player_count=2)\n    assert rule.price == 400\n    assert result.base_amount == 6400\n    assert result.service_quantity == 8\n    assert rule.loyalty_benefits_enabled is True\n    assert set(get_allowed_role_ids(rule)) == {"1545357782906314782"}\n\n    lol = ORDER_RULES["lol_entertain_aram"]\n    assert lol.price == 300\n    assert lol.unit_label == "H"\n    assert lol.loyalty_benefits_enabled is True\n    assert calculate_price(lol, quantity=8, player_count=1).service_quantity == 8\n''',
    '''def test_same_order_buy_get_is_disabled_and_loyalty_is_entertainment_only():\n    tier_rule = ORDER_RULES["valorant_radiant_ranked"]\n    tier_result = calculate_price(tier_rule, quantity=8, player_count=2)\n    assert tier_rule.price == 400\n    assert tier_result.base_amount == 6400\n    assert tier_result.service_quantity == 8\n    assert tier_rule.loyalty_benefits_enabled is False\n    assert set(get_allowed_role_ids(tier_rule)) == {"1545357782906314782"}\n\n    entertainment_ranked = ORDER_RULES["valorant_entertain_ranked"]\n    assert entertainment_ranked.loyalty_benefits_enabled is True\n    assert calculate_price(\n        entertainment_ranked, quantity=8, player_count=2\n    ).service_quantity == 8\n\n    lol = ORDER_RULES["lol_entertain_aram"]\n    assert lol.price == 300\n    assert lol.unit_label == "H"\n    assert lol.loyalty_benefits_enabled is True\n    assert calculate_price(lol, quantity=8, player_count=1).service_quantity == 8\n''',
)

# Self-delete this one-shot migration mechanism.
(ROOT / "scripts/apply_loyalty_policy_test_copy_fix.py").unlink(missing_ok=True)
(ROOT / ".github/workflows/apply-loyalty-policy-test-copy-fix.yml").unlink(missing_ok=True)
