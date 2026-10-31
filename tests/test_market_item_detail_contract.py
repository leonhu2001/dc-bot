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
    assert "history?limit=1000" in template
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
