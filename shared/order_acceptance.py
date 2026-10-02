from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text

from services.order_rules import role_ids_match_requirements
from shared.db import engine
from shared.order_state import (
    ACCEPTED_PENDING_PAY,
    ACTIVE,
    STORED,
    WAITING_ACCEPTANCE,
    latest_transition_into_state,
    transition_order_state_in_connection,
)

PREPAY_ACCEPTANCE_STATUSES = {
    WAITING_ACCEPTANCE,
    ACCEPTED_PENDING_PAY,
}

PROTECTOR_ROLE_IDS = {
    "1500234130871550004",  # 魔丸♛頂護
    "1500234170943934544",  # 魔丸♝女護
    "1500751039060643990",  # 魔丸♜男護
}

# These two-person fun orders must end with exactly one protector-level
# staff member and one companion-only staff member. A member who has both
# a companion role and any protector role is counted as protector-level.
EXACT_ONE_PROTECTOR_RULE_KEYS = {
    "fun_lovebirds",
    "fun_read_no_reply",
}


@dataclass(frozen=True)
class AcceptanceClaim:
    staff_discord_id: str
    staff_display_name: str | None
    staff_role_ids: tuple[str, ...]
    source: str
    claimed_at: str | None


@dataclass(frozen=True)
class AcceptanceState:
    order_id: int
    status: str
    required_staff_count: int
    accepted_count: int
    min_protector_count: int
    protector_count: int
    is_full: bool
    claims: tuple[AcceptanceClaim, ...]


def _now_text() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _json_list(values: list[str] | tuple[str, ...] | set[str] | None) -> str:
    return json.dumps([str(value) for value in (values or [])], ensure_ascii=False)


def _load_json_list(value: Any) -> list[str]:
    if value is None:
        return []

    try:
        parsed = json.loads(str(value))
    except Exception:
        return []

    if not isinstance(parsed, list):
        return []

    return [str(item) for item in parsed if str(item).strip()]


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def ensure_acceptance_tables() -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS order_acceptance_meta (
                order_id INTEGER PRIMARY KEY,
                order_rule_key TEXT,
                required_staff_count INTEGER NOT NULL DEFAULT 1,
                min_protector_count INTEGER NOT NULL DEFAULT 0,
                allowed_role_ids_json TEXT,
                required_game_role_ids_json TEXT,
                specified_staff_ids_json TEXT,
                point_benefits_allowed INTEGER NOT NULL DEFAULT 1,
                rule_version INTEGER,
                rule_snapshot_json TEXT,
                price_snapshot_json TEXT,
                status TEXT NOT NULL DEFAULT 'waiting_acceptance',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS order_acceptance_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                staff_discord_id TEXT NOT NULL,
                staff_display_name TEXT,
                staff_role_ids_json TEXT,
                source TEXT NOT NULL DEFAULT 'unknown',
                is_active INTEGER NOT NULL DEFAULT 1,
                claimed_at TEXT NOT NULL,
                unclaimed_at TEXT,
                UNIQUE(order_id, staff_discord_id)
            )
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_order_acceptance_claims_order_active
            ON order_acceptance_claims(order_id, is_active)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_order_acceptance_claims_staff
            ON order_acceptance_claims(staff_discord_id)
        """))
        for column_name, ddl in (
            ("required_game_role_ids_json", "TEXT"),
            ("rule_version", "INTEGER"),
            ("rule_snapshot_json", "TEXT"),
            ("price_snapshot_json", "TEXT"),
        ):
            existing_columns = {
                row[1]
                for row in conn.exec_driver_sql("PRAGMA table_info(order_acceptance_meta)").fetchall()
            }

            if column_name not in existing_columns:
                conn.exec_driver_sql(
                    f"ALTER TABLE order_acceptance_meta ADD COLUMN {column_name} {ddl}"
                )

        # Existing waiting orders predate the AND-game column. Backfill from the
        # current direct rule definitions so they cannot bypass the new gate.
        try:
            from services.order_rules import get_required_game_role_ids, get_rule

            rows = conn.execute(text("""
                SELECT order_id, order_rule_key, required_game_role_ids_json
                FROM order_acceptance_meta
            """)).mappings().all()

            for row in rows:
                current = _load_json_list(row.get("required_game_role_ids_json"))
                if current:
                    continue

                rule_key = str(row.get("order_rule_key") or "").strip()
                if not rule_key:
                    continue

                try:
                    required_ids = get_required_game_role_ids(get_rule(rule_key))
                except KeyError:
                    continue

                if not required_ids:
                    continue

                conn.execute(text("""
                    UPDATE order_acceptance_meta
                    SET required_game_role_ids_json = :required_game_role_ids_json
                    WHERE order_id = :order_id
                """), {
                    "order_id": int(row["order_id"]),
                    "required_game_role_ids_json": _json_list(required_ids),
                })
        except Exception:
            # Schema creation must remain available even if an old rule key is
            # no longer present in the current catalog.
            pass



def create_or_update_acceptance_meta(
    *,
    order_id: int,
    order_rule_key: str | None = None,
    required_staff_count: int = 1,
    min_protector_count: int = 0,
    allowed_role_ids: list[str] | tuple[str, ...] | set[str] | None = None,
    required_game_role_ids: list[str] | tuple[str, ...] | set[str] | None = None,
    specified_staff_ids: list[str] | tuple[str, ...] | set[str] | None = None,
    point_benefits_allowed: bool = True,
    status: str = WAITING_ACCEPTANCE,
) -> None:
    ensure_acceptance_tables()

    if required_staff_count <= 0:
        raise ValueError("required_staff_count 必須大於 0。")

    if min_protector_count < 0:
        raise ValueError("min_protector_count 不能小於 0。")

    if min_protector_count > required_staff_count:
        raise ValueError("min_protector_count 不能大於 required_staff_count。")

    now = _now_text()

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO order_acceptance_meta (
                order_id,
                order_rule_key,
                required_staff_count,
                min_protector_count,
                allowed_role_ids_json,
                required_game_role_ids_json,
                specified_staff_ids_json,
                point_benefits_allowed,
                status,
                created_at,
                updated_at
            )
            VALUES (
                :order_id,
                :order_rule_key,
                :required_staff_count,
                :min_protector_count,
                :allowed_role_ids_json,
                :required_game_role_ids_json,
                :specified_staff_ids_json,
                :point_benefits_allowed,
                :status,
                :created_at,
                :updated_at
            )
            ON CONFLICT(order_id)
            DO UPDATE SET
                order_rule_key = excluded.order_rule_key,
                required_staff_count = excluded.required_staff_count,
                min_protector_count = excluded.min_protector_count,
                allowed_role_ids_json = excluded.allowed_role_ids_json,
                required_game_role_ids_json = excluded.required_game_role_ids_json,
                specified_staff_ids_json = excluded.specified_staff_ids_json,
                point_benefits_allowed = excluded.point_benefits_allowed,
                status = excluded.status,
                updated_at = excluded.updated_at
        """), {
            "order_id": int(order_id),
            "order_rule_key": order_rule_key,
            "required_staff_count": int(required_staff_count),
            "min_protector_count": int(min_protector_count),
            "allowed_role_ids_json": _json_list(allowed_role_ids),
            "required_game_role_ids_json": _json_list(required_game_role_ids),
            "specified_staff_ids_json": _json_list(specified_staff_ids),
            "point_benefits_allowed": 1 if point_benefits_allowed else 0,
            "status": str(status or WAITING_ACCEPTANCE),
            "created_at": now,
            "updated_at": now,
        })


def _get_meta(conn, order_id: int) -> dict[str, Any]:
    row = conn.execute(text("""
        SELECT
            order_id,
            order_rule_key,
            required_staff_count,
            min_protector_count,
            allowed_role_ids_json,
            required_game_role_ids_json,
            specified_staff_ids_json,
            point_benefits_allowed,
            status
        FROM order_acceptance_meta
        WHERE order_id = :order_id
        LIMIT 1
    """), {"order_id": int(order_id)}).mappings().first()

    if row is None:
        raise ValueError("這張訂單沒有付款前接單資料。")

    return dict(row)


def _get_order_status(conn, order_id: int) -> str:
    row = conn.execute(text("""
        SELECT status
        FROM web_orders
        WHERE id = :order_id
        LIMIT 1
    """), {"order_id": int(order_id)}).mappings().first()

    if row is None:
        raise ValueError("找不到這張訂單。")

    return str(row["status"] or "")


def _active_claim_rows(conn, order_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(text("""
        SELECT
            staff_discord_id,
            staff_display_name,
            staff_role_ids_json,
            source,
            claimed_at
        FROM order_acceptance_claims
        WHERE order_id = :order_id
          AND is_active = 1
        ORDER BY claimed_at ASC, id ASC
    """), {"order_id": int(order_id)}).mappings().all()

    return [dict(row) for row in rows]


def _claim_row_to_claim(row: dict[str, Any]) -> AcceptanceClaim:
    return AcceptanceClaim(
        staff_discord_id=str(row.get("staff_discord_id") or ""),
        staff_display_name=row.get("staff_display_name"),
        staff_role_ids=tuple(_load_json_list(row.get("staff_role_ids_json"))),
        source=str(row.get("source") or "unknown"),
        claimed_at=row.get("claimed_at"),
    )


def _count_protectors_from_rows(rows: list[dict[str, Any]]) -> int:
    count = 0

    for row in rows:
        role_ids = set(_load_json_list(row.get("staff_role_ids_json")))
        if role_ids & PROTECTOR_ROLE_IDS:
            count += 1

    return count


def get_acceptance_state(order_id: int) -> AcceptanceState:
    ensure_acceptance_tables()

    with engine.begin() as conn:
        meta = _get_meta(conn, int(order_id))
        status = _get_order_status(conn, int(order_id))
        rows = _active_claim_rows(conn, int(order_id))

    required_staff_count = _to_int(meta.get("required_staff_count"), 1)
    min_protector_count = _to_int(meta.get("min_protector_count"), 0)
    protector_count = _count_protectors_from_rows(rows)
    claims = tuple(_claim_row_to_claim(row) for row in rows)

    return AcceptanceState(
        order_id=int(order_id),
        status=status,
        required_staff_count=required_staff_count,
        accepted_count=len(claims),
        min_protector_count=min_protector_count,
        protector_count=protector_count,
        is_full=len(claims) >= required_staff_count,
        claims=claims,
    )


def _validate_specified_slot(
    *,
    staff_discord_id: str,
    required_staff_count: int,
    specified_staff_ids: list[str],
    active_rows: list[dict[str, Any]],
) -> None:
    if not specified_staff_ids:
        return

    if staff_discord_id in specified_staff_ids:
        return

    specified_set = set(specified_staff_ids)
    unrestricted_slots = max(0, required_staff_count - len(specified_set))

    non_specified_active_count = sum(
        1
        for row in active_rows
        if str(row.get("staff_discord_id") or "") not in specified_set
    )

    if non_specified_active_count >= unrestricted_slots:
        raise ValueError("這張單已指定其他人員，剩餘名額不可由你接單。")


def claim_acceptance_order(
    *,
    order_id: int,
    staff_discord_id: str,
    staff_display_name: str | None,
    staff_role_ids: list[str] | tuple[str, ...] | set[str],
    source: str,
) -> AcceptanceState:
    ensure_acceptance_tables()

    staff_discord_id = str(staff_discord_id)
    staff_role_ids_set = {str(role_id) for role_id in staff_role_ids or []}
    now = _now_text()

    if not staff_discord_id:
        raise ValueError("無法確認接單人員。")

    with engine.begin() as conn:
        order_status = _get_order_status(conn, int(order_id))

        if order_status not in PREPAY_ACCEPTANCE_STATUSES:
            raise ValueError("這張訂單目前不是等待接單狀態。")

        meta = _get_meta(conn, int(order_id))

        required_staff_count = _to_int(meta.get("required_staff_count"), 1)
        min_protector_count = _to_int(meta.get("min_protector_count"), 0)
        order_rule_key = str(meta.get("order_rule_key") or "")
        allowed_role_ids = set(_load_json_list(meta.get("allowed_role_ids_json")))
        required_game_role_ids = set(
            _load_json_list(meta.get("required_game_role_ids_json"))
        )
        specified_staff_ids = _load_json_list(meta.get("specified_staff_ids_json"))

        if not role_ids_match_requirements(
            staff_role_ids_set,
            allowed_role_ids,
            required_game_role_ids,
        ):
            raise ValueError("你的遊戲身分組或職位／階級不符合這張單的可接條件。")

        active_rows = _active_claim_rows(conn, int(order_id))

        if any(str(row.get("staff_discord_id") or "") == staff_discord_id for row in active_rows):
            raise ValueError("你已經接了這張單。")

        if len(active_rows) >= required_staff_count:
            raise ValueError("這張單已經滿人，無法接單。")

        _validate_specified_slot(
            staff_discord_id=staff_discord_id,
            required_staff_count=required_staff_count,
            specified_staff_ids=specified_staff_ids,
            active_rows=active_rows,
        )

        candidate_is_protector = bool(staff_role_ids_set & PROTECTOR_ROLE_IDS)
        current_protector_count = _count_protectors_from_rows(active_rows)
        next_protector_count = current_protector_count + (1 if candidate_is_protector else 0)
        remaining_slots_after_claim = required_staff_count - (len(active_rows) + 1)

        if (
            order_rule_key in EXACT_ONE_PROTECTOR_RULE_KEYS
            and next_protector_count > 1
        ):
            raise ValueError(
                "這張單固定 1 護 + 1 陪；已有護級接單，"
                "下一位不能持有男護、女護或頂護身分。"
            )

        if next_protector_count + remaining_slots_after_claim < min_protector_count:
            raise ValueError(
                "這張單固定 1 護 + 1 陪；剩餘名額必須由護級接單。"
                if order_rule_key in EXACT_ONE_PROTECTOR_RULE_KEYS
                else "這張單至少需要護級接單，剩餘名額不能再由陪級接。"
            )

        existing = conn.execute(text("""
            SELECT id
            FROM order_acceptance_claims
            WHERE order_id = :order_id
              AND staff_discord_id = :staff_discord_id
            LIMIT 1
        """), {
            "order_id": int(order_id),
            "staff_discord_id": staff_discord_id,
        }).mappings().first()

        params = {
            "order_id": int(order_id),
            "staff_discord_id": staff_discord_id,
            "staff_display_name": staff_display_name,
            "staff_role_ids_json": _json_list(staff_role_ids_set),
            "source": str(source or "unknown"),
            "claimed_at": now,
        }

        if existing is None:
            conn.execute(text("""
                INSERT INTO order_acceptance_claims (
                    order_id,
                    staff_discord_id,
                    staff_display_name,
                    staff_role_ids_json,
                    source,
                    is_active,
                    claimed_at,
                    unclaimed_at
                )
                VALUES (
                    :order_id,
                    :staff_discord_id,
                    :staff_display_name,
                    :staff_role_ids_json,
                    :source,
                    1,
                    :claimed_at,
                    NULL
                )
            """), params)
        else:
            conn.execute(text("""
                UPDATE order_acceptance_claims
                SET
                    staff_display_name = :staff_display_name,
                    staff_role_ids_json = :staff_role_ids_json,
                    source = :source,
                    is_active = 1,
                    claimed_at = :claimed_at,
                    unclaimed_at = NULL
                WHERE order_id = :order_id
                  AND staff_discord_id = :staff_discord_id
            """), params)

        active_rows_after = _active_claim_rows(conn, int(order_id))
        next_status = ACCEPTED_PENDING_PAY if len(active_rows_after) >= required_staff_count else WAITING_ACCEPTANCE

        transition_order_state_in_connection(
            conn,
            order_id=int(order_id),
            target_status=next_status,
            source=f"acceptance_claim:{source or 'unknown'}",
            reason=(
                f"付款前接單進度 {len(active_rows_after)}/{required_staff_count}"
            ),
            actor_discord_id=staff_discord_id,
            expected_statuses=PREPAY_ACCEPTANCE_STATUSES,
        )

    return get_acceptance_state(int(order_id))


def unclaim_acceptance_order(
    *,
    order_id: int,
    staff_discord_id: str,
    source: str,
) -> AcceptanceState:
    ensure_acceptance_tables()

    staff_discord_id = str(staff_discord_id)
    now = _now_text()

    with engine.begin() as conn:
        order_status = _get_order_status(conn, int(order_id))

        if order_status not in PREPAY_ACCEPTANCE_STATUSES:
            raise ValueError("這張訂單目前不是等待接單狀態，不能取消接單。")

        _get_meta(conn, int(order_id))

        active_rows = _active_claim_rows(conn, int(order_id))

        if not any(str(row.get("staff_discord_id") or "") == staff_discord_id for row in active_rows):
            raise ValueError("你目前沒有接這張單。")

        conn.execute(text("""
            UPDATE order_acceptance_claims
            SET is_active = 0,
                source = :source,
                unclaimed_at = :unclaimed_at
            WHERE order_id = :order_id
              AND staff_discord_id = :staff_discord_id
        """), {
            "source": str(source or "unknown"),
            "unclaimed_at": now,
            "order_id": int(order_id),
            "staff_discord_id": staff_discord_id,
        })

        transition_order_state_in_connection(
            conn,
            order_id=int(order_id),
            target_status=WAITING_ACCEPTANCE,
            source=f"acceptance_unclaim:{source or 'unknown'}",
            reason="付款前接單人員取消接單",
            actor_discord_id=staff_discord_id,
            expected_statuses=PREPAY_ACCEPTANCE_STATUSES,
        )

    return get_acceptance_state(int(order_id))


def has_acceptance_meta(order_id: int) -> bool:
    ensure_acceptance_tables()

    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT order_id
            FROM order_acceptance_meta
            WHERE order_id = :order_id
            LIMIT 1
        """), {"order_id": int(order_id)}).first()

    return row is not None


def _set_acceptance_lifecycle_status(
    conn,
    *,
    order_id: int,
    status: str,
    deactivate_claims: bool = False,
    source: str = "lifecycle",
) -> None:
    now = _now_text()

    _get_meta(conn, int(order_id))

    transition_order_state_in_connection(
        conn,
        order_id=int(order_id),
        target_status=str(status),
        source=f"acceptance_lifecycle:{source or 'lifecycle'}",
        reason=f"付款前接單 lifecycle -> {status}",
    )

    if deactivate_claims:
        conn.execute(text("""
            UPDATE order_acceptance_claims
            SET is_active = 0,
                source = :source,
                unclaimed_at = COALESCE(unclaimed_at, :unclaimed_at)
            WHERE order_id = :order_id
              AND is_active = 1
        """), {
            "source": str(source or "lifecycle"),
            "unclaimed_at": now,
            "order_id": int(order_id),
        })


def pause_acceptance_order(order_id: int, *, source: str = "stored") -> AcceptanceState:
    ensure_acceptance_tables()

    with engine.begin() as conn:
        _set_acceptance_lifecycle_status(
            conn,
            order_id=int(order_id),
            status="stored",
            deactivate_claims=False,
            source=source,
        )

    return get_acceptance_state(int(order_id))


def resume_acceptance_order(order_id: int, *, source: str = "resume") -> AcceptanceState:
    ensure_acceptance_tables()

    with engine.begin() as conn:
        meta = _get_meta(conn, int(order_id))
        current_status = _get_order_status(conn, int(order_id))
        if str(current_status or "").strip().lower() != STORED:
            raise ValueError("只有 stored 訂單可以執行恢復。")

        rows = _active_claim_rows(conn, int(order_id))
        required_staff_count = _to_int(meta.get("required_staff_count"), 1)

        stored_transition = latest_transition_into_state(
            conn,
            order_id=int(order_id),
            target_status=STORED,
        )

        previous_status = str(
            (stored_transition or {}).get("from_status")
            or ""
        ).strip().lower()

        active_assignment = conn.execute(text("""
            SELECT 1
            FROM order_assignments
            WHERE order_id = :order_id
              AND is_active = 1
            LIMIT 1
        """), {"order_id": int(order_id)}).first()

        if previous_status == ACTIVE or active_assignment is not None:
            next_status = ACTIVE
        else:
            next_status = (
                ACCEPTED_PENDING_PAY
                if len(rows) >= required_staff_count
                else WAITING_ACCEPTANCE
            )

        _set_acceptance_lifecycle_status(
            conn,
            order_id=int(order_id),
            status=next_status,
            deactivate_claims=False,
            source=source,
        )

    return get_acceptance_state(int(order_id))


def cancel_acceptance_order(order_id: int, *, source: str = "cancelled") -> AcceptanceState:
    ensure_acceptance_tables()

    with engine.begin() as conn:
        _set_acceptance_lifecycle_status(
            conn,
            order_id=int(order_id),
            status="cancelled",
            deactivate_claims=True,
            source=source,
        )

    return get_acceptance_state(int(order_id))


def close_acceptance_order(order_id: int, *, source: str = "closed") -> AcceptanceState:
    ensure_acceptance_tables()

    with engine.begin() as conn:
        _set_acceptance_lifecycle_status(
            conn,
            order_id=int(order_id),
            status="closed",
            deactivate_claims=False,
            source=source,
        )

    return get_acceptance_state(int(order_id))

def find_acceptance_order_id_by_dispatch_message_id(dispatch_message_id) -> int | None:
    ensure_acceptance_tables()

    dispatch_message_id_text = str(dispatch_message_id or "").strip()
    if not dispatch_message_id_text:
        return None

    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT m.order_id
            FROM order_acceptance_meta m
            JOIN web_orders o ON o.id = m.order_id
            WHERE o.dispatch_message_id = :dispatch_message_id
              AND o.status IN ('waiting_acceptance', 'accepted_pending_pay', 'active', 'stored')
              AND m.status IN ('waiting_acceptance', 'accepted_pending_pay', 'active', 'stored')
            LIMIT 1
        """), {
            "dispatch_message_id": dispatch_message_id_text,
        }).mappings().first()

    if row is None:
        return None

    return int(row["order_id"])

def promote_acceptance_claims_to_assignments(
    *,
    order_id: int,
    payment_method: str | None = None,
    amount: int | None = None,
    payout_base_amount: int | None = None,
    original_amount: int | None = None,
    manual_discount_amount: int | None = None,
    cash_coupon_amount: int | None = None,
    store_absorbed_amount: int | None = None,
    customer_pay_amount: int | None = None,
    bot_order_no: str | None = None,
) -> int:
    """付款成功後，將付款前接單名單轉成正式 OrderAssignment 並重算分潤。"""
    ensure_acceptance_tables()

    from sqlalchemy import select
    from shared.db import SessionLocal
    from shared.models import OrderAssignment, WebOrder
    from web.app.services.order_service import recalculate_order_payouts

    db = SessionLocal()

    try:
        order = db.get(WebOrder, int(order_id))
        if order is None:
            raise ValueError("找不到這張網站訂單，無法轉正式接單。")

        claim_rows = db.execute(text("""
            SELECT
                staff_discord_id,
                staff_display_name
            FROM order_acceptance_claims
            WHERE order_id = :order_id
              AND is_active = 1
            ORDER BY claimed_at ASC, id ASC
        """), {"order_id": int(order_id)}).mappings().all()

        if not claim_rows:
            raise ValueError("這張單沒有已確認的接單人員，不能轉正式分潤。")

        for row in claim_rows:
            worker_discord_id = str(row["staff_discord_id"])
            assignment = db.scalar(
                select(OrderAssignment)
                .where(OrderAssignment.order_id == int(order_id))
                .where(OrderAssignment.worker_discord_id == worker_discord_id)
                .limit(1)
            )

            if assignment is None:
                assignment = OrderAssignment(
                    order_id=int(order_id),
                    worker_discord_id=worker_discord_id,
                    worker_display_name=row["staff_display_name"] or worker_discord_id,
                    role_type="booster",
                    is_active=True,
                    # 「指定」只保留接單席位，不等於「掛名」；只有掛名才有額外 5% 分潤。
                    has_named_bonus=False,
                )
                db.add(assignment)
            else:
                assignment.worker_display_name = row["staff_display_name"] or assignment.worker_display_name
                assignment.role_type = "booster"
                assignment.is_active = True
                assignment.removed_at = None
                # 不因「指定」覆寫掛名狀態；既有真正掛名的 assignment 保留原值。

        customer_amount = int(
            customer_pay_amount
            if customer_pay_amount is not None
            else (amount if amount is not None else (order.amount or 0))
        )
        payout_amount = int(
            payout_base_amount
            if payout_base_amount is not None
            else customer_amount
        )

        transition_order_state_in_connection(
            db.connection(),
            order_id=int(order_id),
            target_status=ACTIVE,
            source="payment_finalize",
            reason="付款成立，付款前接單轉正式進行中",
            expected_statuses={
                ACCEPTED_PENDING_PAY,
                ACTIVE,
            },
        )
        db.expire(order, ["status"])

        if payment_method:
            order.payment_method = str(payment_method)

        order.amount = customer_amount
        order.customer_pay_amount = customer_amount
        order.payout_base_amount = payout_amount

        if original_amount is not None:
            order.original_amount = int(original_amount)
        if manual_discount_amount is not None:
            order.manual_discount_amount = int(manual_discount_amount)
        if cash_coupon_amount is not None:
            order.cash_coupon_amount = int(cash_coupon_amount)
        if store_absorbed_amount is not None:
            order.store_absorbed_amount = int(store_absorbed_amount)

        if bot_order_no:
            order.bot_order_no = str(bot_order_no)

        db.flush()
        recalculate_order_payouts(db, int(order_id))
        db.commit()

        try:
            from web.app.services.marketing_funnel import (
                record_attributed_order_event,
            )

            marketing_db_file = None
            try:
                marketing_db_file = str(
                    db.get_bind().url.database
                    or ""
                ).strip() or None
            except Exception:
                marketing_db_file = None

            record_attributed_order_event(
                order_id=int(order_id),
                event_name="payment_completed",
                customer_discord_id=str(
                    getattr(order, "customer_discord_id", "")
                    or ""
                ),
                db_file=marketing_db_file,
                properties={
                    "payment_method": str(
                        payment_method
                        or getattr(order, "payment_method", "")
                        or ""
                    ),
                    "customer_pay_amount": customer_amount,
                },
            )
        except Exception as exc:
            # Marketing telemetry must never turn an already-committed payment
            # finalization into a business failure.
            print(
                f"[marketing] payment_completed skipped "
                f"order={order_id}: {type(exc).__name__}: {exc}",
                flush=True,
            )

        return len(claim_rows)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

__all__ = [
    "ACCEPTED_PENDING_PAY",
    "WAITING_ACCEPTANCE",
    "AcceptanceClaim",
    "AcceptanceState",
    "claim_acceptance_order",
    "create_or_update_acceptance_meta",
    "ensure_acceptance_tables",
    "get_acceptance_state",
    "promote_acceptance_claims_to_assignments",
    "find_acceptance_order_id_by_dispatch_message_id",
    "close_acceptance_order",
    "cancel_acceptance_order",
    "resume_acceptance_order",
    "pause_acceptance_order",
    "has_acceptance_meta",
    "unclaim_acceptance_order",
]
