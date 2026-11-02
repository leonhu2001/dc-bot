from __future__ import annotations

from services import quick_order_v2_price_lists as price_lists


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
    assert plan["image"] == "price_lists/delta_farm_3x3.jpg"

    embed = price_lists._delta_farm_embed("safe_box_3x3")
    image_url = str(embed.image.url)
    assert image_url.startswith(
        "https://mowanentertainment.com/static/price_lists/delta_farm_3x3.jpg?v="
    )


def test_delta_farm_category_opens_second_level_selector() -> None:
    category_embed = price_lists._delta_category_embed("farm")
    assert category_embed.description == "請選擇要查看的單子。"

    view = price_lists.DeltaPriceListView(category="farm")
    assert any(
        isinstance(child, price_lists.DeltaFarmPriceListSelect)
        for child in view.children
    )

    selector = next(
        child
        for child in view.children
        if isinstance(child, price_lists.DeltaFarmPriceListSelect)
    )
    assert selector.custom_id == "quick_order_v2_delta_farm_price_list"
    assert [option.label for option in selector.options] == [
        "AW子彈代撞",
        "守夜人口風琴",
        "代解部門任務",
        "3×3安全箱",
    ]
