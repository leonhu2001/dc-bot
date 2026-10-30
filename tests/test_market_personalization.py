from datetime import datetime, timedelta, timezone

from services.market.personalization import MarketPersonalizationRepository
from services.market.providers.base import MarketSourceItem, MarketSourceSnapshot
from services.market.storage import MarketRepository
from services.market.worker import _evaluate_fresh_alerts


def _repositories(tmp_path):
    market = MarketRepository(f"sqlite:///{tmp_path / 'market.db'}")
    market.create_all()
    personalization = MarketPersonalizationRepository(market)
    personalization.create_all()
    return market, personalization


def _store_price(market: MarketRepository, at: datetime, price: int) -> None:
    market.store_snapshot(
        MarketSourceSnapshot(
            source_name="test-tw-source",
            game_key="delta_force",
            fetched_at=at,
            source_updated_at=at,
            items=(
                MarketSourceItem(
                    source_item_id="m995",
                    name="5.56x45 M995",
                    price=price,
                    category="ammo",
                    tier=6,
                ),
            ),
        )
    )


def test_watchlist_is_idempotent_and_user_scoped(tmp_path):
    _, personalization = _repositories(tmp_path)

    assert personalization.set_watched("user-1", "delta_force", "m995", watched=True)
    assert personalization.set_watched("user-1", "delta_force", "m995", watched=True)
    assert personalization.is_watched("user-1", "delta_force", "m995") is True
    assert personalization.is_watched("user-2", "delta_force", "m995") is False

    rows = personalization.list_watchlist("user-1", "delta_force")
    assert [row.item_key for row in rows] == ["m995"]

    assert personalization.set_watched("user-1", "delta_force", "m995", watched=False) is False
    assert personalization.list_watchlist("user-1", "delta_force") == ()


def test_price_alert_triggers_only_on_false_to_true_crossing(tmp_path):
    _, personalization = _repositories(tmp_path)
    alert = personalization.create_alert(
        "user-1",
        "delta_force",
        "m995",
        condition_type="below",
        target_price=100,
    )
    at = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)

    assert personalization.evaluate_alerts("delta_force", {"m995": 120}, evaluated_at=at) == ()

    first = personalization.evaluate_alerts(
        "delta_force", {"m995": 90}, evaluated_at=at + timedelta(minutes=5)
    )
    assert len(first) == 1
    assert first[0].alert_id == alert.id
    assert first[0].current_price == 90

    assert personalization.evaluate_alerts(
        "delta_force", {"m995": 80}, evaluated_at=at + timedelta(minutes=10)
    ) == ()

    assert personalization.evaluate_alerts(
        "delta_force", {"m995": 110}, evaluated_at=at + timedelta(minutes=15)
    ) == ()

    second = personalization.evaluate_alerts(
        "delta_force", {"m995": 95}, evaluated_at=at + timedelta(minutes=20)
    )
    assert len(second) == 1

    stored = personalization.list_alerts("user-1", "delta_force")[0]
    assert stored.condition_met is True
    assert stored.last_price == 95
    assert stored.last_triggered_at == at + timedelta(minutes=20)


def test_alert_mutations_are_owner_scoped(tmp_path):
    _, personalization = _repositories(tmp_path)
    alert = personalization.create_alert(
        "owner",
        "delta_force",
        "m995",
        condition_type="above",
        target_price=5000,
    )

    assert personalization.set_alert_enabled("other-user", alert.id, enabled=False) is False
    assert personalization.delete_alert("other-user", alert.id) is False

    owner_alert = personalization.list_alerts("owner", "delta_force")[0]
    assert owner_alert.enabled is True

    assert personalization.set_alert_enabled("owner", alert.id, enabled=False) is True
    assert personalization.list_alerts("owner", "delta_force")[0].enabled is False
    assert personalization.delete_alert("owner", alert.id) is True
    assert personalization.list_alerts("owner", "delta_force") == ()


def test_worker_alert_evaluation_skips_stale_market(tmp_path, monkeypatch):
    market, personalization = _repositories(tmp_path)
    old = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=2)
    _store_price(market, old, 90)
    personalization.create_alert(
        "user-1",
        "delta_force",
        "m995",
        condition_type="below",
        target_price=100,
    )
    monkeypatch.setenv("MARKET_STALE_SECONDS", "900")

    assert _evaluate_fresh_alerts(
        repository=market,
        personalization=personalization,
        game_key="delta_force",
    ) == 0

    alert = personalization.list_alerts("user-1", "delta_force")[0]
    assert alert.last_evaluated_at is None
    assert alert.last_triggered_at is None
