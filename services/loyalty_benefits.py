from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.time_utils import get_taipei_now_iso
from shared.db import SessionLocal, engine


TAIPEI_TZ = timezone(timedelta(hours=8))
# 依店內決議：新累積制自 2026-10-10 台灣時間 00:00 起算，不回溯更早訂單。
LOYALTY_START_AT_TAIPEI = datetime(2026, 10, 10, 0, 0, 0, tzinfo=TAIPEI_TZ)
LOYALTY_START_AT_UTC_NAIVE = LOYALTY_START_AT_TAIPEI.astimezone(timezone.utc).replace(tzinfo=None)

HOURLY_THRESHOLD = 10.0
HOURLY_BONUS = 0.5
GAME_THRESHOLD = 20.0
GAME_BONUS = 1.0

ACTIVE = "active"
RESERVED = "reserved"
REDEEMED = "redeemed"


def ensure_loyalty_tables(bind=engine) -> None:
    with bind.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_loyalty_progress (
                customer_discord_id TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                rule_key TEXT NOT NULL,
                rule_label TEXT NOT NULL,
                pricing_type TEXT NOT NULL,
                player_count INTEGER NOT NULL DEFAULT 1,
                progress_units REAL NOT NULL DEFAULT 0,
                threshold_units REAL NOT NULL,
                benefit_kind TEXT NOT NULL,
                benefit_units REAL NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (customer_discord_id, scope_key)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_benefit_coupons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_discord_id TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                rule_key TEXT NOT NULL,
                rule_label TEXT NOT NULL,
                pricing_type TEXT NOT NULL,
                player_count INTEGER NOT NULL DEFAULT 1,
                benefit_kind TEXT NOT NULL,
                benefit_units REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                source TEXT NOT NULL DEFAULT 'loyalty',
                issued_at TEXT NOT NULL,
                reserved_order_id INTEGER,
                redeemed_order_id INTEGER,
                redeemed_at TEXT
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_benefit_coupon_customer_status
            ON customer_benefit_coupons(customer_discord_id, status, rule_key)
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_benefit_coupon_reserved_order
            ON customer_benefit_coupons(reserved_order_id)
            WHERE reserved_order_id IS NOT NULL AND status = 'reserved'
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS loyalty_order_events (
                order_id INTEGER PRIMARY KEY,
                customer_discord_id TEXT,
                scope_key TEXT,
                paid_units REAL NOT NULL DEFAULT 0,
                issued_coupon_count INTEGER NOT NULL DEFAULT 0,
                processed_at TEXT NOT NULL,
                note TEXT
            )
        """))


def _rule_for_key(rule_key: str):
    from services.order_rules import ORDER_RULES

    return ORDER_RULES.get(str(rule_key or "").strip())


def loyalty_policy_for_rule(rule_key: str) -> dict[str, Any] | None:
    rule = _rule_for_key(rule_key)
    if rule is None or not bool(getattr(rule, "loyalty_benefits_enabled", False)):
        return None

    pricing_type = str(getattr(rule, "pricing_type", "") or "")
    if pricing_type == "hourly":
        return {
            "pricing_type": "hourly",
            "threshold_units": HOURLY_THRESHOLD,
            "benefit_kind": "extra_hours",
            "benefit_units": HOURLY_BONUS,
            "unit_label": "小時",
            "benefit_label": "+30 分鐘",
        }
    if pricing_type == "game":
        return {
            "pricing_type": "game",
            "threshold_units": GAME_THRESHOLD,
            "benefit_kind": "extra_games",
            "benefit_units": GAME_BONUS,
            "unit_label": "局",
            "benefit_label": "+1 局",
        }
    return None


def loyalty_scope_key(rule_key: str, player_count: int = 1) -> str:
    rule = _rule_for_key(rule_key)
    players = max(1, int(player_count or 1))
    if rule is None or not bool(getattr(rule, "player_count_enabled", False)):
        players = 1
    return f"{str(rule_key)}|players:{players}"


def _coupon_title(row: dict[str, Any]) -> str:
    kind = str(row.get("benefit_kind") or "")
    units = float(row.get("benefit_units") or 0)
    if kind == "extra_hours":
        benefit = "+30 分鐘" if abs(units - 0.5) < 0.001 else f"+{units:g} 小時"
    else:
        benefit = f"+{int(round(units))} 局"
    players = max(1, int(row.get("player_count") or 1))
    suffix = f"｜{players}位" if players > 1 else ""
    return f"{row.get('rule_label') or row.get('rule_key')}｜{benefit}{suffix}"


def list_customer_loyalty(customer_id: str | int) -> dict[str, Any]:
    ensure_loyalty_tables()
    customer = str(customer_id)
    with engine.begin() as conn:
        coupon_rows = conn.execute(text("""
            SELECT *
            FROM customer_benefit_coupons
            WHERE customer_discord_id = :customer_id
              AND status = 'active'
            ORDER BY issued_at ASC, id ASC
        """), {"customer_id": customer}).mappings().all()
        progress_rows = conn.execute(text("""
            SELECT *
            FROM customer_loyalty_progress
            WHERE customer_discord_id = :customer_id
              AND progress_units > 0.0001
            ORDER BY updated_at DESC, scope_key ASC
        """), {"customer_id": customer}).mappings().all()

    coupons = []
    for raw in coupon_rows:
        row = dict(raw)
        row["title"] = _coupon_title(row)
        coupons.append(row)

    progress = []
    for raw in progress_rows:
        row = dict(raw)
        current = float(row.get("progress_units") or 0)
        threshold = float(row.get("threshold_units") or 1)
        row["progress_text"] = f"{current:g} / {threshold:g}"
        row["percent"] = max(0, min(100, int(round(current / threshold * 100))))
        players = max(1, int(row.get("player_count") or 1))
        row["title"] = str(row.get("rule_label") or row.get("rule_key")) + (
            f"｜{players}位" if players > 1 else ""
        )
        progress.append(row)

    return {
        "active_count": len(coupons),
        "coupons": coupons,
        "progress": progress,
        "has_anything": bool(coupons or progress),
        "start_at": LOYALTY_START_AT_TAIPEI.isoformat(),
    }


def list_applicable_coupons(
    customer_id: str | int,
    *,
    rule_key: str,
    player_count: int = 1,
) -> list[dict[str, Any]]:
    policy = loyalty_policy_for_rule(rule_key)
    if policy is None:
        return []
    ensure_loyalty_tables()
    scope = loyalty_scope_key(rule_key, player_count)
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT *
            FROM customer_benefit_coupons
            WHERE customer_discord_id = :customer_id
              AND scope_key = :scope_key
              AND status = 'active'
            ORDER BY issued_at ASC, id ASC
        """), {
            "customer_id": str(customer_id),
            "scope_key": scope,
        }).mappings().all()
    result = []
    for raw in rows:
        row = dict(raw)
        row["title"] = _coupon_title(row)
        result.append(row)
    return result


def get_applicable_coupon(
    coupon_id: int | str | None,
    *,
    customer_id: str | int,
    rule_key: str,
    player_count: int = 1,
) -> dict[str, Any] | None:
    if coupon_id in (None, ""):
        return None
    ensure_loyalty_tables()
    try:
        coupon_number = int(coupon_id)
    except (TypeError, ValueError):
        return None
    scope = loyalty_scope_key(rule_key, player_count)
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT *
            FROM customer_benefit_coupons
            WHERE id = :coupon_id
              AND customer_discord_id = :customer_id
              AND scope_key = :scope_key
              AND status = 'active'
            LIMIT 1
        """), {
            "coupon_id": coupon_number,
            "customer_id": str(customer_id),
            "scope_key": scope,
        }).mappings().first()
    if row is None:
        return None
    result = dict(row)
    result["title"] = _coupon_title(result)
    return result


def calculate_coupon_service_value(
    *,
    rule_key: str,
    player_count: int,
    coupon: dict[str, Any] | None,
) -> int:
    """Store-funded worker payout value, always based on normal list price.

    VIP/customer discounts never lower the value of gifted work.
    """
    if not coupon:
        return 0
    rule = _rule_for_key(rule_key)
    if rule is None:
        return 0
    kind = str(coupon.get("benefit_kind") or "")
    units = float(coupon.get("benefit_units") or 0)
    if units <= 0:
        return 0
    if kind not in {"extra_hours", "extra_games"}:
        return 0
    per_unit = max(0, int(getattr(rule, "price", 0) or 0))
    if bool(getattr(rule, "price_multiply_player_count", False)):
        per_unit *= max(1, int(player_count or 1))
    return max(0, int(round(per_unit * units)))


def coupon_service_note(coupon: dict[str, Any] | None) -> str:
    if not coupon:
        return ""
    kind = str(coupon.get("benefit_kind") or "")
    units = float(coupon.get("benefit_units") or 0)
    if kind == "extra_hours":
        return "福利券：服務時間 +30 分鐘" if abs(units - 0.5) < 0.001 else f"福利券：服務時間 +{units:g} 小時"
    return f"福利券：服務局數 +{int(round(units))} 局"


def reserve_coupon_in_session(
    db: Session,
    *,
    coupon_id: int,
    customer_id: str | int,
    order_id: int,
    rule_key: str,
    player_count: int = 1,
) -> None:
    # Schema is initialized at application/bot startup. Avoid opening a second
    # SQLite write transaction while this Session already owns the order transaction.
    scope = loyalty_scope_key(rule_key, player_count)
    result = db.execute(text("""
        UPDATE customer_benefit_coupons
        SET status = 'reserved',
            reserved_order_id = :order_id
        WHERE id = :coupon_id
          AND customer_discord_id = :customer_id
          AND scope_key = :scope_key
          AND status = 'active'
    """), {
        "order_id": int(order_id),
        "coupon_id": int(coupon_id),
        "customer_id": str(customer_id),
        "scope_key": scope,
    })
    if int(result.rowcount or 0) != 1:
        raise ValueError("這張福利券已被使用、保留，或不適用這個方案。請重新整理後再試。")


def reserve_coupon_for_order(
    *,
    coupon_id: int,
    customer_id: str | int,
    order_id: int,
    rule_key: str,
    player_count: int = 1,
) -> None:
    db = SessionLocal()
    try:
        reserve_coupon_in_session(
            db,
            coupon_id=int(coupon_id),
            customer_id=customer_id,
            order_id=int(order_id),
            rule_key=rule_key,
            player_count=player_count,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def release_coupon_for_order(order_id: int) -> int:
    ensure_loyalty_tables()
    with engine.begin() as conn:
        result = conn.execute(text("""
            UPDATE customer_benefit_coupons
            SET status = 'active', reserved_order_id = NULL
            WHERE reserved_order_id = :order_id
              AND status = 'reserved'
        """), {"order_id": int(order_id)})
        return int(result.rowcount or 0)


def redeem_coupon_for_order(order_id: int) -> int:
    ensure_loyalty_tables()
    now = get_taipei_now_iso()
    with engine.begin() as conn:
        result = conn.execute(text("""
            UPDATE customer_benefit_coupons
            SET status = 'redeemed',
                redeemed_order_id = :order_id,
                redeemed_at = :redeemed_at
            WHERE reserved_order_id = :order_id
              AND status = 'reserved'
        """), {
            "order_id": int(order_id),
            "redeemed_at": now,
        })
        return int(result.rowcount or 0)


def _event_time_is_in_scope(row: dict[str, Any]) -> bool:
    value = row.get("closed_at") or row.get("updated_at") or row.get("created_at")
    if value is None:
        return False
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return False
    if dt.tzinfo is None:
        # web_dashboard.db 的時間歷史上同時存在 UTC 與台北 naive；closed_at
        # 由 Bot 寫入時是台北時間。為避免漏掉 10/10 當天已完成訂單，naive
        # 以台北時間解讀，僅影響新制度起算邊界。
        dt = dt.replace(tzinfo=TAIPEI_TZ)
    return dt.astimezone(TAIPEI_TZ) >= LOYALTY_START_AT_TAIPEI


def _qualifying_paid_amount(row: dict[str, Any]) -> int:
    """Paid service amount before wallet deduction; wallet spend still qualifies."""
    amount = int(row.get("customer_pay_amount") or row.get("amount") or 0)
    try:
        import json

        snapshot = json.loads(str(row.get("price_snapshot_json") or "{}"))
        if isinstance(snapshot, dict):
            preview = (
                snapshot.get("preview")
                if isinstance(snapshot.get("preview"), dict)
                else snapshot
            )
            finance = (
                preview.get("finance")
                if isinstance(preview, dict)
                and isinstance(preview.get("finance"), dict)
                else {}
            )
            if "subtotal_before_wallet" in finance:
                return max(0, int(finance.get("subtotal_before_wallet") or 0))
            if "customer_pay_amount" in snapshot:
                return max(0, int(snapshot.get("customer_pay_amount") or 0))
    except Exception:
        pass
    return max(0, amount)


def process_closed_order(order_id: int) -> dict[str, Any] | None:
    """Idempotently accrue one closed order and issue any earned coupons."""
    ensure_loyalty_tables()
    with engine.begin() as conn:
        existing = conn.execute(text(
            "SELECT order_id FROM loyalty_order_events WHERE order_id = :order_id LIMIT 1"
        ), {"order_id": int(order_id)}).first()
        if existing is not None:
            return None

        raw = conn.execute(text("""
            SELECT id, customer_discord_id, order_rule_key, quantity,
                   amount, original_amount, customer_pay_amount, status, created_at, updated_at, closed_at,
                   price_snapshot_json, ticket_channel_id
            FROM web_orders
            WHERE id = :order_id
            LIMIT 1
        """), {"order_id": int(order_id)}).mappings().first()
        if raw is None:
            return None
        row = dict(raw)
        if str(row.get("status") or "").strip().lower() != "closed":
            return None

        customer_id = str(row.get("customer_discord_id") or "").strip()
        rule_key = str(row.get("order_rule_key") or "").strip()
        policy = loyalty_policy_for_rule(rule_key)
        note = ""
        paid_units = 0.0
        issued_count = 0
        issued_coupons: list[dict[str, Any]] = []
        scope = ""

        if not customer_id:
            note = "missing_customer"
        elif not _event_time_is_in_scope(row):
            note = "before_program_start"
        elif policy is None:
            note = "rule_not_eligible"
        elif _qualifying_paid_amount(row) <= 0:
            note = "no_paid_amount"
        else:
            player_count = 1
            try:
                import json
                snapshot = json.loads(str(row.get("price_snapshot_json") or "{}"))
                if isinstance(snapshot, dict):
                    preview = snapshot.get("preview") if isinstance(snapshot.get("preview"), dict) else snapshot
                    quote = preview.get("quote") if isinstance(preview, dict) and isinstance(preview.get("quote"), dict) else {}
                    input_data = snapshot.get("input") if isinstance(snapshot.get("input"), dict) else {}
                    player_count = int(quote.get("player_count") or input_data.get("player_count") or 1)
            except Exception:
                player_count = 1

            rule = _rule_for_key(rule_key)
            if rule is None or not bool(getattr(rule, "player_count_enabled", False)):
                player_count = 1
            player_count = max(1, player_count)
            scope = loyalty_scope_key(rule_key, player_count)
            paid_units = float(max(0, int(row.get("quantity") or 0)))
            threshold = float(policy["threshold_units"])
            previous = conn.execute(text("""
                SELECT progress_units
                FROM customer_loyalty_progress
                WHERE customer_discord_id = :customer_id
                  AND scope_key = :scope_key
                LIMIT 1
            """), {
                "customer_id": customer_id,
                "scope_key": scope,
            }).scalar()
            total = float(previous or 0) + paid_units
            issued_count = int(total // threshold)
            remainder = total - issued_count * threshold
            rule_label = str(getattr(rule, "label", rule_key))
            now = get_taipei_now_iso()
            conn.execute(text("""
                INSERT INTO customer_loyalty_progress (
                    customer_discord_id, scope_key, rule_key, rule_label,
                    pricing_type, player_count, progress_units, threshold_units,
                    benefit_kind, benefit_units, updated_at
                ) VALUES (
                    :customer_id, :scope_key, :rule_key, :rule_label,
                    :pricing_type, :player_count, :progress_units, :threshold_units,
                    :benefit_kind, :benefit_units, :updated_at
                )
                ON CONFLICT(customer_discord_id, scope_key) DO UPDATE SET
                    rule_label = excluded.rule_label,
                    progress_units = excluded.progress_units,
                    threshold_units = excluded.threshold_units,
                    benefit_kind = excluded.benefit_kind,
                    benefit_units = excluded.benefit_units,
                    updated_at = excluded.updated_at
            """), {
                "customer_id": customer_id,
                "scope_key": scope,
                "rule_key": rule_key,
                "rule_label": rule_label,
                "pricing_type": policy["pricing_type"],
                "player_count": player_count,
                "progress_units": remainder,
                "threshold_units": threshold,
                "benefit_kind": policy["benefit_kind"],
                "benefit_units": policy["benefit_units"],
                "updated_at": now,
            })

            for _ in range(issued_count):
                result = conn.execute(text("""
                    INSERT INTO customer_benefit_coupons (
                        customer_discord_id, scope_key, rule_key, rule_label,
                        pricing_type, player_count, benefit_kind, benefit_units,
                        status, source, issued_at
                    ) VALUES (
                        :customer_id, :scope_key, :rule_key, :rule_label,
                        :pricing_type, :player_count, :benefit_kind, :benefit_units,
                        'active', 'loyalty', :issued_at
                    )
                """), {
                    "customer_id": customer_id,
                    "scope_key": scope,
                    "rule_key": rule_key,
                    "rule_label": rule_label,
                    "pricing_type": policy["pricing_type"],
                    "player_count": player_count,
                    "benefit_kind": policy["benefit_kind"],
                    "benefit_units": policy["benefit_units"],
                    "issued_at": now,
                })
                coupon_id = int(result.lastrowid or 0)
                coupon = {
                    "id": coupon_id,
                    "rule_key": rule_key,
                    "rule_label": rule_label,
                    "pricing_type": policy["pricing_type"],
                    "player_count": player_count,
                    "benefit_kind": policy["benefit_kind"],
                    "benefit_units": policy["benefit_units"],
                }
                coupon["title"] = _coupon_title(coupon)
                issued_coupons.append(coupon)

        conn.execute(text("""
            INSERT INTO loyalty_order_events (
                order_id, customer_discord_id, scope_key, paid_units,
                issued_coupon_count, processed_at, note
            ) VALUES (
                :order_id, :customer_id, :scope_key, :paid_units,
                :issued_coupon_count, :processed_at, :note
            )
        """), {
            "order_id": int(order_id),
            "customer_id": customer_id or None,
            "scope_key": scope or None,
            "paid_units": paid_units,
            "issued_coupon_count": issued_count,
            "processed_at": get_taipei_now_iso(),
            "note": note or None,
        })

    return {
        "order_id": int(order_id),
        "customer_id": customer_id,
        "ticket_channel_id": row.get("ticket_channel_id"),
        "paid_units": paid_units,
        "issued_coupon_count": issued_count,
        "issued_coupons": issued_coupons,
        "note": note,
    }


def process_closed_orders_since_start(limit: int = 200) -> list[dict[str, Any]]:
    ensure_loyalty_tables()
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT o.id
            FROM web_orders o
            LEFT JOIN loyalty_order_events e ON e.order_id = o.id
            WHERE o.status = 'closed'
              AND e.order_id IS NULL
            ORDER BY o.id ASC
            LIMIT :limit
        """), {"limit": max(1, int(limit or 200))}).fetchall()
    results = []
    for raw in rows:
        result = process_closed_order(int(raw[0]))
        if result is not None:
            results.append(result)
    return results


def reconcile_coupon_reservations(limit: int = 200) -> dict[str, int]:
    ensure_loyalty_tables()
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT c.id, c.reserved_order_id, o.status
            FROM customer_benefit_coupons c
            LEFT JOIN web_orders o ON o.id = c.reserved_order_id
            WHERE c.status = 'reserved'
              AND c.reserved_order_id IS NOT NULL
            ORDER BY c.id ASC
            LIMIT :limit
        """), {"limit": max(1, int(limit or 200))}).mappings().all()
    released = 0
    redeemed = 0
    for raw in rows:
        order_id = int(raw["reserved_order_id"])
        status = str(raw.get("status") or "").strip().lower()
        if status == "cancelled" or not status:
            released += release_coupon_for_order(order_id)
        elif status == "closed":
            redeemed += redeem_coupon_for_order(order_id)
    return {"released": released, "redeemed": redeemed}
