from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (str(table),),
        ).fetchone()
        is not None
    )


def _format_units(value: object) -> str:
    number = float(value or 0)
    return f"{number:g}"


def _benefit_text(kind: object, units: object) -> str:
    benefit_kind = str(kind or "")
    amount = float(units or 0)
    if benefit_kind == "extra_hours":
        if abs(amount - 0.5) < 0.001:
            return "+30 分鐘"
        return f"+{amount:g} 小時"
    if benefit_kind == "extra_games":
        return f"+{int(round(amount))} 局"
    return "福利"


def load_customer_loyalty(
    db_path: Path,
    customer_ids: Iterable[str],
) -> dict[str, dict[str, Any]]:
    ids = [str(value or "").strip() for value in customer_ids]
    ids = [value for value in ids if value]
    result = {
        customer_id: {
            "progress": [],
            "coupon_counts": {
                "active": 0,
                "reserved": 0,
                "redeemed": 0,
                "expired": 0,
                "other": 0,
            },
        }
        for customer_id in ids
    }
    if not ids or not Path(db_path).exists():
        return result

    placeholders = ",".join("?" for _ in ids)
    with _connect(Path(db_path)) as conn:
        if _table_exists(conn, "customer_loyalty_progress"):
            rows = conn.execute(
                f"""
                SELECT
                    customer_discord_id,
                    scope_key,
                    rule_key,
                    rule_label,
                    pricing_type,
                    player_count,
                    progress_units,
                    threshold_units,
                    benefit_kind,
                    benefit_units,
                    updated_at
                FROM customer_loyalty_progress
                WHERE customer_discord_id IN ({placeholders})
                  AND COALESCE(progress_units, 0) > 0.0001
                ORDER BY customer_discord_id, updated_at DESC, scope_key ASC
                """,
                ids,
            ).fetchall()

            for raw in rows:
                customer_id = str(raw["customer_discord_id"] or "")
                if customer_id not in result:
                    continue
                player_count = max(1, int(raw["player_count"] or 1))
                title = str(raw["rule_label"] or raw["rule_key"] or "福利進度")
                if player_count > 1:
                    title = f"{title}｜{player_count}位"

                pricing_type = str(raw["pricing_type"] or "")
                unit_label = "H" if pricing_type == "hourly" else "局" if pricing_type == "game" else ""
                current = float(raw["progress_units"] or 0)
                threshold = float(raw["threshold_units"] or 0)
                percent = 0
                if threshold > 0:
                    percent = max(0, min(100, int(round(current / threshold * 100))))

                result[customer_id]["progress"].append(
                    {
                        "scope_key": str(raw["scope_key"] or ""),
                        "rule_key": str(raw["rule_key"] or ""),
                        "title": title,
                        "pricing_type": pricing_type,
                        "player_count": player_count,
                        "progress_units": current,
                        "threshold_units": threshold,
                        "progress_text": (
                            f"{_format_units(current)} / {_format_units(threshold)}{unit_label}"
                        ),
                        "benefit_text": _benefit_text(
                            raw["benefit_kind"],
                            raw["benefit_units"],
                        ),
                        "percent": percent,
                        "updated_at": str(raw["updated_at"] or ""),
                    }
                )

        if _table_exists(conn, "customer_benefit_coupons"):
            coupon_rows = conn.execute(
                f"""
                SELECT customer_discord_id, status, COUNT(*) AS count
                FROM customer_benefit_coupons
                WHERE customer_discord_id IN ({placeholders})
                GROUP BY customer_discord_id, status
                """,
                ids,
            ).fetchall()

            for raw in coupon_rows:
                customer_id = str(raw["customer_discord_id"] or "")
                if customer_id not in result:
                    continue
                status = str(raw["status"] or "").strip().lower()
                key = status if status in {"active", "reserved", "redeemed", "expired"} else "other"
                result[customer_id]["coupon_counts"][key] += int(raw["count"] or 0)

    return result


def enrich_customer_rows(
    db_path: Path,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    loyalty = load_customer_loyalty(
        Path(db_path),
        [str(row.get("customer_discord_id") or "") for row in rows],
    )

    enriched: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        customer_id = str(row.get("customer_discord_id") or "")
        data = loyalty.get(
            customer_id,
            {
                "progress": [],
                "coupon_counts": {
                    "active": 0,
                    "reserved": 0,
                    "redeemed": 0,
                    "expired": 0,
                    "other": 0,
                },
            },
        )
        row["loyalty_progress"] = list(data.get("progress") or [])
        row["loyalty_coupon_counts"] = dict(data.get("coupon_counts") or {})
        row["loyalty_has_anything"] = bool(
            row["loyalty_progress"]
            or any(int(value or 0) > 0 for value in row["loyalty_coupon_counts"].values())
        )
        enriched.append(row)
    return enriched
