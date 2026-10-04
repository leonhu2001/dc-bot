from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEB_DB = ROOT / "web_dashboard.db"
DEFAULT_BOT_DB = ROOT / "bot.db"
DEFAULT_BACKUP_DIR = ROOT / "_archive"
FINAL_WEB_STATUSES = {"closed", "cancelled", "canceled"}


@dataclass(frozen=True)
class StaleClaim:
    dispatch_message_id: int
    source_channel_id: int | None
    claim_status: str | None
    linked_order_id: int
    linked_order_status: str


@dataclass(frozen=True)
class StaleClaimAudit:
    total_claims: int
    stale_claims: tuple[StaleClaim, ...]


def _connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table(conn: sqlite3.Connection, table: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"missing required table: {table}")


def _linked_web_order(
    web: sqlite3.Connection,
    *,
    dispatch_message_id: int,
    source_channel_id: int | None,
) -> sqlite3.Row | None:
    dispatch_text = str(dispatch_message_id)

    row = web.execute(
        """
        SELECT id, status, ticket_channel_id, dispatch_message_id
        FROM web_orders
        WHERE CAST(dispatch_message_id AS TEXT) = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (dispatch_text,),
    ).fetchone()

    if row is not None:
        return row

    if source_channel_id is None:
        return None

    return web.execute(
        """
        SELECT id, status, ticket_channel_id, dispatch_message_id
        FROM web_orders
        WHERE CAST(ticket_channel_id AS TEXT) = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (str(source_channel_id),),
    ).fetchone()


def audit_stale_bot_claims(
    *,
    web_db: str | Path = DEFAULT_WEB_DB,
    bot_db: str | Path = DEFAULT_BOT_DB,
) -> StaleClaimAudit:
    with _connect(web_db) as web, _connect(bot_db) as bot:
        _ensure_table(web, "web_orders")
        _ensure_table(bot, "claims")

        claims = bot.execute(
            """
            SELECT dispatch_message_id, source_channel_id, status
            FROM claims
            ORDER BY dispatch_message_id
            """
        ).fetchall()

        stale: list[StaleClaim] = []

        for claim in claims:
            dispatch_message_id = int(claim["dispatch_message_id"])
            source_channel_id = (
                int(claim["source_channel_id"])
                if claim["source_channel_id"] is not None
                else None
            )
            linked = _linked_web_order(
                web,
                dispatch_message_id=dispatch_message_id,
                source_channel_id=source_channel_id,
            )
            if linked is None:
                continue

            web_status = str(linked["status"] or "").strip().lower()
            if web_status not in FINAL_WEB_STATUSES:
                continue

            stale.append(
                StaleClaim(
                    dispatch_message_id=dispatch_message_id,
                    source_channel_id=source_channel_id,
                    claim_status=(
                        str(claim["status"])
                        if claim["status"] is not None
                        else None
                    ),
                    linked_order_id=int(linked["id"]),
                    linked_order_status=web_status,
                )
            )

    return StaleClaimAudit(
        total_claims=len(claims),
        stale_claims=tuple(stale),
    )


def _backup_bot_db(
    bot_db: str | Path,
    backup_dir: str | Path,
) -> Path:
    destination_dir = Path(backup_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = (
        destination_dir
        / f"bot_before_stale_claim_repair_{stamp}.db"
    )

    source = sqlite3.connect(str(bot_db), timeout=15)
    backup = sqlite3.connect(str(destination))
    try:
        source.backup(backup)
    finally:
        backup.close()
        source.close()

    return destination


def apply_stale_bot_claim_repairs(
    *,
    web_db: str | Path = DEFAULT_WEB_DB,
    bot_db: str | Path = DEFAULT_BOT_DB,
    backup_dir: str | Path = DEFAULT_BACKUP_DIR,
) -> tuple[Path, int]:
    before = audit_stale_bot_claims(
        web_db=web_db,
        bot_db=bot_db,
    )
    backup_path = _backup_bot_db(bot_db, backup_dir)

    if not before.stale_claims:
        return backup_path, 0

    conn = _connect(bot_db)
    try:
        conn.execute("BEGIN IMMEDIATE")

        for stale in before.stale_claims:
            cursor = conn.execute(
                """
                DELETE FROM claims
                WHERE dispatch_message_id = ?
                  AND (
                        status = ?
                        OR (
                            status IS NULL
                            AND ? IS NULL
                        )
                  )
                """,
                (
                    stale.dispatch_message_id,
                    stale.claim_status,
                    stale.claim_status,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    "claim changed during repair; "
                    f"dispatch_message_id={stale.dispatch_message_id}; "
                    "rolling back"
                )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    after = audit_stale_bot_claims(
        web_db=web_db,
        bot_db=bot_db,
    )
    if after.stale_claims:
        raise RuntimeError(
            "stale bot-claim repair left final-order claims: "
            f"{len(after.stale_claims)}"
        )

    return backup_path, len(before.stale_claims)


def _print_audit(audit: StaleClaimAudit) -> None:
    print("=== STALE BOT CLAIM AUDIT ===")
    print("Total claims:", audit.total_claims)
    print("Final-order stale claims:", len(audit.stale_claims))

    for row in audit.stale_claims:
        print(
            "dispatch=%s source_channel=%s claim_status=%r "
            "order=%s web_status=%s"
            % (
                row.dispatch_message_id,
                row.source_channel_id,
                row.claim_status,
                row.linked_order_id,
                row.linked_order_status,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Remove bot.db claims only when they can be linked to "
            "a final closed/cancelled web order."
        )
    )
    parser.add_argument("--web-db", default=str(DEFAULT_WEB_DB))
    parser.add_argument("--bot-db", default=str(DEFAULT_BOT_DB))
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply guarded deletes. Default is dry-run.",
    )
    args = parser.parse_args()

    before = audit_stale_bot_claims(
        web_db=args.web_db,
        bot_db=args.bot_db,
    )
    _print_audit(before)

    if not args.apply:
        print("DRY_RUN: no database rows changed")
        return

    backup_path, changed = apply_stale_bot_claim_repairs(
        web_db=args.web_db,
        bot_db=args.bot_db,
        backup_dir=args.backup_dir,
    )
    print("BACKUP:", backup_path)
    print("DELETED ROWS:", changed)

    print("=== POST-REPAIR ===")
    _print_audit(
        audit_stale_bot_claims(
            web_db=args.web_db,
            bot_db=args.bot_db,
        )
    )


if __name__ == "__main__":
    main()
