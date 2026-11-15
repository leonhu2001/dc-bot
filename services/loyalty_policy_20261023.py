from __future__ import annotations

from sqlalchemy import text


_MIGRATION_KEY = "20261026_game_threshold_15_v5"
_FULL_RECONCILE_MIGRATION_KEY = "20261026_entertainment_loyalty_full_reconcile_v6"
_GAME_THRESHOLD = 15.0
_OPEN_LOYALTY_STATUSES = {"active", "paid", "stored"}


def _eligible_game_rule(loyalty, rule_key: object) -> bool:
    policy = loyalty.loyalty_policy_for_rule(str(rule_key or "").strip())
    return bool(policy and str(policy.get("pricing_type") or "") == "game")


def _sync_existing_game_progress(loyalty, bind) -> None:
    """Rebuild stored game-based loyalty state against the owner-approved 15-game rule.

    Active/expired rewards that were over-issued by the old 10-game threshold may be
    revoked by the existing reconciliation routine. Reserved/redeemed rewards are
    preserved and converted to loyalty debt, matching normal admin reconciliation.
    """
    with bind.begin() as conn:
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


def _sync_all_entertainment_progress(loyalty, bind) -> None:
    """One-time full rebuild for undercounted entertainment loyalty progress.

    Earlier companion-unit repairs were themselves one-time migrations, so a server
    that had already recorded those migration keys could keep stale single-person
    units for historical double/triple/quad orders. This pass intentionally uses a
    new migration key and rebuilds every currently eligible customer's closed-order
    pools with the current per-companion calculation. Missing coupons are issued by
    the normal reconciliation routine; redeemed/reserved rewards remain protected.
    """
    with bind.begin() as conn:
        applied = conn.execute(text("""
            SELECT migration_key
            FROM loyalty_migrations
            WHERE migration_key = :migration_key
            LIMIT 1
        """), {"migration_key": _FULL_RECONCILE_MIGRATION_KEY}).first()
        if applied is not None:
            return

        affected_customers: set[str] = set()

        has_orders = conn.execute(text("""
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'web_orders'
            LIMIT 1
        """)).first()
        if has_orders is not None:
            rows = conn.execute(text("""
                SELECT DISTINCT customer_discord_id, order_rule_key
                FROM web_orders
                WHERE status = 'closed'
                  AND customer_discord_id IS NOT NULL
                ORDER BY customer_discord_id
            """)).fetchall()
            for row in rows:
                customer_id = str(row[0] or "").strip()
                rule_key = str(row[1] or "").strip()
                if customer_id and loyalty.loyalty_policy_for_rule(rule_key) is not None:
                    affected_customers.add(customer_id)

        for row in conn.execute(text("""
            SELECT customer_discord_id, rule_key
            FROM customer_loyalty_progress
        """)).fetchall():
            customer_id = str(row[0] or "").strip()
            rule_key = str(row[1] or "").strip()
            if customer_id and loyalty.loyalty_policy_for_rule(rule_key) is not None:
                affected_customers.add(customer_id)

        for row in conn.execute(text("""
            SELECT DISTINCT customer_discord_id, rule_key
            FROM customer_benefit_coupons
            WHERE source = 'loyalty'
        """)).fetchall():
            customer_id = str(row[0] or "").strip()
            rule_key = str(row[1] or "").strip()
            if customer_id and loyalty.loyalty_policy_for_rule(rule_key) is not None:
                affected_customers.add(customer_id)

        reconciled = 0
        revoked = 0
        issued = 0
        scopes = 0
        for customer_id in sorted(affected_customers):
            summary = loyalty.reconcile_customer_loyalty_in_connection(conn, customer_id)
            reconciled += 1
            revoked += int(summary.get("revoked") or 0)
            issued += int(summary.get("issued") or 0)
            scopes += int(summary.get("scopes") or 0)

        conn.execute(text("""
            INSERT INTO loyalty_migrations (migration_key, applied_at, note)
            VALUES (:migration_key, :applied_at, :note)
        """), {
            "migration_key": _FULL_RECONCILE_MIGRATION_KEY,
            "applied_at": loyalty.get_taipei_now_iso(),
            "note": (
                f"reconciled_customers={reconciled};"
                f"scopes={scopes};revoked={revoked};issued={issued}"
            ),
        })


def _open_paid_units_for_scope(loyalty, conn, *, customer_id: str, scope_key: str) -> float:
    """Return service units from paid/active orders that are not closed yet.

    Closed orders already live in customer_loyalty_progress and must not be counted
    here. Pending unpaid orders are intentionally excluded; the order currently being
    quoted is added separately by the same-order preview.
    """
    try:
        rows = conn.execute(text("""
            SELECT *
            FROM web_orders
            WHERE customer_discord_id = :customer_id
              AND LOWER(COALESCE(status, '')) IN ('active', 'paid', 'stored')
            ORDER BY id ASC
        """), {"customer_id": customer_id}).mappings().all()
    except Exception:
        return 0.0

    total = 0.0
    for raw in rows:
        row = dict(raw)
        rule_key = str(row.get("order_rule_key") or "").strip()
        policy = loyalty.loyalty_policy_for_rule(rule_key)
        if policy is None:
            continue
        try:
            if not loyalty._event_time_is_in_scope(row):
                continue
            if loyalty._qualifying_paid_amount(row) <= 0:
                continue
        except Exception:
            continue

        player_count = loyalty._extract_player_count(row)
        if loyalty.loyalty_scope_key(rule_key, player_count) != scope_key:
            continue

        rule = loyalty._rule_for_key(rule_key)
        companion_count = loyalty._service_companion_count(rule, player_count)
        try:
            quantity = max(0, int(row.get("quantity") or 0))
        except (TypeError, ValueError):
            quantity = 0
        total += float(quantity * companion_count)

    return total


def install_loyalty_policy_20261023() -> None:
    """Legacy compatibility entrypoint.

    Actual threshold constants, idempotent schema migrations and checkout
    preview are now owned by loyalty_benefits, not rebound on package import.
    """
    return None


__all__ = ["install_loyalty_policy_20261023"]
