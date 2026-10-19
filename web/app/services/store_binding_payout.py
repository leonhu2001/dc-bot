from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from shared.staff_models import StaffStoreBinding
from web.app.services.store_binding_service import ACTIVE, ENDED


def is_store_binding_effective_at(
    db: Session,
    staff_discord_id: str,
    effective_at: datetime | None,
) -> bool:
    """Return whether the worker had an effective store binding at a historical time.

    Financial eligibility is derived only from the Web DB history. Discord roles are
    a mirror and must never be used to recalculate historical payouts.
    """
    if effective_at is None:
        return False

    row_id = db.scalar(
        select(StaffStoreBinding.id)
        .where(StaffStoreBinding.staff_discord_id == str(staff_discord_id))
        .where(StaffStoreBinding.status.in_((ACTIVE, ENDED)))
        .where(StaffStoreBinding.started_at.is_not(None))
        .where(StaffStoreBinding.started_at <= effective_at)
        .where(
            or_(
                StaffStoreBinding.ended_at.is_(None),
                StaffStoreBinding.ended_at > effective_at,
            )
        )
        .order_by(StaffStoreBinding.started_at.desc(), StaffStoreBinding.id.desc())
        .limit(1)
    )
    return row_id is not None
