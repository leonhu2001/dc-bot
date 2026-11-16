from __future__ import annotations

from pathlib import Path

from services import orders
from services import quick_order_v2 as quick
from services import quick_order_v2_fixes as fixes
from services import order_runtime
from services import self_service_selection_state as selection_state


ROOT = Path(__file__).resolve().parents[1]


def test_quick_order_groups_read_native_source_without_runtime_patch(monkeypatch):
    seen = []
    monkeypatch.setattr(
        quick,
        "get_live_order_item_groups",
        lambda category: seen.append(category) or ["賽季3x3", "其他服務"],
    )
    assert quick._groups.__module__ == "services.quick_order_v2"
    assert quick._groups("farm") == ["賽季3x3", "其他服務"]
    assert seen == ["farm"]
    assert [item.label for item in quick._options("farm")] == ["賽季3x3", "其他服務"]


def test_fixed_farm_3x3_group_offers_four_boxes_and_contract():
    groups = orders.get_live_order_item_groups("farm")
    assert groups.count("賽季3x3") == 1
    assert "命運契約" not in groups
    details = orders.get_order_item_details_for_group("farm", "賽季3x3")
    # One second-level 3x3 group offers exact priced configurations; the
    # website may equivalently show the normal plan and two extra toggles.
    assert [detail["rule_key"] for detail in details] == [
        "farm_season_3x3_normal",
        "farm_season_3x3_dc_skin",
        "farm_season_3x3_dc_loss",
        "farm_season_3x3_dc_skin_loss",
        "farm_season_3x3_contract",
    ]
    assert [detail["label"] for detail in details] == [
        "3×3安全箱",
        "3×3安全箱＋外觀",
        "3×3安全箱＋包損",
        "3×3安全箱＋外觀＋包損",
        "命運契約",
    ]


def test_discord_and_web_import_same_unpatched_resolver():
    # These modules import the resolver directly. They must all own the
    # exact same callable without a delayed setup_hook monkey patch.
    assert order_runtime.get_order_item_details_for_group is orders.get_order_item_details_for_group
    assert selection_state.get_order_item_details_for_group is orders.get_order_item_details_for_group

    fixes.install_quick_order_v2_fixes(None)
    assert order_runtime.get_order_item_details_for_group is orders.get_order_item_details_for_group
    assert selection_state.get_order_item_details_for_group is orders.get_order_item_details_for_group

    source = (ROOT / "services/quick_order_v2_fixes.py").read_text(encoding="utf-8")
    assert "_ORIGINAL_DETAILS_RESOLVER" not in source
    assert "_install_canonical_group_resolver" not in source
    assert "orders.get_order_item_details_for_group =" not in source
    assert "order_runtime.get_order_item_details_for_group =" not in source
    assert "selection_state.get_order_item_details_for_group =" not in source
    quick_source = (ROOT / "services/quick_order_v2.py").read_text(encoding="utf-8")
    assert "return get_live_order_item_groups(category)" in quick_source


def test_internal_service_labels_keep_original_fullwidth_separator():
    assert fixes._normalized_label("倒子彈｜500M") == "倒子彈｜500M"
    assert fixes._normalized_label("撞車｜500M") == "撞車｜500M"
    assert fixes._normalized_key("倒子彈|500M") == fixes._normalized_key("倒子彈｜500M")


def test_semantically_equal_group_labels_resolve_same_detail_keys():
    category = "farm"
    for label in ("賽季3x3", "賽季３×３", "賽季３x３"):
        assert [
            detail["rule_key"]
            for detail in orders.get_order_item_details_for_group(category, label)
        ] == list(orders._FARM_3X3_RULE_ORDER)


def test_custom_order_still_supports_four_headcounts_with_one_rule_key():
    details = orders.get_order_item_details_for_group("custom", "自訂")
    assert [detail["value"] for detail in details] == [
        "players_1", "players_2", "players_3", "players_4",
    ]
    assert len({detail["rule_key"] for detail in details}) == 1
