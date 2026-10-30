from datetime import datetime, timezone

import pytest

from services.market.provider_registry import build_configured_provider
from services.market.providers.base import MarketSourceUnavailable
from services.market.providers.public_852941 import (
    Public852941Provider,
    _build_snapshot,
)


def _last_updated():
    return {
        "last_updated": 437884,
        "latest_market_time": "2026-10-30 23:34:40",
        "snapshot_group_time": "2026-10-30 23:34:40",
        "status": "success",
    }


def _dashboard():
    return {
        "categories": [".300BLK", "5.56x45mm"],
        "data": {
            ".300BLK": [
                {
                    "bullet_name": ".300BLK_3",
                    "current_price": 692,
                    "tier": 3,
                    "trade_score": 4.3,
                    "safety_gate": "CAUTION",
                },
                {
                    "bullet_name": ".300BLK_4",
                    "current_price": 2352,
                    "tier": 4,
                },
            ],
            "5.56x45mm": [
                {
                    "bullet_name": "5.56x45mm_6",
                    "current_price": 5642,
                    "tier": 6,
                }
            ],
        },
        "score_config": {"anything": "ignored"},
        "status": "success",
    }


def test_852941_payload_builds_normalized_taiwan_snapshot():
    fetched_at = datetime(2026, 10, 30, 15, 35, tzinfo=timezone.utc)
    snapshot = _build_snapshot(
        game_key="delta_force",
        last_updated_payload=_last_updated(),
        dashboard_payload=_dashboard(),
        fetched_at=fetched_at,
    )

    assert snapshot.source_name == "852941-tw-public"
    assert snapshot.game_key == "delta_force"
    assert snapshot.fetched_at == fetched_at
    assert snapshot.source_updated_at == datetime(2026, 10, 30, 15, 34, 40, tzinfo=timezone.utc)
    assert [(item.source_item_id, item.name, item.price, item.category, item.tier) for item in snapshot.items] == [
        (".300BLK_3", ".300BLK 3級", 692, ".300BLK", 3),
        (".300BLK_4", ".300BLK 4級", 2352, ".300BLK", 4),
        ("5.56x45mm_6", "5.56x45mm 6級", 5642, "5.56x45mm", 6),
    ]


def test_852941_payload_skips_invalid_rows_but_keeps_valid_market():
    dashboard = _dashboard()
    dashboard["data"][".300BLK"].extend(
        [
            {"bullet_name": "", "current_price": 100, "tier": 3},
            {"bullet_name": "bad-zero", "current_price": 0, "tier": 3},
            {"bullet_name": "bad-text", "current_price": "x", "tier": 3},
        ]
    )

    snapshot = _build_snapshot(
        game_key="delta_force",
        last_updated_payload=_last_updated(),
        dashboard_payload=dashboard,
    )

    assert len(snapshot.items) == 3


def test_852941_payload_rejects_unhealthy_or_unsupported_source():
    bad_last = _last_updated()
    bad_last["status"] = "error"
    with pytest.raises(MarketSourceUnavailable):
        _build_snapshot(
            game_key="delta_force",
            last_updated_payload=bad_last,
            dashboard_payload=_dashboard(),
        )

    with pytest.raises(MarketSourceUnavailable):
        _build_snapshot(
            game_key="other_game",
            last_updated_payload=_last_updated(),
            dashboard_payload=_dashboard(),
        )


def test_provider_registry_builds_852941_only_when_explicitly_configured(monkeypatch):
    monkeypatch.delenv("MARKET_PROVIDER", raising=False)
    assert build_configured_provider() is None

    monkeypatch.setenv("MARKET_PROVIDER", "852941-tw")
    provider = build_configured_provider()
    assert isinstance(provider, Public852941Provider)
