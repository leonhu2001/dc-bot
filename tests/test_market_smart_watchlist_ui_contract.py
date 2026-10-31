from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "web" / "app" / "static" / "js" / "pages" / "game_market_live.js"


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_market_list_reads_shared_watchlist_from_notifications_surface():
    source = _source()

    assert "replace(/\\/market\\/?$/, '/notifications')" in source
    assert ".game-notification-watch[href*=\"/market/items/\"]" in source
    assert "credentials: 'same-origin'" in source
    assert "favorites.add(itemKey)" in source
    assert "★ 收藏" in source


def test_default_smart_sort_prioritizes_favorite_and_signal_rows():
    source = _source()

    assert "const smartSortEnabled = requestedSort === '' || requestedSort === 'name'" in source
    assert "favorite && signals.hasSignal" in source
    assert "signals.abnormalDown" in source
    assert "signals.restock" in source
    assert "signals.abnormalUp" in source
    assert "listHost.appendChild(row)" in source
    assert "智慧排序" in source


def test_market_quick_filters_cover_favorites_anomalies_and_restock():
    source = _source()

    assert "★ 只看收藏" in source
    assert "⚠️ 只看異常" in source
    assert "📦 只看疑似補貨" in source
    assert "activeQuickFilter === 'favorites'" in source
    assert "activeQuickFilter === 'abnormal'" in source
    assert "activeQuickFilter === 'restock'" in source


def test_market_filters_compose_with_caliber_filter_instead_of_overwriting_it():
    source = _source()

    assert "const categoryMatches = !activeCategory || rowCategory === activeCategory" in source
    assert "row.hidden = !(categoryMatches && rowMatchesQuickFilter(row))" in source
    assert "suffixes.join(' · ')" in source
