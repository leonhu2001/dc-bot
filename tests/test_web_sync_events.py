from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from shared.models import OrderAssignment, WebOrder
from shared import web_sync_events


def test_web_sync_payload_keeps_companions_separate_from_boosters(
    tmp_path,
    monkeypatch,
):
    db_file = tmp_path / "web-sync.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)

    test_session = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    monkeypatch.setattr(
        web_sync_events,
        "SessionLocal",
        test_session,
    )

    db = test_session()
    try:
        order = WebOrder(
            category="三角洲",
            item="護航",
            quantity=1,
            amount=1000,
            status="active",
        )
        db.add(order)
        db.flush()

        db.add_all(
            [
                OrderAssignment(
                    order_id=order.id,
                    worker_discord_id="101",
                    role_type="booster",
                    is_active=True,
                ),
                OrderAssignment(
                    order_id=order.id,
                    worker_discord_id="202",
                    role_type=" Companion ",
                    is_active=True,
                ),
                OrderAssignment(
                    order_id=order.id,
                    worker_discord_id="303",
                    role_type="companion",
                    is_active=False,
                ),
            ]
        )
        db.commit()
        order_id = int(order.id)
    finally:
        db.close()

    payload = web_sync_events.get_web_order_sync_payload(order_id)

    assert payload["booster_ids"] == [101]
    assert payload["companion_ids"] == [202]
