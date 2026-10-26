from __future__ import annotations

from sqlalchemy import text


_MIGRATION_KEY = "20261026_game_threshold_15_v5"
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
    """Install the owner-approved entertainment loyalty policy.

    - Hourly entertainment: 10H -> 1H.
    - Game-based entertainment: 15 games -> 1 game.
    - Current and already-paid active orders participate in eligibility immediately;
      customers do not need to wait for order close before the next checkout can use
      the accumulated service units.
    - A single order may consume at most one loyalty reward, even if it crosses
      multiple thresholds. Any additional earned value remains available later.
    """
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
        _sync_existing_game_progress(loyalty, bind)

    def preview_same_order_benefit_immediate_one_per_order(
        customer_id,
        *,
        rule_key: str,
        quantity: int,
        player_count: int = 1,
    ):
        """Preview immediate checkout eligibility across closed + active paid units."""
        policy = loyalty.loyalty_policy_for_rule(rule_key)
        rule = loyalty._rule_for_key(rule_key)
        customer = str(customer_id or "").strip()
        if policy is None or rule is None or not customer:
            return None

        requested_players = max(1, int(player_count or 1))
        companion_count = loyalty._service_companion_count(rule, requested_players)
        current_units = float(max(0, int(quantity or 0)) * companion_count)
        if current_units <= 0:
            return None

        loyalty.ensure_loyalty_tables()
        scope = loyalty.loyalty_scope_key(rule_key, requested_players)
        threshold = float(policy["threshold_units"] or 0)
        if threshold <= 0:
            return None

        with loyalty.engine.begin() as conn:
            progress_row = conn.execute(text("""
                SELECT progress_units, debt_units
                FROM customer_loyalty_progress
                WHERE customer_discord_id = :customer_id
                  AND scope_key = :scope_key
                LIMIT 1
            """), {
                "customer_id": customer,
                "scope_key": scope,
            }).mappings().first()
            previous = float(progress_row.get("progress_units") or 0) if progress_row else 0.0
            debt_before = float(progress_row.get("debt_units") or 0) if progress_row else 0.0
            open_units = _open_paid_units_for_scope(
                loyalty,
                conn,
                customer_id=customer,
                scope_key=scope,
            )
            credited_units = max(0.0, open_units + current_units - debt_before)
            projected_total = previous + credited_units
            earned_count = max(0, int(projected_total // threshold))
            pending_count = loyalty._pending_same_order_claim_count(
                conn,
                customer_id=customer,
                scope_key=scope,
            )

        available_count = max(0, earned_count - pending_count)
        if available_count <= 0:
            return None

        # Owner rule: regardless of how many thresholds this checkout projection
        # crosses, this one order can consume only one loyalty reward.
        base_units = float(policy["benefit_units"] or 0)
        benefit = {
            "id": None,
            "source": "same_order",
            "same_order": True,
            "earned_count": 1,
            "scope_key": scope,
            "rule_key": str(rule_key),
            "rule_label": loyalty._loyalty_display_label(
                rule_key,
                getattr(rule, "label", rule_key),
            ),
            "pricing_type": str(policy["pricing_type"]),
            "player_count": requested_players,
            "benefit_kind": str(policy["benefit_kind"]),
            "benefit_units": base_units,
            "threshold_units": threshold,
        }
        benefit["title"] = loyalty._coupon_title(benefit)
        return benefit

    loyalty.ensure_loyalty_tables = ensure_loyalty_tables_with_owner_policy
    loyalty.preview_same_order_benefit = preview_same_order_benefit_immediate_one_per_order
    loyalty._owner_20261023_policy_installed = True


__all__ = ["install_loyalty_policy_20261023"]
