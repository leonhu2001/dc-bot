from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, String, create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Session

from shared.db import ensure_worker_payout_constraints


class _TestBase(DeclarativeBase):
    pass


class _PendingWorkerPayout(_TestBase):
    __tablename__ = "worker_payouts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, nullable=False)
    worker_discord_id = Column(String(32), nullable=False)
    final_payout = Column(Integer, nullable=False, default=0)


def _create_minimal_worker_payout_table(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE worker_payouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    worker_discord_id TEXT NOT NULL,
                    final_payout INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )


def test_pending_duplicate_worker_payouts_are_collapsed_before_flush(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'pending.db'}")
    _TestBase.metadata.create_all(engine)

    with Session(engine, autoflush=False) as db:
        db.add(
            _PendingWorkerPayout(
                order_id=270,
                worker_discord_id="worker-1",
                final_payout=100,
            )
        )
        db.add(
            _PendingWorkerPayout(
                order_id=270,
                worker_discord_id="worker-1",
                final_payout=120,
            )
        )
        db.commit()

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT order_id, worker_discord_id, final_payout "
                "FROM worker_payouts"
            )
        ).all()

    assert rows == [(270, "worker-1", 120)]


def test_existing_duplicates_are_preserved_but_future_duplicates_are_blocked(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'historical.db'}")
    _create_minimal_worker_payout_table(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO worker_payouts(order_id, worker_discord_id, final_payout) "
                "VALUES (270, 'worker-1', 100), (270, 'worker-1', 100)"
            )
        )

    ensure_worker_payout_constraints(engine)

    with engine.begin() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM worker_payouts "
                "WHERE order_id=270 AND worker_discord_id='worker-1'"
            )
        ).scalar_one()
        unique_index = conn.execute(
            text(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='index' AND name='uq_worker_payouts_order_worker'"
            )
        ).first()

    assert count == 2
    assert unique_index is None

    with pytest.raises(IntegrityError, match="worker_payout_duplicate_guard"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO worker_payouts(order_id, worker_discord_id, final_payout) "
                    "VALUES (270, 'worker-1', 100)"
                )
            )


def test_clean_worker_payout_table_gets_unique_index(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'clean.db'}")
    _create_minimal_worker_payout_table(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO worker_payouts(order_id, worker_discord_id, final_payout) "
                "VALUES (270, 'worker-1', 100), (270, 'worker-2', 100)"
            )
        )

    ensure_worker_payout_constraints(engine)

    with engine.begin() as conn:
        unique_index = conn.execute(
            text(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='index' AND name='uq_worker_payouts_order_worker'"
            )
        ).first()

    assert unique_index is not None

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO worker_payouts(order_id, worker_discord_id, final_payout) "
                    "VALUES (270, 'worker-1', 100)"
                )
            )
