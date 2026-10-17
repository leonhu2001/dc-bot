from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


TAIPEI_TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEB_DB = ROOT / "web_dashboard.db"
MIGRATION_KEY = "cs_margin_pool_25_v1_existing_orders_legacy"
LEGACY_POLICY = "legacy_gross_5_v1"
NEW_POLICY = "margin_pool_25_v1"


def _finance_container(snapshot: dict) -> dict:
    preview = snapshot.get("preview")
    if isinstance(preview, dict):
        finance = preview.get("finance")
        if not isinstance(finance, dict):
            finance = {}
            preview["finance"] = finance
        return finance

    finance = snapshot.get("finance")
    if not isinstance(finance, dict):
        finance = {}
        snapshot["finance"] = finance
    return finance


def freeze_existing_orders_on_legacy_cs_policy(
    web_db: str | Path | None = None,
) -> int:
    """Tag orders that existed before first deploy of the new CS policy.

    The migration is idempotent and runs only once per database. This makes the
    effective moment the first process startup after deployment: existing orders
    keep the historical gross 5% CS formula, while orders created afterwards use
    25% of the post-worker margin pool.
    """
    path = Path(web_db) if web_db is not None else DEFAULT_WEB_DB
    if not path.exists():
        return 0

    now = datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")
    changed = 0

    with sqlite3.connect(path, timeout=30) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_policy_migrations (
                migration_key TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        conn.execute("BEGIN IMMEDIATE")
        already = conn.execute(
            "SELECT 1 FROM runtime_policy_migrations WHERE migration_key=? LIMIT 1",
            (MIGRATION_KEY,),
        ).fetchone()
        if already is not None:
            conn.commit()
            return 0

        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='web_orders' LIMIT 1"
        ).fetchone()
        if exists is not None:
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(web_orders)").fetchall()
            }
            if "price_snapshot_json" in columns:
                rows = conn.execute(
                    "SELECT id, price_snapshot_json FROM web_orders"
                ).fetchall()
                for order_id, raw in rows:
                    try:
                        snapshot = json.loads(str(raw or "{}"))
                    except Exception:
                        snapshot = {}
                    if not isinstance(snapshot, dict):
                        snapshot = {}
                    finance = _finance_container(snapshot)
                    if finance.get("customer_service_payout_policy"):
                        continue
                    finance["customer_service_payout_policy"] = LEGACY_POLICY
                    conn.execute(
                        "UPDATE web_orders SET price_snapshot_json=? WHERE id=?",
                        (
                            json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
                            int(order_id),
                        ),
                    )
                    changed += 1

        conn.execute(
            "INSERT INTO runtime_policy_migrations (migration_key, applied_at) VALUES (?, ?)",
            (MIGRATION_KEY, now),
        )
        conn.commit()

    return changed
