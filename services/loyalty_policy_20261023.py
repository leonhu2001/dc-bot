from __future__ import annotations

from sqlalchemy import text


_MIGRATION_KEY = "20261026_game_threshold_15_v5"
_GAME_THRESHOLD = 15.0


def _eligible_game_rule(loyalty, rule_key: object) -> bool:
    policy = loyalty.loyalty_policy_for_rule(str(rule_key or "").strip())
    return bool(policy and str(policy.get("pricing_type") or "") == "game")


def _sync_existing_game_progress(loyalty) -> None:
    """Rebuild stored game-based loyalty state against the owner-approved 15-game rule.

    Active/expired rewards that were over-issued by the old 10-game threshold may be
    revoked by the existing reconciliation routine. Reserved/redeemed rewards are
    preserved and converted to loyalty debt, matching normal admin reconciliation.
    """
    with loyalty.engine.begin() as conn:
        applied = conn.execute(text("""
            SELECT migration_key
            FROM loyalty_migrations
            WHERE migration_key = :migration_key
            LIMIT 1
        """), {"migration_key": _MIGRATION_KEY}).first()
        if applied is not None:
            return

        affected_customers: set[str] = set()

        for row in conn.execute(text("""
            SELECT customer_discord_id, rule_key
            FROM customer_loyalty_progress
            WHERE pricing_type = 'game'
        """)).fetchall():
            customer_id = str(row[0] or "").strip()
            if customer_id and _eligible_game_rule(loyalty, row[1]):
                affected_customers.add(customer_id)

        for row in conn.execute(text("""
            SELECT DISTINCT customer_discord_id, rule_key
            FROM customer_benefit_coupons
            WHERE pricing_type = 'game'
              AND source = 'loyalty'
        """)).fetchall():
            customer_id = str(row[0] or "").strip()
            if customer_id and _eligible_game_rule(loyalty, row[1]):
                affected_customers.add(customer_id)

        has_orders = conn.execute(text("""
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'web_orders'
            LIMIT 1
        """)).first()
        if has_orders is not None:
            for row in conn.execute(text("""
                SELECT DISTINCT customer_discord_id, order_rule_key
                FROM web_orders
                WHERE status = 'closed'
                  AND customer_discord_id IS NOT NULL
            """)).fetchall():
                customer_id = str(row[0] or "").strip()
                if customer_id and _eligible_game_rule(loyalty, row[1]):
                    affected_customers.add(customer_id)

        reconciled = 0
        revoked = 0
        issued = 0
        for customer_id in sorted(affected_customers):
            summary = loyalty.reconcile_customer_loyalty_in_connection(conn, customer_id)
            reconciled += 1
            revoked += int(summary.get("revoked") or 0)
            issued += int(summary.get("issued") or 0)

        # Keep any surviving rows aligned even when they predate a source order that
        # can still be reconstructed by the current reconciliation policy.
        conn.execute(text("""
            UPDATE customer_loyalty_progress
            SET threshold_units = :threshold_units
            WHERE pricing_type = 'game'
        """), {"threshold_units": _GAME_THRESHOLD})

        conn.execute(text("""
            INSERT INTO loyalty_migrations (migration_key, applied_at, note)
            VALUES (:migration_key, :applied_at, :note)
        """), {
            "migration_key": _MIGRATION_KEY,
            "applied_at": loyalty.get_taipei_now_iso(),
            "note": (
                f"game_threshold={_GAME_THRESHOLD:g};"
                f"reconciled_customers={reconciled};"
                f"revoked={revoked};issued={issued}"
            ),
        })


def install_loyalty_policy_20261023() -> None:
    """Make 10H->1H and 15 games->1 game authoritative in every process."""
    from services import loyalty_benefits as loyalty

    # Hourly policy is intentionally unchanged; multi-companion service units are
    # already counted per companion by loyalty_benefits._service_companion_count().
    loyalty.HOURLY_THRESHOLD = 10.0
    loyalty.HOURLY_BONUS = 1.0
    loyalty.GAME_THRESHOLD = _GAME_THRESHOLD
    loyalty.GAME_BONUS = 1.0

    if getattr(loyalty, "_owner_20261023_policy_installed", False):
        return

    original_ensure = loyalty.ensure_loyalty_tables

    def ensure_loyalty_tables_with_owner_policy(bind=loyalty.engine) -> None:
        original_ensure(bind)
        _sync_existing_game_progress(loyalty)

    loyalty.ensure_loyalty_tables = ensure_loyalty_tables_with_owner_policy
    loyalty._owner_20261023_policy_installed = True


__all__ = ["install_loyalty_policy_20261023"]
