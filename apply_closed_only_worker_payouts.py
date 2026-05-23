from pathlib import Path
import sqlite3

DB_CANDIDATES = [
    Path("web_dashboard.db"),
    Path("/opt/dc-bot/web_dashboard.db"),
]

DB_PATH = next((path for path in DB_CANDIDATES if path.exists()), DB_CANDIDATES[0])


def table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def get_columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def recalc_order(conn, order_id: int) -> None:
    order = conn.execute(
        "SELECT id, status, amount FROM web_orders WHERE id = ?",
        (order_id,),
    ).fetchone()

    if not order:
        return

    status = order[1]
    amount = int(order[2] or 0)

    conn.execute("DELETE FROM worker_payouts WHERE order_id = ?", (order_id,))

    if status != "closed":
        return

    assignments = conn.execute(
        """
        SELECT worker_discord_id, worker_display_name, has_named_bonus
        FROM order_assignments
        WHERE order_id = ?
          AND is_active = 1
        ORDER BY id ASC
        """,
        (order_id,),
    ).fetchall()

    if not assignments:
        return

    gross_share = amount // len(assignments)

    payout_columns = get_columns(conn, "worker_payouts")

    for worker_id, worker_name, has_named_bonus in assignments:
        has_named_bonus = bool(has_named_bonus)
        base_payout = round(gross_share * 0.80)
        named_bonus_amount = round(gross_share * 0.05) if has_named_bonus else 0
        final_payout = base_payout + named_bonus_amount

        values = {
            "order_id": order_id,
            "worker_discord_id": worker_id,
            "worker_display_name": worker_name,
            "gross_share": gross_share,
            "base_rate": 0.80,
            "base_payout": base_payout,
            "named_bonus_rate": 0.05,
            "named_bonus_amount": named_bonus_amount,
            "has_named_bonus": 1 if has_named_bonus else 0,
            "final_payout": final_payout,
            "payout_status": "unpaid",
            "paid_at": None,
            "note": None,
        }

        usable_keys = [key for key in values if key in payout_columns]
        placeholders = ", ".join("?" for _ in usable_keys)
        column_sql = ", ".join(usable_keys)

        conn.execute(
            f"INSERT INTO worker_payouts ({column_sql}) VALUES ({placeholders})",
            [values[key] for key in usable_keys],
        )


def install_triggers(conn) -> None:
    # 不管程式在哪裡誤算，只要訂單不是 closed，打手分潤一律歸 0。
    conn.executescript(
        """
        DROP TRIGGER IF EXISTS trg_worker_payout_zero_non_closed_insert;
        DROP TRIGGER IF EXISTS trg_worker_payout_zero_non_closed_update;
        DROP TRIGGER IF EXISTS trg_web_order_zero_payout_non_closed;

        CREATE TRIGGER trg_worker_payout_zero_non_closed_insert
        AFTER INSERT ON worker_payouts
        WHEN COALESCE((SELECT status FROM web_orders WHERE id = NEW.order_id), '') <> 'closed'
        BEGIN
            UPDATE worker_payouts
            SET gross_share = 0,
                base_payout = 0,
                named_bonus_amount = 0,
                final_payout = 0
            WHERE id = NEW.id;
        END;

        CREATE TRIGGER trg_worker_payout_zero_non_closed_update
        AFTER UPDATE ON worker_payouts
        WHEN COALESCE((SELECT status FROM web_orders WHERE id = NEW.order_id), '') <> 'closed'
        BEGIN
            UPDATE worker_payouts
            SET gross_share = 0,
                base_payout = 0,
                named_bonus_amount = 0,
                final_payout = 0
            WHERE id = NEW.id;
        END;

        CREATE TRIGGER trg_web_order_zero_payout_non_closed
        AFTER UPDATE OF status ON web_orders
        WHEN NEW.status <> 'closed'
        BEGIN
            UPDATE worker_payouts
            SET gross_share = 0,
                base_payout = 0,
                named_bonus_amount = 0,
                final_payout = 0
            WHERE order_id = NEW.id;
        END;
        """
    )


def main() -> None:
    print(f"db={DB_PATH}")

    conn = sqlite3.connect(DB_PATH)

    try:
        required = ["web_orders", "worker_payouts", "order_assignments"]

        for table in required:
            if not table_exists(conn, table):
                raise RuntimeError(f"missing table: {table}")

        install_triggers(conn)

        order_ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM web_orders WHERE status IN ('active', 'stored', 'closed') ORDER BY id"
            ).fetchall()
        ]

        for order_id in order_ids:
            recalc_order(conn, int(order_id))

        conn.commit()

        print("status_counts:")
        for row in conn.execute(
            "SELECT status, COUNT(*) FROM web_orders GROUP BY status ORDER BY status"
        ):
            print(row)

        print("worker_payout_summary:")
        for row in conn.execute(
            """
            SELECT w.status, COUNT(p.id), COALESCE(SUM(p.final_payout), 0)
            FROM web_orders w
            LEFT JOIN worker_payouts p ON p.order_id = w.id
            GROUP BY w.status
            ORDER BY w.status
            """
        ):
            print(row)

        print("done")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
