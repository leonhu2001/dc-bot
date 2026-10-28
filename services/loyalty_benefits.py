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
HOURLY_BONUS = 1.0
GAME_THRESHOLD = 10.0
GAME_BONUS = 1.0
COUPON_VALID_DAYS = 90

ACTIVE = "active"
RESERVED = "reserved"
REDEEMED = "redeemed"
EXPIRED = "expired"
REVOKED = "revoked"


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
                debt_units REAL NOT NULL DEFAULT 0,
                threshold_units REAL NOT NULL,
                benefit_kind TEXT NOT NULL,
                benefit_units REAL NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (customer_discord_id, scope_key)
            )
        """))
        progress_columns = {
            str(row[1])
            for row in conn.execute(text("PRAGMA table_info(customer_loyalty_progress)")).fetchall()
        }
        if "debt_units" not in progress_columns:
            conn.execute(text(
                "ALTER TABLE customer_loyalty_progress "
                "ADD COLUMN debt_units REAL NOT NULL DEFAULT 0"
            ))

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
        _repair_entertainment_loyalty_policy_v3(conn)
        _repair_apex_entertainment_shared_scope_v4(conn)


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
            "benefit_label": "+1 小時",
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


_APEX_ENTERTAINMENT_RULE_KEYS = {
    "apex_entertain_ng",
    "apex_entertain_ranked",
}
_LOYALTY_SCOPE_FAMILY_ALIASES = {
    # 同一個遊戲／服務只是陪玩席位數不同，必須共用同一個老闆福利池。
    "basic_entertain_single": "basic_entertain",
    "basic_entertain_double": "basic_entertain",
    "basic_entertain_female_single": "basic_entertain",
    "basic_entertain_male_single": "basic_entertain",
    "basic_entertain_female_double": "basic_entertain",
    "basic_entertain_male_double": "basic_entertain",
    "basic_mobile_entertain_single": "basic_mobile_entertain",
    "basic_mobile_entertain_double": "basic_mobile_entertain",
    "basic_mobile_entertain_female_single": "basic_mobile_entertain",
    "basic_mobile_entertain_male_single": "basic_mobile_entertain",
    "basic_mobile_entertain_female_double": "basic_mobile_entertain",
    "basic_mobile_entertain_male_double": "basic_mobile_entertain",
    # APEX 娛樂陪 NG / 積分皆為計時制，共用同一個 10H -> 1H 福利池。
    "apex_entertain_ng": "apex_entertain",
    "apex_entertain_ranked": "apex_entertain",
}
_LOYALTY_COMPANION_MIGRATION_KEY = "20261011_companion_service_units_v2"
_LOYALTY_POLICY_V3_MIGRATION_KEY = "20261014_entertainment_only_policy_v3"
_LOYALTY_APEX_SHARED_SCOPE_MIGRATION_KEY = "20261017_apex_entertain_shared_scope_v4"
_POLICY_V3_NONRETROACTIVE_MARKER = "policy_v3_nonretroactive"
_POLICY_V3_RANKED_START_AT_TAIPEI = datetime(2026, 10, 14, 15, 0, 0, tzinfo=TAIPEI_TZ)
_POLICY_V3_NEWLY_ELIGIBLE_RULES = {
    "valorant_entertain_ranked",
    "lol_entertain_ranked",
    "apex_entertain_ranked",
}


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
    key = str(rule_key or "").strip()
    family = _canonical_loyalty_rule_key(key)
    family_label = {
        "basic_entertain": "三角洲端遊｜娛樂陪",
        "basic_mobile_entertain": "三角洲手遊｜娛樂陪",
        "apex_entertain": "APEX｜娛樂陪",
    }.get(family)
    if family_label:
        return family_label

    label = str(fallback or rule_key or "").strip()
    if label in {"單陪", "雙陪", "三陪", "四陪"}:
        return "娛樂陪"
    for suffix in ("｜單陪", "｜雙陪", "｜三陪", "｜四陪"):
        if label.endswith(suffix):
            label = label[: -len(suffix)].rstrip("｜")
            break
    return label or key or "娛樂陪"


def _snapshot_preview(row: dict[str, Any]) -> dict[str, Any]:
    try:
        import json

        snapshot = json.loads(str(row.get("price_snapshot_json") or "{}"))
    except Exception:
        return {}
    if not isinstance(snapshot, dict):
        return {}
    preview = snapshot.get("preview")
    return preview if isinstance(preview, dict) else snapshot


def _extract_same_order_benefit_count(
    row: dict[str, Any],
    *,
    scope_key: str | None = None,
) -> int:
    preview = _snapshot_preview(row)
    benefit = preview.get("benefit_coupon") if isinstance(preview, dict) else None
    if not isinstance(benefit, dict):
        return 0
    if str(benefit.get("source") or "").strip() != "same_order":
        return 0
    if scope_key is not None:
        expected_scope = str(scope_key)
        stored_scope = str(benefit.get("scope_key") or "").strip()
        if stored_scope != expected_scope:
            benefit_rule_key = str(benefit.get("rule_key") or "").strip()
            try:
                benefit_player_count = max(1, int(benefit.get("player_count") or 1))
            except (TypeError, ValueError):
                benefit_player_count = 1
            canonical_scope = (
                loyalty_scope_key(benefit_rule_key, benefit_player_count)
                if benefit_rule_key
                else ""
            )
            if canonical_scope != expected_scope:
                return 0
    try:
        return max(0, int(benefit.get("earned_count") or 0))
    except (TypeError, ValueError):
        return 0


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


def _pending_same_order_claim_count(
    conn,
    *,
    customer_id: str,
    scope_key: str,
) -> int:
    try:
        has_orders = conn.execute(text("""
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'web_orders'
            LIMIT 1
        """)).first()
        if has_orders is None:
            return 0
        rows = conn.execute(text("""
            SELECT price_snapshot_json
            FROM web_orders
            WHERE customer_discord_id = :customer_id
              AND LOWER(COALESCE(status, '')) NOT IN ('closed', 'cancelled')
        """), {"customer_id": customer_id}).mappings().all()
    except Exception:
        return 0

    return sum(
        _extract_same_order_benefit_count(dict(row), scope_key=scope_key)
        for row in rows
    )


def preview_same_order_benefit(
    customer_id: str | int,
    *,
    rule_key: str,
    quantity: int,
    player_count: int = 1,
) -> dict[str, Any] | None:
    """Return the loyalty reward earned by this order so it can be used now.

    This is read-only. The order snapshot records the consumed reward and the
    close-order path subtracts it before issuing any future coupon.
    """
    policy = loyalty_policy_for_rule(rule_key)
    rule = _rule_for_key(rule_key)
    customer = str(customer_id or "").strip()
    if policy is None or rule is None or not customer:
        return None

    requested_players = max(1, int(player_count or 1))
    companion_count = _service_companion_count(rule, requested_players)
    paid_units = float(max(0, int(quantity or 0)) * companion_count)
    if paid_units <= 0:
        return None

    ensure_loyalty_tables()
    scope = loyalty_scope_key(rule_key, requested_players)
    threshold = float(policy["threshold_units"] or 0)
    if threshold <= 0:
        return None

    with engine.begin() as conn:
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
        credited_units = max(0.0, paid_units - debt_before)
        projected_total = previous + credited_units
        earned_count = max(0, int(projected_total // threshold))
        pending_count = _pending_same_order_claim_count(
            conn,
            customer_id=customer,
            scope_key=scope,
        )

    available_count = max(0, earned_count - pending_count)
    if available_count <= 0:
        return None

    base_units = float(policy["benefit_units"] or 0)
    benefit = {
        "id": None,
        "source": "same_order",
        "same_order": True,
        "earned_count": available_count,
        "scope_key": scope,
        "rule_key": str(rule_key),
        "rule_label": _loyalty_display_label(rule_key, getattr(rule, "label", rule_key)),
        "pricing_type": str(policy["pricing_type"]),
        "player_count": requested_players,
        "benefit_kind": str(policy["benefit_kind"]),
        "benefit_units": base_units * available_count,
        "threshold_units": threshold,
    }
    benefit["title"] = _coupon_title(benefit)
    return benefit


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
        if loyalty_policy_for_rule(str(row.get("rule_key") or "").strip()) is None:
            continue
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
    # Grandfather already-earned coupons even when this service no longer
    # accrues new loyalty progress. Scope matching still keeps the coupon tied
    # to the original game/service family.
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
    prefix = "本單累積福利" if str(coupon.get("source") or "") == "same_order" else "福利券"
    kind = str(coupon.get("benefit_kind") or "")
    units = float(coupon.get("benefit_units") or 0)
    if kind == "extra_hours":
        amount = "30 分鐘" if abs(units - 0.5) < 0.001 else f"{units:g} 小時"
        return f"{prefix}：折抵 {amount} 服務額度"
    return f"{prefix}：折抵 {int(round(units))} 局服務額度"


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


def _event_time_as_taipei(row: dict[str, Any]) -> datetime | None:
    value = row.get("closed_at") or row.get("updated_at") or row.get("created_at")
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if dt.tzinfo is None:
        # web_dashboard.db 的時間歷史上同時存在 UTC 與台北 naive；closed_at
        # 由 Bot 寫入時是台北時間。為避免漏掉制度切換當天已完成訂單，naive
        # 以台北時間解讀，只用於福利制度時間邊界。
        dt = dt.replace(tzinfo=TAIPEI_TZ)
    return dt.astimezone(TAIPEI_TZ)


def _event_time_is_in_scope(row: dict[str, Any]) -> bool:
    dt = _event_time_as_taipei(row)
    return dt is not None and dt >= LOYALTY_START_AT_TAIPEI


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
            benefit = preview.get("benefit_coupon") if isinstance(preview, dict) else None
            if isinstance(benefit, dict) and str(benefit.get("source") or "") == "same_order":
                return max(0, int(
                    finance.get("service_after_vip")
                    or finance.get("service_amount")
                    or snapshot.get("payout_base_amount")
                    or amount
                    or 0
                ))
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



def _repair_entertainment_loyalty_policy_v3(conn) -> None:
    """Align stored loyalty state with the entertainment-only policy.

    Existing eligible progress is preserved exactly. Progress for services that
    no longer accrue loyalty is removed. Already-earned coupons are untouched
    (including their original 0.5h/1h value) and remain redeemable on their
    original scope. Ranked entertainment orders that were already closed while
    those rules were ineligible are explicitly marked non-retroactive so later
    admin reconciliation cannot backfill them.
    """
    applied = conn.execute(text("""
        SELECT migration_key
        FROM loyalty_migrations
        WHERE migration_key = :migration_key
        LIMIT 1
    """), {"migration_key": _LOYALTY_POLICY_V3_MIGRATION_KEY}).first()
    if applied is not None:
        return

    now = get_taipei_now_iso()
    removed_progress = 0
    synced_progress = 0
    marked_orders = 0
    affected_customers: set[str] = set()

    progress_rows = conn.execute(text("""
        SELECT customer_discord_id, scope_key, rule_key
        FROM customer_loyalty_progress
    """)).mappings().all()
    for raw in progress_rows:
        row = dict(raw)
        rule_key = str(row.get("rule_key") or "").strip()
        policy = loyalty_policy_for_rule(rule_key)
        params = {
            "customer_id": str(row.get("customer_discord_id") or ""),
            "scope_key": str(row.get("scope_key") or ""),
        }
        if policy is None:
            result = conn.execute(text("""
                DELETE FROM customer_loyalty_progress
                WHERE customer_discord_id = :customer_id
                  AND scope_key = :scope_key
            """), params)
            removed_progress += int(result.rowcount or 0)
            continue

        conn.execute(text("""
            UPDATE customer_loyalty_progress
            SET threshold_units = :threshold_units,
                benefit_kind = :benefit_kind,
                benefit_units = :benefit_units,
                updated_at = :updated_at
            WHERE customer_discord_id = :customer_id
              AND scope_key = :scope_key
        """), {
            **params,
            "threshold_units": float(policy["threshold_units"]),
            "benefit_kind": str(policy["benefit_kind"]),
            "benefit_units": float(policy["benefit_units"]),
            "updated_at": now,
        })
        synced_progress += 1

    has_orders = conn.execute(text("""
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'web_orders'
        LIMIT 1
    """)).first()
    if has_orders is not None:
        for rule_key in sorted(_POLICY_V3_NEWLY_ELIGIBLE_RULES):
            rows = conn.execute(text("""
                SELECT o.id, o.customer_discord_id,
                       o.created_at, o.updated_at, o.closed_at,
                       e.order_id AS event_order_id, e.note AS event_note
                FROM web_orders o
                LEFT JOIN loyalty_order_events e ON e.order_id = o.id
                WHERE o.status = 'closed'
                  AND o.order_rule_key = :rule_key
                ORDER BY o.id ASC
            """), {"rule_key": rule_key}).mappings().all()
            for raw in rows:
                row = dict(raw)
                order_id = int(row["id"])
                event_time = _event_time_as_taipei(row)
                if event_time is None or event_time >= _POLICY_V3_RANKED_START_AT_TAIPEI:
                    continue
                event_order_id = row.get("event_order_id")
                event_note = str(row.get("event_note") or "").strip()
                parts = [part.strip() for part in event_note.split(";") if part.strip()]
                customer_id = str(row.get("customer_discord_id") or "").strip()
                if customer_id:
                    affected_customers.add(customer_id)

                if event_order_id is not None:
                    if _POLICY_V3_NONRETROACTIVE_MARKER not in parts:
                        parts.append(_POLICY_V3_NONRETROACTIVE_MARKER)
                        marked_orders += 1
                    conn.execute(text("""
                        UPDATE loyalty_order_events
                        SET note = :note,
                            processed_at = :processed_at
                        WHERE order_id = :order_id
                    """), {
                        "order_id": order_id,
                        "note": ";".join(parts),
                        "processed_at": now,
                    })
                    continue

                conn.execute(text("""
                    INSERT INTO loyalty_order_events (
                        order_id, customer_discord_id, scope_key, paid_units,
                        issued_coupon_count, processed_at, note
                    ) VALUES (
                        :order_id, :customer_id, NULL, 0,
                        0, :processed_at, :note
                    )
                """), {
                    "order_id": order_id,
                    "customer_id": str(row.get("customer_discord_id") or "") or None,
                    "processed_at": now,
                    "note": _POLICY_V3_NONRETROACTIVE_MARKER,
                })
                marked_orders += 1

    # If #270 briefly processed a pre-rollout ranked order before this cleanup
    # deployed, rebuild those customers now so the accidental backfill is
    # removed immediately instead of waiting for a future admin edit.
    for customer_id in sorted(affected_customers):
        reconcile_customer_loyalty_in_connection(conn, customer_id)

    conn.execute(text("""
        INSERT INTO loyalty_migrations (migration_key, applied_at, note)
        VALUES (:migration_key, :applied_at, :note)
    """), {
        "migration_key": _LOYALTY_POLICY_V3_MIGRATION_KEY,
        "applied_at": now,
        "note": (
            f"removed_progress={removed_progress};"
            f"synced_progress={synced_progress};"
            f"marked_orders={marked_orders};"
            f"reconciled_customers={len(affected_customers)}"
        ),
    })


def _repair_apex_entertainment_shared_scope_v4(conn) -> None:
    """Merge APEX entertainment NG/ranked into one hourly loyalty pool."""
    applied = conn.execute(text("""
        SELECT migration_key
        FROM loyalty_migrations
        WHERE migration_key = :migration_key
        LIMIT 1
    """), {"migration_key": _LOYALTY_APEX_SHARED_SCOPE_MIGRATION_KEY}).first()
    if applied is not None:
        return

    has_orders = conn.execute(text("""
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'web_orders'
        LIMIT 1
    """)).first()
    if has_orders is None:
        return

    now = get_taipei_now_iso()
    shared_scope = loyalty_scope_key("apex_entertain_ng")
    old_scopes = (
        "apex|apex_entertain_ng",
        "apex|apex_entertain_ranked",
        shared_scope,
    )
    affected_customers: set[str] = set()

    customer_queries = (
        """
        SELECT DISTINCT customer_discord_id
        FROM customer_loyalty_progress
        WHERE rule_key IN ('apex_entertain_ng', 'apex_entertain_ranked')
           OR scope_key IN (:scope_1, :scope_2, :scope_3)
        """,
        """
        SELECT DISTINCT customer_discord_id
        FROM customer_benefit_coupons
        WHERE rule_key IN ('apex_entertain_ng', 'apex_entertain_ranked')
           OR scope_key IN (:scope_1, :scope_2, :scope_3)
        """,
        """
        SELECT DISTINCT customer_discord_id
        FROM web_orders
        WHERE order_rule_key IN ('apex_entertain_ng', 'apex_entertain_ranked')
        """,
    )
    scope_params = {
        "scope_1": old_scopes[0],
        "scope_2": old_scopes[1],
        "scope_3": old_scopes[2],
    }
    for query in customer_queries:
        for row in conn.execute(text(query), scope_params).fetchall():
            customer_id = str(row[0] or "").strip()
            if customer_id:
                affected_customers.add(customer_id)

    conn.execute(text("""
        UPDATE customer_benefit_coupons
        SET scope_key = :shared_scope,
            rule_label = 'APEX｜娛樂陪'
        WHERE rule_key IN ('apex_entertain_ng', 'apex_entertain_ranked')
           OR scope_key IN (:scope_1, :scope_2, :scope_3)
    """), {"shared_scope": shared_scope, **scope_params})

    conn.execute(text("""
        DELETE FROM customer_loyalty_progress
        WHERE rule_key IN ('apex_entertain_ng', 'apex_entertain_ranked')
           OR scope_key IN (:scope_1, :scope_2, :scope_3)
    """), scope_params)

    revoked = 0
    issued = 0
    for customer_id in sorted(affected_customers):
        summary = reconcile_customer_loyalty_in_connection(conn, customer_id)
        revoked += int(summary.get("revoked") or 0)
        issued += int(summary.get("issued") or 0)

    conn.execute(text("""
        INSERT INTO loyalty_migrations (migration_key, applied_at, note)
        VALUES (:migration_key, :applied_at, :note)
    """), {
        "migration_key": _LOYALTY_APEX_SHARED_SCOPE_MIGRATION_KEY,
        "applied_at": now,
        "note": (
            f"shared_scope={shared_scope};"
            f"reconciled_customers={len(affected_customers)};"
            f"revoked={revoked};issued={issued}"
        ),
    })


def _append_reconcile_note(existing: object, marker: str) -> str:
    note = str(existing or "").strip()
    if not note:
        return marker
    parts = [part.strip() for part in note.split(";") if part.strip()]
    if marker not in parts:
        parts.append(marker)
    return ";".join(parts)


def _loyalty_bucket_from_order(row: dict[str, Any]) -> dict[str, Any] | None:
    customer_id = str(row.get("customer_discord_id") or "").strip()
    rule_key = str(row.get("order_rule_key") or "").strip()
    policy = loyalty_policy_for_rule(rule_key)
    if (
        not customer_id
        or str(row.get("status") or "").strip().lower() != "closed"
        or policy is None
        or not _event_time_is_in_scope(row)
        or _qualifying_paid_amount(row) <= 0
    ):
        return None

    rule = _rule_for_key(rule_key)
    player_count = _extract_player_count(row)
    companion_count = _service_companion_count(rule, player_count)
    return {
        "customer_id": customer_id,
        "scope_key": loyalty_scope_key(rule_key, player_count),
        "rule_key": rule_key,
        "rule_label": _loyalty_display_label(
            rule_key,
            getattr(rule, "label", rule_key),
        ),
        "pricing_type": str(policy["pricing_type"]),
        "threshold_units": float(policy["threshold_units"]),
        "benefit_kind": str(policy["benefit_kind"]),
        "benefit_units": float(policy["benefit_units"]),
        "paid_units": float(
            max(0, int(row.get("quantity") or 0)) * companion_count
        ),
        "same_order_consumed_count": _extract_same_order_benefit_count(row),
    }


def reconcile_customer_loyalty_in_connection(conn, customer_id: str | int) -> dict[str, Any]:
    """Rebuild one customer's loyalty pools from current closed orders.

    Unused over-issued rewards are revoked. Redeemed/reserved rewards are never
    clawed back; when an edit makes them exceed the customer's earned total,
    debt_units makes future service units pay back that difference before new
    progress can earn another reward.
    """
    customer = str(customer_id or "").strip()
    if not customer:
        return {"customer_id": "", "scopes": 0, "revoked": 0, "issued": 0}

    progress_columns = {
        str(row[1])
        for row in conn.execute(text("PRAGMA table_info(customer_loyalty_progress)")).fetchall()
    }
    if "debt_units" not in progress_columns:
        conn.execute(text(
            "ALTER TABLE customer_loyalty_progress "
            "ADD COLUMN debt_units REAL NOT NULL DEFAULT 0"
        ))

    now = get_taipei_now_iso()
    _expire_active_coupons(conn)

    # Existing events are markers for idempotency. Reset this customer's markers
    # first, then rewrite them from the current source-of-truth order rows.
    event_rows = conn.execute(text("""
        SELECT order_id, note
        FROM loyalty_order_events
        WHERE customer_discord_id = :customer_id
    """), {"customer_id": customer}).mappings().all()
    event_notes = {
        int(event["order_id"]): str(event.get("note") or "")
        for event in event_rows
    }
    for event in event_rows:
        conn.execute(text("""
            UPDATE loyalty_order_events
            SET scope_key = NULL,
                paid_units = 0,
                processed_at = :processed_at,
                note = :note
            WHERE order_id = :order_id
        """), {
            "order_id": int(event["order_id"]),
            "processed_at": now,
            "note": _append_reconcile_note(event.get("note"), "admin_reconciled"),
        })

    order_rows = conn.execute(text("""
        SELECT id, customer_discord_id, order_rule_key, quantity,
               amount, original_amount, customer_pay_amount,
               status, created_at, updated_at, closed_at,
               price_snapshot_json, ticket_channel_id
        FROM web_orders
        WHERE customer_discord_id = :customer_id
          AND status = 'closed'
        ORDER BY id ASC
    """), {"customer_id": customer}).mappings().all()

    buckets: dict[str, dict[str, Any]] = {}
    for raw in order_rows:
        row = dict(raw)
        prior_note = event_notes.get(int(row["id"]), "")
        prior_parts = {part.strip() for part in prior_note.split(";") if part.strip()}
        nonretroactive = _POLICY_V3_NONRETROACTIVE_MARKER in prior_parts
        bucket = None if nonretroactive else _loyalty_bucket_from_order(row)
        note = "admin_reconciled"
        scope = None
        paid_units = 0.0
        if bucket is not None:
            scope = str(bucket["scope_key"])
            paid_units = float(bucket["paid_units"])
            aggregate = buckets.get(scope)
            if aggregate is None:
                aggregate = dict(bucket)
                aggregate["paid_units"] = 0.0
                aggregate["same_order_consumed_count"] = 0
                buckets[scope] = aggregate
            aggregate["paid_units"] = float(aggregate.get("paid_units") or 0) + paid_units
            aggregate["same_order_consumed_count"] = int(
                aggregate.get("same_order_consumed_count") or 0
            ) + int(bucket.get("same_order_consumed_count") or 0)
        elif nonretroactive:
            note = f"admin_reconciled;{_POLICY_V3_NONRETROACTIVE_MARKER}"
        elif not str(row.get("customer_discord_id") or "").strip():
            note = "admin_reconciled;missing_customer"
        elif not _event_time_is_in_scope(row):
            note = "admin_reconciled;before_program_start"
        elif loyalty_policy_for_rule(str(row.get("order_rule_key") or "").strip()) is None:
            note = "admin_reconciled;rule_not_eligible"
        elif _qualifying_paid_amount(row) <= 0:
            note = "admin_reconciled;no_paid_amount"

        conn.execute(text("""
            INSERT INTO loyalty_order_events (
                order_id, customer_discord_id, scope_key, paid_units,
                issued_coupon_count, processed_at, note
            ) VALUES (
                :order_id, :customer_id, :scope_key, :paid_units,
                0, :processed_at, :note
            )
            ON CONFLICT(order_id) DO UPDATE SET
                customer_discord_id = excluded.customer_discord_id,
                scope_key = excluded.scope_key,
                paid_units = excluded.paid_units,
                processed_at = excluded.processed_at,
                note = excluded.note
        """), {
            "order_id": int(row["id"]),
            "customer_id": customer,
            "scope_key": scope,
            "paid_units": paid_units,
            "processed_at": now,
            "note": note,
        })

    scope_meta: dict[str, dict[str, Any]] = {
        scope: dict(bucket) for scope, bucket in buckets.items()
    }

    progress_rows = conn.execute(text("""
        SELECT *
        FROM customer_loyalty_progress
        WHERE customer_discord_id = :customer_id
    """), {"customer_id": customer}).mappings().all()
    for raw in progress_rows:
        row = dict(raw)
        scope = str(row.get("scope_key") or "").strip()
        rule_key = str(row.get("rule_key") or "").strip()
        policy = loyalty_policy_for_rule(rule_key)
        if not scope or scope in scope_meta or policy is None:
            continue
        scope_meta[scope] = {
            "customer_id": customer,
            "scope_key": scope,
            "rule_key": rule_key,
            "rule_label": str(row.get("rule_label") or rule_key or "福利"),
            "pricing_type": str(policy["pricing_type"]),
            "threshold_units": float(policy["threshold_units"]),
            "benefit_kind": str(policy["benefit_kind"]),
            "benefit_units": float(policy["benefit_units"]),
            "paid_units": 0.0,
            "same_order_consumed_count": 0,
        }

    coupon_meta_rows = conn.execute(text("""
        SELECT scope_key, rule_key, rule_label, pricing_type,
               benefit_kind, benefit_units
        FROM customer_benefit_coupons
        WHERE customer_discord_id = :customer_id
          AND source = 'loyalty'
        ORDER BY id ASC
    """), {"customer_id": customer}).mappings().all()
    for raw in coupon_meta_rows:
        row = dict(raw)
        scope = str(row.get("scope_key") or "").strip()
        if not scope or scope in scope_meta:
            continue
        rule_key = str(row.get("rule_key") or "").strip()
        policy = loyalty_policy_for_rule(rule_key)
        if policy is None:
            continue
        scope_meta[scope] = {
            "customer_id": customer,
            "scope_key": scope,
            "rule_key": rule_key,
            "rule_label": _loyalty_display_label(rule_key, row.get("rule_label")),
            "pricing_type": str(row.get("pricing_type") or policy["pricing_type"]),
            "threshold_units": float(policy["threshold_units"]),
            "benefit_kind": str(row.get("benefit_kind") or policy["benefit_kind"]),
            "benefit_units": float(row.get("benefit_units") or policy["benefit_units"]),
            "paid_units": 0.0,
            "same_order_consumed_count": 0,
        }

    revoked_total = 0
    issued_total = 0

    for scope, meta in scope_meta.items():
        threshold = float(meta.get("threshold_units") or 0)
        if threshold <= 0:
            continue
        total_units = float((buckets.get(scope) or {}).get("paid_units") or 0)
        earned_count = max(0, int(total_units // threshold))
        remainder = max(0.0, total_units - earned_count * threshold)

        coupons = [
            dict(row)
            for row in conn.execute(text("""
                SELECT *
                FROM customer_benefit_coupons
                WHERE customer_discord_id = :customer_id
                  AND scope_key = :scope_key
                  AND source = 'loyalty'
                ORDER BY issued_at ASC, id ASC
            """), {
                "customer_id": customer,
                "scope_key": scope,
            }).mappings().all()
        ]
        protected = [
            row for row in coupons
            if str(row.get("status") or "").lower() in {RESERVED, REDEEMED}
        ]
        expired = [
            row for row in coupons
            if str(row.get("status") or "").lower() == EXPIRED
        ]
        active = [
            row for row in coupons
            if str(row.get("status") or "").lower() == ACTIVE
        ]

        same_order_consumed = max(
            0,
            int((buckets.get(scope) or {}).get("same_order_consumed_count") or 0),
        )
        protected_count = len(protected) + same_order_consumed
        target_nonprotected = max(0, earned_count - protected_count)
        keep_expired = min(len(expired), target_nonprotected)
        revoke_expired = expired[keep_expired:]
        target_active = max(0, target_nonprotected - keep_expired)

        excess_active = max(0, len(active) - target_active)
        # Revoke newest active rewards first so the oldest valid reward remains FIFO.
        revoke_active = list(reversed(active))[:excess_active]
        revoke_rows = revoke_expired + revoke_active
        if revoke_rows:
            ids = [int(row["id"]) for row in revoke_rows]
            placeholders = ",".join(str(value) for value in ids)
            result = conn.execute(text(f"""
                UPDATE customer_benefit_coupons
                SET status = 'revoked',
                    reserved_order_id = NULL
                WHERE id IN ({placeholders})
                  AND status IN ('active', 'expired')
            """))
            revoked_total += int(result.rowcount or 0)

        active_after = max(0, len(active) - excess_active)
        missing_active = max(0, target_active - active_after)
        expires_at = _coupon_expiry_iso(now)
        for _ in range(missing_active):
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
                "customer_id": customer,
                "scope_key": scope,
                "rule_key": str(meta.get("rule_key") or ""),
                "rule_label": str(meta.get("rule_label") or meta.get("rule_key") or "福利"),
                "pricing_type": str(meta.get("pricing_type") or ""),
                "benefit_kind": str(meta.get("benefit_kind") or ""),
                "benefit_units": float(meta.get("benefit_units") or 0),
                "issued_at": now,
                "expires_at": expires_at,
            })
            issued_total += 1

        debt_units = max(0.0, protected_count * threshold - total_units)
        progress_units = 0.0 if debt_units > 0.0001 else remainder
        current_bucket = buckets.get(scope)

        if current_bucket is None and progress_units <= 0.0001 and debt_units <= 0.0001:
            conn.execute(text("""
                DELETE FROM customer_loyalty_progress
                WHERE customer_discord_id = :customer_id
                  AND scope_key = :scope_key
            """), {"customer_id": customer, "scope_key": scope})
            continue

        conn.execute(text("""
            INSERT INTO customer_loyalty_progress (
                customer_discord_id, scope_key, rule_key, rule_label,
                pricing_type, player_count, progress_units, debt_units,
                threshold_units, benefit_kind, benefit_units, updated_at
            ) VALUES (
                :customer_id, :scope_key, :rule_key, :rule_label,
                :pricing_type, 1, :progress_units, :debt_units,
                :threshold_units, :benefit_kind, :benefit_units, :updated_at
            )
            ON CONFLICT(customer_discord_id, scope_key) DO UPDATE SET
                rule_key = excluded.rule_key,
                rule_label = excluded.rule_label,
                pricing_type = excluded.pricing_type,
                player_count = 1,
                progress_units = excluded.progress_units,
                debt_units = excluded.debt_units,
                threshold_units = excluded.threshold_units,
                benefit_kind = excluded.benefit_kind,
                benefit_units = excluded.benefit_units,
                updated_at = excluded.updated_at
        """), {
            "customer_id": customer,
            "scope_key": scope,
            "rule_key": str(meta.get("rule_key") or ""),
            "rule_label": str(meta.get("rule_label") or meta.get("rule_key") or "福利"),
            "pricing_type": str(meta.get("pricing_type") or ""),
            "progress_units": progress_units,
            "debt_units": debt_units,
            "threshold_units": threshold,
            "benefit_kind": str(meta.get("benefit_kind") or ""),
            "benefit_units": float(meta.get("benefit_units") or 0),
            "updated_at": now,
        })

    return {
        "customer_id": customer,
        "scopes": len(scope_meta),
        "revoked": revoked_total,
        "issued": issued_total,
    }


def reconcile_loyalty_after_order_edit_in_connection(
    conn,
    *,
    order_id: int,
    previous_customer_id: str | int | None = None,
) -> dict[str, Any]:
    """Reconcile old/new customer pools after an admin changes an order."""
    row = conn.execute(text("""
        SELECT customer_discord_id, status
        FROM web_orders
        WHERE id = :order_id
        LIMIT 1
    """), {"order_id": int(order_id)}).mappings().first()
    if row is None:
        return {"customers": [], "revoked": 0, "issued": 0}

    current_customer = str(row.get("customer_discord_id") or "").strip()
    current_status = str(row.get("status") or "").strip().lower()
    previous_customer = str(previous_customer_id or "").strip()

    if current_status != "closed":
        conn.execute(text(
            "DELETE FROM loyalty_order_events WHERE order_id = :order_id"
        ), {"order_id": int(order_id)})

    customers = []
    for customer in (previous_customer, current_customer):
        if customer and customer not in customers:
            customers.append(customer)

    summaries = [
        reconcile_customer_loyalty_in_connection(conn, customer)
        for customer in customers
    ]
    return {
        "customers": customers,
        "revoked": sum(int(item.get("revoked") or 0) for item in summaries),
        "issued": sum(int(item.get("issued") or 0) for item in summaries),
    }


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
            progress_row = conn.execute(text("""
                SELECT progress_units, debt_units
                FROM customer_loyalty_progress
                WHERE customer_discord_id = :customer_id
                  AND scope_key = :scope_key
                LIMIT 1
            """), {
                "customer_id": customer_id,
                "scope_key": scope,
            }).mappings().first()
            previous = float(progress_row.get("progress_units") or 0) if progress_row else 0.0
            debt_before = float(progress_row.get("debt_units") or 0) if progress_row else 0.0
            debt_after = max(0.0, debt_before - paid_units)
            credited_units = max(0.0, paid_units - debt_before)
            total = previous + credited_units
            same_order_consumed = _extract_same_order_benefit_count(row)
            consumed_units = float(same_order_consumed) * threshold
            if consumed_units > total:
                debt_after += consumed_units - total
                rewardable_total = 0.0
            else:
                rewardable_total = total - consumed_units
            issued_count = max(0, int(rewardable_total // threshold))
            remainder = rewardable_total - issued_count * threshold
            rule_label = _loyalty_display_label(
                rule_key,
                getattr(rule, "label", rule_key),
            )
            now = get_taipei_now_iso()
            conn.execute(text("""
                INSERT INTO customer_loyalty_progress (
                    customer_discord_id, scope_key, rule_key, rule_label,
                    pricing_type, player_count, progress_units, debt_units, threshold_units,
                    benefit_kind, benefit_units, updated_at
                ) VALUES (
                    :customer_id, :scope_key, :rule_key, :rule_label,
                    :pricing_type, :player_count, :progress_units, :debt_units, :threshold_units,
                    :benefit_kind, :benefit_units, :updated_at
                )
                ON CONFLICT(customer_discord_id, scope_key) DO UPDATE SET
                    rule_label = excluded.rule_label,
                    progress_units = excluded.progress_units,
                    debt_units = excluded.debt_units,
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
                "debt_units": debt_after,
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