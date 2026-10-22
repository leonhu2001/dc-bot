from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, String, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Session

import shared.db  # noqa: F401 - registers the payout Session guards


class _TestBase(DeclarativeBase):
    pass


class _PendingWorkerPayout(_TestBase):
    __tablename__ = "worker_payouts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, nullable=False)
    worker_discord_id = Column(String(32), nullable=False)
    final_payout = Column(Integer, nullable=False, default=0)


def _create_engine(tmp_path, name: str):
    engine = create_engine(f"sqlite:///{tmp_path / name}")
    _TestBase.metadata.create_all(engine)
    return engine


def test_pending_duplicate_worker_payouts_are_collapsed_before_flush(tmp_path):
    engine = _create_engine(tmp_path, "pending.db")

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


def test_new_duplicate_against_existing_rows_rolls_back_without_rewriting_history(tmp_path):
    engine = _create_engine(tmp_path, "historical.db")

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO worker_payouts(order_id, worker_discord_id, final_payout) "
                "VALUES (270, 'worker-1', 100), (270, 'worker-1', 100)"
            )
        )

    with pytest.raises(RuntimeError, match="worker_payout_duplicate_guard"):
        with Session(engine, autoflush=False) as db:
            db.add(
                _PendingWorkerPayout(
                    order_id=270,
                    worker_discord_id="worker-1",
                    final_payout=130,
                )
            )
            db.commit()

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT final_payout FROM worker_payouts "
                "WHERE order_id=270 AND worker_discord_id='worker-1' "
                "ORDER BY id"
            )
        ).all()

    assert rows == [(100,), (100,)]


def test_legacy_delete_then_add_rebuild_remains_compatible(tmp_path):
    engine = _create_engine(tmp_path, "replace.db")

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO worker_payouts(order_id, worker_discord_id, final_payout) "
                "VALUES (270, 'worker-1', 100)"
            )
        )

    with Session(engine, autoflush=False) as db:
        existing = db.scalar(
            select(_PendingWorkerPayout)
            .where(_PendingWorkerPayout.order_id == 270)
            .where(_PendingWorkerPayout.worker_discord_id == "worker-1")
        )
        assert existing is not None
        db.delete(existing)
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
                "SELECT final_payout FROM worker_payouts "
                "WHERE order_id=270 AND worker_discord_id='worker-1'"
            )
        ).all()

    assert rows == [(120,)]


def test_safe_repair_can_replace_historical_duplicates_with_one_row(tmp_path):
    engine = _create_engine(tmp_path, "repair.db")

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO worker_payouts(order_id, worker_discord_id, final_payout) "
                "VALUES (270, 'worker-1', 100), (270, 'worker-1', 100)"
            )
        )

    with Session(engine, autoflush=False) as db:
        existing_rows = list(
            db.scalars(
                select(_PendingWorkerPayout)
                .where(_PendingWorkerPayout.order_id == 270)
                .where(_PendingWorkerPayout.worker_discord_id == "worker-1")
            ).all()
        )
        assert len(existing_rows) == 2
        for row in existing_rows:
            db.delete(row)
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
                "SELECT final_payout FROM worker_payouts "
                "WHERE order_id=270 AND worker_discord_id='worker-1'"
            )
        ).all()

    assert rows == [(120,)]
