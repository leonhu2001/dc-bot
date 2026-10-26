from __future__ import annotations

from sqlalchemy import text


_MIGRATION_KEY = "20261026_entertainment_loyalty_confirmed_reconcile_v7"


def run_entertainment_loyalty_reconcile_v7() -> dict[str, int]:
    """Re-run the confirmed closed-order loyalty rebuild once on production.

    This is intentionally separate from the older migration keys. It gives the
    deployment a fresh, auditable pass after the companion-unit and 15-game
    policy fixes, so already-closed eligible entertainment orders are rebuilt
    immediately even on servers where older repair migrations had already run.
    """
    from services import loyalty_benefits as loyalty

    loyalty.ensure_loyalty_tables()

    with loyalty.engine.begin() as conn:
        applied = conn.execute(
            text(
                "SELECT migration_key FROM loyalty_migrations "
                "WHERE migration_key=:migration_key LIMIT 1"
            ),
            {"migration_key": _MIGRATION_KEY},
        ).first()
        if applied is not None:
            return {"customers": 0, "scopes": 0, "issued": 0, "revoked": 0}

        has_orders = conn.execute(
            text(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='web_orders' LIMIT 1"
            )
        ).first()

        affected_customers: set[str] = set()
        if has_orders is not None:
            rows = conn.execute(
                text(
                    "SELECT DISTINCT customer_discord_id, order_rule_key "
                    "FROM web_orders "
                    "WHERE status='closed' AND customer_discord_id IS NOT NULL "
                    "ORDER BY customer_discord_id"
                )
            ).fetchall()
            for customer_id_raw, rule_key_raw in rows:
                customer_id = str(customer_id_raw or "").strip()
                rule_key = str(rule_key_raw or "").strip()
                if (
                    customer_id
                    and rule_key
                    and loyalty.loyalty_policy_for_rule(rule_key) is not None
                ):
                    affected_customers.add(customer_id)

        scopes = 0
        issued = 0
        revoked = 0
        for customer_id in sorted(affected_customers):
            summary = loyalty.reconcile_customer_loyalty_in_connection(
                conn,
                customer_id,
            )
            scopes += int(summary.get("scopes") or 0)
            issued += int(summary.get("issued") or 0)
            revoked += int(summary.get("revoked") or 0)

        conn.execute(
            text(
                "INSERT INTO loyalty_migrations (migration_key, applied_at, note) "
                "VALUES (:migration_key, :applied_at, :note)"
            ),
            {
                "migration_key": _MIGRATION_KEY,
                "applied_at": loyalty.get_taipei_now_iso(),
                "note": (
                    f"customers={len(affected_customers)};"
                    f"scopes={scopes};issued={issued};revoked={revoked}"
                ),
            },
        )

    return {
        "customers": len(affected_customers),
        "scopes": scopes,
        "issued": issued,
        "revoked": revoked,
    }


__all__ = ["run_entertainment_loyalty_reconcile_v7"]
