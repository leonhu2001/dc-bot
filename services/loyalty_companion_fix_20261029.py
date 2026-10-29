from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text


_MIGRATION_KEY = "20261029_loyalty_companion_price_and_units_v5"
_PLAYER_COUNT_KEYS = (
    "player_count",
    "requested_player_count",
    "service_player_count",
    "companion_count",
)


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _find_player_count(value: Any) -> int | None:
    """Find the selected companion count in old and new checkout snapshots."""
    if isinstance(value, dict):
        for key in _PLAYER_COUNT_KEYS:
            if key in value:
                parsed = _positive_int(value.get(key))
                if parsed is not None:
                    return parsed
        # Prefer the checkout source-of-truth containers before walking the rest.
        for key in ("quote", "input", "preview", "selection", "order", "data"):
            if key in value:
                parsed = _find_player_count(value.get(key))
                if parsed is not None:
                    return parsed
        for nested in value.values():
            parsed = _find_player_count(nested)
            if parsed is not None:
                return parsed
    elif isinstance(value, (list, tuple)):
        for nested in value:
            parsed = _find_player_count(nested)
            if parsed is not None:
                return parsed
    return None


def extract_player_count(row: dict[str, Any]) -> int:
    """Read companion count from every snapshot layout used by Discord/Web orders."""
    for column in ("price_snapshot_json", "quote_snapshot_json"):
        raw = row.get(column)
        if not raw:
            continue
        try:
            snapshot = json.loads(str(raw))
        except Exception:
            continue
        parsed = _find_player_count(snapshot)
        if parsed is not None:
            return parsed

    # Some repair/admin callers already provide decoded data or a direct count.
    parsed = _find_player_count(row)
    return parsed if parsed is not None else 1


def _selected_unit_total(rule: Any, player_count: int) -> int:
    """Return the formal total price for one hour/game at the selected headcount."""
    requested = max(1, int(player_count or 1))
    try:
        from services.multi_seat_order_policy_20261028 import (
            get_player_count_price_table,
            normalize_rule_player_count,
        )

        normalized = normalize_rule_player_count(rule, requested)
        table = get_player_count_price_table(rule)
        if table:
            if normalized not in table:
                return 0
            return max(0, int(table[normalized]))
        requested = normalized
    except Exception:
        pass

    amount = max(0, int(getattr(rule, "price", 0) or 0))
    if bool(getattr(rule, "price_multiply_player_count", False)):
        amount *= requested
    return amount


def calculate_for_rule(
    rule: Any,
    *,
    player_count: int,
    coupon: dict[str, Any] | None,
    companion_count: int | None = None,
) -> int:
    """Value one cumulative reward as one companion's share of the selected tier.

    Example: a 2-companion hourly tier priced at 600 has a one-hour reward value
    of 600 / 2 = 300. This intentionally follows the formal tier table instead of
    the one-companion price, so nonlinear multi-seat prices remain correct.
    """
    if rule is None or not coupon:
        return 0
    kind = str(coupon.get("benefit_kind") or "")
    try:
        units = float(coupon.get("benefit_units") or 0)
    except (TypeError, ValueError):
        units = 0.0
    if units <= 0 or kind not in {"extra_hours", "extra_games"}:
        return 0

    requested = max(1, int(player_count or 1))
    if companion_count is None:
        required = getattr(rule, "required_staff_count", 1)
        if str(required) == "player_count":
            companions = requested
        else:
            try:
                companions = max(1, int(required or 1))
            except (TypeError, ValueError):
                companions = requested if bool(getattr(rule, "player_count_enabled", False)) else 1
    else:
        companions = max(1, int(companion_count or 1))

    selected_total = _selected_unit_total(rule, requested)
    if selected_total <= 0:
        return 0
    return max(0, int(round((selected_total / companions) * units)))


def _repair_existing_progress(loyalty) -> dict[str, int]:
    """One-time idempotent rebuild so already-closed multi-seat orders are topped up."""
    loyalty.ensure_loyalty_tables()
    with loyalty.engine.begin() as conn:
        applied = conn.execute(text("""
            SELECT migration_key
            FROM loyalty_migrations
            WHERE migration_key = :migration_key
            LIMIT 1
        """), {"migration_key": _MIGRATION_KEY}).first()
        if applied is not None:
            return {"customers": 0, "issued": 0, "revoked": 0}

        has_orders = conn.execute(text("""
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'web_orders'
            LIMIT 1
        """)).first()
        if has_orders is None:
            conn.execute(text("""
                INSERT INTO loyalty_migrations (migration_key, applied_at, note)
                VALUES (:migration_key, :applied_at, 'no_web_orders_table')
            """), {
                "migration_key": _MIGRATION_KEY,
                "applied_at": loyalty.get_taipei_now_iso(),
            })
            return {"customers": 0, "issued": 0, "revoked": 0}

        rows = conn.execute(text("""
            SELECT DISTINCT customer_discord_id, order_rule_key
            FROM web_orders
            WHERE status = 'closed'
              AND customer_discord_id IS NOT NULL
              AND TRIM(CAST(customer_discord_id AS TEXT)) <> ''
        """)).mappings().all()
        customers = sorted({
            str(row.get("customer_discord_id") or "").strip()
            for row in rows
            if loyalty.loyalty_policy_for_rule(str(row.get("order_rule_key") or "").strip()) is not None
        })

        issued = 0
        revoked = 0
        for customer_id in customers:
            summary = loyalty.reconcile_customer_loyalty_in_connection(conn, customer_id)
            issued += int(summary.get("issued") or 0)
            revoked += int(summary.get("revoked") or 0)

        now = loyalty.get_taipei_now_iso()
        conn.execute(text("""
            INSERT INTO loyalty_migrations (migration_key, applied_at, note)
            VALUES (:migration_key, :applied_at, :note)
        """), {
            "migration_key": _MIGRATION_KEY,
            "applied_at": now,
            "note": (
                f"reconciled_customers={len(customers)};"
                f"issued={issued};revoked={revoked}"
            ),
        })
        return {"customers": len(customers), "issued": issued, "revoked": revoked}


def install_loyalty_companion_fix_20261029() -> None:
    from services import loyalty_benefits as loyalty

    if bool(getattr(loyalty, "_loyalty_companion_fix_20261029_installed", False)):
        return

    loyalty._extract_player_count = extract_player_count

    def calculate_coupon_service_value(
        *,
        rule_key: str,
        player_count: int,
        coupon: dict[str, Any] | None,
    ) -> int:
        rule = loyalty._rule_for_key(rule_key)
        companion_count = loyalty._service_companion_count(rule, player_count)
        return calculate_for_rule(
            rule,
            player_count=player_count,
            coupon=coupon,
            companion_count=companion_count,
        )

    loyalty.calculate_coupon_service_value = calculate_coupon_service_value
    loyalty._loyalty_companion_fix_20261029_installed = True

    # Run after replacing the extractor: both the existing migration/reconcile code
    # and this new repair now use the corrected headcount source of truth.
    _repair_existing_progress(loyalty)


__all__ = [
    "calculate_for_rule",
    "extract_player_count",
    "install_loyalty_companion_fix_20261029",
]
