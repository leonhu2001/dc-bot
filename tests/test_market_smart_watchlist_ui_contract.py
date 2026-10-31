from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "web" / "app" / "static" / "js" / "pages" / "game_market_live.js"
TEMPLATE = ROOT / "web" / "app" / "templates" / "game_market.html"
ROUTER = ROOT / "web" / "app" / "routers" / "game_tools.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_market_list_reads_shared_watchlist_server_side_and_exposes_inline_toggle():
    router = _source(ROUTER)
    template = _source(TEMPLATE)
    script = _source(SCRIPT)

    assert "personalization.list_watchlist(user_id, game_key)" in router
    assert "pin_market_items(" in router
    assert "market_watched_keys=watched_item_keys" in router
    assert 'data-market-watched="{% if is_watched %}1{% else %}0{% endif %}"' in template
    assert "data-market-watch-toggle" in template
    assert "data-market-watch-url" in template
    assert "csrf_token" in script
    assert "body.set('watched', nextWatched ? '1' : '0')" in script
    assert "row.dataset.marketWatched = nextWatched ? '1' : '0'" in script
    assert "replace(/\\/market\\/?$/, '/notifications')" not in script


def test_smart_pinning_reacts_to_inline_favorite_changes_without_page_reload():
    router = _source(ROUTER)
    script = _source(SCRIPT)

    assert "snapshot = filter_market_snapshot(" in router
    assert "items=pin_market_items(" in router
    assert "watched_item_keys=watched_item_keys" in router
    assert "function applySmartPinning()" in script
    assert "if (watched && signals.hasSignal) group = 0" in script
    assert "else if (watched) group = 1" in script
    assert "applySmartPinning();" in script


def test_market_quick_filters_cover_favorites_predictions_anomalies_and_restock():
    source = _source(SCRIPT)

    assert "★ 只看收藏" in source
    assert "⏱ 有補貨預測" in source
    assert "⚠️ 只看異常" in source
    assert "📦 只看疑似補貨" in source
    assert "activeQuickFilter === 'favorites'" in source
    assert "activeQuickFilter === 'prediction'" in source
    assert "activeQuickFilter === 'abnormal'" in source
    assert "activeQuickFilter === 'restock'" in source
    assert "row.dataset.marketWatched === '1'" in source
    assert "row.dataset.marketRestockAt" in source


def test_market_filters_compose_with_caliber_filter_instead_of_overwriting_it():
    source = _source(SCRIPT)

    assert "const categoryMatches = !activeCategory || rowCategory === activeCategory" in source
    assert "row.hidden = !(categoryMatches && rowMatchesQuickFilter(row))" in source
    assert "suffixes.join(' · ')" in source
