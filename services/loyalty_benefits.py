from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.order_rules import ORDER_RULES
from shared.db import SessionLocal


CANCELLED_ORDER_STATUSES = {
    "cancelled",
    "canceled",
    "rejected",
    "refunded",
    "void",
    "voided",
}
COMPLETED_ORDER_STATUSES = {
    "closed",
    "completed",
    "complete",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def ensure_loyalty_benefit_tables(db: Session | None = None) -> None:
    own_session = db is None
    session = db or SessionLocal()
    try:
        session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS customer_loyalty_progress (
                    customer_discord_id TEXT NOT NULL,
                    track_key TEXT NOT NULL,
                    rule_key TEXT NOT NULL,
                    player_count INTEGER NOT NULL DEFAULT 1,
                    pricing_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    target_units REAL NOT NULL,
                    progress_units REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (customer_discord_id, track_key)
                )
                """
            )
        )
        session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS customer_loyalty_coupons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_discord_id TEXT NOT NULL,
                    track_key TEXT NOT NULL,
                    rule_key TEXT NOT NULL,
                    player_count INTEGER NOT NULL DEFAULT 1,
                    kind TEXT NOT NULL,
                    units REAL NOT NULL,
                    label TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available',
                    reserved_order_id INTEGER,
                    issued_at TEXT NOT NULL,
                    reserved_at TEXT,
                    used_at TEXT
                )
                """
            )
        )
        session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_loyalty_coupon_customer_status
                ON customer_loyalty_coupons(customer_discord_id, status, rule_key, player_count)
                """
            )
        )
        session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS customer_loyalty_credits (
                    source_key TEXT PRIMARY KEY,
                    customer_discord_id TEXT NOT NULL,
                    track_key TEXT NOT NULL,
                    paid_units REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        if own_session:
            session.commit()
    finally:
        if own_session:
            session.close()


def loyalty_policy_for_rule(rule_key: str) -> dict | None:
    rule = ORDER_RULES.get(str(rule_key or "").strip())
    if rule is None:
        return None

    buy_units = _to_float(getattr(rule, "loyalty_reward_buy_units", 0), 0)
    gift_units = _to_float(getattr(rule, "loyalty_reward_gift_units", 0), 0)
    pricing_type = str(getattr(rule, "pricing_type", "") or "")
    if buy_units <= 0 or gift_units <= 0 or pricing_type not in {"hourly", "game"}:
        return None

    kind = "extra_hours" if pricing_type == "hourly" else "extra_games"
    return {
        "rule_key": str(rule.key),
        "pricing_type": pricing_type,
        "target_units": buy_units,
        "gift_units": gift_units,
        "kind": kind,
        "label": str(rule.label),
        "unit_label": "小時" if pricing_type == "hourly" else "局",
    }


def loyalty_track_key(rule_key: str, player_count: int = 1) -> str:
    return f"{str(rule_key)}:players={max(1, int(player_count or 1))}"


def _track_label(rule_key: str, player_count: int) -> str:
    rule = ORDER_RULES.get(str(rule_key))
    label = str(getattr(rule, "label", rule_key) or rule_key)
    if bool(getattr(rule, "player_count_enabled", False)):
        label += f"｜{max(1, int(player_count or 1))}人"
    return label


def _coupon_label(policy: dict, track_label: str) -> str:
    if policy["kind"] == "extra_hours":
        units = float(policy["gift_units"])
        gift = "+30分鐘" if units == 0.5 else f"+{units:g}小時"
    else:
        gift = f"+{int(policy['gift_units'])}局"
    return f"{track_label}｜{gift}"


def _reconcile_reserved_coupons(db: Session, customer_id: str) -> None:
    ensure_loyalty_benefit_tables(db)
    rows = db.execute(
        text(
            """
            SELECT c.id, c.reserved_order_id, o.status AS order_status
            FROM customer_loyalty_coupons c
            LEFT JOIN web_orders o ON o.id = c.reserved_order_id
            WHERE c.customer_discord_id = :customer_id
              AND c.status = 'reserved'
            """
        ),
        {"customer_id": str(customer_id)},
    ).mappings().all()

    now = _now()
    for row in rows:
        status = str(row.get("order_status") or "").strip().lower()
        coupon_id = int(row["id"])
        if not row.get("reserved_order_id") or status in CANCELLED_ORDER_STATUSES:
            db.execute(
                text(
                    """
                    UPDATE customer_loyalty_coupons
                    SET status='available', reserved_order_id=NULL, reserved_at=NULL
                    WHERE id=:coupon_id AND status='reserved'
                    """
                ),
                {"coupon_id": coupon_id},
            )
        elif status in COMPLETED_ORDER_STATUSES:
            db.execute(
                text(
                    """
                    UPDATE customer_loyalty_coupons
                    SET status='used', used_at=:used_at
                    WHERE id=:coupon_id AND status='reserved'
                    """
                ),
                {"coupon_id": coupon_id, "used_at": now},
            )


def list_compatible_coupons(
    customer_id: str,
    *,
    rule_key: str,
    player_count: int = 1,
) -> list[dict]:
    db = SessionLocal()
    try:
        ensure_loyalty_benefit_tables(db)
        _reconcile_reserved_coupons(db, customer_id)
        rows = db.execute(
            text(
                """
                SELECT id, label, kind, units, rule_key, player_count, issued_at
                FROM customer_loyalty_coupons
                WHERE customer_discord_id=:customer_id
                  AND rule_key=:rule_key
                  AND player_count=:player_count
                  AND status='available'
                ORDER BY id ASC
                """
            ),
            {
                "customer_id": str(customer_id),
                "rule_key": str(rule_key),
                "player_count": max(1, int(player_count or 1)),
            },
        ).mappings().all()
        db.commit()
        return [dict(row) for row in rows]
    finally:
        db.close()


def get_coupon_for_preview(
    customer_id: str,
    coupon_id: int | str,
    *,
    rule_key: str,
    player_count: int = 1,
) -> dict:
    db = SessionLocal()
    try:
        ensure_loyalty_benefit_tables(db)
        _reconcile_reserved_coupons(db, customer_id)
        row = db.execute(
            text(
                """
                SELECT id, label, kind, units, rule_key, player_count, status
                FROM customer_loyalty_coupons
                WHERE id=:coupon_id
                  AND customer_discord_id=:customer_id
                LIMIT 1
                """
            ),
            {"coupon_id": int(coupon_id), "customer_id": str(customer_id)},
        ).mappings().first()
        db.commit()
        if row is None:
            raise ValueError("找不到這張福利券。")
        if str(row["status"]) != "available":
            raise ValueError("這張福利券目前不可使用。")
        if str(row["rule_key"]) != str(rule_key):
            raise ValueError("這張福利券不適用目前方案。")
        if int(row["player_count"] or 1) != max(1, int(player_count or 1)):
            raise ValueError("這張福利券不適用目前陪玩人數。")
        return dict(row)
    finally:
        db.close()


def reserve_coupon(
    db: Session,
    *,
    customer_id: str,
    coupon_id: int,
    rule_key: str,
    player_count: int,
    order_id: int,
) -> None:
    ensure_loyalty_benefit_tables(db)
    row = db.execute(
        text(
            """
            SELECT status, customer_discord_id, rule_key, player_count, reserved_order_id
            FROM customer_loyalty_coupons
            WHERE id=:coupon_id
            LIMIT 1
            """
        ),
        {"coupon_id": int(coupon_id)},
    ).mappings().first()
    if row is None:
        raise ValueError("找不到這張福利券。")
    if str(row["customer_discord_id"]) != str(customer_id):
        raise ValueError("這張福利券不屬於目前帳號。")
    if str(row["rule_key"]) != str(rule_key):
        raise ValueError("這張福利券不適用目前方案。")
    if int(row["player_count"] or 1) != max(1, int(player_count or 1)):
        raise ValueError("這張福利券不適用目前陪玩人數。")
    if str(row["status"]) == "reserved" and int(row.get("reserved_order_id") or 0) == int(order_id):
        return
    if str(row["status"]) != "available":
        raise ValueError("這張福利券已被其他訂單使用或保留。")

    result = db.execute(
        text(
            """
            UPDATE customer_loyalty_coupons
            SET status='reserved', reserved_order_id=:order_id, reserved_at=:reserved_at
            WHERE id=:coupon_id AND status='available'
            """
        ),
        {"coupon_id": int(coupon_id), "order_id": int(order_id), "reserved_at": _now()},
    )
    if int(result.rowcount or 0) != 1:
        raise ValueError("福利券狀態已變更，請重新取得價格。")


def consume_coupon(coupon_id: int | str, *, customer_id: str | None = None) -> bool:
    db = SessionLocal()
    try:
        ensure_loyalty_benefit_tables(db)
        params = {"coupon_id": int(coupon_id), "used_at": _now()}
        customer_sql = ""
        if customer_id is not None:
            customer_sql = " AND customer_discord_id=:customer_id"
            params["customer_id"] = str(customer_id)
        result = db.execute(
            text(
                f"""
                UPDATE customer_loyalty_coupons
                SET status='used', used_at=:used_at
                WHERE id=:coupon_id
                  AND status IN ('available','reserved')
                  {customer_sql}
                """
            ),
            params,
        )
        db.commit()
        return int(result.rowcount or 0) == 1
    finally:
        db.close()


def record_completed_paid_service(
    *,
    customer_id: str | int,
    order_data: dict,
    source_key: str,
) -> dict:
    customer_id = str(customer_id)
    order_data = dict(order_data or {})

    coupon_id = order_data.get("benefit_coupon_id") or order_data.get("loyalty_coupon_id")
    if coupon_id:
        try:
            consume_coupon(coupon_id, customer_id=customer_id)
        except Exception:
            pass

    rule_key = str(order_data.get("order_rule_key") or "").strip()
    policy = loyalty_policy_for_rule(rule_key)
    if policy is None:
        return {"credited": False, "issued": []}

    quantity = _to_float(order_data.get("quantity"), 0)
    if quantity <= 0:
        return {"credited": False, "issued": []}

    player_count = max(1, _to_int(order_data.get("player_count"), 1))
    track_key = loyalty_track_key(rule_key, player_count)
    label = _track_label(rule_key, player_count)
    now = _now()

    db = SessionLocal()
    try:
        ensure_loyalty_benefit_tables(db)
        already = db.execute(
            text("SELECT 1 FROM customer_loyalty_credits WHERE source_key=:source_key LIMIT 1"),
            {"source_key": str(source_key)},
        ).first()
        if already:
            return {"credited": False, "duplicate": True, "issued": []}

        db.execute(
            text(
                """
                INSERT INTO customer_loyalty_credits
                    (source_key, customer_discord_id, track_key, paid_units, created_at)
                VALUES
                    (:source_key, :customer_id, :track_key, :paid_units, :created_at)
                """
            ),
            {
                "source_key": str(source_key),
                "customer_id": customer_id,
                "track_key": track_key,
                "paid_units": quantity,
                "created_at": now,
            },
        )

        row = db.execute(
            text(
                """
                SELECT progress_units
                FROM customer_loyalty_progress
                WHERE customer_discord_id=:customer_id AND track_key=:track_key
                LIMIT 1
                """
            ),
            {"customer_id": customer_id, "track_key": track_key},
        ).first()
        progress = _to_float(row[0], 0) if row else 0.0
        progress += quantity
        target = float(policy["target_units"])
        issued: list[dict] = []

        while progress + 1e-9 >= target:
            progress -= target
            coupon_label = _coupon_label(policy, label)
            result = db.execute(
                text(
                    """
                    INSERT INTO customer_loyalty_coupons
                        (customer_discord_id, track_key, rule_key, player_count, kind, units, label, status, issued_at)
                    VALUES
                        (:customer_id, :track_key, :rule_key, :player_count, :kind, :units, :label, 'available', :issued_at)
                    """
                ),
                {
                    "customer_id": customer_id,
                    "track_key": track_key,
                    "rule_key": rule_key,
                    "player_count": player_count,
                    "kind": policy["kind"],
                    "units": float(policy["gift_units"]),
                    "label": coupon_label,
                    "issued_at": now,
                },
            )
            issued.append({"id": int(result.lastrowid), "label": coupon_label})

        db.execute(
            text(
                """
                INSERT INTO customer_loyalty_progress
                    (customer_discord_id, track_key, rule_key, player_count, pricing_type, label, target_units, progress_units, updated_at)
                VALUES
                    (:customer_id, :track_key, :rule_key, :player_count, :pricing_type, :label, :target_units, :progress_units, :updated_at)
                ON CONFLICT(customer_discord_id, track_key)
                DO UPDATE SET
                    rule_key=excluded.rule_key,
                    player_count=excluded.player_count,
                    pricing_type=excluded.pricing_type,
                    label=excluded.label,
                    target_units=excluded.target_units,
                    progress_units=excluded.progress_units,
                    updated_at=excluded.updated_at
                """
            ),
            {
                "customer_id": customer_id,
                "track_key": track_key,
                "rule_key": rule_key,
                "player_count": player_count,
                "pricing_type": policy["pricing_type"],
                "label": label,
                "target_units": target,
                "progress_units": max(0.0, progress),
                "updated_at": now,
            },
        )
        db.commit()
        return {
            "credited": True,
            "paid_units": quantity,
            "progress_units": max(0.0, progress),
            "target_units": target,
            "issued": issued,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_customer_loyalty_snapshot(customer_id: str | int) -> dict:
    customer_id = str(customer_id)
    db = SessionLocal()
    try:
        ensure_loyalty_benefit_tables(db)
        _reconcile_reserved_coupons(db, customer_id)
        coupons = [
            dict(row)
            for row in db.execute(
                text(
                    """
                    SELECT id, label, rule_key, player_count, kind, units, issued_at
                    FROM customer_loyalty_coupons
                    WHERE customer_discord_id=:customer_id AND status='available'
                    ORDER BY id ASC
                    """
                ),
                {"customer_id": customer_id},
            ).mappings().all()
        ]
        progress_rows = db.execute(
            text(
                """
                SELECT track_key, rule_key, player_count, pricing_type, label, target_units, progress_units
                FROM customer_loyalty_progress
                WHERE customer_discord_id=:customer_id
                  AND progress_units > 0.000001
                ORDER BY updated_at DESC
                """
            ),
            {"customer_id": customer_id},
        ).mappings().all()
        progress = []
        for row in progress_rows:
            item = dict(row)
            current = float(item["progress_units"] or 0)
            target = float(item["target_units"] or 0)
            item["progress_text"] = f"{current:g} / {target:g}"
            item["percent"] = 0 if target <= 0 else min(100, round(current / target * 100, 1))
            item["unit_label"] = "小時" if str(item["pricing_type"]) == "hourly" else "局"
            progress.append(item)
        db.commit()
        return {
            "available_count": len(coupons),
            "coupons": coupons,
            "progress": progress,
        }
    finally:
        db.close()
