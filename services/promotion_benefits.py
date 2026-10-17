from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TAIPEI_TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEB_DB = ROOT / "web_dashboard.db"

ACTIVE = "active"
RESERVED = "reserved"
REDEEMED = "redeemed"
EXPIRED = "expired"
REVOKED = "revoked"

FUNDING_SHARED = "shared"
FUNDING_STORE = "store"

EFFECT_FIXED_CASH = "fixed_cash"
EFFECT_PERCENT = "percent"
EFFECT_FREE_HOURS = "free_hours"
EFFECT_FREE_GAMES = "free_games"
EFFECT_WAIVE_SPECIFY = "waive_specify"
EFFECT_FREE_ORDER = "free_order"

VALID_EFFECT_KINDS = {
    EFFECT_FIXED_CASH,
    EFFECT_PERCENT,
    EFFECT_FREE_HOURS,
    EFFECT_FREE_GAMES,
    EFFECT_WAIVE_SPECIFY,
    EFFECT_FREE_ORDER,
}
VALID_FUNDING = {FUNDING_SHARED, FUNDING_STORE}

# Keep generic issued-benefit IDs disjoint from loyalty coupon IDs while still
# remaining numeric, so the existing checkout select / formal-create payload can
# carry them without a front-end migration.
GENERIC_SELECTION_OFFSET = 1_000_000_000


def _db_path(web_db: str | Path | None = None) -> Path:
    return Path(web_db) if web_db is not None else DEFAULT_WEB_DB


def _now() -> datetime:
    return datetime.now(TAIPEI_TZ)


def _now_text() -> str:
    return _now().isoformat(timespec="seconds")


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_load(value: object, default):
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(str(value or ""))
    except Exception:
        return default
    return parsed if isinstance(parsed, type(default)) else default


def encode_selection_id(issued_id: int | str) -> int:
    return -(GENERIC_SELECTION_OFFSET + int(issued_id))


def decode_selection_id(value: int | str | None) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number > -GENERIC_SELECTION_OFFSET:
        return None
    issued_id = (-number) - GENERIC_SELECTION_OFFSET
    return issued_id if issued_id > 0 else None


def ensure_promotion_benefit_tables(web_db: str | Path | None = None) -> None:
    path = _db_path(web_db)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS promotion_benefit_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                effect_kind TEXT NOT NULL,
                effect_value REAL NOT NULL DEFAULT 0,
                funding TEXT NOT NULL DEFAULT 'store',
                min_order_amount INTEGER NOT NULL DEFAULT 0,
                scope_type TEXT NOT NULL DEFAULT 'all',
                scope_json TEXT NOT NULL DEFAULT '[]',
                excluded_rule_keys_json TEXT NOT NULL DEFAULT '[]',
                valid_days INTEGER,
                usage_limit INTEGER NOT NULL DEFAULT 1,
                consume_mode TEXT NOT NULL DEFAULT 'one_shot',
                seat_mode TEXT NOT NULL DEFAULT 'one_seat',
                include_specify_fee INTEGER NOT NULL DEFAULT 0,
                allow_vip_discount INTEGER NOT NULL DEFAULT 1,
                allow_points INTEGER NOT NULL DEFAULT 0,
                is_high_risk INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS promotion_issued_benefits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER,
                customer_discord_id TEXT NOT NULL,
                title TEXT NOT NULL,
                rules_snapshot_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                remaining_uses INTEGER NOT NULL DEFAULT 1,
                remaining_value REAL,
                issued_by TEXT,
                issue_note TEXT,
                issued_at TEXT NOT NULL,
                expires_at TEXT,
                reserved_order_id INTEGER,
                redeemed_order_id INTEGER,
                redeemed_at TEXT,
                revoked_at TEXT,
                revoke_reason TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_promotion_issued_customer_status
            ON promotion_issued_benefits(customer_discord_id, status, expires_at);

            CREATE UNIQUE INDEX IF NOT EXISTS uq_promotion_reserved_order
            ON promotion_issued_benefits(reserved_order_id)
            WHERE reserved_order_id IS NOT NULL AND status = 'reserved';

            CREATE TABLE IF NOT EXISTS promotion_benefit_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                template_id INTEGER,
                issued_benefit_id INTEGER,
                customer_discord_id TEXT,
                actor_discord_id TEXT,
                detail_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()


def _normalize_rules(data: dict[str, Any]) -> dict[str, Any]:
    effect_kind = str(data.get("effect_kind") or EFFECT_FIXED_CASH).strip()
    if effect_kind not in VALID_EFFECT_KINDS:
        raise ValueError("不支援的福利效果。")

    funding = str(data.get("funding") or FUNDING_STORE).strip()
    if funding not in VALID_FUNDING:
        raise ValueError("折扣負擔方式只能是 shared 或 store。")

    try:
        effect_value = max(0.0, float(data.get("effect_value") or 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("福利額度格式錯誤。") from exc

    if effect_kind in {EFFECT_FIXED_CASH, EFFECT_PERCENT, EFFECT_FREE_HOURS, EFFECT_FREE_GAMES} and effect_value <= 0:
        raise ValueError("這種福利必須設定大於 0 的額度。")
    if effect_kind == EFFECT_PERCENT and effect_value > 100:
        raise ValueError("百分比折扣不可超過 100%。")

    scope_type = str(data.get("scope_type") or "all").strip()
    if scope_type not in {"all", "category", "rule"}:
        raise ValueError("適用範圍格式錯誤。")

    scope_values = data.get("scope_values")
    if isinstance(scope_values, str):
        scope_values = [item.strip() for item in scope_values.split(",") if item.strip()]
    if not isinstance(scope_values, list):
        scope_values = []

    excluded = data.get("excluded_rule_keys")
    if isinstance(excluded, str):
        excluded = [item.strip() for item in excluded.split(",") if item.strip()]
    if not isinstance(excluded, list):
        excluded = []

    try:
        min_order_amount = max(0, int(float(data.get("min_order_amount") or 0)))
        usage_limit = max(1, int(data.get("usage_limit") or 1))
    except (TypeError, ValueError) as exc:
        raise ValueError("門檻或使用次數格式錯誤。") from exc

    valid_days_raw = data.get("valid_days")
    valid_days = None
    if valid_days_raw not in (None, ""):
        try:
            valid_days = max(1, int(valid_days_raw))
        except (TypeError, ValueError) as exc:
            raise ValueError("有效天數格式錯誤。") from exc

    consume_mode = str(data.get("consume_mode") or "one_shot").strip()
    if consume_mode not in {"one_shot", "balance"}:
        consume_mode = "one_shot"

    seat_mode = str(data.get("seat_mode") or "one_seat").strip()
    if seat_mode not in {"one_seat", "whole_order"}:
        seat_mode = "one_seat"

    return {
        "effect_kind": effect_kind,
        "effect_value": effect_value,
        "funding": funding,
        "min_order_amount": min_order_amount,
        "scope_type": scope_type,
        "scope_values": [str(item) for item in scope_values if str(item).strip()],
        "excluded_rule_keys": [str(item) for item in excluded if str(item).strip()],
        "valid_days": valid_days,
        "usage_limit": usage_limit,
        "consume_mode": consume_mode,
        "seat_mode": seat_mode,
        "include_specify_fee": bool(data.get("include_specify_fee")),
        "allow_vip_discount": bool(data.get("allow_vip_discount", True)),
        "allow_points": bool(data.get("allow_points", False)),
        "is_high_risk": bool(data.get("is_high_risk")),
    }


def create_template(
    *,
    name: str,
    rules: dict[str, Any],
    actor_discord_id: str | int | None = None,
    web_db: str | Path | None = None,
) -> int:
    ensure_promotion_benefit_tables(web_db)
    title = str(name or "").strip()
    if not title:
        raise ValueError("請輸入福利模板名稱。")
    normalized = _normalize_rules(rules)
    now = _now_text()
    path = _db_path(web_db)
    with sqlite3.connect(path, timeout=15) as conn:
        cur = conn.execute(
            """
            INSERT INTO promotion_benefit_templates (
                name, effect_kind, effect_value, funding, min_order_amount,
                scope_type, scope_json, excluded_rule_keys_json, valid_days,
                usage_limit, consume_mode, seat_mode, include_specify_fee,
                allow_vip_discount, allow_points, is_high_risk, is_active,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                title,
                normalized["effect_kind"],
                normalized["effect_value"],
                normalized["funding"],
                normalized["min_order_amount"],
                normalized["scope_type"],
                _json_dump(normalized["scope_values"]),
                _json_dump(normalized["excluded_rule_keys"]),
                normalized["valid_days"],
                normalized["usage_limit"],
                normalized["consume_mode"],
                normalized["seat_mode"],
                int(normalized["include_specify_fee"]),
                int(normalized["allow_vip_discount"]),
                int(normalized["allow_points"]),
                int(normalized["is_high_risk"]),
                str(actor_discord_id or ""),
                now,
                now,
            ),
        )
        template_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO promotion_benefit_audit (
                action, template_id, actor_discord_id, detail_json, created_at
            ) VALUES ('template_created', ?, ?, ?, ?)
            """,
            (template_id, str(actor_discord_id or ""), _json_dump(normalized), now),
        )
        conn.commit()
    return template_id


def list_templates(*, include_inactive: bool = False, web_db: str | Path | None = None) -> list[dict[str, Any]]:
    ensure_promotion_benefit_tables(web_db)
    where = "" if include_inactive else "WHERE is_active=1"
    with sqlite3.connect(_db_path(web_db), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT * FROM promotion_benefit_templates {where} ORDER BY is_active DESC, id DESC"
        ).fetchall()
    result = []
    for raw in rows:
        row = dict(raw)
        row["scope_values"] = _json_load(row.get("scope_json"), [])
        row["excluded_rule_keys"] = _json_load(row.get("excluded_rule_keys_json"), [])
        result.append(row)
    return result


def get_template(template_id: int | str, *, web_db: str | Path | None = None) -> dict[str, Any] | None:
    ensure_promotion_benefit_tables(web_db)
    try:
        wanted = int(template_id)
    except (TypeError, ValueError):
        return None
    with sqlite3.connect(_db_path(web_db), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM promotion_benefit_templates WHERE id=? LIMIT 1",
            (wanted,),
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["scope_values"] = _json_load(data.get("scope_json"), [])
    data["excluded_rule_keys"] = _json_load(data.get("excluded_rule_keys_json"), [])
    return data


def _template_snapshot(template: dict[str, Any]) -> dict[str, Any]:
    return {
        "template_id": int(template["id"]),
        "name": str(template.get("name") or "福利券"),
        "effect_kind": str(template.get("effect_kind") or EFFECT_FIXED_CASH),
        "effect_value": float(template.get("effect_value") or 0),
        "funding": str(template.get("funding") or FUNDING_STORE),
        "min_order_amount": int(template.get("min_order_amount") or 0),
        "scope_type": str(template.get("scope_type") or "all"),
        "scope_values": list(template.get("scope_values") or []),
        "excluded_rule_keys": list(template.get("excluded_rule_keys") or []),
        "usage_limit": int(template.get("usage_limit") or 1),
        "consume_mode": str(template.get("consume_mode") or "one_shot"),
        "seat_mode": str(template.get("seat_mode") or "one_seat"),
        "include_specify_fee": bool(template.get("include_specify_fee")),
        "allow_vip_discount": bool(template.get("allow_vip_discount", 1)),
        "allow_points": bool(template.get("allow_points")),
        "is_high_risk": bool(template.get("is_high_risk")),
        "snapshot_version": 1,
    }


def issue_benefit(
    *,
    template_id: int | str,
    customer_discord_id: str | int,
    actor_discord_id: str | int | None = None,
    note: str = "",
    expires_at: str | None = None,
    web_db: str | Path | None = None,
) -> int:
    template = get_template(template_id, web_db=web_db)
    if template is None or not bool(template.get("is_active")):
        raise ValueError("找不到可用的福利模板。")
    customer_id = str(customer_discord_id or "").strip()
    if not customer_id:
        raise ValueError("請選擇要發放的會員。")

    snapshot = _template_snapshot(template)
    now = _now()
    if expires_at:
        expiry = str(expires_at).strip()
    elif template.get("valid_days"):
        expiry = (now + timedelta(days=int(template["valid_days"]))).isoformat(timespec="seconds")
    else:
        expiry = None

    remaining_value = (
        float(snapshot["effect_value"])
        if snapshot["consume_mode"] == "balance"
        and snapshot["effect_kind"] == EFFECT_FIXED_CASH
        else None
    )
    now_text = now.isoformat(timespec="seconds")
    with sqlite3.connect(_db_path(web_db), timeout=15) as conn:
        cur = conn.execute(
            """
            INSERT INTO promotion_issued_benefits (
                template_id, customer_discord_id, title, rules_snapshot_json,
                status, remaining_uses, remaining_value, issued_by, issue_note,
                issued_at, expires_at
            ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
            """,
            (
                int(template["id"]),
                customer_id,
                str(template.get("name") or "福利券"),
                _json_dump(snapshot),
                int(snapshot["usage_limit"]),
                remaining_value,
                str(actor_discord_id or ""),
                str(note or "").strip(),
                now_text,
                expiry,
            ),
        )
        issued_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO promotion_benefit_audit (
                action, template_id, issued_benefit_id, customer_discord_id,
                actor_discord_id, detail_json, created_at
            ) VALUES ('issued', ?, ?, ?, ?, ?, ?)
            """,
            (
                int(template["id"]),
                issued_id,
                customer_id,
                str(actor_discord_id or ""),
                _json_dump({"note": str(note or ""), "expires_at": expiry}),
                now_text,
            ),
        )
        conn.commit()
    return issued_id


def _expire(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE promotion_issued_benefits
        SET status='expired'
        WHERE status='active'
          AND expires_at IS NOT NULL
          AND expires_at <= ?
        """,
        (_now_text(),),
    )


def list_issued_benefits(
    *,
    customer_discord_id: str | int | None = None,
    limit: int = 300,
    web_db: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_promotion_benefit_tables(web_db)
    with sqlite3.connect(_db_path(web_db), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        _expire(conn)
        params: list[Any] = []
        where = ""
        if customer_discord_id not in (None, ""):
            where = "WHERE customer_discord_id=?"
            params.append(str(customer_discord_id))
        params.append(max(1, min(1000, int(limit or 300))))
        rows = conn.execute(
            f"SELECT * FROM promotion_issued_benefits {where} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()
        conn.commit()
    result = []
    for raw in rows:
        row = dict(raw)
        row["rules"] = _json_load(row.get("rules_snapshot_json"), {})
        row["selection_id"] = encode_selection_id(row["id"])
        result.append(row)
    return result


def _scope_allowed(rules: dict[str, Any], *, rule_key: str, category: str) -> bool:
    key = str(rule_key or "").strip()
    if key in {str(item) for item in rules.get("excluded_rule_keys") or []}:
        return False
    scope_type = str(rules.get("scope_type") or "all")
    values = {str(item) for item in rules.get("scope_values") or []}
    if scope_type == "rule":
        return key in values
    if scope_type == "category":
        return str(category or "") in values
    return True


def _decorate_issued(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    rules = _json_load(item.get("rules_snapshot_json"), {})
    item["rules"] = rules
    item["source"] = "promotion"
    item["issued_benefit_id"] = int(item["id"])
    item["id"] = encode_selection_id(item["issued_benefit_id"])
    item["title"] = str(item.get("title") or rules.get("name") or "優惠福利")
    item["funding"] = str(rules.get("funding") or FUNDING_STORE)
    return item


def list_applicable_issued_benefits(
    customer_discord_id: str | int,
    *,
    rule_key: str,
    category: str,
    original_service_amount: int,
    vip_discount_active: bool = False,
    point_selected: bool = False,
    web_db: str | Path | None = None,
) -> list[dict[str, Any]]:
    customer_id = str(customer_discord_id or "").strip()
    if not customer_id:
        return []
    ensure_promotion_benefit_tables(web_db)
    with sqlite3.connect(_db_path(web_db), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        _expire(conn)
        rows = conn.execute(
            """
            SELECT * FROM promotion_issued_benefits
            WHERE customer_discord_id=? AND status='active'
              AND remaining_uses > 0
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY issued_at ASC, id ASC
            """,
            (customer_id, _now_text()),
        ).fetchall()
        conn.commit()

    result = []
    original = max(0, int(original_service_amount or 0))
    for raw in rows:
        row = dict(raw)
        rules = _json_load(row.get("rules_snapshot_json"), {})
        if not _scope_allowed(rules, rule_key=rule_key, category=category):
            continue
        if original < max(0, int(rules.get("min_order_amount") or 0)):
            continue
        if vip_discount_active and not bool(rules.get("allow_vip_discount", True)):
            continue
        if point_selected and not bool(rules.get("allow_points", False)):
            continue
        result.append(_decorate_issued(row))
    return result


def get_applicable_issued_benefit(
    selection_id: int | str | None,
    *,
    customer_discord_id: str | int,
    rule_key: str,
    category: str,
    original_service_amount: int,
    vip_discount_active: bool = False,
    point_selected: bool = False,
    web_db: str | Path | None = None,
) -> dict[str, Any] | None:
    issued_id = decode_selection_id(selection_id)
    if issued_id is None:
        return None
    for item in list_applicable_issued_benefits(
        customer_discord_id,
        rule_key=rule_key,
        category=category,
        original_service_amount=original_service_amount,
        vip_discount_active=vip_discount_active,
        point_selected=point_selected,
        web_db=web_db,
    ):
        if int(item.get("issued_benefit_id") or 0) == issued_id:
            return item
    return None


def calculate_discount_amount(
    benefit: dict[str, Any] | None,
    *,
    service_amount_after_percent: int,
    original_service_amount: int,
    specify_fee: int,
    quantity: int,
    staff_count: int,
) -> int:
    if not benefit:
        return 0
    rules = benefit.get("rules") if isinstance(benefit.get("rules"), dict) else {}
    kind = str(rules.get("effect_kind") or "")
    value = max(0.0, float(rules.get("effect_value") or 0))
    service_after = max(0, int(service_amount_after_percent or 0))
    specify = max(0, int(specify_fee or 0))
    eligible = service_after + (specify if bool(rules.get("include_specify_fee")) else 0)

    if kind == EFFECT_FIXED_CASH:
        remaining_value = benefit.get("remaining_value")
        cap = value if remaining_value in (None, "") else max(0.0, float(remaining_value or 0))
        return min(eligible, max(0, int(round(cap))))
    if kind == EFFECT_PERCENT:
        return min(eligible, max(0, int(round(eligible * value / 100))))
    if kind == EFFECT_FREE_ORDER:
        return eligible
    if kind == EFFECT_WAIVE_SPECIFY:
        return min(eligible, specify)
    if kind in {EFFECT_FREE_HOURS, EFFECT_FREE_GAMES}:
        qty = max(1, int(quantity or 1))
        seats = max(1, int(staff_count or 1))
        one_seat_unit = max(0.0, float(original_service_amount or 0) / qty / seats)
        seat_multiplier = seats if str(rules.get("seat_mode") or "one_seat") == "whole_order" else 1
        return min(eligible, max(0, int(round(one_seat_unit * value * seat_multiplier))))
    return 0


def benefit_note(benefit: dict[str, Any] | None) -> str:
    if not benefit:
        return ""
    rules = benefit.get("rules") if isinstance(benefit.get("rules"), dict) else {}
    funding = "店家吸收" if str(rules.get("funding") or FUNDING_STORE) == FUNDING_STORE else "共同分攤"
    return f"{benefit.get('title') or '優惠福利'}｜{funding}"


def reserve_issued_benefit_in_session(
    db,
    *,
    selection_id: int | str,
    customer_discord_id: str | int,
    order_id: int,
) -> None:
    issued_id = decode_selection_id(selection_id)
    if issued_id is None:
        raise ValueError("福利券識別碼錯誤。")
    now = _now_text()
    result = db.execute(
        __import__("sqlalchemy").text(
            """
            UPDATE promotion_issued_benefits
            SET status='reserved', reserved_order_id=?
            WHERE id=? AND customer_discord_id=? AND status='active'
              AND remaining_uses > 0
              AND (expires_at IS NULL OR expires_at > ?)
            """.replace("?", ":p", 1)
        )
    )
    # The SQLAlchemy Session path uses named parameters below; keep sqlite SQL
    # out of the transaction to avoid a second writer. Re-run with proper text.
    raise RuntimeError("unreachable")


def reserve_in_sqlalchemy_session(
    db,
    *,
    selection_id: int | str,
    customer_discord_id: str | int,
    order_id: int,
) -> None:
    from sqlalchemy import text

    issued_id = decode_selection_id(selection_id)
    if issued_id is None:
        raise ValueError("福利券識別碼錯誤。")
    now = _now_text()
    result = db.execute(
        text(
            """
            UPDATE promotion_issued_benefits
            SET status='reserved', reserved_order_id=:order_id
            WHERE id=:issued_id
              AND customer_discord_id=:customer_id
              AND status='active'
              AND remaining_uses > 0
              AND (expires_at IS NULL OR expires_at > :now)
            """
        ),
        {
            "order_id": int(order_id),
            "issued_id": int(issued_id),
            "customer_id": str(customer_discord_id),
            "now": now,
        },
    )
    if int(result.rowcount or 0) != 1:
        raise ValueError("這張優惠福利已被使用、保留、過期，或不屬於此會員。")


def release_for_order(order_id: int, *, web_db: str | Path | None = None) -> int:
    ensure_promotion_benefit_tables(web_db)
    now = _now_text()
    with sqlite3.connect(_db_path(web_db), timeout=15) as conn:
        result = conn.execute(
            """
            UPDATE promotion_issued_benefits
            SET status=CASE
                    WHEN expires_at IS NOT NULL AND expires_at <= ? THEN 'expired'
                    ELSE 'active'
                END,
                reserved_order_id=NULL
            WHERE reserved_order_id=? AND status='reserved'
            """,
            (now, int(order_id)),
        )
        conn.commit()
        return int(result.rowcount or 0)


def redeem_for_order(order_id: int, *, web_db: str | Path | None = None) -> int:
    ensure_promotion_benefit_tables(web_db)
    now = _now_text()
    with sqlite3.connect(_db_path(web_db), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM promotion_issued_benefits
            WHERE reserved_order_id=? AND status='reserved'
            """,
            (int(order_id),),
        ).fetchall()
        changed = 0
        for raw in rows:
            row = dict(raw)
            rules = _json_load(row.get("rules_snapshot_json"), {})
            remaining_uses = max(0, int(row.get("remaining_uses") or 0) - 1)
            status = REDEEMED if remaining_uses <= 0 else ACTIVE
            conn.execute(
                """
                UPDATE promotion_issued_benefits
                SET status=?, remaining_uses=?, reserved_order_id=NULL,
                    redeemed_order_id=?, redeemed_at=?
                WHERE id=? AND status='reserved'
                """,
                (status, remaining_uses, int(order_id), now, int(row["id"])),
            )
            changed += 1
        conn.commit()
    return changed


def revoke_issued_benefit(
    issued_id: int | str,
    *,
    actor_discord_id: str | int | None = None,
    reason: str = "",
    web_db: str | Path | None = None,
) -> None:
    ensure_promotion_benefit_tables(web_db)
    wanted = int(issued_id)
    now = _now_text()
    with sqlite3.connect(_db_path(web_db), timeout=15) as conn:
        row = conn.execute(
            "SELECT template_id, customer_discord_id FROM promotion_issued_benefits WHERE id=?",
            (wanted,),
        ).fetchone()
        if row is None:
            raise ValueError("找不到這張福利。")
        result = conn.execute(
            """
            UPDATE promotion_issued_benefits
            SET status='revoked', revoked_at=?, revoke_reason=?, reserved_order_id=NULL
            WHERE id=? AND status IN ('active','reserved')
            """,
            (now, str(reason or "").strip(), wanted),
        )
        if int(result.rowcount or 0) != 1:
            raise ValueError("這張福利目前不能撤回。")
        conn.execute(
            """
            INSERT INTO promotion_benefit_audit (
                action, template_id, issued_benefit_id, customer_discord_id,
                actor_discord_id, detail_json, created_at
            ) VALUES ('revoked', ?, ?, ?, ?, ?, ?)
            """,
            (
                int(row[0]) if row[0] is not None else None,
                wanted,
                str(row[1] or ""),
                str(actor_discord_id or ""),
                _json_dump({"reason": str(reason or "")}),
                now,
            ),
        )
        conn.commit()
