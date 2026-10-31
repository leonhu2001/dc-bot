from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_market_overview_discovers_available_tiers_without_losing_query_state():
    template = _read("web/app/templates/game_market.html")
    script = _read("web/app/static/js/pages/game_market_live.js")

    assert "data-market-tier-filters" in template
    assert "game_market_live.js?v=20261031-4" in template
    assert "async function installTierFilters()" in script
    assert "discoveryParams.delete('tier')" in script
    assert "params.set('tier', String(tier))" in script
    assert "new URLSearchParams(window.location.search)" in script
    assert "tiers.forEach" in script


def test_market_item_same_caliber_comparison_uses_read_only_market_api():
    template = _read("web/app/templates/game_market_item.html")
    script = _read("web/app/static/js/pages/game_market_item.js")
    stylesheet = _read("web/app/static/css/pages/game_market_item.css")

    assert "data-market-compare" in template
    assert "data-market-items-url" in template
    assert "data-market-current-category" in template
    assert "data-market-current-item-key" in template
    assert "同口徑比較" in template
    assert "game_market_item.js?v=20261031-2" in template
    assert "game_market_item.css?v=20261031-2" in template

    assert "const loadComparison = async ()" in script
    assert "String(item?.category || \"\").trim() === currentCategory" in script
    assert "String(item?.item_key || \"\").trim() !== currentKey" in script
    assert "encodeURIComponent(String(item.item_key || \"\"))" in script
    assert "比本品" in script
    assert "trade_score" not in script
    assert "safety_gate" not in script

    assert ".market-item-compare" in stylesheet
    assert ".market-item-compare-row" in stylesheet
    assert ".market-item-compare-delta.is-higher" in stylesheet
    assert ".market-item-compare-delta.is-lower" in stylesheet
