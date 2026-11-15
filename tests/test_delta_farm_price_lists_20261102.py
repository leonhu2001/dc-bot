from __future__ import annotations

from pathlib import Path

from services import quick_order_v2_price_lists as price_lists
from services.order_rules import ORDER_RULES


def test_delta_farm_price_list_has_owner_approved_four_items() -> None:
    labels = [str(plan["label"]) for plan in price_lists.DELTA_FARM_PRICE_LISTS.values()]
    assert labels == [
        "AW子彈代撞",
        "守夜人口風琴",
        "代解部門任務",
        "3×3安全箱",
    ]


def test_delta_farm_aw_collision_prices_match_source_copy() -> None:
    text = str(price_lists.DELTA_FARM_PRICE_LISTS["aw_collision"]["text"])
    for fragment in (
        "1～100 發",
        "每發 5T",
        "101～500 發",
        "每發 4.5T",
        "501 發以上",
        "每發 4T",
    ):
        assert fragment in text
    assert "｜" not in text
    assert "```text" in text


def test_delta_farm_night_population_copy_matches_source() -> None:
    text = str(price_lists.DELTA_FARM_PRICE_LISTS["night_population"]["text"])
    assert "800T" in text
    assert "3 天" in text
    assert "登入前會通知" in text


def test_delta_farm_department_mission_copy_matches_source() -> None:
    text = str(price_lists.DELTA_FARM_PRICE_LISTS["department_mission"]["text"])
    for fragment in (
        "等級 1～3",
        "25T / 聲望",
        "等級 3～4",
        "40T / 聲望",
        "等級 1→2",
        "20 聲望",
        "等級 2→3",
        "等級 3→4",
        "30 聲望",
        "兩週內結單",
        "包損耗 +500T",
    ):
        assert fragment in text
    assert "｜" not in text


def test_delta_farm_3x3_uses_static_image_with_cache_busting() -> None:
    plan = price_lists.DELTA_FARM_PRICE_LISTS["safe_box_3x3"]
    assert plan["image"] == "order_panels/delta_farm_3x3.png"

    embed = price_lists._delta_farm_embed("safe_box_3x3")
    image_url = str(embed.image.url)
    assert image_url.startswith(
        "https://mowanentertainment.com/static/order_panels/delta_farm_3x3.png?v="
    )


def test_delta_farm_s12_prices_match_price_sheet() -> None:
    expected = {
        "farm_season_3x3_normal": 5500,
        "farm_season_3x3_dc_loss": 6000,
        "farm_season_3x3_dc_skin": 8000,
        "farm_season_3x3_dc_skin_loss": 8500,
        "farm_season_3x3_contract": 600,
    }
    for key, price in expected.items():
        assert ORDER_RULES[key].price == price

    regular = ORDER_RULES["farm_season_3x3_normal"]
    assert regular.staff_adjustments == {"skin": 2500, "loss_cover": 500}

    copy = price_lists.DELTA_FARM_PRICE_LISTS["safe_box_3x3"]["text"]
    for amount in ("S12", "5500T", "8000T", "＋500T", "−500T", "600T"):
        assert amount in copy


def test_season_3x3_image_is_in_deployed_public_panel_assets() -> None:
    script = Path("scripts/deploy_main.ps1").read_text(encoding="utf-8")
    assert '"delta_farm_3x3.png"' in script
    assert "web/app/static/order_panels" in script


def test_delta_farm_prices_remain_approved_but_category_is_not_in_price_list_ui() -> None:
    assert [c[0] for c in price_lists.DELTA_PRICE_LIST_CATEGORIES] == [
        "desktop", "mobile", "fun"
    ]
    category_view = price_lists.DeltaPriceListView()
    assert [item.value for item in category_view.children[0].options] == [
        "desktop", "mobile", "fun"
    ]
    # Even a stale private farm category selection cannot regenerate its
    # retired second-level picker. Data and actual ordering are untouched.
    assert not any(
        isinstance(child, price_lists.DeltaFarmPriceListSelect)
        for child in price_lists.DeltaPriceListView(category="farm").children
    )
    assert len(price_lists.DELTA_FARM_PRICE_LISTS) == 4
