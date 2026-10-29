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
    if isinstance(value, dict):
        for key in _PLAYER_COUNT_KEYS:
            parsed = _positive_int(value.get(key)) if key in value else None
            if parsed is not None:
                return parsed
        for key in ("quote", "input", "preview", "selection", "order", "data"):
            parsed = _find_player_count(value.get(key)) if key in value else None
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
    """Compatibility helper matching loyalty_benefits' canonical parser."""

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
    parsed = _find_player_count(row)
    return parsed if parsed is not None else 1


def _canonical_rule_for_compat(rule: Any) -> Any:
    """Resolve a partial legacy/test rule to the formal rule when possible.

    Older callers passed lightweight objects that carried only ``key`` and ``price``.
    Reading the live rule by key preserves the old compatibility API without copying
    any player-count price table back into this dated migration module.
    """

    key = str(getattr(rule, "key", "") or "").strip()
    if not key:
        return rule
    try:
        from services.order_rules import ORDER_RULES

        canonical = ORDER_RULES.get(key)
    except Exception:
        canonical = None
    return canonical or rule


def _selected_unit_total(rule: Any, player_count: int) -> int:
    """Read the selected tier directly from the formal OrderRule."""

    rule = _canonical_rule_for_compat(rule)
    requested = max(1, int(player_count or 1))
    if bool(getattr(rule, "player_count_enabled", False)):
        minimum = max(1, int(getattr(rule, "min_player_count", 1) or 1))
        maximum_raw = getattr(rule, "max_player_count", None)
        maximum = int(maximum_raw) if maximum_raw is not None else minimum
        maximum = max(minimum, maximum)
        if requested < minimum or requested > maximum:
            requested = minimum

    table = dict(getattr(rule, "player_count_prices", None) or {})
    if table:
        normalized = {int(count): int(price) for count, price in table.items()}
        if requested in normalized:
            return max(0, normalized[requested])

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
    """Compatibility helper for one companion's share of the selected formal tier."""

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
    """One-time data reconciliation only; never rebind production functions.

    The migration row is claimed as the first write in the same transaction. SQLite
    serializes competing writers, so Bot/Web concurrent startup cannot both run the
    reconciliation. A failed transaction rolls the claim back and a later startup
    can safely retry it.
    """

    loyalty.ensure_loyalty_tables()
    with loyalty.engine.begin() as conn:
        claimed = conn.execute(text("""
            INSERT OR IGNORE INTO loyalty_migrations (migration_key, applied_at, note)
            VALUES (:migration_key, :applied_at, 'in_progress')
        """), {
            "migration_key": _MIGRATION_KEY,
            "applied_at": loyalty.get_taipei_now_iso(),
        })
        if int(claimed.rowcount or 0) == 0:
            return {"customers": 0, "issued": 0, "revoked": 0}

        has_orders = conn.execute(text("""
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'web_orders' LIMIT 1
        """)).first()
        if has_orders is None:
            conn.execute(text("""
                UPDATE loyalty_migrations
                SET note = 'no_web_orders_table'
                WHERE migration_key = :migration_key
            """), {"migration_key": _MIGRATION_KEY})
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

        issued = revoked = 0
        for customer_id in customers:
            summary = loyalty.reconcile_customer_loyalty_in_connection(conn, customer_id)
            issued += int(summary.get("issued") or 0)
            revoked += int(summary.get("revoked") or 0)

        conn.execute(text("""
            UPDATE loyalty_migrations
            SET applied_at = :applied_at, note = :note
            WHERE migration_key = :migration_key
        """), {
            "migration_key": _MIGRATION_KEY,
            "applied_at": loyalty.get_taipei_now_iso(),
            "note": f"reconciled_customers={len(customers)};issued={issued};revoked={revoked}",
        })
        return {"customers": len(customers), "issued": issued, "revoked": revoked}


def run_loyalty_companion_repair_20261029() -> dict[str, int]:
    from services import loyalty_benefits as loyalty

    return _repair_existing_progress(loyalty)


def install_loyalty_companion_fix_20261029() -> None:
    """Deprecated compatibility entrypoint; now performs data repair only."""

    run_loyalty_companion_repair_20261029()


__all__ = [
    "calculate_for_rule",
    "extract_player_count",
    "run_loyalty_companion_repair_20261029",
    "install_loyalty_companion_fix_20261029",
]
