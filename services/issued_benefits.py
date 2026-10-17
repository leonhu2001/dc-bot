from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from services.order_discounts import FUNDING_SHARED, FUNDING_STORE


TAIPEI_TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEB_DB = ROOT / "web_dashboard.db"

STATUS_AVAILABLE = "available"
STATUS_RESERVED = "reserved"
STATUS_REDEEMED = "redeemed"
STATUS_REVOKED = "revoked"
STATUS_EXPIRED = "expired"

EFFECT_FIXED_CASH = "fixed_cash"
EFFECT_PERCENT = "percent"
EFFECT_SERVICE_HOURS = "service_hours"
EFFECT_SERVICE_GAMES = "service_games"
EFFECT_WAIVE_FEE = "waive_fee"
EFFECT_FULL_ORDER = "full_order"

SUPPORTED_EFFECT_TYPES = {
    EFFECT_FIXED_CASH,
    EFFECT_PERCENT,
    EFFECT_SERVICE_HOURS,
    EFFECT_SERVICE_GAMES,
    EFFECT_WAIVE_FEE,
    EFFECT_FULL_ORDER,
}
SUPPORTED_FUNDING = {FUNDING_SHARED, FUNDING_STORE}


@dataclass(frozen=True)
class BenefitResolution:
    benefit_id: int
    title: str
    effect_type: str
    funding: str
    discount_amount: int
    payout_base_discount_amount: int
    store_absorbed_amount: int
    service_hours: float
    service_games: int
    waived_fee_amount: int
    consumes_on_use: bool
    rules: dict[str, Any]


def _path(web_db: str | Path | None = None) -> Path:
    return Path(web_db) if web_db is not None else DEFAULT_WEB_DB


def _now() -> datetime:
    return datetime.now(TAIPEI_TZ)


def _normalize_dt(value: datetime | str | None) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI_TZ)
    return dt.astimezone(TAIPEI_TZ)


def _dt_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    dt = _normalize_dt(value)
    return dt.isoformat(timespec="seconds") if dt is not None else None


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def normalize_rules(rules: dict[str, Any]) -> dict[str, Any]:
    data = dict(rules or {})
    effect_type = str(data.get("effect_type") or EFFECT_FIXED_CASH).strip()
    if effect_type not in SUPPORTED_EFFECT_TYPES:
        raise ValueError("不支援的福利類型。")

    funding = str(data.get("funding") or FUNDING_STORE).strip()
    if funding not in SUPPORTED_FUNDING:
        raise ValueError("折扣負擔方式只能是 shared 或 store。")

    def _int(name: str, default: int = 0) -> int:
        try:
            return max(0, int(float(data.get(name, default) or 0)))
        except (TypeError, ValueError):
            return max(0, int(default))

    def _float(name: str, default: float = 0.0) -> float:
        try:
            return max(0.0, float(data.get(name, default) or 0))
        except (TypeError, ValueError):
            return max(0.0, float(default))

    normalized: dict[str, Any] = {
        "effect_type": effect_type,
        "funding": funding,
        "amount": _int("amount"),
        "percent_off": min(100.0, _float("percent_off")),
        "service_hours": _float("service_hours"),
        "service_games": _int("service_games"),
        "minimum_order_amount": _int("minimum_order_amount"),
        "maximum_discount_amount": _int("maximum_discount_amount"),
        "max_uses": max(1, _int("max_uses", 1)),
        "unused_balance_policy": str(data.get("unused_balance_policy") or "forfeit").strip(),
        "include_specify_fee": bool(data.get("include_specify_fee", False)),
        "exclusive_coupon": bool(data.get("exclusive_coupon", True)),
        "allow_vip_percent": bool(data.get("allow_vip_percent", True)),
        "manager_only": bool(data.get("manager_only", False)),
    }

    for key in ("rule_keys", "categories", "excluded_rule_keys", "excluded_categories"):
        raw = data.get(key) or []
        if isinstance(raw, str):
            raw = [part.strip() for part in raw.split(",") if part.strip()]
        if not isinstance(raw, list):
            raw = []
        normalized[key] = list(dict.fromkeys(str(item).strip() for item in raw if str(item).strip()))

    fee_key = str(data.get("fee_key") or "specify").strip()
    normalized["fee_key"] = fee_key or "specify"

    if effect_type == EFFECT_FIXED_CASH and normalized["amount"] <= 0:
        raise ValueError("固定折抵券必須設定折抵金額。")
    if effect_type == EFFECT_PERCENT and normalized["percent_off"] <= 0:
        raise ValueError("百分比券必須設定折扣百分比。")
    if effect_type == EFFECT_SERVICE_HOURS and normalized["service_hours"] <= 0:
        raise ValueError("服務加時券必須設定時數。")
    if effect_type == EFFECT_SERVICE_GAMES and normalized["service_games"] <= 0:
        raise ValueError("服務加局券必須設定局數。")

    return normalized


def ensure_issued_benefit_tables(web_db: str | Path | None = None) -> None:
    path = _path(web_db)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS benefit_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                rules_json TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS issued_benefits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER,
                customer_id TEXT NOT NULL,
                title TEXT NOT NULL,
                rules_snapshot_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'available',
                remaining_uses INTEGER NOT NULL DEFAULT 1,
                issued_by TEXT,
                issued_reason TEXT,
                issued_at TEXT NOT NULL,
                expires_at TEXT,
                reserved_order_key TEXT,
                reserved_at TEXT,
                redeemed_order_key TEXT,
                redeemed_at TEXT,
                revoked_by TEXT,
                revoked_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS ix_issued_benefits_customer_status
            ON issued_benefits(customer_id, status, expires_at);

            CREATE INDEX IF NOT EXISTS ix_issued_benefits_template
            ON issued_benefits(template_id, issued_at);

            CREATE TABLE IF NOT EXISTS benefit_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                actor_id TEXT,
                template_id INTEGER,
                benefit_id INTEGER,
                customer_id TEXT,
                detail_json TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()


def _audit(
    conn: sqlite3.Connection,
    *,
    action: str,
    actor_id: str | None = None,
    template_id: int | None = None,
    benefit_id: int | None = None,
    customer_id: str | None = None,
    detail: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> None:
    current = _normalize_dt(now) or _now()
    conn.execute(
        """
        INSERT INTO benefit_audit_log (
            action, actor_id, template_id, benefit_id, customer_id,
            detail_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(action),
            str(actor_id or "") or None,
            template_id,
            benefit_id,
            str(customer_id or "") or None,
            json.dumps(detail or {}, ensure_ascii=False, sort_keys=True),
            current.isoformat(timespec="seconds"),
        ),
    )


def ensure_default_benefit_templates(web_db: str | Path | None = None) -> None:
    ensure_issued_benefit_tables(web_db)
    path = _path(web_db)
    current = _now().isoformat(timespec="seconds")
    with sqlite3.connect(path, timeout=15) as conn:
        row = conn.execute(
            "SELECT id FROM benefit_templates WHERE name=? LIMIT 1",
            ("主播宣傳單 1500T",),
        ).fetchone()
        if row is None:
            rules = normalize_rules(
                {
                    "effect_type": EFFECT_FIXED_CASH,
                    "amount": 1500,
                    "funding": FUNDING_STORE,
                    "max_uses": 1,
                    "unused_balance_policy": "forfeit",
                    "exclusive_coupon": True,
                    "allow_vip_percent": True,
                    "manager_only": False,
                }
            )
            cur = conn.execute(
                """
                INSERT INTO benefit_templates (
                    name, description, rules_json, is_active,
                    created_by, created_at, updated_at
                ) VALUES (?, ?, ?, 1, 'system', ?, ?)
                """,
                (
                    "主播宣傳單 1500T",
                    "單次最高折抵 1500T；店家全額吸收，打手與客服結算基數不受影響。",
                    json.dumps(rules, ensure_ascii=False, sort_keys=True),
                    current,
                    current,
                ),
            )
            template_id = int(cur.lastrowid)
            _audit(
                conn,
                action="seed_template",
                actor_id="system",
                template_id=template_id,
                detail={"name": "主播宣傳單 1500T"},
            )
        conn.commit()


def create_benefit_template(
    *,
    name: str,
    rules: dict[str, Any],
    description: str = "",
    actor_id: str | None = None,
    web_db: str | Path | None = None,
) -> int:
    name = str(name or "").strip()
    if not name:
        raise ValueError("請填寫福利模板名稱。")
    normalized = normalize_rules(rules)
    ensure_issued_benefit_tables(web_db)
    current = _now().isoformat(timespec="seconds")
    path = _path(web_db)
    with sqlite3.connect(path, timeout=15) as conn:
        cur = conn.execute(
            """
            INSERT INTO benefit_templates (
                name, description, rules_json, is_active,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, 1, ?, ?, ?)
            """,
            (
                name,
                str(description or "").strip(),
                json.dumps(normalized, ensure_ascii=False, sort_keys=True),
                str(actor_id or "") or None,
                current,
                current,
            ),
        )
        template_id = int(cur.lastrowid)
        _audit(
            conn,
            action="create_template",
            actor_id=actor_id,
            template_id=template_id,
            detail={"name": name, "rules": normalized},
        )
        conn.commit()
        return template_id


def list_benefit_templates(
    *,
    include_inactive: bool = False,
    web_db: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_default_benefit_templates(web_db)
    path = _path(web_db)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        where = "" if include_inactive else "WHERE is_active=1"
        rows = conn.execute(
            f"SELECT * FROM benefit_templates {where} ORDER BY is_active DESC, id DESC"
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["rules"] = _json(item.pop("rules_json", "{}"))
        result.append(item)
    return result


def get_benefit_template(
    template_id: int,
    *,
    web_db: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_issued_benefit_tables(web_db)
    path = _path(web_db)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM benefit_templates WHERE id=? LIMIT 1",
            (int(template_id),),
        ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["rules"] = _json(item.pop("rules_json", "{}"))
    return item


def set_benefit_template_active(
    template_id: int,
    *,
    is_active: bool,
    actor_id: str | None = None,
    web_db: str | Path | None = None,
) -> None:
    ensure_issued_benefit_tables(web_db)
    path = _path(web_db)
    current = _now().isoformat(timespec="seconds")
    with sqlite3.connect(path, timeout=15) as conn:
        cur = conn.execute(
            "UPDATE benefit_templates SET is_active=?, updated_at=? WHERE id=?",
            (1 if is_active else 0, current, int(template_id)),
        )
        if int(cur.rowcount or 0) <= 0:
            raise ValueError("找不到福利模板。")
        _audit(
            conn,
            action="activate_template" if is_active else "deactivate_template",
            actor_id=actor_id,
            template_id=int(template_id),
        )
        conn.commit()


def issue_benefit(
    *,
    customer_id: str,
    actor_id: str | None,
    template_id: int | None = None,
    title: str | None = None,
    rules: dict[str, Any] | None = None,
    reason: str = "",
    expires_at: datetime | str | None = None,
    expires_in_days: int | None = None,
    web_db: str | Path | None = None,
) -> int:
    customer_id = str(customer_id or "").strip()
    if not customer_id:
        raise ValueError("請指定要發放福利的會員。")

    template = None
    if template_id is not None:
        template = get_benefit_template(int(template_id), web_db=web_db)
        if template is None or not bool(template.get("is_active")):
            raise ValueError("這個福利模板不存在或已停用。")
        snapshot = normalize_rules(template["rules"])
        issue_title = str(title or template.get("name") or "會員福利").strip()
    else:
        snapshot = normalize_rules(rules or {})
        issue_title = str(title or "自訂福利").strip()

    current = _now()
    expiry = _normalize_dt(expires_at)
    if expiry is None and expires_in_days not in (None, 0):
        expiry = current + timedelta(days=max(1, int(expires_in_days or 0)))
    if expiry is not None and expiry <= current:
        raise ValueError("福利到期時間必須晚於現在。")

    max_uses = max(1, int(snapshot.get("max_uses") or 1))
    ensure_issued_benefit_tables(web_db)
    path = _path(web_db)
    now_text = current.isoformat(timespec="seconds")
    with sqlite3.connect(path, timeout=15) as conn:
        cur = conn.execute(
            """
            INSERT INTO issued_benefits (
                template_id, customer_id, title, rules_snapshot_json,
                status, remaining_uses, issued_by, issued_reason,
                issued_at, expires_at, updated_at
            ) VALUES (?, ?, ?, ?, 'available', ?, ?, ?, ?, ?, ?)
            """,
            (
                int(template_id) if template_id is not None else None,
                customer_id,
                issue_title,
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                max_uses,
                str(actor_id or "") or None,
                str(reason or "").strip(),
                now_text,
                _dt_text(expiry),
                now_text,
            ),
        )
        benefit_id = int(cur.lastrowid)
        _audit(
            conn,
            action="issue_benefit",
            actor_id=actor_id,
            template_id=int(template_id) if template_id is not None else None,
            benefit_id=benefit_id,
            customer_id=customer_id,
            detail={"title": issue_title, "rules": snapshot, "expires_at": _dt_text(expiry)},
        )
        conn.commit()
        return benefit_id


def _refresh_expired(conn: sqlite3.Connection, now: datetime) -> None:
    now_text = now.isoformat(timespec="seconds")
    conn.execute(
        """
        UPDATE issued_benefits
        SET status='expired', updated_at=?
        WHERE status='available'
          AND expires_at IS NOT NULL
          AND expires_at <= ?
        """,
        (now_text, now_text),
    )


def list_issued_benefits(
    *,
    customer_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
    web_db: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_issued_benefit_tables(web_db)
    path = _path(web_db)
    now = _now()
    conditions: list[str] = []
    params: list[Any] = []
    if customer_id:
        conditions.append("customer_id=?")
        params.append(str(customer_id))
    if status:
        conditions.append("status=?")
        params.append(str(status))
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(max(1, min(1000, int(limit or 200))))
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        _refresh_expired(conn, now)
        rows = conn.execute(
            f"SELECT * FROM issued_benefits{where} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()
        conn.commit()
    result = []
    for row in rows:
        item = dict(row)
        item["rules"] = _json(item.pop("rules_snapshot_json", "{}"))
        result.append(item)
    return result


def get_issued_benefit(
    benefit_id: int,
    *,
    web_db: str | Path | None = None,
) -> dict[str, Any] | None:
    rows = list_issued_benefits(web_db=web_db, limit=1000)
    target = int(benefit_id)
    for row in rows:
        if int(row.get("id") or 0) == target:
            return row
    return None


def list_available_benefits_for_customer(
    customer_id: str,
    *,
    web_db: str | Path | None = None,
) -> list[dict[str, Any]]:
    return list_issued_benefits(
        customer_id=str(customer_id),
        status=STATUS_AVAILABLE,
        web_db=web_db,
        limit=500,
    )


def _validate_scope(rules: dict[str, Any], order: dict[str, Any]) -> None:
    rule_key = str(order.get("rule_key") or "").strip()
    category = str(order.get("category") or "").strip()
    allowed_rules = set(rules.get("rule_keys") or [])
    allowed_categories = set(rules.get("categories") or [])
    excluded_rules = set(rules.get("excluded_rule_keys") or [])
    excluded_categories = set(rules.get("excluded_categories") or [])

    if allowed_rules and rule_key not in allowed_rules:
        raise ValueError("這張福利券不適用此商品。")
    if allowed_categories and category not in allowed_categories:
        raise ValueError("這張福利券不適用此商品分類。")
    if rule_key and rule_key in excluded_rules:
        raise ValueError("這張福利券不適用此商品。")
    if category and category in excluded_categories:
        raise ValueError("這張福利券不適用此商品分類。")


def resolve_issued_benefit(
    *,
    benefit_id: int,
    customer_id: str,
    order: dict[str, Any],
    web_db: str | Path | None = None,
) -> BenefitResolution:
    benefit = get_issued_benefit(int(benefit_id), web_db=web_db)
    if benefit is None:
        raise ValueError("找不到這張福利券。")
    if str(benefit.get("customer_id") or "") != str(customer_id or ""):
        raise ValueError("這張福利券不屬於目前會員。")
    if str(benefit.get("status") or "") != STATUS_AVAILABLE:
        raise ValueError("這張福利券目前不可使用。")

    rules = normalize_rules(benefit.get("rules") or {})
    _validate_scope(rules, order)

    original_service_amount = max(0, int(order.get("original_service_amount") or 0))
    if original_service_amount < int(rules.get("minimum_order_amount") or 0):
        raise ValueError(
            f"這張福利券需單筆原始服務金額滿 {int(rules['minimum_order_amount']):,}T 才能使用。"
        )

    effect_type = str(rules["effect_type"])
    funding = str(rules["funding"])
    include_specify = bool(rules.get("include_specify_fee"))
    specify_fee = max(0, int(order.get("specify_fee") or 0))
    discountable = original_service_amount + (specify_fee if include_specify else 0)
    maximum = max(0, int(rules.get("maximum_discount_amount") or 0))

    discount = 0
    service_hours = 0.0
    service_games = 0
    waived_fee = 0

    if effect_type == EFFECT_FIXED_CASH:
        discount = min(discountable, int(rules.get("amount") or 0))
    elif effect_type == EFFECT_PERCENT:
        discount = int(round(discountable * float(rules.get("percent_off") or 0) / 100))
    elif effect_type == EFFECT_FULL_ORDER:
        discount = discountable
    elif effect_type == EFFECT_WAIVE_FEE:
        waived_fee = specify_fee if str(rules.get("fee_key") or "specify") == "specify" else 0
        discount = waived_fee
    elif effect_type == EFFECT_SERVICE_HOURS:
        service_hours = float(rules.get("service_hours") or 0)
    elif effect_type == EFFECT_SERVICE_GAMES:
        service_games = int(rules.get("service_games") or 0)

    if maximum > 0:
        discount = min(discount, maximum)
    discount = max(0, int(discount))

    return BenefitResolution(
        benefit_id=int(benefit["id"]),
        title=str(benefit.get("title") or "會員福利"),
        effect_type=effect_type,
        funding=funding,
        discount_amount=discount,
        payout_base_discount_amount=discount if funding == FUNDING_SHARED else 0,
        store_absorbed_amount=discount if funding == FUNDING_STORE else 0,
        service_hours=service_hours,
        service_games=service_games,
        waived_fee_amount=waived_fee,
        consumes_on_use=True,
        rules=rules,
    )


def reserve_issued_benefit(
    benefit_id: int,
    *,
    customer_id: str,
    order_key: str,
    actor_id: str | None = None,
    web_db: str | Path | None = None,
) -> None:
    ensure_issued_benefit_tables(web_db)
    path = _path(web_db)
    current = _now().isoformat(timespec="seconds")
    with sqlite3.connect(path, timeout=15) as conn:
        cur = conn.execute(
            """
            UPDATE issued_benefits
            SET status='reserved', reserved_order_key=?, reserved_at=?, updated_at=?
            WHERE id=? AND customer_id=? AND status='available'
            """,
            (str(order_key), current, current, int(benefit_id), str(customer_id)),
        )
        if int(cur.rowcount or 0) != 1:
            raise ValueError("這張福利券已被使用、保留或失效。")
        _audit(
            conn,
            action="reserve_benefit",
            actor_id=actor_id,
            benefit_id=int(benefit_id),
            customer_id=str(customer_id),
            detail={"order_key": str(order_key)},
        )
        conn.commit()


def release_issued_benefit(
    benefit_id: int,
    *,
    order_key: str | None = None,
    actor_id: str | None = None,
    web_db: str | Path | None = None,
) -> None:
    ensure_issued_benefit_tables(web_db)
    path = _path(web_db)
    current = _now().isoformat(timespec="seconds")
    with sqlite3.connect(path, timeout=15) as conn:
        if order_key:
            cur = conn.execute(
                """
                UPDATE issued_benefits
                SET status='available', reserved_order_key=NULL, reserved_at=NULL, updated_at=?
                WHERE id=? AND status='reserved' AND reserved_order_key=?
                """,
                (current, int(benefit_id), str(order_key)),
            )
        else:
            cur = conn.execute(
                """
                UPDATE issued_benefits
                SET status='available', reserved_order_key=NULL, reserved_at=NULL, updated_at=?
                WHERE id=? AND status='reserved'
                """,
                (current, int(benefit_id)),
            )
        if int(cur.rowcount or 0):
            _audit(
                conn,
                action="release_benefit",
                actor_id=actor_id,
                benefit_id=int(benefit_id),
                detail={"order_key": str(order_key or "")},
            )
        conn.commit()


def redeem_issued_benefit(
    benefit_id: int,
    *,
    customer_id: str,
    order_key: str,
    actor_id: str | None = None,
    web_db: str | Path | None = None,
) -> None:
    ensure_issued_benefit_tables(web_db)
    path = _path(web_db)
    current = _now().isoformat(timespec="seconds")
    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, remaining_uses, reserved_order_key FROM issued_benefits WHERE id=? AND customer_id=?",
            (int(benefit_id), str(customer_id)),
        ).fetchone()
        if row is None:
            raise ValueError("找不到這張福利券。")
        status = str(row["status"] or "")
        if status not in {STATUS_AVAILABLE, STATUS_RESERVED}:
            raise ValueError("這張福利券已使用或失效。")
        if status == STATUS_RESERVED and str(row["reserved_order_key"] or "") != str(order_key):
            raise ValueError("這張福利券目前保留在另一張訂單。")

        remaining = max(1, int(row["remaining_uses"] or 1)) - 1
        if remaining > 0:
            next_status = STATUS_AVAILABLE
            redeemed_order_key = None
            redeemed_at = None
        else:
            next_status = STATUS_REDEEMED
            redeemed_order_key = str(order_key)
            redeemed_at = current

        conn.execute(
            """
            UPDATE issued_benefits
            SET status=?, remaining_uses=?, reserved_order_key=NULL, reserved_at=NULL,
                redeemed_order_key=?, redeemed_at=?, updated_at=?
            WHERE id=?
            """,
            (
                next_status,
                remaining,
                redeemed_order_key,
                redeemed_at,
                current,
                int(benefit_id),
            ),
        )
        _audit(
            conn,
            action="redeem_benefit",
            actor_id=actor_id,
            benefit_id=int(benefit_id),
            customer_id=str(customer_id),
            detail={"order_key": str(order_key), "remaining_uses": remaining},
        )
        conn.commit()


def revoke_issued_benefit(
    benefit_id: int,
    *,
    actor_id: str | None = None,
    reason: str = "",
    web_db: str | Path | None = None,
) -> None:
    ensure_issued_benefit_tables(web_db)
    path = _path(web_db)
    current = _now().isoformat(timespec="seconds")
    with sqlite3.connect(path, timeout=15) as conn:
        row = conn.execute(
            "SELECT customer_id, status FROM issued_benefits WHERE id=?",
            (int(benefit_id),),
        ).fetchone()
        if row is None:
            raise ValueError("找不到這張福利券。")
        if str(row[1] or "") == STATUS_REDEEMED:
            raise ValueError("已核銷的福利券不能直接撤回。")
        conn.execute(
            """
            UPDATE issued_benefits
            SET status='revoked', revoked_by=?, revoked_at=?, updated_at=?
            WHERE id=?
            """,
            (str(actor_id or "") or None, current, current, int(benefit_id)),
        )
        _audit(
            conn,
            action="revoke_benefit",
            actor_id=actor_id,
            benefit_id=int(benefit_id),
            customer_id=str(row[0] or ""),
            detail={"reason": str(reason or "").strip()},
        )
        conn.commit()


def describe_rules(rules: dict[str, Any]) -> str:
    rules = normalize_rules(rules)
    effect = str(rules["effect_type"])
    if effect == EFFECT_FIXED_CASH:
        value = f"折抵 {int(rules['amount']):,}T"
    elif effect == EFFECT_PERCENT:
        value = f"折 {float(rules['percent_off']):g}%"
    elif effect == EFFECT_FULL_ORDER:
        value = "整單免單"
    elif effect == EFFECT_SERVICE_HOURS:
        value = f"免費服務 {float(rules['service_hours']):g}H"
    elif effect == EFFECT_SERVICE_GAMES:
        value = f"免費服務 {int(rules['service_games'])} 局"
    else:
        value = "免指定費"

    minimum = int(rules.get("minimum_order_amount") or 0)
    funding = "店家吸收" if rules["funding"] == FUNDING_STORE else "共同分攤"
    parts = [value, funding, f"可用 {int(rules['max_uses'])} 次"]
    if minimum > 0:
        parts.append(f"滿 {minimum:,}T 可用")
    return "｜".join(parts)
