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
_OPEN_LOYALTY_STATUSES = {"active", "paid", "stored"}


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


def _merge_open_paid_progress(
    conn: sqlite3.Connection,
    *,
    placeholders: str,
    ids: list[str],
    result: dict[str, dict[str, Any]],
) -> None:
    """Add paid/open service units to display progress without persisting them.

    Closed orders remain the durable loyalty source of truth. Paid active/stored
    orders are shown as provisional progress so staff and customers can see the
    same units that the checkout eligibility logic already uses immediately.
    """
    if not _table_exists(conn, "web_orders"):
        return

    try:
        from services.loyalty_policy_20261023 import install_loyalty_policy_20261023
        from services import loyalty_benefits as loyalty

        install_loyalty_policy_20261023()
    except Exception:
        return

    try:
        rows = conn.execute(
            f"""
            SELECT *
            FROM web_orders
            WHERE customer_discord_id IN ({placeholders})
              AND LOWER(COALESCE(status, '')) IN ('active', 'paid', 'stored')
            ORDER BY id ASC
            """,
            ids,
        ).fetchall()
    except sqlite3.Error:
        return

    open_scopes: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        customer_id = str(row.get("customer_discord_id") or "").strip()
        rule_key = str(row.get("order_rule_key") or "").strip()
        if not customer_id or customer_id not in result or not rule_key:
            continue

        try:
            policy = loyalty.loyalty_policy_for_rule(rule_key)
            if policy is None:
                continue
            if not loyalty._event_time_is_in_scope(row):
                continue
            if loyalty._qualifying_paid_amount(row) <= 0:
                continue

            player_count = loyalty._extract_player_count(row)
            rule = loyalty._rule_for_key(rule_key)
            companion_count = loyalty._service_companion_count(rule, player_count)
            quantity = max(0, int(row.get("quantity") or 0))
            paid_units = float(quantity * companion_count)
            if paid_units <= 0:
                continue
            scope_key = loyalty.loyalty_scope_key(rule_key, player_count)
        except Exception:
            continue

        key = (customer_id, scope_key)
        entry = open_scopes.setdefault(
            key,
            {
                "customer_id": customer_id,
                "scope_key": scope_key,
                "rule_key": rule_key,
                "title": loyalty._loyalty_display_label(
                    rule_key,
                    getattr(rule, "label", rule_key),
                ),
                "pricing_type": str(policy.get("pricing_type") or ""),
                "threshold_units": float(policy.get("threshold_units") or 0),
                "benefit_kind": str(policy.get("benefit_kind") or ""),
                "benefit_units": float(policy.get("benefit_units") or 0),
                "open_paid_units": 0.0,
            },
        )
        entry["open_paid_units"] = float(entry["open_paid_units"]) + paid_units

    for (customer_id, scope_key), live in open_scopes.items():
        data = result[customer_id]
        existing = next(
            (
                item
                for item in data.get("progress") or []
                if str(item.get("scope_key") or "") == scope_key
            ),
            None,
        )
        pricing_type = str(live.get("pricing_type") or "")
        unit_label = "H" if pricing_type == "hourly" else "局" if pricing_type == "game" else ""
        threshold = float(live.get("threshold_units") or 0)
        open_units = float(live.get("open_paid_units") or 0)

        if existing is None:
            existing = {
                "scope_key": scope_key,
                "rule_key": str(live.get("rule_key") or ""),
                "title": str(live.get("title") or "福利"),
                "pricing_type": pricing_type,
                "progress_units": 0.0,
                "threshold_units": threshold,
                "benefit_text": _benefit_text(
                    live.get("benefit_kind"),
                    live.get("benefit_units"),
                ),
                "updated_at": "",
                "updated_at_text": "—",
            }
            data["progress"].append(existing)

        confirmed = float(existing.get("progress_units") or 0)
        projected = confirmed + open_units
        earned_preview = int(projected // threshold) if threshold > 0 else 0
        projected_remainder = (
            max(0.0, projected - earned_preview * threshold)
            if threshold > 0
            else projected
        )
        existing["confirmed_progress_units"] = confirmed
        existing["open_paid_units"] = open_units
        existing["display_progress_units"] = projected
        # The headline is confirmed progress only. Showing provisional units in
        # the numerator made a 6H confirmed + 6H active order look like a missed
        # 12/10H reward even though the active order had not closed yet.
        existing["progress_text"] = (
            f"{_format_units(confirmed)} / {_format_units(threshold)}{unit_label}"
        )
        if earned_preview > 0:
            existing["open_progress_text"] = (
                f"進行中暫計 +{_format_units(open_units)}{unit_label}｜"
                f"正常結單後預計發 {earned_preview} 張，"
                f"剩 {_format_units(projected_remainder)} / {_format_units(threshold)}{unit_label}"
            )
        else:
            existing["open_progress_text"] = (
                f"進行中暫計 +{_format_units(open_units)}{unit_label}｜"
                f"正常結單後預計 {_format_units(projected)} / {_format_units(threshold)}{unit_label}"
            )
        existing["earned_preview_count"] = earned_preview
        existing["percent"] = (
            max(0, min(100, int(round(confirmed / threshold * 100))))
            if threshold > 0
            else 0
        )


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
                        "confirmed_progress_units": current,
                        "open_paid_units": 0.0,
                        "display_progress_units": current,
                        "threshold_units": threshold,
                        "progress_text": f"{_format_units(current)} / {_format_units(threshold)}{unit_label}",
                        "open_progress_text": "",
                        "benefit_text": _benefit_text(raw["benefit_kind"], raw["benefit_units"]),
                        "percent": percent,
                        "updated_at": str(raw["updated_at"] or ""),
                        "updated_at_text": _time_text(raw["updated_at"]),
                    }
                )

        _merge_open_paid_progress(
            conn,
            placeholders=placeholders,
            ids=ids,
            result=result,
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
        data["progress"].sort(
            key=lambda item: (
                str(item.get("title") or ""),
                str(item.get("scope_key") or ""),
            )
        )
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