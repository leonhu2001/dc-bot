from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from services import quick_order_v2_price_lists as price_lists


ROOT = Path(__file__).resolve().parents[1]
PRICE_SOURCE = ROOT / "services" / "quick_order_v2_price_lists.py"
WEB_ORDER_TEMPLATE = ROOT / "web" / "app" / "templates" / "order_catalog.html"


def test_every_discord_price_list_is_separator_free_and_uses_aligned_blocks() -> None:
    interaction = SimpleNamespace(guild=None)
    rendered = [
        price_lists._valorant_price_list(interaction),
        price_lists._apex_price_list(interaction),
        price_lists._lol_price_list(interaction),
        price_lists._steam_price_list(interaction),
        *(str(plan["text"]) for plan in price_lists.DELTA_MOBILE_PRICE_LISTS.values()),
    ]

    for text in rendered:
        assert "｜" not in text
        assert "```text" in text


def test_price_list_button_title_does_not_use_vertical_separator() -> None:
    source = PRICE_SOURCE.read_text(encoding="utf-8")
    assert 'title=f"📋 {label}・陪玩價目"' in source
    assert 'title=f"📋 {label}｜陪玩價目"' not in source


def test_web_order_catalog_does_not_use_vertical_separators_for_price_layout() -> None:
    source = WEB_ORDER_TEMPLATE.read_text(encoding="utf-8")
    assert "｜" not in source


def test_alignment_helper_accounts_for_full_width_cjk_labels() -> None:
    block = price_lists._aligned_code_block((("NG", "300T"), ("積分", "250T")))
    rows = [line for line in block.splitlines() if line and not line.startswith("```")]
    first_value_column = rows[0].index("300T")
    second_value_column = rows[1].index("250T")

    # Raw string indexes differ because CJK glyphs are double-width, so compare display width.
    first_prefix = rows[0][:first_value_column]
    second_prefix = rows[1][:second_value_column]
    assert price_lists._display_width(first_prefix) == price_lists._display_width(second_prefix)
