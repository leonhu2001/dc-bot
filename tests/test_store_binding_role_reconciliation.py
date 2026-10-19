import json
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.staff_models import StaffStoreBinding, WebStaffMember
from web.app.services import store_binding_service


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    WebStaffMember.__table__.create(engine)
    StaffStoreBinding.__table__.create(engine)
    return engine


def test_active_binding_restores_missing_discord_role(monkeypatch):
    engine = _engine()
    calls = []
    monkeypatch.setattr(
        store_binding_service,
        "_discord_role_request",
        lambda staff_id, enabled: (calls.append((staff_id, enabled)) or (True, None)),
    )

    with Session(engine) as db:
        db.add(
            WebStaffMember(
                discord_id="worker-1",
                roles_json="[]",
                is_worker=True,
                is_active=True,
            )
        )
        db.add(
            StaffStoreBinding(
                staff_discord_id="worker-1",
                status="active",
                started_at=datetime(2026, 10, 1, 0, 0, 0),
                discord_sync_status="error",
            )
        )
        db.commit()

        assert store_binding_service.reconcile_store_binding_role_from_cache(db, "worker-1") is True
        member = db.get(WebStaffMember, "worker-1")
        binding = store_binding_service.get_active_binding(db, "worker-1")
        assert store_binding_service.STORE_BOUND_ROLE_ID in set(json.loads(member.roles_json))
        assert binding.discord_sync_status == "synced"
        assert binding.discord_sync_error is None

    assert calls == [("worker-1", True)]


def test_inactive_binding_removes_rogue_discord_role(monkeypatch):
    engine = _engine()
    calls = []
    monkeypatch.setattr(
        store_binding_service,
        "_discord_role_request",
        lambda staff_id, enabled: (calls.append((staff_id, enabled)) or (True, None)),
    )

    with Session(engine) as db:
        db.add(
            WebStaffMember(
                discord_id="worker-2",
                roles_json=json.dumps([store_binding_service.STORE_BOUND_ROLE_ID]),
                is_worker=True,
                is_active=True,
            )
        )
        db.add(
            StaffStoreBinding(
                staff_discord_id="worker-2",
                status="ended",
                started_at=datetime(2026, 10, 1, 0, 0, 0),
                ended_at=datetime(2026, 10, 5, 0, 0, 0),
            )
        )
        db.commit()

        assert store_binding_service.reconcile_store_binding_role_from_cache(db, "worker-2") is True
        member = db.get(WebStaffMember, "worker-2")
        assert store_binding_service.STORE_BOUND_ROLE_ID not in set(json.loads(member.roles_json))

    assert calls == [("worker-2", False)]
