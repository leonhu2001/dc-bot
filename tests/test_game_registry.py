from services.game_registry import get_game_feature_cards, get_game_hub
from services.market.public_snapshot import get_public_market_snapshot


def test_delta_force_game_hub_exposes_price_tracking_only():
    game = get_game_hub("delta-force")

    assert game is not None
    assert game.key == "delta_force"
    assert game.market_title == "三角洲子彈行情"
    assert game.has_news is False
    assert game.has_notifications is False

    cards = get_game_feature_cards(game)
    assert [card["key"] for card in cards] == ["market"]
    assert cards[0]["href"] == "/games/delta-force/market"


def test_unknown_game_does_not_create_implicit_hub():
    assert get_game_hub("not-a-game") is None


def test_market_snapshot_never_fabricates_prices_before_source_is_ready():
    snapshot = get_public_market_snapshot("delta_force")

    assert snapshot.status == "source_pending"
    assert snapshot.recommended_item is None
    assert snapshot.items == ()
    assert snapshot.message == "行情準備中。"
