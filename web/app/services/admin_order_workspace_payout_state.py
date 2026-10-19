from __future__ import annotations

from sqlalchemy import text


def _mw_r8_jsonable_row(row):
    if row is None:
        return None

    result = {}
    for key, value in dict(row).items():
        if value is not None and hasattr(value, "isoformat"):
            try:
                value = value.isoformat()
            except Exception:
                value = str(value)
        result[str(key)] = value

    return result


def _mw_r8_snapshot_payout_status(db, order_id: int) -> dict:
    snapshot = {
        "worker": {},
        "customer_service": {},
    }

    for row in db.execute(
        text(
            """
            SELECT
                worker_discord_id AS person_id,
                payout_status,
                paid_at
            FROM worker_payouts
            WHERE order_id = :order_id
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all():
        person_id = str(row.get("person_id") or "").strip()
        if person_id:
            snapshot["worker"][person_id] = {
                "payout_status": row.get("payout_status"),
                "paid_at": row.get("paid_at"),
            }

    for row in db.execute(
        text(
            """
            SELECT
                customer_service_discord_id AS person_id,
                payout_status,
                paid_at
            FROM customer_service_payouts
            WHERE order_id = :order_id
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all():
        person_id = str(row.get("person_id") or "").strip()
        if person_id:
            snapshot["customer_service"][person_id] = {
                "payout_status": row.get("payout_status"),
                "paid_at": row.get("paid_at"),
            }

    return snapshot


def _mw_r8_restore_payout_status(db, order_id: int, snapshot: dict) -> None:
    for person_id, state in (snapshot.get("worker") or {}).items():
        db.execute(
            text(
                """
                UPDATE worker_payouts
                SET payout_status = :payout_status,
                    paid_at = :paid_at
                WHERE order_id = :order_id
                  AND worker_discord_id = :person_id
                """
            ),
            {
                "payout_status": state.get("payout_status"),
                "paid_at": state.get("paid_at"),
                "order_id": int(order_id),
                "person_id": str(person_id),
            },
        )

    for person_id, state in (snapshot.get("customer_service") or {}).items():
        db.execute(
            text(
                """
                UPDATE customer_service_payouts
                SET payout_status = :payout_status,
                    paid_at = :paid_at
                WHERE order_id = :order_id
                  AND customer_service_discord_id = :person_id
                """
            ),
            {
                "payout_status": state.get("payout_status"),
                "paid_at": state.get("paid_at"),
                "order_id": int(order_id),
                "person_id": str(person_id),
            },
        )


def _mw_r8_cs_payout_rows(db, order_id: int) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT
                id,
                customer_service_discord_id,
                customer_service_display_name,
                rate,
                payout_amount,
                payout_status,
                paid_at
            FROM customer_service_payouts
            WHERE order_id = :order_id
            ORDER BY id DESC
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all()

    return [dict(row) for row in rows]
