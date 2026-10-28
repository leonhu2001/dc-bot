from __future__ import annotations

import services  # noqa: F401
from services import order_rules, order_runtime
from web.app.routers import admin_order_rules
from web.app.services import order_groups


def _web_group(category: str, key: str) -> dict:
    return next(group for group in order_groups.get_grouped_order_catalog(category) if group["key"] == key)


def test_web_fixed_option_labels_match_current_discord_catalog() -> None:
    desktop = {group["key"]: group for group in order_groups.get_grouped_order_catalog("delta_desktop_basic")}
    assert [row["label"] for row in desktop["exbar_gamble"]["variants"]] == ["縱橫", "萬金淚冠", "天圓地方", "測距儀"]
    assert [row["label"] for row in desktop["bet"]["variants"]] == ["800w", "1000w", "1200w"]
    assert [row["label"] for row in desktop["trial"]["variants"]] == ["777w", "1688w"]
    assert [row["label"] for row in order_runtime.get_order_item_details_for_group("delta_desktop_basic", "賭約單")] == ["800w", "1000w", "1200w"]
    assert [row["label"] for row in order_runtime.get_order_item_details_for_group("delta_desktop_basic", "體驗單")] == ["777w", "1688w"]


def test_web_loyalty_and_apex_copy_matches_authoritative_rules() -> None:
    assert "積分累積 15 個服務局回饋 1 局" in _web_group("valorant", "valorant_entertain")["description"]
    assert "積分累積 15 個服務局回饋 1 局" in _web_group("lol", "lol_entertain")["description"]
    apex_master = _web_group("apex", "apex_master")
    apex_predator = _web_group("apex", "apex_predator")
    assert order_rules.ORDER_RULES["apex_master_ng"].price == 480
    assert order_rules.ORDER_RULES["apex_master_ranked"].price == 530
    assert order_rules.ORDER_RULES["apex_predator_ng"].price == 580
    assert order_rules.ORDER_RULES["apex_predator_ranked"].price == 630
    assert "NG 480T/人/H、積分 530T/人/H" in apex_master["description"]
    assert "NG 580T/人/H、積分 630T/人/H" in apex_predator["description"]


def test_web_manager_hides_historical_fixed_seat_rules() -> None:
    for key in ("basic_tech_secret_double", "basic_entertain_double", "valorant_sweet_female_single", "valorant_sweet_female_double"):
        assert key in order_rules.ORDER_RULES
        assert admin_order_rules._is_admin_editable_rule(key) is False
    for key in ("basic_tech_secret_single", "basic_entertain_single", "valorant_sweet_female", "apex_master_ng"):
        assert key in order_rules.ORDER_RULES
        assert admin_order_rules._is_admin_editable_rule(key) is True
