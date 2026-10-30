from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_market_items_api_exposes_7d_value_signal():
    source = (ROOT / "web/app/routers/game_tools.py").read_text(encoding="utf-8")

    assert '"vs_7d_avg_pct": item.vs_7d_avg_pct' in source
    assert '"value_asc"' in source
    assert '"value_desc"' in source


def test_market_list_renders_7d_value_signal_on_desktop_and_mobile():
    template = (ROOT / "web/app/templates/game_market.html").read_text(encoding="utf-8")
    css = (ROOT / "web/app/static/css/pages/game_market.css").read_text(encoding="utf-8")

    assert 'value="value_asc"' in template
    assert 'value="value_desc"' in template
    assert "item.vs_7d_avg_pct" in template
    assert "game-market-value-badge" in template
    assert "game-market-mobile-value" in template
    assert ".game-market-value-badge" in css
    assert ".game-market-mobile-value" in css
