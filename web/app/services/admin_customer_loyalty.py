from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable


KNOWN_STATUSES = ("active", "reserved", "redeemed", "expired", "revoked")
STATUS_LABELS = {
    "active": "可使用",
    "reserved": "使用中",
    "redeemed": "已使用",
    "expired": "已過期",
    "revoked": "已收回",
}


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
    return f"{float(value or 0):g}"


def _display_label(rule_key: object, fallback: object = "") -> str:
    label = str(fallback or rule_key or "福利").strip()
    for suffix in ("｜單陪", "｜雙陪", "｜三陪", "｜四陪"):
        if label.endswith(suffix):
            label = label[: -len(suffix)]
            break
    return label or str(rule_key or "福利")


def _benefit_text(kind: object, units: object) -> str:
    benefit_kind = str(kind or "")
    amount = float(units or 0)
    if benefit_kind == "extra_hours":
        if abs(amount - 0.5) < 0.001:
            return "折抵 30 分鐘額度"
        return f"折抵 {amount:g} 小時額度"
    if benefit_kind == "extra_games":
        return f"折抵 {int(round(amount))} 局額度"
    return "福利額度"


def _time_text(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "—"
    return raw.replace("T", " ").replace("+08:00", "")[:16]


def _empty_customer_data() -> dict[str, Any]:
    return {
        "progress": [],
        "coupons": [],
        "active_coupons": [],
        "coupon_counts": {
            "active": 0,
            "reserved": 0,
            "redeemed": 0,
            "expired": 0,
            "revoked": 0,
            "other": 0,
        },
        "groups": [],
    }


def _build_groups(data: dict[str, Any]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}

    for progress in data.get("progress") or []:
        scope = str(progress.get("scope_key") or progress.get("rule_key") or "unknown")
        group = groups.setdefault(
            scope,
            {
                "scope_key": scope,
                "title": str(progress.get("title") or "福利"),
                "progress": [],
                "coupons": [],
            },
        )
        group["progress"].append(progress)

    for coupon in data.get("coupons") or []:
        scope = str(coupon.get("scope_key") or coupon.get("rule_key") or "unknown")
        group = groups.setdefault(
            scope,
            {
                "scope_key": scope,
                "title": str(coupon.get("service_title") or "福利"),
                "progress": [],
                "coupons": [],
            },
        )
        group["coupons"].append(coupon)

    result = list(groups.values())
    result.sort(key=lambda item: str(item.get("title") or item.get("scope_key") or ""))
    return result


def load_customer_loyalty(
    db_path: Path,
    customer_ids: Iterable[str],
) -> dict[str, dict[str, Any]]:
    ids = [str(value or "").strip() for value in customer_ids]
    ids = list(dict.fromkeys(value for value in ids if value))
    result = {customer_id: _empty_customer_data() for customer_id in ids}
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
                        "title": _display_label(raw["rule_key"], raw["rule_label"]),
                        "pricing_type": pricing_type,
                        "progress_units": current,
                        "threshold_units": threshold,
                        "progress_text": f"{_format_units(current)} / {_format_units(threshold)}{unit_label}",
                        "benefit_text": _benefit_text(raw["benefit_kind"], raw["benefit_units"]),
                        "percent": percent,
                        "updated_at": str(raw["updated_at"] or ""),
                        "updated_at_text": _time_text(raw["updated_at"]),
                    }
                )

        if _table_exists(conn, "customer_benefit_coupons"):
            coupon_rows = conn.execute(
                f"""
                SELECT
                    id,
                    customer_discord_id,
                    scope_key,
                    rule_key,
                    rule_label,
                    pricing_type,
                    benefit_kind,
                    benefit_units,
                    status,
                    source,
                    issued_at,
                    expires_at,
                    reserved_order_id,
                    redeemed_order_id,
                    redeemed_at
                FROM customer_benefit_coupons
                WHERE customer_discord_id IN ({placeholders})
                ORDER BY
                    customer_discord_id,
                    CASE status
                        WHEN 'active' THEN 0
                        WHEN 'reserved' THEN 1
                        WHEN 'redeemed' THEN 2
                        WHEN 'expired' THEN 3
                        ELSE 4
                    END,
                    issued_at DESC,
                    id DESC
                """,
                ids,
            ).fetchall()

            for raw in coupon_rows:
                customer_id = str(raw["customer_discord_id"] or "")
                if customer_id not in result:
                    continue

                status = str(raw["status"] or "").strip().lower()
                count_key = status if status in KNOWN_STATUSES else "other"
                result[customer_id]["coupon_counts"][count_key] += 1

                service_title = _display_label(raw["rule_key"], raw["rule_label"])
                benefit_text = _benefit_text(raw["benefit_kind"], raw["benefit_units"])
                coupon = {
                    "id": int(raw["id"]),
                    "scope_key": str(raw["scope_key"] or ""),
                    "rule_key": str(raw["rule_key"] or ""),
                    "service_title": service_title,
                    "title": f"{service_title}｜{benefit_text}",
                    "pricing_type": str(raw["pricing_type"] or ""),
                    "benefit_kind": str(raw["benefit_kind"] or ""),
                    "benefit_units": float(raw["benefit_units"] or 0),
                    "benefit_text": benefit_text,
                    "status": status,
                    "status_label": STATUS_LABELS.get(status, status or "其他"),
                    "source": str(raw["source"] or ""),
                    "issued_at": str(raw["issued_at"] or ""),
                    "issued_at_text": _time_text(raw["issued_at"]),
                    "expires_at": str(raw["expires_at"] or ""),
                    "expires_at_text": _time_text(raw["expires_at"]),
                    "reserved_order_id": raw["reserved_order_id"],
                    "redeemed_order_id": raw["redeemed_order_id"],
                    "redeemed_at": str(raw["redeemed_at"] or ""),
                    "redeemed_at_text": _time_text(raw["redeemed_at"]),
                }
                result[customer_id]["coupons"].append(coupon)
                if status == "active":
                    result[customer_id]["active_coupons"].append(coupon)

    for data in result.values():
        data["groups"] = _build_groups(data)

    return result


def load_customer_loyalty_detail(
    db_path: Path,
    customer_id: str | int,
) -> dict[str, Any]:
    customer = str(customer_id or "").strip()
    if not customer:
        return _empty_customer_data()
    return load_customer_loyalty(Path(db_path), [customer]).get(
        customer,
        _empty_customer_data(),
    )


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
        data = loyalty.get(customer_id, _empty_customer_data())
        row["loyalty_progress"] = list(data.get("progress") or [])
        row["loyalty_coupons"] = list(data.get("coupons") or [])
        row["loyalty_active_coupons"] = list(data.get("active_coupons") or [])
        row["loyalty_coupon_counts"] = dict(data.get("coupon_counts") or {})
        row["loyalty_has_anything"] = bool(
            row["loyalty_progress"]
            or any(int(value or 0) > 0 for value in row["loyalty_coupon_counts"].values())
        )
        enriched.append(row)
    return enriched
