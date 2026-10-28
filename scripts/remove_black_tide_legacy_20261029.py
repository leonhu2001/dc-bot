from pathlib import Path


def main() -> None:
    # 1) Canonical source rules: remove the 8 old fixed-seat Black Tide rules.
    path = Path("services/order_rules.py")
    text = path.read_text(encoding="utf-8")
    marker = "# 舊 Black Tide 1～4 人 key 只供已建立訂單／快照回查；新 catalog 不使用。"
    if marker in text:
        start = text.index(marker)
        end = text.index("# ========= APEX Legends 陪玩 =========", start)
        text = (
            text[:start]
            + "# 黑潮爆破新單只保留娛樂陪／技術陪；人數由獨立 1～4 人欄位決定。\n\n\n"
            + text[end:]
        )
        path.write_text(text, encoding="utf-8")

    # 2) Kill the old installer path too, so no future import can recreate them.
    path = Path("services/multi_seat_order_policy_20261028.py")
    text = path.read_text(encoding="utf-8")
    legacy_marker = "_BLACK_TIDE_LEGACY_VARIANTS = ("
    if legacy_marker in text:
        legacy_start = text.index(legacy_marker)
        legacy_end = text.index("\n\n_BLACK_TIDE_CANONICAL = (", legacy_start)
        text = text[:legacy_start] + "_BLACK_TIDE_LEGACY_VARIANTS: tuple = ()" + text[legacy_end:]
    loop_marker = "    for key, label, template_key, staff_count, price in _BLACK_TIDE_LEGACY_VARIANTS:"
    if loop_marker in text:
        loop_start = text.index(loop_marker)
        loop_end = text.index(
            "    for key, label, template_key, price_table in _BLACK_TIDE_CANONICAL:",
            loop_start,
        )
        text = text[:loop_start] + text[loop_end:]
    path.write_text(text, encoding="utf-8")

    # 3) Web storefront gets one canonical Black Tide group with only 2 service types.
    path = Path("web/app/services/order_groups.py")
    text = path.read_text(encoding="utf-8")
    if '"key": "black_tide"' not in text:
        anchor = '''    {
        "key": "oil",
        "category": "delta_desktop_basic",
'''
        block = '''    {
        "key": "black_tide",
        "category": "delta_desktop_basic",
        "label": "黑潮爆破",
        "selector_label": "服務類型",
        "description": "黑潮爆破只選娛樂陪或技術陪；陪玩人數另選 1～4 人。",
        "variants": [
            ("basic_black_tide_entertain", "娛樂陪"),
            ("basic_black_tide_tech", "技術陪"),
        ],
    },

'''
        if anchor not in text:
            raise RuntimeError("web Black Tide insertion anchor not found")
        text = text.replace(anchor, block + anchor, 1)
        path.write_text(text, encoding="utf-8")

    # 4) Regression: active source/UI must never expose old Black Tide seat variants again.
    path = Path("tests/test_companion_count_finish_20261028.py")
    text = path.read_text(encoding="utf-8")
    if "test_black_tide_legacy_seat_variants_are_not_active_rules" not in text:
        text += '''


def test_black_tide_legacy_seat_variants_are_not_active_rules() -> None:
    legacy = {
        f"basic_black_tide_{tier}_{count}"
        for tier in ("entertain", "tech")
        for count in range(1, 5)
    }
    assert legacy.isdisjoint(order_rules.ORDER_RULES)


def test_black_tide_discord_catalog_has_only_service_type_then_count() -> None:
    details = _discord_details("delta_desktop_basic", "黑潮爆破")
    assert [item["label"] for item in details] == ["娛樂陪", "技術陪"]
    assert [item["rule_key"] for item in details] == [
        "basic_black_tide_entertain",
        "basic_black_tide_tech",
    ]
    for item in details:
        rule = order_rules.ORDER_RULES[item["rule_key"]]
        assert rule.required_staff_count == "player_count"
        assert rule.player_count_enabled is True
        assert rule.min_player_count == 1
        assert rule.max_player_count == 4


def test_black_tide_web_catalog_has_only_two_canonical_variants() -> None:
    from web.app.services import order_groups

    group = next(
        item for item in order_groups.get_grouped_order_catalog("delta_desktop_basic")
        if item["key"] == "black_tide"
    )
    assert [item["label"] for item in group["variants"]] == ["娛樂陪", "技術陪"]
    assert [item["rule_key"] for item in group["variants"]] == [
        "basic_black_tide_entertain",
        "basic_black_tide_tech",
    ]
    assert all(item["player_count_enabled"] for item in group["variants"])
    assert all(item["max_player_count"] == 4 for item in group["variants"])
'''
        path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
