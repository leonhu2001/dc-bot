from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from shared.order_state import CANCELLATION_REASON_LABELS

TAIPEI_TZ = timezone(timedelta(hours=8))
UTC = timezone.utc


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[3] / "web_dashboard.db"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (str(name),),
    ).fetchone()
    return row is not None


def _load_json_list(value: Any) -> list[str]:
    try:
        data = json.loads(str(value or "[]"))
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if str(item).strip()]


def _parse_time(value: Any, *, naive_tz) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=naive_tz)
    return parsed


def _seconds_between(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(
        0,
        int(
            (
                end.astimezone(UTC)
                - start.astimezone(UTC)
            ).total_seconds()
        ),
    )


def _average(values: list[int]) -> int | None:
    if not values:
        return None
    return int(round(sum(values) / len(values)))


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    if hours:
        return f"{hours} 小時 {minute} 分"
    if minutes:
        return f"{minutes} 分 {sec} 秒"
    return f"{sec} 秒"


def _active_staff_role_sets(conn: sqlite3.Connection) -> list[set[str]]:
    if not _table_exists(conn, "web_staff_members"):
        return []

    rows = conn.execute(
        """
        SELECT roles_json
        FROM web_staff_members
        WHERE COALESCE(is_active, 1) = 1
          AND (
                COALESCE(is_worker, 0) = 1
             OR COALESCE(is_companion, 0) = 1
          )
        """
    ).fetchall()
    return [set(_load_json_list(row[0])) for row in rows]


def _eligible_staff_count(
    rule_key: str,
    staff_roles: list[set[str]],
) -> int | None:
    key = str(rule_key or "").strip()
    if not key:
        return None

    try:
        from services.order_rules import (
            get_allowed_role_ids,
            get_required_game_role_ids,
            get_rule,
            role_ids_match_requirements,
        )

        rule = get_rule(key)
        allowed = get_allowed_role_ids(rule)
        required_games = get_required_game_role_ids(rule)
    except Exception:
        return None

    return sum(
        1
        for roles in staff_roles
        if role_ids_match_requirements(
            roles,
            allowed,
            required_games,
        )
    )


def build_smart_dispatch_snapshot(
    *,
    days: int = 30,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    days = max(1, min(int(days or 30), 365))
    path = _db_path(db_file)
    empty = {
        "days": days,
        "total": 0,
        "filled": 0,
        "fill_rate": 0.0,
        "pending": 0,
        "avg_first_claim_seconds": None,
        "avg_fill_seconds": None,
        "avg_first_claim_text": "—",
        "avg_fill_text": "—",
        "no_candidate": 0,
        "full_expansion": 0,
        "errors": 0,
        "specified_dm_failed": 0,
        "groups": [],
        "problem_plans": [],
    }
    if not path.exists():
        return empty

    cutoff = datetime.now(TAIPEI_TZ) - timedelta(days=days)

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn, "smart_dispatch_notifications"):
            return empty

        has_orders = _table_exists(conn, "web_orders")
        rows = conn.execute(
            """
            SELECT
                s.*,
                %s
            FROM smart_dispatch_notifications s
            %s
            ORDER BY s.id DESC
            LIMIT 3000
            """
            % (
                (
                    "o.category AS category, "
                    "o.item AS item, "
                    "o.order_rule_key AS order_rule_key, "
                    "o.status AS order_status"
                )
                if has_orders
                else (
                    "NULL AS category, NULL AS item, "
                    "NULL AS order_rule_key, NULL AS order_status"
                ),
                "LEFT JOIN web_orders o ON o.id = s.order_id"
                if has_orders
                else "",
            )
        ).fetchall()

        plans: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            created = _parse_time(
                data.get("created_at"),
                naive_tz=TAIPEI_TZ,
            )
            if created is None or created.astimezone(TAIPEI_TZ) < cutoff:
                continue
            data["_created"] = created
            plans.append(data)

        if not plans:
            return empty

        order_ids = [int(row["order_id"]) for row in plans]
        placeholders = ",".join("?" for _ in order_ids)
        claims_by_order: dict[int, list[datetime]] = defaultdict(list)
        filled_at_by_order: dict[int, datetime] = {}

        if _table_exists(conn, "order_acceptance_claims"):
            claim_rows = conn.execute(
                f"""
                SELECT order_id, claimed_at
                FROM order_acceptance_claims
                WHERE order_id IN ({placeholders})
                ORDER BY order_id, claimed_at, id
                """,
                order_ids,
            ).fetchall()
            for claim in claim_rows:
                claimed_at = _parse_time(
                    claim["claimed_at"],
                    naive_tz=UTC,
                )
                if claimed_at is not None:
                    claims_by_order[int(claim["order_id"])].append(
                        claimed_at
                    )

        if _table_exists(conn, "order_state_history"):
            fill_rows = conn.execute(
                f"""
                SELECT order_id, MIN(created_at) AS filled_at
                FROM order_state_history
                WHERE order_id IN ({placeholders})
                  AND to_status = 'accepted_pending_pay'
                GROUP BY order_id
                """,
                order_ids,
            ).fetchall()
            for fill_row in fill_rows:
                filled_at = _parse_time(
                    fill_row["filled_at"],
                    naive_tz=UTC,
                )
                if filled_at is not None:
                    filled_at_by_order[int(fill_row["order_id"])] = (
                        filled_at
                    )

        staff_roles = _active_staff_role_sets(conn)

    first_claim_values: list[int] = []
    fill_values: list[int] = []
    group_data: dict[tuple[str, str, str], dict[str, Any]] = {}
    problem_plans: list[dict[str, Any]] = []

    filled_count = 0
    pending_count = 0
    no_candidate_count = 0
    full_expansion_count = 0
    error_count = 0
    specified_dm_failed_count = 0

    for plan in plans:
        order_id = int(plan["order_id"])
        created = plan["_created"]
        claims = claims_by_order.get(order_id, [])
        required = max(1, int(plan.get("required_staff_count") or 1))
        ranked = _load_json_list(plan.get("ranked_candidate_ids_json"))
        notified = _load_json_list(plan.get("notified_candidate_ids_json"))
        specified_failed = _load_json_list(
            plan.get("specified_dm_failed_ids_json")
        )

        first_claim_seconds = (
            _seconds_between(created, claims[0])
            if claims
            else None
        )
        canonical_fill_at = filled_at_by_order.get(order_id)
        fill_seconds = (
            _seconds_between(created, canonical_fill_at)
            if canonical_fill_at is not None
            else (
                _seconds_between(created, claims[required - 1])
                if len(claims) >= required
                else None
            )
        )

        if first_claim_seconds is not None:
            first_claim_values.append(first_claim_seconds)
        if fill_seconds is not None:
            fill_values.append(fill_seconds)
            filled_count += 1
        else:
            status = str(plan.get("order_status") or "").strip().lower()
            if status in {
                "pending_cs_dispatch",
                "waiting_acceptance",
                "accepted_pending_pay",
                "active",
                "stored",
            }:
                pending_count += 1

        no_candidate = len(ranked) == 0
        full_expansion = (
            str(plan.get("completion_reason") or "")
            == "full_expansion_sent"
        )
        has_error = bool(str(plan.get("last_error") or "").strip())

        no_candidate_count += int(no_candidate)
        full_expansion_count += int(full_expansion)
        error_count += int(has_error)
        specified_dm_failed_count += len(specified_failed)

        category = str(plan.get("category") or "未分類").strip() or "未分類"
        item = str(plan.get("item") or "未紀錄").strip() or "未紀錄"
        rule_key = str(plan.get("order_rule_key") or "").strip()
        group_key = (category, item, rule_key)

        group = group_data.setdefault(
            group_key,
            {
                "category": category,
                "item": item,
                "rule_key": rule_key,
                "total": 0,
                "filled": 0,
                "first_claim_values": [],
                "fill_values": [],
                "no_candidate": 0,
                "full_expansion": 0,
                "eligible_staff": _eligible_staff_count(
                    rule_key,
                    staff_roles,
                ),
            },
        )
        group["total"] += 1
        group["filled"] += int(fill_seconds is not None)
        group["no_candidate"] += int(no_candidate)
        group["full_expansion"] += int(full_expansion)
        if first_claim_seconds is not None:
            group["first_claim_values"].append(first_claim_seconds)
        if fill_seconds is not None:
            group["fill_values"].append(fill_seconds)

        if (
            no_candidate
            or full_expansion
            or has_error
            or fill_seconds is None
        ):
            problem_plans.append(
                {
                    "order_id": order_id,
                    "category": category,
                    "item": item,
                    "status": str(plan.get("order_status") or "—"),
                    "candidate_count": len(ranked),
                    "notified_count": len(notified),
                    "stage": int(plan.get("stage") or 0),
                    "completion_reason": str(
                        plan.get("completion_reason") or ""
                    ),
                    "last_error": str(plan.get("last_error") or ""),
                    "created_at": str(plan.get("created_at") or ""),
                }
            )

    groups = []
    for group in group_data.values():
        total = int(group["total"])
        filled = int(group["filled"])
        avg_first = _average(group.pop("first_claim_values"))
        avg_fill = _average(group.pop("fill_values"))
        group.update(
            {
                "fill_rate": round(
                    (filled / total * 100) if total else 0.0,
                    1,
                ),
                "avg_first_claim_seconds": avg_first,
                "avg_first_claim_text": format_duration(avg_first),
                "avg_fill_seconds": avg_fill,
                "avg_fill_text": format_duration(avg_fill),
            }
        )
        groups.append(group)

    groups.sort(
        key=lambda row: (
            -int(row["total"]),
            str(row["category"]),
            str(row["item"]),
        )
    )

    avg_first = _average(first_claim_values)
    avg_fill = _average(fill_values)
    total = len(plans)

    return {
        "days": days,
        "total": total,
        "filled": filled_count,
        "fill_rate": round(
            (filled_count / total * 100) if total else 0.0,
            1,
        ),
        "pending": pending_count,
        "avg_first_claim_seconds": avg_first,
        "avg_fill_seconds": avg_fill,
        "avg_first_claim_text": format_duration(avg_first),
        "avg_fill_text": format_duration(avg_fill),
        "no_candidate": no_candidate_count,
        "full_expansion": full_expansion_count,
        "errors": error_count,
        "specified_dm_failed": specified_dm_failed_count,
        "groups": groups[:20],
        "problem_plans": problem_plans[:20],
    }


def build_cancellation_snapshot(
    *,
    days: int = 30,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    days = max(1, min(int(days or 30), 365))
    path = _db_path(db_file)
    empty = {
        "days": days,
        "orders_created": 0,
        "cancelled_orders": 0,
        "cancellation_rate": 0.0,
        "lost_value": 0,
        "unclassified": 0,
        "reasons": [],
        "categories": [],
        "recent": [],
    }
    if not path.exists():
        return empty

    cutoff = datetime.now(TAIPEI_TZ) - timedelta(days=days)

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        if not _table_exists(conn, "web_orders"):
            return empty

        order_rows = conn.execute(
            """
            SELECT id, status, created_at
            FROM web_orders
            ORDER BY id DESC
            LIMIT 10000
            """
        ).fetchall()

        created_in_window = []
        for row in order_rows:
            created = _parse_time(
                row["created_at"],
                naive_tz=UTC,
            )
            if (
                created is not None
                and created.astimezone(TAIPEI_TZ) >= cutoff
            ):
                created_in_window.append(row)

        cancelled_created = sum(
            1
            for row in created_in_window
            if str(row["status"] or "").strip().lower()
            in {"cancelled", "canceled"}
        )

        result = dict(empty)
        result["orders_created"] = len(created_in_window)
        result["cancelled_orders"] = cancelled_created
        result["cancellation_rate"] = round(
            (
                cancelled_created
                / len(created_in_window)
                * 100
            )
            if created_in_window
            else 0.0,
            1,
        )

        if not _table_exists(conn, "order_cancellations"):
            return result

        rows = conn.execute(
            """
            SELECT
                c.order_id,
                c.reason_code,
                c.reason_text,
                c.source,
                c.actor_discord_id,
                c.created_at,
                o.category,
                o.item,
                o.customer_pay_amount,
                o.amount,
                o.bot_order_no
            FROM order_cancellations c
            LEFT JOIN web_orders o ON o.id = c.order_id
            ORDER BY c.created_at DESC, c.order_id DESC
            LIMIT 5000
            """
        ).fetchall()

    recent_rows = []
    reason_counts: dict[str, int] = defaultdict(int)
    category_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"count": 0, "lost_value": 0}
    )
    lost_value = 0
    unclassified = 0

    for row in rows:
        created = _parse_time(
            row["created_at"],
            naive_tz=(
                UTC
                if str(row["source"] or "") == "legacy_backfill"
                else TAIPEI_TZ
            ),
        )
        if created is None or created.astimezone(TAIPEI_TZ) < cutoff:
            continue

        code = str(row["reason_code"] or "unspecified").strip()
        if code not in CANCELLATION_REASON_LABELS:
            code = "unspecified"
        reason_counts[code] += 1
        unclassified += int(code == "unspecified")

        amount = int(
            row["customer_pay_amount"]
            if row["customer_pay_amount"] is not None
            else (row["amount"] or 0)
        )
        lost_value += max(0, amount)

        category = str(row["category"] or "未分類").strip() or "未分類"
        category_counts[category]["count"] += 1
        category_counts[category]["lost_value"] += max(0, amount)

        if len(recent_rows) < 20:
            recent_rows.append(
                {
                    "order_id": int(row["order_id"]),
                    "order_no": str(
                        row["bot_order_no"]
                        or f"WEB-{int(row['order_id'])}"
                    ),
                    "category": category,
                    "item": str(row["item"] or "未紀錄"),
                    "reason_code": code,
                    "reason_label": CANCELLATION_REASON_LABELS[code],
                    "reason_text": str(row["reason_text"] or ""),
                    "source": str(row["source"] or ""),
                    "created_at": str(row["created_at"] or ""),
                    "amount": max(0, amount),
                }
            )

    reasons = [
        {
            "code": code,
            "label": CANCELLATION_REASON_LABELS.get(code, code),
            "count": count,
        }
        for code, count in reason_counts.items()
    ]
    reasons.sort(key=lambda row: (-int(row["count"]), str(row["label"])))

    categories = [
        {
            "category": category,
            "count": values["count"],
            "lost_value": values["lost_value"],
        }
        for category, values in category_counts.items()
    ]
    categories.sort(
        key=lambda row: (
            -int(row["count"]),
            -int(row["lost_value"]),
            str(row["category"]),
        )
    )

    result["lost_value"] = lost_value
    result["unclassified"] = unclassified
    result["reasons"] = reasons
    result["categories"] = categories[:20]
    result["recent"] = recent_rows
    return result


def build_operations_monitoring_snapshot(
    *,
    days: int = 30,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    return {
        "days": max(1, min(int(days or 30), 365)),
        "smart_dispatch": build_smart_dispatch_snapshot(
            days=days,
            db_file=db_file,
        ),
        "cancellations": build_cancellation_snapshot(
            days=days,
            db_file=db_file,
        ),
    }
