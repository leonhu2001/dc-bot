from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.order_rules import COMPANION_ROLES, PROTECTOR_ROLES, ROLE_IDS
DEFAULT_DB = ROOT / "web_dashboard.db"
DEFAULT_BACKUP_DIR = ROOT / "_archive"

PROTECTOR_ROLE_IDS = {
    str(ROLE_IDS[key])
    for key in PROTECTOR_ROLES
}
COMPANION_ROLE_IDS = {
    str(ROLE_IDS[key])
    for key in COMPANION_ROLES
}


@dataclass(frozen=True)
class AssignmentRoleRepair:
    assignment_id: int
    order_id: int
    worker_discord_id: str
    worker_display_name: str | None
    current_role_type: str | None
    expected_role_type: str
    order_status: str | None
    item: str | None


@dataclass(frozen=True)
class AssignmentRoleAudit:
    evidence_backed_count: int
    invalid_role_type_count: int
    repairs: tuple[AssignmentRoleRepair, ...]


def _load_role_ids(value) -> set[str]:
    if not value:
        return set()

    try:
        parsed = json.loads(str(value))
    except Exception:
        return set()

    if not isinstance(parsed, list):
        return set()

    return {
        str(item).strip()
        for item in parsed
        if str(item).strip()
    }


def _expected_role_type(role_ids: set[str]) -> str | None:
    if role_ids & PROTECTOR_ROLE_IDS:
        return "booster"
    if role_ids & COMPANION_ROLE_IDS:
        return "companion"
    return None


def _connect(db_file: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_file), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_required_tables(conn: sqlite3.Connection) -> None:
    tables = {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    required = {
        "web_orders",
        "order_assignments",
        "order_acceptance_claims",
    }
    missing = required - tables
    if missing:
        raise RuntimeError(
            "missing required tables: "
            + ", ".join(sorted(missing))
        )


def audit_assignment_role_types(
    db_file: str | Path = DEFAULT_DB,
) -> AssignmentRoleAudit:
    with _connect(db_file) as conn:
        _ensure_required_tables(conn)

        rows = conn.execute(
            """
            SELECT
                a.id AS assignment_id,
                a.order_id,
                a.worker_discord_id,
                a.worker_display_name,
                a.role_type,
                c.staff_role_ids_json,
                o.status,
                o.item
            FROM order_assignments a
            JOIN order_acceptance_claims c
              ON c.order_id = a.order_id
             AND CAST(c.staff_discord_id AS TEXT)
               = CAST(a.worker_discord_id AS TEXT)
            JOIN web_orders o
              ON o.id = a.order_id
            ORDER BY a.order_id, a.id
            """
        ).fetchall()

        evidence_backed_count = 0
        repairs: list[AssignmentRoleRepair] = []

        for row in rows:
            expected = _expected_role_type(
                _load_role_ids(row["staff_role_ids_json"])
            )
            if expected is None:
                continue

            evidence_backed_count += 1
            current_raw = row["role_type"]
            current_normalized = str(
                current_raw or ""
            ).strip().lower()

            if current_normalized == expected:
                continue

            repairs.append(
                AssignmentRoleRepair(
                    assignment_id=int(row["assignment_id"]),
                    order_id=int(row["order_id"]),
                    worker_discord_id=str(
                        row["worker_discord_id"]
                        or ""
                    ),
                    worker_display_name=(
                        str(row["worker_display_name"])
                        if row["worker_display_name"] is not None
                        else None
                    ),
                    current_role_type=(
                        str(current_raw)
                        if current_raw is not None
                        else None
                    ),
                    expected_role_type=expected,
                    order_status=(
                        str(row["status"])
                        if row["status"] is not None
                        else None
                    ),
                    item=(
                        str(row["item"])
                        if row["item"] is not None
                        else None
                    ),
                )
            )

        invalid_role_type_count = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM order_assignments
                WHERE LOWER(
                    TRIM(COALESCE(role_type, ''))
                ) NOT IN ('booster', 'companion')
                """
            ).fetchone()[0]
            or 0
        )

    return AssignmentRoleAudit(
        evidence_backed_count=evidence_backed_count,
        invalid_role_type_count=invalid_role_type_count,
        repairs=tuple(repairs),
    )


def _create_sqlite_backup(
    db_file: str | Path,
    backup_dir: str | Path,
) -> Path:
    source_path = Path(db_file)
    destination_dir = Path(backup_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = (
        destination_dir
        / f"web_dashboard_before_assignment_role_repair_{stamp}.db"
    )

    source = sqlite3.connect(str(source_path), timeout=15)
    backup = sqlite3.connect(str(destination))
    try:
        source.backup(backup)
    finally:
        backup.close()
        source.close()

    return destination


def apply_assignment_role_repairs(
    db_file: str | Path = DEFAULT_DB,
    *,
    backup_dir: str | Path = DEFAULT_BACKUP_DIR,
) -> tuple[Path, int]:
    before = audit_assignment_role_types(db_file)
    if not before.repairs:
        return _create_sqlite_backup(db_file, backup_dir), 0

    backup_path = _create_sqlite_backup(
        db_file,
        backup_dir,
    )

    conn = _connect(db_file)
    try:
        conn.execute("BEGIN IMMEDIATE")

        for repair in before.repairs:
            cursor = conn.execute(
                """
                UPDATE order_assignments
                SET role_type = ?
                WHERE id = ?
                  AND (
                        role_type = ?
                        OR (
                            role_type IS NULL
                            AND ? IS NULL
                        )
                  )
                """,
                (
                    repair.expected_role_type,
                    repair.assignment_id,
                    repair.current_role_type,
                    repair.current_role_type,
                ),
            )

            if cursor.rowcount != 1:
                raise RuntimeError(
                    "assignment changed during repair; "
                    f"id={repair.assignment_id} "
                    "rolling back"
                )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    after = audit_assignment_role_types(db_file)
    if after.repairs:
        raise RuntimeError(
            "role-type repair left evidence-backed mismatches: "
            f"{len(after.repairs)}"
        )

    return backup_path, len(before.repairs)


def _print_audit(audit: AssignmentRoleAudit) -> None:
    print("=== ASSIGNMENT ROLE AUDIT ===")
    print(
        "Evidence-backed assignments:",
        audit.evidence_backed_count,
    )
    print("Mismatches:", len(audit.repairs))
    print(
        "Non-canonical/legacy role_type rows:",
        audit.invalid_role_type_count,
    )

    for repair in audit.repairs:
        print(
            "assignment=%s order=%s worker=%s name=%r "
            "actual=%r expected=%s status=%s item=%r"
            % (
                repair.assignment_id,
                repair.order_id,
                repair.worker_discord_id,
                repair.worker_display_name,
                repair.current_role_type,
                repair.expected_role_type,
                repair.order_status,
                repair.item,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Repair order_assignments.role_type only when "
            "order_acceptance_claims contains role-ID evidence."
        )
    )
    parser.add_argument(
        "--db-file",
        default=str(DEFAULT_DB),
    )
    parser.add_argument(
        "--backup-dir",
        default=str(DEFAULT_BACKUP_DIR),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply evidence-backed changes. Default is dry-run.",
    )
    args = parser.parse_args()

    before = audit_assignment_role_types(
        args.db_file
    )
    _print_audit(before)

    if not args.apply:
        print("DRY_RUN: no database rows changed")
        return

    backup_path, changed = apply_assignment_role_repairs(
        args.db_file,
        backup_dir=args.backup_dir,
    )
    print("BACKUP:", backup_path)
    print("UPDATED ROWS:", changed)

    after = audit_assignment_role_types(
        args.db_file
    )
    print("=== POST-REPAIR ===")
    _print_audit(after)


if __name__ == "__main__":
    main()
