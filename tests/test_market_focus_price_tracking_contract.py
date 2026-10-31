from pathlib import Path

from services.game_registry import get_game_feature_cards, get_game_hub


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_delta_force_web_product_is_price_tracking_only():
    game = get_game_hub("delta-force")
    assert game is not None
    assert game.has_market is True
    assert game.has_news is False
    assert game.has_notifications is False

    cards = get_game_feature_cards(game)
    assert [card["key"] for card in cards] == ["market"]

    delta_template = _read("web/app/templates/game_delta_force.html")
    market_template = _read("web/app/templates/game_market.html")
    hub_template = _read("web/app/templates/game_hub.html")

    assert "BULLET MARKET" in delta_template
    assert "三角洲消息" not in delta_template
    assert "通知中心" not in delta_template
    assert "game.news_title" not in market_template
    assert "game.notifications_title" not in market_template
    assert "消息與通知" not in hub_template


def test_market_server_fallback_never_renders_tier_six_button():
    template = _read("web/app/templates/game_market.html")
    script = _read("web/app/static/js/pages/game_market_live.js")

    assert ">4級</a>" in template
    assert ">5級</a>" in template
    assert ">6級</a>" not in template
    assert "tier >= 4 && tier <= 5" in script
    assert "tier <= 10" not in script


def test_item_detail_exposes_restock_radar_without_legacy_explainer():
    template = _read("web/app/templates/game_market_item.html")
    script = _read("web/app/static/js/pages/game_market_item_focus.js")

    assert "data-market-restock-card" in template
    assert "下次預估" in template
    assert "可信度" in template
    assert "歷史樣本" in template
    assert "時間抖動" in template
    assert "資料怎麼看" not in template
    assert "data-market-overview-url" in template
    assert "DOMParser" in script
    assert "data-market-row" in script


def test_market_health_exposes_prediction_backtest_and_dm_delivery_metrics():
    source = _read("web/app/services/market_health.py")

    assert '"prediction_count"' in source
    assert '"scheduled_forecasts"' in source
    assert '"resolved_forecasts"' in source
    assert '"forecast_mae_minutes"' in source
    assert '"restock_dm"' in source
    assert "func.abs(MarketRestockForecast.error_minutes)" in source
    assert 'MarketRestockDelivery.status == status' in source
