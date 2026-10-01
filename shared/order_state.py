from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection


PENDING_CS_DISPATCH = "pending_cs_dispatch"
WAITING_ACCEPTANCE = "waiting_acceptance"
ACCEPTED_PENDING_PAY = "accepted_pending_pay"
ACTIVE = "active"
STORED = "stored"
CLOSED = "closed"
CANCELLED = "cancelled"

CANONICAL_ORDER_STATES = {
    PENDING_CS_DISPATCH,
    WAITING_ACCEPTANCE,
    ACCEPTED_PENDING_PAY,
    ACTIVE,
    STORED,
    CLOSED,
    CANCELLED,
}

ORDER_STATE_ALIASES = {
    "created": PENDING_CS_DISPATCH,
    "paid": ACTIVE,
    "completed": CLOSED,
    "done": CLOSED,
    "canceled": CANCELLED,
}

ALLOWED_ORDER_TRANSITIONS = {
    PENDING_CS_DISPATCH: {
        WAITING_ACCEPTANCE,
        CANCELLED,
    },
    WAITING_ACCEPTANCE: {
        PENDING_CS_DISPATCH,
        ACCEPTED_PENDING_PAY,
        STORED,
        CANCELLED,
    },
    ACCEPTED_PENDING_PAY: {
        WAITING_ACCEPTANCE,
        ACTIVE,
        STORED,
        CANCELLED,
    },
    ACTIVE: {
        STORED,
        CLOSED,
        CANCELLED,
    },
    STORED: {
        WAITING_ACCEPTANCE,
        ACCEPTED_PENDING_PAY,
        ACTIVE,
        CLOSED,
        CANCELLED,
    },
    CLOSED: set(),
    CANCELLED: set(),
}

TERMINAL_ORDER_STATES = {
    CLOSED,
    CANCELLED,
}

PREPAY_ORDER_STATES = {
    PENDING_CS_DISPATCH,
    WAITING_ACCEPTANCE,
    ACCEPTED_PENDING_PAY,
}

TAIPEI_TZ = timezone(timedelta(hours=8))


class OrderStateTransitionError(ValueError):
    pass


@dataclass(frozen=True)
class OrderStateTransitionResult:
    order_id: int
    from_status: str
    to_status: str
    changed: bool
    acceptance_meta_synced: bool


def _now_iso() -> str:
    return datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")


def normalize_order_status(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    return ORDER_STATE_ALIASES.get(normalized, normalized)


def is_known_order_status(value: str | None) -> bool:
    return normalize_order_status(value) in CANONICAL_ORDER_STATES


def is_terminal_order_status(value: str | None) -> bool:
    return normalize_order_status(value) in TERMINAL_ORDER_STATES


def can_transition_order_status(
    current_status: str | None,
    target_status: str | None,
) -> bool:
    current = normalize_order_status(current_status)
    target = normalize_order_status(target_status)

    if current not in CANONICAL_ORDER_STATES:
        return False
    if target not in CANONICAL_ORDER_STATES:
        return False
    if current == target:
        return True

    return target in ALLOWED_ORDER_TRANSITIONS[current]


def validate_order_transition(
    current_status: str | None,
    target_status: str | None,
) -> tuple[str, str]:
    current = normalize_order_status(current_status)
    target = normalize_order_status(target_status)

    if current not in CANONICAL_ORDER_STATES:
        raise OrderStateTransitionError(
            f"未知訂單狀態：{current_status!r}。"
        )

    if target not in CANONICAL_ORDER_STATES:
        raise OrderStateTransitionError(
            f"未知目標訂單狀態：{target_status!r}。"
        )

    if not can_transition_order_status(current, target):
        raise OrderStateTransitionError(
            f"不允許訂單狀態從 {current} 直接切換到 {target}。"
        )

    return current, target


def _ensure_history_table(conn: Connection) -> None:
    from shared.models import OrderStateHistory

    OrderStateHistory.__table__.create(
        bind=conn,
        checkfirst=True,
    )


def _acceptance_table_exists(conn: Connection) -> bool:
    try:
        return inspect(conn).has_table("order_acceptance_meta")
    except Exception:
        return False


def _sync_acceptance_meta_status(
    conn: Connection,
    *,
    order_id: int,
    status: str,
) -> bool:
    if not _acceptance_table_exists(conn):
        return False

    result = conn.execute(
        text(
            """
            UPDATE order_acceptance_meta
            SET status = :status,
                updated_at = :updated_at
            WHERE order_id = :order_id
            """
        ),
        {
            "status": status,
            "updated_at": _now_iso(),
            "order_id": int(order_id),
        },
    )

    return int(result.rowcount or 0) > 0


def _record_transition(
    conn: Connection,
    *,
    order_id: int,
    from_status: str,
    to_status: str,
    source: str,
    reason: str | None,
    actor_discord_id: str | int | None,
) -> None:
    from shared.models import OrderStateHistory

    _ensure_history_table(conn)

    conn.execute(
        OrderStateHistory.__table__.insert().values(
            order_id=int(order_id),
            from_status=str(from_status),
            to_status=str(to_status),
            source=str(source or "unknown"),
            reason=str(reason or "").strip() or None,
            actor_discord_id=(
                str(actor_discord_id)
                if actor_discord_id is not None
                else None
            ),
            created_at=datetime.now(TAIPEI_TZ).replace(tzinfo=None),
        )
    )


def transition_order_state_in_connection(
    conn: Connection,
    *,
    order_id: int,
    target_status: str,
    source: str,
    reason: str | None = None,
    actor_discord_id: str | int | None = None,
    expected_statuses: Iterable[str] | None = None,
    sync_acceptance_meta: bool = True,
    require_empty_dispatch_message: bool = False,
) -> OrderStateTransitionResult:
    row = conn.execute(
        text(
            """
            SELECT status
            FROM web_orders
            WHERE id = :order_id
            LIMIT 1
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().first()

    if row is None:
        raise OrderStateTransitionError(
            f"找不到 WEB-{int(order_id)}，無法更新訂單狀態。"
        )

    raw_current = str(row["status"] or "").strip().lower()
    current, target = validate_order_transition(
        raw_current,
        target_status,
    )

    if expected_statuses is not None:
        expected = {
            normalize_order_status(status)
            for status in expected_statuses
        }
        if current not in expected:
            raise OrderStateTransitionError(
                f"WEB-{int(order_id)} 狀態已改變，"
                f"目前是 {current}，預期為 {sorted(expected)}。"
            )

    acceptance_synced = False

    if current == target and raw_current == target:
        if sync_acceptance_meta:
            acceptance_synced = _sync_acceptance_meta_status(
                conn,
                order_id=int(order_id),
                status=target,
            )

        return OrderStateTransitionResult(
            order_id=int(order_id),
            from_status=current,
            to_status=target,
            changed=False,
            acceptance_meta_synced=acceptance_synced,
        )

    guard_sql = ""
    if require_empty_dispatch_message:
        guard_sql = (
            " AND (dispatch_message_id IS NULL "
            "OR TRIM(dispatch_message_id) = '')"
        )

    result = conn.execute(
        text(
            """
            UPDATE web_orders
            SET status = :target_status,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :order_id
              AND status = :raw_current
            """
            + guard_sql
        ),
        {
            "target_status": target,
            "order_id": int(order_id),
            "raw_current": raw_current,
        },
    )

    if int(result.rowcount or 0) != 1:
        latest = conn.execute(
            text(
                """
                SELECT status
                FROM web_orders
                WHERE id = :order_id
                LIMIT 1
                """
            ),
            {"order_id": int(order_id)},
        ).mappings().first()
        latest_status = normalize_order_status(
            latest["status"] if latest else None
        )
        raise OrderStateTransitionError(
            f"WEB-{int(order_id)} 狀態在操作期間被其他流程更新，"
            f"目前是 {latest_status or 'unknown'}，請重新操作。"
        )

    if sync_acceptance_meta:
        acceptance_synced = _sync_acceptance_meta_status(
            conn,
            order_id=int(order_id),
            status=target,
        )

    _record_transition(
        conn,
        order_id=int(order_id),
        from_status=current,
        to_status=target,
        source=source,
        reason=reason,
        actor_discord_id=actor_discord_id,
    )

    return OrderStateTransitionResult(
        order_id=int(order_id),
        from_status=current,
        to_status=target,
        changed=True,
        acceptance_meta_synced=acceptance_synced,
    )


def transition_order_state(
    *,
    order_id: int,
    target_status: str,
    source: str,
    reason: str | None = None,
    actor_discord_id: str | int | None = None,
    expected_statuses: Iterable[str] | None = None,
    sync_acceptance_meta: bool = True,
    require_empty_dispatch_message: bool = False,
) -> OrderStateTransitionResult:
    from shared.db import engine

    with engine.begin() as conn:
        return transition_order_state_in_connection(
            conn,
            order_id=int(order_id),
            target_status=target_status,
            source=source,
            reason=reason,
            actor_discord_id=actor_discord_id,
            expected_statuses=expected_statuses,
            sync_acceptance_meta=sync_acceptance_meta,
            require_empty_dispatch_message=require_empty_dispatch_message,
        )


def latest_transition_into_state(
    conn: Connection,
    *,
    order_id: int,
    target_status: str,
) -> dict | None:
    target = normalize_order_status(target_status)
    _ensure_history_table(conn)

    row = conn.execute(
        text(
            """
            SELECT
                id,
                order_id,
                from_status,
                to_status,
                source,
                reason,
                actor_discord_id,
                created_at
            FROM order_state_history
            WHERE order_id = :order_id
              AND to_status = :to_status
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        {
            "order_id": int(order_id),
            "to_status": target,
        },
    ).mappings().first()

    return dict(row) if row is not None else None


def get_order_state_drift_count(conn: Connection) -> int:
    if not _acceptance_table_exists(conn):
        return 0

    rows = conn.execute(
        text(
            """
            SELECT
                o.status AS order_status,
                m.status AS acceptance_status
            FROM web_orders o
            JOIN order_acceptance_meta m
              ON m.order_id = o.id
            """
        )
    ).mappings().all()

    return sum(
        1
        for row in rows
        if normalize_order_status(row["order_status"])
        != normalize_order_status(row["acceptance_status"])
    )
