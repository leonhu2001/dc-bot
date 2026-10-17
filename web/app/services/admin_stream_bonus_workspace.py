from __future__ import annotations

from sqlalchemy import text

from web.app.services.admin_service import (
    can_override_stream_bonus_for_order,
    toggle_stream_bonus_for_assignment,
)


def load_stream_bonus_workspace_rows(db, order_id: int) -> tuple[list[dict], bool]:
    """Load assignment/payout rows and attach effective livestream bonus state."""
    rows = db.execute(
        text(
            """
            SELECT
                oa.id AS assignment_id,
                oa.worker_discord_id,
                oa.worker_display_name,
                oa.has_named_bonus,
                oa.stream_bonus_override,
                oa.is_active,
                wp.id AS payout_id,
                wp.gross_share,
                wp.base_payout,
                wp.named_bonus_amount,
                wp.final_payout,
                wp.payout_status,
                wp.paid_at
            FROM order_assignments oa
            LEFT JOIN worker_payouts wp
              ON wp.id = (
                    SELECT wp2.id
                    FROM worker_payouts wp2
                    WHERE wp2.order_id = oa.order_id
                      AND wp2.worker_discord_id = oa.worker_discord_id
                    ORDER BY wp2.id DESC
                    LIMIT 1
                )
            WHERE oa.order_id = :order_id
              AND COALESCE(oa.is_active, 1) = 1
            ORDER BY oa.id ASC
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all()
    result = [dict(row) for row in rows]

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

    for row in result:
        worker_id = str(row.get("worker_discord_id") or "")
        report_streamed = bool(report_stream_map.get(worker_id))
        override = row.get("stream_bonus_override")
        row["report_streamed"] = report_streamed
        row["effective_stream_bonus"] = (
            report_streamed if override is None else bool(override)
        )
        row["stream_bonus_override_active"] = override is not None

    editable = can_override_stream_bonus_for_order(db, int(order_id))
    return result, editable


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
