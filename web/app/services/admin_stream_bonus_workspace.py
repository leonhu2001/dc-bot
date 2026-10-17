from __future__ import annotations

from sqlalchemy import text

from web.app.services.admin_service import (
    can_override_stream_bonus_for_order,
    toggle_stream_bonus_for_assignment,
)


def attach_stream_bonus_workspace_state(db, order_id: int, rows: list[dict]) -> bool:
    """Attach report/effective stream state without mutating approved report evidence."""
    stream_rows = db.execute(
        text(
            """
            SELECT rw.worker_discord_id, rw.streamed
            FROM order_reports r
            JOIN order_report_workers rw ON rw.report_id = r.id
            WHERE r.order_id = :order_id
              AND r.status = 'approved'
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all()
    report_stream_map = {
        str(row.get("worker_discord_id") or ""): bool(row.get("streamed"))
        for row in stream_rows
        if str(row.get("worker_discord_id") or "").strip()
    }

    for row in rows:
        worker_id = str(row.get("worker_discord_id") or "")
        report_streamed = bool(report_stream_map.get(worker_id))
        override = row.get("stream_bonus_override")
        row["report_streamed"] = report_streamed
        row["effective_stream_bonus"] = (
            report_streamed if override is None else bool(override)
        )
        row["stream_bonus_override_active"] = override is not None

    return can_override_stream_bonus_for_order(db, int(order_id))


def _snapshot_payout_status(db, order_id: int) -> dict[str, dict[str, dict]]:
    snapshot: dict[str, dict[str, dict]] = {
        "worker": {},
        "customer_service": {},
    }
    specs = (
        ("worker", "worker_payouts", "worker_discord_id"),
        ("customer_service", "customer_service_payouts", "customer_service_discord_id"),
    )
    for bucket, table_name, person_column in specs:
        rows = db.execute(
            text(
                f"SELECT {person_column} AS person_id, payout_status, paid_at "
                f"FROM {table_name} WHERE order_id = :order_id"
            ),
            {"order_id": int(order_id)},
        ).mappings().all()
        for row in rows:
            person_id = str(row.get("person_id") or "").strip()
            if person_id:
                snapshot[bucket][person_id] = {
                    "payout_status": row.get("payout_status"),
                    "paid_at": row.get("paid_at"),
                }
    return snapshot


def _restore_payout_status(db, order_id: int, snapshot: dict) -> None:
    specs = (
        ("worker", "worker_payouts", "worker_discord_id"),
        ("customer_service", "customer_service_payouts", "customer_service_discord_id"),
    )
    for bucket, table_name, person_column in specs:
        for person_id, state in (snapshot.get(bucket) or {}).items():
            db.execute(
                text(
                    f"UPDATE {table_name} "
                    "SET payout_status = :payout_status, paid_at = :paid_at "
                    f"WHERE order_id = :order_id AND {person_column} = :person_id"
                ),
                {
                    "payout_status": state.get("payout_status"),
                    "paid_at": state.get("paid_at"),
                    "order_id": int(order_id),
                    "person_id": str(person_id),
                },
            )


def update_stream_bonus_from_workspace(
    db,
    *,
    order_id: int,
    assignment_id: int,
    enabled: bool,
    admin_user: dict,
) -> None:
    """Apply the admin override while preserving existing payout paid-state flags."""
    payout_snapshot = _snapshot_payout_status(db, int(order_id))
    toggle_stream_bonus_for_assignment(
        db,
        assignment_id=int(assignment_id),
        enabled=bool(enabled),
        admin_user=admin_user,
    )
    _restore_payout_status(db, int(order_id), payout_snapshot)
    db.commit()
