from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import datetime
from pathlib import Path


TIP_REFERENCE_RE = re.compile(r":TIP-(\d+)$", re.IGNORECASE)
WALLET_PAYMENT_METHOD = "\u6211\u7684\u9322\u5305"


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _load_tips(web_path: Path, tip_id: int | None) -> list[sqlite3.Row]:
    conn = sqlite3.connect(f"file:{web_path}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "worker_tips"):
            raise RuntimeError("worker_tips table is missing")

        where = """
            WHERE payment_method = ?
              AND LOWER(COALESCE(payment_status, '')) = 'paid'
              AND wallet_transaction_id IS NOT NULL
        """
        params: list[object] = [WALLET_PAYMENT_METHOD]

        if tip_id is not None:
            where += " AND id = ?"
            params.append(int(tip_id))

        return list(
            conn.execute(
                f"""
                SELECT
                    id,
                    receipt_id,
                    customer_discord_id,
                    amount,
                    wallet_transaction_id
                FROM worker_tips
                {where}
                ORDER BY id ASC
                """,
                params,
            ).fetchall()
        )
    finally:
        conn.close()


def _backup_bot_db(bot_path: Path) -> Path:
    archive = bot_path.parent / "_archive"
    archive.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = archive / f"bot_tip_reference_{stamp}.db"

    source = sqlite3.connect(bot_path, timeout=15)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()

    return backup_path


def repair(
    *,
    root: Path,
    tip_id: int | None,
    apply: bool,
) -> int:
    web_path = root / "web_dashboard.db"
    bot_path = root / "bot.db"

    if not web_path.exists():
        raise RuntimeError(f"missing {web_path}")
    if not bot_path.exists():
        raise RuntimeError(f"missing {bot_path}")

    tips = _load_tips(web_path, tip_id)
    if not tips:
        print("No matching paid wallet tips found.")
        return 0

    bot = sqlite3.connect(bot_path, timeout=15)
    bot.row_factory = sqlite3.Row
    bot.execute("PRAGMA busy_timeout=15000")

    try:
        if not _table_exists(bot, "wallet_transactions"):
            raise RuntimeError("wallet_transactions table is missing")

        plans: list[tuple[int, int, str, str]] = []
        errors: list[str] = []

        for tip in tips:
            current_tip_id = int(tip["id"])
            tx_id = int(tip["wallet_transaction_id"] or 0)
            receipt_id = str(tip["receipt_id"] or "").strip()
            customer_id = str(tip["customer_discord_id"] or "").strip()
            amount = int(tip["amount"] or 0)

            tx = bot.execute(
                """
                SELECT
                    id,
                    customer_discord_id,
                    amount,
                    balance_before,
                    balance_after,
                    type,
                    order_no
                FROM wallet_transactions
                WHERE id = ?
                LIMIT 1
                """,
                (tx_id,),
            ).fetchone()

            prefix = f"TIP-{current_tip_id}"
            if tx is None:
                errors.append(f"{prefix}: wallet tx #{tx_id} not found")
                continue

            actual_customer = str(tx["customer_discord_id"] or "").strip()
            actual_type = str(tx["type"] or "").strip()
            actual_amount = int(tx["amount"] or 0)
            before = int(tx["balance_before"] or 0)
            after = int(tx["balance_after"] or 0)
            old_ref = str(tx["order_no"] or "").strip()

            checks = {
                "customer": actual_customer == customer_id,
                "type": actual_type == "tip_payment",
                "amount": actual_amount == -amount,
                "wallet_math": before + actual_amount == after,
                "receipt": bool(receipt_id) and old_ref == receipt_id,
            }

            suffix = f":TIP-{current_tip_id}"
            if old_ref.lower().endswith(suffix.lower()):
                print(f"{prefix}: already current ({old_ref})")
                continue

            existing = TIP_REFERENCE_RE.search(old_ref)
            if existing:
                errors.append(
                    f"{prefix}: unexpected existing suffix in {old_ref!r}"
                )
                continue

            failed = [name for name, ok in checks.items() if not ok]
            if failed:
                errors.append(
                    f"{prefix}: validation failed: {', '.join(failed)}"
                )
                continue

            new_ref = f"{receipt_id}{suffix}"
            plans.append((current_tip_id, tx_id, old_ref, new_ref))
            print(f"{prefix}: {old_ref} -> {new_ref}")

        if errors:
            print("\nValidation errors:")
            for message in errors:
                print(f"- {message}")

        if not plans:
            return 2 if errors else 0

        if not apply:
            print(
                f"\nDry run only. {len(plans)} reference(s) can be repaired. "
                "Re-run with --apply."
            )
            return 2 if errors else 0

        backup_path = _backup_bot_db(bot_path)
        print(f"Backup: {backup_path}")

        bot.execute("BEGIN IMMEDIATE")
        try:
            for current_tip_id, tx_id, old_ref, new_ref in plans:
                cur = bot.execute(
                    """
                    UPDATE wallet_transactions
                    SET order_no = ?
                    WHERE id = ?
                      AND order_no = ?
                    """,
                    (new_ref, tx_id, old_ref),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(
                        f"TIP-{current_tip_id}: update rowcount={cur.rowcount}"
                    )
            bot.commit()
        except Exception:
            bot.rollback()
            raise

        print(
            f"Applied {len(plans)} reference repair(s). "
            "No balances or amounts were changed."
        )
        return 2 if errors else 0
    finally:
        bot.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair legacy worker-tip wallet order_no references."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--tip-id", type=int)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply validated changes. Default is dry-run.",
    )
    args = parser.parse_args()

    try:
        return repair(
            root=args.root.resolve(),
            tip_id=args.tip_id,
            apply=bool(args.apply),
        )
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
