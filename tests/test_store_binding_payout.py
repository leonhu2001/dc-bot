from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.staff_models import StaffStoreBinding
from web.app.services.store_binding_payout import is_store_binding_effective_at
from web.app.services.worker_bonus_payout import _calculate_worker_rate


def test_worker_rate_store_binding_is_added_after_normal_cap():
    assert _calculate_worker_rate(
        legacy=False,
        named=False,
        streamed=False,
        previous_bonus=False,
        store_bound=False,
    ) == pytest.approx(0.80)
    assert _calculate_worker_rate(
        legacy=False,
        named=False,
        streamed=False,
        previous_bonus=False,
        store_bound=True,
    ) == pytest.approx(0.83)
    assert _calculate_worker_rate(
        legacy=False,
        named=True,
        streamed=False,
        previous_bonus=False,
        store_bound=True,
    ) == pytest.approx(0.86)
    assert _calculate_worker_rate(
        legacy=False,
        named=True,
        streamed=True,
        previous_bonus=False,
        store_bound=True,
    ) == pytest.approx(0.88)
    assert _calculate_worker_rate(
        legacy=False,
        named=True,
        streamed=True,
        previous_bonus=True,
        store_bound=False,
    ) == pytest.approx(0.87)
    assert _calculate_worker_rate(
        legacy=False,
        named=True,
        streamed=True,
        previous_bonus=True,
        store_bound=True,
    ) == pytest.approx(0.90)


def test_legacy_worker_rate_ignores_store_binding_bonus():
    assert _calculate_worker_rate(
        legacy=True,
        named=True,
        streamed=True,
        previous_bonus=True,
        store_bound=True,
    ) == pytest.approx(0.85)


def test_store_binding_eligibility_uses_historical_db_window():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    StaffStoreBinding.__table__.create(engine)

    close_at = datetime(2026, 10, 10, 12, 0, 0)
    with Session(engine) as db:
        db.add_all(
            [
                StaffStoreBinding(
                    staff_discord_id="active-before-close",
                    status="active",
                    started_at=close_at - timedelta(days=2),
                ),
                StaffStoreBinding(
                    staff_discord_id="ended-after-close",
                    status="ended",
                    started_at=close_at - timedelta(days=2),
                    ended_at=close_at + timedelta(days=1),
                ),
                StaffStoreBinding(
                    staff_discord_id="starts-after-close",
                    status="active",
                    started_at=close_at + timedelta(seconds=1),
                ),
                StaffStoreBinding(
                    staff_discord_id="ended-at-close",
                    status="ended",
                    started_at=close_at - timedelta(days=2),
                    ended_at=close_at,
                ),
                StaffStoreBinding(
                    staff_discord_id="pending-before-close",
                    status="pending",
                    started_at=close_at - timedelta(days=2),
                ),
                StaffStoreBinding(
                    staff_discord_id="starts-at-close",
                    status="active",
                    started_at=close_at,
                ),
            ]
        )
        db.commit()

        assert is_store_binding_effective_at(db, "active-before-close", close_at) is True
        assert is_store_binding_effective_at(db, "ended-after-close", close_at) is True
        assert is_store_binding_effective_at(db, "starts-after-close", close_at) is False
        assert is_store_binding_effective_at(db, "ended-at-close", close_at) is False
        assert is_store_binding_effective_at(db, "pending-before-close", close_at) is False
        assert is_store_binding_effective_at(db, "starts-at-close", close_at) is True
        assert is_store_binding_effective_at(db, "active-before-close", None) is False
