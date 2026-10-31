from pathlib import Path

from services.market.scope import (
    market_item_enabled,
    maximum_market_tier,
    minimum_market_tier,
)


ROOT = Path(__file__).resolve().parents[1]


def test_delta_force_tracks_only_tradable_tier_four_and_five():
    assert minimum_market_tier("delta_force") == 4
    assert maximum_market_tier("delta_force") == 5
    assert market_item_enabled("delta_force", 1) is False
    assert market_item_enabled("delta_force", 2) is False
    assert market_item_enabled("delta_force", 3) is False
    assert market_item_enabled("delta_force", 4) is True
    assert market_item_enabled("delta_force", 5) is True
    assert market_item_enabled("delta_force", 6) is False
    assert market_item_enabled("delta_force", None) is True


def test_other_games_keep_existing_tier_behavior():
    assert minimum_market_tier("other_game") is None
    assert maximum_market_tier("other_game") is None
    assert market_item_enabled("other_game", 1) is True
    assert market_item_enabled("other_game", 6) is True


def test_non_tradable_tiers_are_filtered_before_storage_alerts_and_public_snapshot():
    ingest = (ROOT / "services" / "market" / "ingest.py").read_text(encoding="utf-8")
    worker = (ROOT / "services" / "market" / "worker.py").read_text(encoding="utf-8")
    prediction = (ROOT / "services" / "market" / "restock_prediction.py").read_text(encoding="utf-8")
    snapshot = (ROOT / "services" / "market" / "public_snapshot.py").read_text(encoding="utf-8")

    assert "if market_item_enabled(snapshot.game_key, item.tier)" in ingest
    assert "if market_item_enabled(game_key, item.tier)" in worker
    assert "maximum_market_tier(clean_game)" in prediction
    assert "MarketItem.tier <= maximum_tier" in prediction
    assert "if market_item_enabled(clean_game_key, item.tier)" in snapshot


def test_market_ui_hides_standalone_single_item_anomaly_bar_and_non_tradable_filters():
    script = (ROOT / "web" / "app" / "static" / "js" / "pages" / "game_market_live.js").read_text(
        encoding="utf-8"
    )

    assert "removeStandaloneAnomalyBar" in script
    assert "label.includes('單品異常')" in script
    assert "tier >= 4 && tier <= 5" in script
