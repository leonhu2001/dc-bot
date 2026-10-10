from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any

from core.time_utils import get_taipei_now, get_taipei_now_iso


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_FILE = ROOT / "bot.db"
LOYALTY_PROGRAM_START_DATE = "2026-10-10"


def _db_path(db_file: str | Path | None = None) -> Path:
    return Path(db_file) if db_file is not None else DEFAULT_DB_FILE


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _format_units(value: float) -> str:
    number = float(value or 0)
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


def _completed_after_program_start(value: str | None) -> bool:
    if not value:
        return True
    text = str(value).strip()
    if not text:
        return True
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed.date().isoformat() >= LOYALTY_PROGRAM_START_DATE
    except ValueError:
        # Unknown legacy date format: do not block a live completion event.
        return True


def ensure_loyalty_tables(db_file: str | Path | None = None) -> None:
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS loyalty_progress (
                customer_discord_id TEXT NOT NULL,
                rule_key TEXT NOT NULL,
                player_count INTEGER NOT NULL DEFAULT 1,
                pricing_type TEXT NOT NULL,
                paid_units REAL NOT NULL DEFAULT 0,
                lifetime_paid_units REAL NOT NULL DEFAULT 0,
                threshold_units REAL NOT NULL,
                reward_units REAL NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(customer_discord_id, rule_key, player_count)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS loyalty_coupons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_discord_id TEXT NOT NULL,
                rule_key TEXT NOT NULL,
                player_count INTEGER NOT NULL DEFAULT 1,
                pricing_type TEXT NOT NULL,
                reward_units REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'available',
                source_order_key TEXT NOT NULL,
                reservation_key TEXT,
                used_order_key TEXT,
                issued_at TEXT NOT NULL,
                reserved_at TEXT,
                used_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_loyalty_coupon_source
            ON loyalty_coupons(source_order_key)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_loyalty_coupon_customer
            ON loyalty_coupons(customer_discord_id, status, rule_key, player_count)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS loyalty_order_events (
                source_order_key TEXT PRIMARY KEY,
                customer_discord_id TEXT NOT NULL,
                rule_key TEXT NOT NULL,
                player_count INTEGER NOT NULL DEFAULT 1,
                paid_units REAL NOT NULL,
                completed_at TEXT,
                processed_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def get_loyalty_program(rule_key: str) -> dict[str, Any] | None:
    try:
        from services.order_rules import ORDER_RULES

        rule = ORDER_RULES.get(str(rule_key or "").strip())
    except Exception:
        rule = None

    if rule is None:
        return None

    threshold = _to_float(getattr(rule, "loyalty_threshold_units", 0), 0)
    reward = _to_float(getattr(rule, "loyalty_reward_units", 0), 0)
    pricing_type = str(getattr(rule, "pricing_type", "") or "").strip().lower()

    if threshold <= 0 or reward <= 0 or pricing_type not in {"hourly", "game"}:
        return None

    return {
        "rule_key": str(rule.key),
        "label": str(rule.label),
        "pricing_type": pricing_type,
        "threshold_units": threshold,
        "reward_units": reward,
        "unit_label": "小時" if pricing_type == "hourly" else "局",
        "reward_label": reward_label(pricing_type, reward),
    }


def reward_label(pricing_type: str, reward_units: float) -> str:
    pricing_type = str(pricing_type or "").lower()
    units = float(reward_units or 0)
    if pricing_type == "hourly":
        if units == 0.5:
            return "加時 30 分鐘"
        if units == 1:
            return "加時 1 小時"
        return f"加時 {_format_units(units)} 小時"
    if units == 1:
        return "加 1 局"
    return f"加 {_format_units(units)} 局"


def _decorate_coupon(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    program = get_loyalty_program(str(item.get("rule_key") or ""))
    item["program_label"] = (
        str(program.get("label"))
        if program
        else str(item.get("rule_key") or "福利")
    )
    item["benefit_label"] = reward_label(
        str(item.get("pricing_type") or ""),
        _to_float(item.get("reward_units"), 0),
    )
    item["display_name"] = f"{item['program_label']}｜{item['benefit_label']}"
    return item


def list_available_coupons(
    customer_id: str | int,
    *,
    rule_key: str | None = None,
    player_count: int | None = None,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_loyalty_tables(db_file)
    sql = (
        "SELECT * FROM loyalty_coupons "
        "WHERE customer_discord_id=? AND status='available'"
    )
    params: list[Any] = [str(customer_id)]
    if rule_key:
        sql += " AND rule_key=?"
        params.append(str(rule_key))
    if player_count is not None:
        sql += " AND player_count=?"
        params.append(max(1, int(player_count or 1)))
    sql += " ORDER BY id ASC"

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        return [_decorate_coupon(row) for row in conn.execute(sql, params).fetchall()]


def get_coupon(
    coupon_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_loyalty_tables(db_file)
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM loyalty_coupons WHERE id=? LIMIT 1",
            (int(coupon_id),),
        ).fetchone()
        return _decorate_coupon(row) if row else None


def validate_coupon_for_order(
    coupon_id: int,
    *,
    customer_id: str | int,
    rule_key: str,
    player_count: int = 1,
    allow_reserved: bool = False,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    coupon = get_coupon(int(coupon_id), db_file=db_file)
    if coupon is None:
        raise ValueError("找不到這張累積福利券。")
    if str(coupon.get("customer_discord_id")) != str(customer_id):
        raise ValueError("這張福利券不屬於目前顧客。")
    if str(coupon.get("rule_key")) != str(rule_key):
        raise ValueError("這張福利券不適用目前選擇的商品。")
    if int(coupon.get("player_count") or 1) != max(1, int(player_count or 1)):
        raise ValueError("這張福利券的人數規格與目前訂單不同。")
    status = str(coupon.get("status") or "")
    allowed_statuses = {"available", "reserved"} if allow_reserved else {"available"}
    if status not in allowed_statuses:
        raise ValueError("這張福利券目前不可使用。")
    return coupon


def reserve_coupon(
    coupon_id: int,
    *,
    customer_id: str | int,
    rule_key: str,
    player_count: int = 1,
    reservation_key: str,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_loyalty_tables(db_file)
    path = _db_path(db_file)
    reservation_key = str(reservation_key or "").strip()
    if not reservation_key:
        raise ValueError("福利券缺少訂單保留識別碼。")

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM loyalty_coupons WHERE id=? LIMIT 1",
            (int(coupon_id),),
        ).fetchone()
        if row is None:
            raise ValueError("找不到這張累積福利券。")
        item = dict(row)
        if str(item.get("customer_discord_id")) != str(customer_id):
            raise ValueError("這張福利券不屬於目前顧客。")
        if str(item.get("rule_key")) != str(rule_key):
            raise ValueError("這張福利券不適用目前選擇的商品。")
        if int(item.get("player_count") or 1) != max(1, int(player_count or 1)):
            raise ValueError("這張福利券的人數規格與目前訂單不同。")

        status = str(item.get("status") or "")
        if status == "reserved" and str(item.get("reservation_key") or "") == reservation_key:
            conn.rollback()
            return _decorate_coupon(item)
        if status != "available":
            raise ValueError("這張福利券已被其他訂單使用或保留。")

        now = get_taipei_now_iso()
        result = conn.execute(
            """
            UPDATE loyalty_coupons
            SET status='reserved', reservation_key=?, reserved_at=?
            WHERE id=? AND status='available'
            """,
            (reservation_key, now, int(coupon_id)),
        )
        if int(result.rowcount or 0) != 1:
            raise ValueError("福利券狀態已變更，請重新選擇。")
        conn.commit()

    return get_coupon(int(coupon_id), db_file=db_file) or item


def consume_coupon(
    coupon_id: int,
    *,
    customer_id: str | int,
    used_order_key: str,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_loyalty_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM loyalty_coupons WHERE id=? LIMIT 1",
            (int(coupon_id),),
        ).fetchone()
        if row is None:
            raise ValueError("找不到這張累積福利券。")
        item = dict(row)
        if str(item.get("customer_discord_id")) != str(customer_id):
            raise ValueError("這張福利券不屬於目前顧客。")
        status = str(item.get("status") or "")
        if status == "used":
            if str(item.get("used_order_key") or "") == str(used_order_key):
                conn.rollback()
                return _decorate_coupon(item)
            raise ValueError("這張福利券已使用。")
        if status not in {"available", "reserved"}:
            raise ValueError("這張福利券目前不可使用。")

        now = get_taipei_now_iso()
        conn.execute(
            """
            UPDATE loyalty_coupons
            SET status='used', used_order_key=?, used_at=?
            WHERE id=?
            """,
            (str(used_order_key), now, int(coupon_id)),
        )
        conn.commit()

    return get_coupon(int(coupon_id), db_file=db_file) or _decorate_coupon(item)


def release_coupon(
    coupon_id: int,
    *,
    customer_id: str | int | None = None,
    db_file: str | Path | None = None,
) -> bool:
    ensure_loyalty_tables(db_file)
    params: list[Any] = [int(coupon_id)]
    sql = (
        "UPDATE loyalty_coupons "
        "SET status='available', reservation_key=NULL, reserved_at=NULL "
        "WHERE id=? AND status='reserved'"
    )
    if customer_id is not None:
        sql += " AND customer_discord_id=?"
        params.append(str(customer_id))
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        result = conn.execute(sql, params)
        conn.commit()
        return int(result.rowcount or 0) == 1



def restore_coupon(
    coupon_id: int,
    *,
    customer_id: str | int | None = None,
    db_file: str | Path | None = None,
) -> bool:
    """Return a reserved/used loyalty coupon after an order cancellation."""
    ensure_loyalty_tables(db_file)
    params: list[Any] = [int(coupon_id)]
    sql = (
        "UPDATE loyalty_coupons "
        "SET status='available', reservation_key=NULL, reserved_at=NULL, "
        "used_order_key=NULL, used_at=NULL "
        "WHERE id=? AND status IN ('reserved','used')"
    )
    if customer_id is not None:
        sql += " AND customer_discord_id=?"
        params.append(str(customer_id))
    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        result = conn.execute(sql, params)
        conn.commit()
        return int(result.rowcount or 0) == 1

def record_paid_service(
    *,
    customer_id: str | int,
    rule_key: str,
    player_count: int,
    paid_units: float,
    source_order_key: str,
    completed_at: str | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    """Accumulate only purchased base units and issue coupons at thresholds.

    Callers must pass the purchased quantity only. Point-added time/games and
    loyalty-coupon bonus units are deliberately excluded from paid_units.
    """
    program = get_loyalty_program(rule_key)
    if program is None:
        return {"eligible": False, "issued": [], "progress": None}

    paid_units = max(0.0, float(paid_units or 0))
    if paid_units <= 0:
        return {"eligible": True, "issued": [], "progress": None}

    if not _completed_after_program_start(completed_at):
        return {
            "eligible": False,
            "reason": "program_not_started_for_order",
            "issued": [],
            "progress": None,
        }

    source_order_key = str(source_order_key or "").strip()
    if not source_order_key:
        raise ValueError("累積福利缺少訂單識別碼。")

    ensure_loyalty_tables(db_file)
    path = _db_path(db_file)
    customer_id = str(customer_id)
    player_count = max(1, int(player_count or 1))
    now = get_taipei_now_iso()

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT source_order_key FROM loyalty_order_events WHERE source_order_key=?",
            (source_order_key,),
        ).fetchone()
        if existing is not None:
            row = conn.execute(
                """
                SELECT * FROM loyalty_progress
                WHERE customer_discord_id=? AND rule_key=? AND player_count=?
                """,
                (customer_id, str(rule_key), player_count),
            ).fetchone()
            conn.rollback()
            return {
                "eligible": True,
                "duplicate": True,
                "issued": [],
                "progress": dict(row) if row else None,
            }

        conn.execute(
            """
            INSERT INTO loyalty_order_events(
                source_order_key, customer_discord_id, rule_key, player_count,
                paid_units, completed_at, processed_at
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                source_order_key,
                customer_id,
                str(rule_key),
                player_count,
                paid_units,
                str(completed_at or "") or None,
                now,
            ),
        )

        row = conn.execute(
            """
            SELECT * FROM loyalty_progress
            WHERE customer_discord_id=? AND rule_key=? AND player_count=?
            """,
            (customer_id, str(rule_key), player_count),
        ).fetchone()
        old_progress = _to_float(row["paid_units"], 0) if row else 0.0
        old_lifetime = _to_float(row["lifetime_paid_units"], 0) if row else 0.0
        threshold = float(program["threshold_units"])
        reward_units = float(program["reward_units"])
        combined = old_progress + paid_units
        earned = int(combined // threshold)
        remaining = combined - (earned * threshold)
        lifetime = old_lifetime + paid_units

        conn.execute(
            """
            INSERT INTO loyalty_progress(
                customer_discord_id, rule_key, player_count, pricing_type,
                paid_units, lifetime_paid_units, threshold_units, reward_units,
                updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(customer_discord_id, rule_key, player_count)
            DO UPDATE SET
                pricing_type=excluded.pricing_type,
                paid_units=excluded.paid_units,
                lifetime_paid_units=excluded.lifetime_paid_units,
                threshold_units=excluded.threshold_units,
                reward_units=excluded.reward_units,
                updated_at=excluded.updated_at
            """,
            (
                customer_id,
                str(rule_key),
                player_count,
                str(program["pricing_type"]),
                remaining,
                lifetime,
                threshold,
                reward_units,
                now,
            ),
        )

        issued_ids: list[int] = []
        for index in range(earned):
            coupon_source = f"{source_order_key}:coupon:{index + 1}"
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO loyalty_coupons(
                    customer_discord_id, rule_key, player_count, pricing_type,
                    reward_units, status, source_order_key, issued_at
                ) VALUES(?,?,?,?,?,'available',?,?)
                """,
                (
                    customer_id,
                    str(rule_key),
                    player_count,
                    str(program["pricing_type"]),
                    reward_units,
                    coupon_source,
                    now,
                ),
            )
            if int(cursor.rowcount or 0) == 1:
                issued_ids.append(int(cursor.lastrowid))
        conn.commit()

    issued = [
        coupon
        for coupon_id in issued_ids
        if (coupon := get_coupon(coupon_id, db_file=db_file)) is not None
    ]
    return {
        "eligible": True,
        "duplicate": False,
        "issued": issued,
        "progress": {
            "customer_discord_id": customer_id,
            "rule_key": str(rule_key),
            "player_count": player_count,
            "pricing_type": str(program["pricing_type"]),
            "paid_units": remaining,
            "lifetime_paid_units": lifetime,
            "threshold_units": threshold,
            "reward_units": reward_units,
            "label": str(program["label"]),
            "unit_label": str(program["unit_label"]),
        },
    }


def get_customer_benefit_snapshot(
    customer_id: str | int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_loyalty_tables(db_file)
    path = _db_path(db_file)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        coupons = [
            _decorate_coupon(row)
            for row in conn.execute(
                """
                SELECT * FROM loyalty_coupons
                WHERE customer_discord_id=? AND status='available'
                ORDER BY id ASC
                """,
                (str(customer_id),),
            ).fetchall()
        ]
        progress_rows = conn.execute(
            """
            SELECT * FROM loyalty_progress
            WHERE customer_discord_id=? AND lifetime_paid_units > 0
            ORDER BY updated_at DESC
            """,
            (str(customer_id),),
        ).fetchall()

    progress: list[dict[str, Any]] = []
    for row in progress_rows:
        item = dict(row)
        program = get_loyalty_program(str(item.get("rule_key") or ""))
        if not program:
            continue
        item["label"] = str(program["label"])
        item["unit_label"] = str(program["unit_label"])
        item["reward_label"] = str(program["reward_label"])
        progress.append(item)

    return {
        "program_start_date": LOYALTY_PROGRAM_START_DATE,
        "available_count": len(coupons),
        "coupons": coupons,
        "progress": progress,
    }
