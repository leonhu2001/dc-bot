from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_market_item_detail_uses_real_history_maturity_rules():
    template = _read("web/app/templates/game_market_item.html")
    script = _read("web/app/static/js/pages/game_market_item.js")
    stylesheet = _read("web/app/static/css/pages/game_market_item.css")

    assert "data-market-change-24h" in template
    assert "data-market-range-24h" in template
    assert "data-market-average-7d" in template
    assert "data-market-range-7d" in template
    assert "data-market-coverage" in template
    assert "history?limit=5000" in template
    assert "data-market-restock-card" in template
    assert "Web Push 已正式啟用" not in template

    assert 'timeZone: "Asia/Taipei"' in script
    assert "baselineGap <= 6 * HOUR" in script
    assert "baselineSpan >= 20" in script
    assert "totalCoverage >= 6 * 24" in script
    assert "market-item-chart-average-line" in script
    assert "formatPrice(average)" in script

    assert ".market-item-chart-average-line" in stylesheet
    assert ".market-item-chart-axis-label" in stylesheet
    assert ".market-item-chart-point" in stylesheet


def test_market_provider_example_is_fail_closed_until_database_is_configured():
    env_example = _read("web/.env.example")

    assert "# Verified Taiwan/Garena public reader: MARKET_PROVIDER=852941-tw" in env_example
    assert "\nMARKET_PROVIDER=\n" in env_example


def test_market_summary_is_integrated_into_chart_without_duplicate_price_cards():
    template = _read("web/app/templates/game_market_item.html")
    script = _read("web/app/static/js/pages/game_market_item.js")
    stylesheet = _read("web/app/static/css/pages/game_market_item.css")
    assert 'class="market-item-stats"' not in template
    assert template.count('data-market-summary') == 1
    assert template.index('data-market-chart') < template.index('data-market-summary') < template.index('data-market-chart-stage')
    for binding in (
        "data-market-change-24h", "data-market-change-24h-note",
        "data-market-range-24h", "data-market-average-7d",
        "data-market-range-7d", "data-market-coverage",
        "data-market-coverage-note",
    ):
        assert binding in template
    assert 'data-market-chart-last' not in template
    assert 'data-market-chart-low' not in template
    assert 'data-market-chart-high' not in template
    assert 'data-market-chart-avg' not in template
    assert 'data-market-chart-count' not in template
    assert 'data-market-chart-kpis' not in template
    assert 'chartKpis' not in script
    assert ".market-item-chart-kpis[data-market-summary]" in stylesheet
