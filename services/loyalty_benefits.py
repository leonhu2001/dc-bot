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
COUPON_VALID_DAYS = 90

ACTIVE = "active"
RESERVED = "reserved"
REDEEMED = "redeemed"
EXPIRED = "expired"


def _parse_coupon_time(value: object) -> datetime | None:
    raw = str(value or "").strip().replace("Z", "+00:00")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI_TZ)
    return dt.astimezone(TAIPEI_TZ)


def _coupon_expiry_iso(issued_at: object = None) -> str:
    base = _parse_coupon_time(issued_at) or datetime.now(TAIPEI_TZ)
    return (base + timedelta(days=COUPON_VALID_DAYS)).isoformat(timespec="seconds")


def _coupon_expiry_text(value: object) -> str:
    dt = _parse_coupon_time(value)
    return dt.strftime("%Y/%m/%d") if dt else ""


def _expire_active_coupons(conn) -> int:
    now = datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")
    result = conn.execute(text("""
        UPDATE customer_benefit_coupons
        SET status = 'expired'
        WHERE status = 'active'
          AND expires_at IS NOT NULL
          AND expires_at <= :now
    """), {"now": now})
    return int(result.rowcount or 0)


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
                expires_at TEXT,
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
        coupon_columns = {
            str(row[1])
            for row in conn.execute(text("PRAGMA table_info(customer_benefit_coupons)")).fetchall()
        }
        if "expires_at" not in coupon_columns:
            conn.execute(text("ALTER TABLE customer_benefit_coupons ADD COLUMN expires_at TEXT"))

        missing_expiry = conn.execute(text("""
            SELECT id, issued_at
            FROM customer_benefit_coupons
            WHERE expires_at IS NULL OR TRIM(expires_at) = ''
        """)).mappings().all()
        for row in missing_expiry:
            conn.execute(text("""
                UPDATE customer_benefit_coupons
                SET expires_at = :expires_at
                WHERE id = :coupon_id
            """), {
                "coupon_id": int(row["id"]),
                "expires_at": _coupon_expiry_iso(row.get("issued_at")),
            })
        _expire_active_coupons(conn)

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
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS loyalty_migrations (
                migration_key TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL,
                note TEXT
            )
        """))
        _repair_companion_loyalty_v2(conn)


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


_LOYALTY_SCOPE_FAMILY_ALIASES = {
    # 同一個遊戲／服務只是陪玩席位數不同，必須共用同一個老闆福利池。
    "basic_entertain_single": "basic_entertain",
    "basic_entertain_double": "basic_entertain",
    "basic_mobile_entertain_single": "basic_mobile_entertain",
    "basic_mobile_entertain_double": "basic_mobile_entertain",
}
_LOYALTY_COMPANION_MIGRATION_KEY = "20261011_companion_service_units_v2"


def _canonical_loyalty_rule_key(rule_key: str) -> str:
    key = str(rule_key or "").strip()
    return _LOYALTY_SCOPE_FAMILY_ALIASES.get(key, key)


def _service_companion_count(rule: Any, player_count: int = 1) -> int:
    requested = max(1, int(player_count or 1))
    if rule is None:
        return requested
    required = getattr(rule, "required_staff_count", 1)
    if str(required) == "player_count":
        return requested
    try:
        return max(1, int(required or 1))
    except (TypeError, ValueError):
        return requested if bool(getattr(rule, "player_count_enabled", False)) else 1


def _extract_player_count(row: dict[str, Any]) -> int:
    try:
        import json

        snapshot = json.loads(str(row.get("price_snapshot_json") or "{}"))
        if isinstance(snapshot, dict):
            preview = (
                snapshot.get("preview")
                if isinstance(snapshot.get("preview"), dict)
                else snapshot
            )
            quote = (
                preview.get("quote")
                if isinstance(preview, dict)
                and isinstance(preview.get("quote"), dict)
                else {}
            )
            input_data = snapshot.get("input") if isinstance(snapshot.get("input"), dict) else {}
            return max(1, int(quote.get("player_count") or input_data.get("player_count") or 1))
    except Exception:
        pass
    return 1


def _loyalty_display_label(rule_key: str, fallback: object = "") -> str:
    label = str(fallback or rule_key or "").strip()
    for suffix in ("｜單陪", "｜雙陪", "｜三陪", "｜四陪"):
        if label.endswith(suffix):
            label = label[: -len(suffix)]
            break
    return label or str(rule_key or "")


def loyalty_scope_key(rule_key: str, player_count: int = 1) -> str:
    # player_count intentionally does not participate in the scope. A customer
    # owns one progress pool per game/service family, regardless of 1/2/3/4陪.
    _ = player_count
    rule = _rule_for_key(rule_key)
    category = str(getattr(rule, "category", "") or "unknown").strip()
    family = _canonical_loyalty_rule_key(rule_key)
    return f"{category}|{family}"


def _coupon_title(row: dict[str, Any]) -> str:
    kind = str(row.get("benefit_kind") or "")
    units = float(row.get("benefit_units") or 0)
    if kind == "extra_hours":
        benefit = "折抵 30 分鐘額度" if abs(units - 0.5) < 0.001 else f"折抵 {units:g} 小時額度"
    else:
        benefit = f"折抵 {int(round(units))} 局額度"
    label = _loyalty_display_label(str(row.get("rule_key") or ""), row.get("rule_label"))
    return f"{label}｜{benefit}"


def list_customer_loyalty(customer_id: str | int) -> dict[str, Any]:
    ensure_loyalty_tables()
    customer = str(customer_id)
    with engine.begin() as conn:
        _expire_active_coupons(conn)
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
        row["expires_at_text"] = _coupon_expiry_text(row.get("expires_at"))
        coupons.append(row)

    progress = []
    for raw in progress_rows:
        row = dict(raw)
        current = float(row.get("progress_units") or 0)
        threshold = float(row.get("threshold_units") or 1)
        row["progress_text"] = f"{current:g} / {threshold:g}"
        row["percent"] = max(0, min(100, int(round(current / threshold * 100))))
        row["title"] = _loyalty_display_label(
            str(row.get("rule_key") or ""),
            row.get("rule_label"),
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
        _expire_active_coupons(conn)
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
        row["expires_at_text"] = _coupon_expiry_text(row.get("expires_at"))
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
        _expire_active_coupons(conn)
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
    result["expires_at_text"] = _coupon_expiry_text(result.get("expires_at"))
    return result


def calculate_coupon_service_value(
    *,
    rule_key: str,
    player_count: int,
    coupon: dict[str, Any] | None,
) -> int:
    """Cash value of one customer benefit service-unit credit at list price.

    One benefit hour/game always means one companion's service unit. Multi-
    companion orders therefore redeem the same credit proportionally instead
    of multiplying the coupon by the number of companions.
    """
    if not coupon:
        return 0
    rule = _rule_for_key(rule_key)
    if rule is None:
        return 0
    kind = str(coupon.get("benefit_kind") or "")
    units = float(coupon.get("benefit_units") or 0)
    if units <= 0 or kind not in {"extra_hours", "extra_games"}:
        return 0

    requested_players = max(1, int(player_count or 1))
    companion_count = _service_companion_count(rule, requested_players)
    order_unit_price = max(0, int(getattr(rule, "price", 0) or 0))
    if bool(getattr(rule, "price_multiply_player_count", False)):
        order_unit_price *= requested_players

    per_companion_unit = order_unit_price / max(1, companion_count)
    return max(0, int(round(per_companion_unit * units)))


def coupon_service_note(coupon: dict[str, Any] | None) -> str:
    if not coupon:
        return ""
    kind = str(coupon.get("benefit_kind") or "")
    units = float(coupon.get("benefit_units") or 0)
    if kind == "extra_hours":
        amount = "30 分鐘" if abs(units - 0.5) < 0.001 else f"{units:g} 小時"
        return f"福利券：折抵 {amount} 服務額度"
    return f"福利券：折抵 {int(round(units))} 局服務額度"


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
          AND (expires_at IS NULL OR expires_at > :now)
    """), {
        "order_id": int(order_id),
        "coupon_id": int(coupon_id),
        "customer_id": str(customer_id),
        "scope_key": scope,
        "now": datetime.now(TAIPEI_TZ).isoformat(timespec="seconds"),
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
        now = datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")
        result = conn.execute(text("""
            UPDATE customer_benefit_coupons
            SET status = CASE
                    WHEN expires_at IS NOT NULL AND expires_at <= :now THEN 'expired'
                    ELSE 'active'
                END,
                reserved_order_id = NULL
            WHERE reserved_order_id = :order_id
              AND status = 'reserved'
        """), {"order_id": int(order_id), "now": now})
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


def _repair_companion_loyalty_v2(conn) -> None:
    """One-time repair for progress created before companion service units.

    Only orders that already have loyalty_order_events are recalculated. Orders
    not yet processed remain untouched so the normal close-order flow can issue
    rewards exactly once after deployment.
    """
    applied = conn.execute(text("""
        SELECT migration_key
        FROM loyalty_migrations
        WHERE migration_key = :migration_key
        LIMIT 1
    """), {"migration_key": _LOYALTY_COMPANION_MIGRATION_KEY}).first()
    if applied is not None:
        return

    has_orders = conn.execute(text("""
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'web_orders'
        LIMIT 1
    """)).first()
    if has_orders is None:
        conn.execute(text("""
            INSERT INTO loyalty_migrations (migration_key, applied_at, note)
            VALUES (:migration_key, :applied_at, 'no_web_orders_table')
        """), {
            "migration_key": _LOYALTY_COMPANION_MIGRATION_KEY,
            "applied_at": get_taipei_now_iso(),
        })
        return

    now = get_taipei_now_iso()

    # Existing coupons keep their status/order links, but become usable across
    # companion counts inside the same canonical game/service scope.
    coupon_rows = conn.execute(text("""
        SELECT id, rule_key, rule_label, player_count
        FROM customer_benefit_coupons
    """)).mappings().all()
    for raw in coupon_rows:
        row = dict(raw)
        rule_key = str(row.get("rule_key") or "").strip()
        if loyalty_policy_for_rule(rule_key) is None:
            continue
        scope = loyalty_scope_key(rule_key, int(row.get("player_count") or 1))
        conn.execute(text("""
            UPDATE customer_benefit_coupons
            SET scope_key = :scope_key,
                rule_label = :rule_label
            WHERE id = :coupon_id
        """), {
            "scope_key": scope,
            "rule_label": _loyalty_display_label(rule_key, row.get("rule_label")),
            "coupon_id": int(row["id"]),
        })

    # Old progress rows were split by player count. Remove eligible rows and
    # rebuild them from already-processed closed orders so double/triple/quad
    # orders receive the missing multiplier without double-counting.
    progress_rows = conn.execute(text("""
        SELECT customer_discord_id, scope_key, rule_key
        FROM customer_loyalty_progress
    """)).mappings().all()
    for raw in progress_rows:
        rule_key = str(raw.get("rule_key") or "").strip()
        if loyalty_policy_for_rule(rule_key) is None:
            continue
        conn.execute(text("""
            DELETE FROM customer_loyalty_progress
            WHERE customer_discord_id = :customer_id
              AND scope_key = :scope_key
        """), {
            "customer_id": str(raw.get("customer_discord_id") or ""),
            "scope_key": str(raw.get("scope_key") or ""),
        })

    order_rows = conn.execute(text("""
        SELECT o.id, o.customer_discord_id, o.order_rule_key, o.quantity,
               o.amount, o.original_amount, o.customer_pay_amount,
               o.status, o.created_at, o.updated_at, o.closed_at,
               o.price_snapshot_json, o.ticket_channel_id
        FROM web_orders o
        INNER JOIN loyalty_order_events e ON e.order_id = o.id
        WHERE o.status = 'closed'
        ORDER BY o.id ASC
    """)).mappings().all()

    aggregates: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in order_rows:
        row = dict(raw)
        customer_id = str(row.get("customer_discord_id") or "").strip()
        rule_key = str(row.get("order_rule_key") or "").strip()
        policy = loyalty_policy_for_rule(rule_key)
        if (
            not customer_id
            or policy is None
            or not _event_time_is_in_scope(row)
            or _qualifying_paid_amount(row) <= 0
        ):
            continue

        rule = _rule_for_key(rule_key)
        player_count = _extract_player_count(row)
        companion_count = _service_companion_count(rule, player_count)
        paid_units = float(max(0, int(row.get("quantity") or 0)) * companion_count)
        scope = loyalty_scope_key(rule_key, player_count)
        key = (customer_id, scope)
        bucket = aggregates.setdefault(key, {
            "customer_id": customer_id,
            "scope_key": scope,
            "rule_key": rule_key,
            "rule_label": _loyalty_display_label(
                rule_key,
                getattr(rule, "label", rule_key),
            ),
            "pricing_type": policy["pricing_type"],
            "threshold_units": float(policy["threshold_units"]),
            "benefit_kind": policy["benefit_kind"],
            "benefit_units": float(policy["benefit_units"]),
            "paid_units": 0.0,
        })
        bucket["paid_units"] = float(bucket["paid_units"]) + paid_units

        conn.execute(text("""
            UPDATE loyalty_order_events
            SET scope_key = :scope_key,
                paid_units = :paid_units,
                note = CASE
                    WHEN note IS NULL OR TRIM(note) = '' THEN 'companion_units_v2'
                    ELSE note || ';companion_units_v2'
                END
            WHERE order_id = :order_id
        """), {
            "scope_key": scope,
            "paid_units": paid_units,
            "order_id": int(row["id"]),
        })

    for bucket in aggregates.values():
        total = float(bucket["paid_units"])
        threshold = float(bucket["threshold_units"])
        earned_count = int(total // threshold) if threshold > 0 else 0
        remainder = total - earned_count * threshold if threshold > 0 else 0.0

        existing_count = int(conn.execute(text("""
            SELECT COUNT(*)
            FROM customer_benefit_coupons
            WHERE customer_discord_id = :customer_id
              AND scope_key = :scope_key
              AND source = 'loyalty'
        """), {
            "customer_id": bucket["customer_id"],
            "scope_key": bucket["scope_key"],
        }).scalar() or 0)

        missing_count = max(0, earned_count - existing_count)
        expires_at = _coupon_expiry_iso(now)
        for _ in range(missing_count):
            conn.execute(text("""
                INSERT INTO customer_benefit_coupons (
                    customer_discord_id, scope_key, rule_key, rule_label,
                    pricing_type, player_count, benefit_kind, benefit_units,
                    status, source, issued_at, expires_at
                ) VALUES (
                    :customer_id, :scope_key, :rule_key, :rule_label,
                    :pricing_type, 1, :benefit_kind, :benefit_units,
                    'active', 'loyalty', :issued_at, :expires_at
                )
            """), {
                "customer_id": bucket["customer_id"],
                "scope_key": bucket["scope_key"],
                "rule_key": bucket["rule_key"],
                "rule_label": bucket["rule_label"],
                "pricing_type": bucket["pricing_type"],
                "benefit_kind": bucket["benefit_kind"],
                "benefit_units": bucket["benefit_units"],
                "issued_at": now,
                "expires_at": expires_at,
            })

        conn.execute(text("""
            INSERT INTO customer_loyalty_progress (
                customer_discord_id, scope_key, rule_key, rule_label,
                pricing_type, player_count, progress_units, threshold_units,
                benefit_kind, benefit_units, updated_at
            ) VALUES (
                :customer_id, :scope_key, :rule_key, :rule_label,
                :pricing_type, 1, :progress_units, :threshold_units,
                :benefit_kind, :benefit_units, :updated_at
            )
            ON CONFLICT(customer_discord_id, scope_key) DO UPDATE SET
                rule_key = excluded.rule_key,
                rule_label = excluded.rule_label,
                pricing_type = excluded.pricing_type,
                player_count = 1,
                progress_units = excluded.progress_units,
                threshold_units = excluded.threshold_units,
                benefit_kind = excluded.benefit_kind,
                benefit_units = excluded.benefit_units,
                updated_at = excluded.updated_at
        """), {
            "customer_id": bucket["customer_id"],
            "scope_key": bucket["scope_key"],
            "rule_key": bucket["rule_key"],
            "rule_label": bucket["rule_label"],
            "pricing_type": bucket["pricing_type"],
            "progress_units": remainder,
            "threshold_units": threshold,
            "benefit_kind": bucket["benefit_kind"],
            "benefit_units": bucket["benefit_units"],
            "updated_at": now,
        })

    conn.execute(text("""
        INSERT INTO loyalty_migrations (migration_key, applied_at, note)
        VALUES (:migration_key, :applied_at, :note)
    """), {
        "migration_key": _LOYALTY_COMPANION_MIGRATION_KEY,
        "applied_at": now,
        "note": f"repaired_scopes={len(aggregates)}",
    })


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
            player_count = _extract_player_count(row)
            rule = _rule_for_key(rule_key)
            companion_count = _service_companion_count(rule, player_count)
            scope = loyalty_scope_key(rule_key, player_count)
            paid_units = float(
                max(0, int(row.get("quantity") or 0)) * companion_count
            )
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
            rule_label = _loyalty_display_label(
                rule_key,
                getattr(rule, "label", rule_key),
            )
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

            expires_at = _coupon_expiry_iso(now)
            for _ in range(issued_count):
                result = conn.execute(text("""
                    INSERT INTO customer_benefit_coupons (
                        customer_discord_id, scope_key, rule_key, rule_label,
                        pricing_type, player_count, benefit_kind, benefit_units,
                        status, source, issued_at, expires_at
                    ) VALUES (
                        :customer_id, :scope_key, :rule_key, :rule_label,
                        :pricing_type, :player_count, :benefit_kind, :benefit_units,
                        'active', 'loyalty', :issued_at, :expires_at
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
                    "expires_at": expires_at,
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
                    "expires_at": expires_at,
                    "expires_at_text": _coupon_expiry_text(expires_at),
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
