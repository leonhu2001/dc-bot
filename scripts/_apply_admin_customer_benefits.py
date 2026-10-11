from pathlib import Path


SERVICE_PATH = Path("web/app/services/admin_customer_loyalty.py")
ROUTER_PATH = Path("web/app/routers/admin_centers.py")
CENTER_TEMPLATE_PATH = Path("web/app/templates/admin_center.html")
DETAIL_TEMPLATE_PATH = Path("web/app/templates/admin_customer_benefits.html")
TEST_PATH = Path("tests/test_admin_customer_loyalty.py")


SERVICE_CONTENT = '''from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable


KNOWN_STATUSES = ("active", "reserved", "redeemed", "expired")
STATUS_LABELS = {
    "active": "可使用",
    "reserved": "使用中",
    "redeemed": "已使用",
    "expired": "已過期",
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
'''


DETAIL_TEMPLATE_CONTENT = '''{% extends "layout.html" %}

{% block page_title %}客戶福利明細{% endblock %}

{% block content %}
<style>
.benefit-page{display:grid;gap:14px}.benefit-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;flex-wrap:wrap}.benefit-head h2{margin:0 0 5px}.benefit-stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}.benefit-stat{padding:14px;border:1px solid var(--r5-line,rgba(255,255,255,.08));border-radius:12px;background:var(--r5-panel,#11110f)}.benefit-stat span{display:block;color:var(--r5-muted,#969289);font-size:11px;font-weight:800}.benefit-stat strong{display:block;margin-top:6px;color:var(--r5-gold-soft,#f2d68d);font-size:25px}.benefit-group{display:grid;gap:10px;padding:14px;border:1px solid rgba(255,255,255,.08);border-radius:12px;background:rgba(255,255,255,.018)}.benefit-group-head{display:flex;justify-content:space-between;gap:10px;align-items:center}.benefit-group-head h3{margin:0;font-size:17px}.benefit-progress{padding:11px;border:1px solid rgba(223,183,92,.18);border-radius:10px;background:rgba(223,183,92,.035)}.benefit-progress-top{display:flex;justify-content:space-between;gap:10px}.benefit-bar{height:7px;margin-top:9px;border-radius:999px;background:rgba(255,255,255,.07);overflow:hidden}.benefit-bar i{display:block;height:100%;background:var(--r5-gold,#dfb75c)}.coupon-list{display:grid;gap:8px}.coupon-row{display:grid;grid-template-columns:minmax(200px,1.3fr) 90px 150px 150px minmax(150px,.8fr);gap:10px;padding:10px 11px;border:1px solid rgba(255,255,255,.07);border-radius:10px;align-items:center}.coupon-row small,.benefit-progress small{color:var(--r5-muted,#969289)}.coupon-status{font-size:11px;font-weight:900}.coupon-status.active{color:#8fd7a7}.coupon-status.reserved{color:#f2d68d}.coupon-status.redeemed{color:#9bb9e8}.coupon-status.expired{color:#969289}.empty-benefit{padding:24px;text-align:center;color:var(--r5-muted,#969289);border:1px dashed rgba(255,255,255,.1);border-radius:12px}@media(max-width:980px){.benefit-stats{grid-template-columns:repeat(2,1fr)}.coupon-row{grid-template-columns:1fr 1fr}}@media(max-width:600px){.benefit-stats{grid-template-columns:1fr 1fr}.coupon-row{grid-template-columns:1fr}}
</style>

<div class="benefit-page">
    <div class="panel compact-panel benefit-head">
        <div>
            <span class="eyebrow">CUSTOMER BENEFITS</span>
            <h2>{{ customer.display_name }}</h2>
            <p class="muted-text">{{ customer.id }}｜不同遊戲的累積與福利彼此獨立。</p>
        </div>
        <div class="center-actions">
            <a class="button secondary" href="/admin/customer-center">← 返回客戶中心</a>
            <a class="button secondary" href="/admin/search/customer/{{ customer.id }}?return_to=/admin/customer-center/{{ customer.id }}/benefits">客戶資料</a>
        </div>
    </div>

    <div class="benefit-stats">
        <div class="benefit-stat"><span>累積進度</span><strong>{{ loyalty.progress|length }}</strong></div>
        <div class="benefit-stat"><span>可使用</span><strong>{{ loyalty.coupon_counts.active or 0 }}</strong></div>
        <div class="benefit-stat"><span>使用中</span><strong>{{ loyalty.coupon_counts.reserved or 0 }}</strong></div>
        <div class="benefit-stat"><span>已使用</span><strong>{{ loyalty.coupon_counts.redeemed or 0 }}</strong></div>
        <div class="benefit-stat"><span>已過期</span><strong>{{ loyalty.coupon_counts.expired or 0 }}</strong></div>
    </div>

    {% for group in loyalty.groups %}
    <section class="benefit-group">
        <div class="benefit-group-head">
            <h3>{{ group.title }}</h3>
            <small class="muted-text">{{ group.scope_key }}</small>
        </div>

        {% for progress in group.progress %}
        <div class="benefit-progress">
            <div class="benefit-progress-top">
                <strong>目前 {{ progress.progress_text }}</strong>
                <small>達標後：{{ progress.benefit_text }}</small>
            </div>
            <div class="benefit-bar"><i style="width:{{ progress.percent }}%"></i></div>
            <small>最近更新：{{ progress.updated_at_text }}</small>
        </div>
        {% endfor %}

        {% if group.coupons %}
        <div class="coupon-list">
            {% for coupon in group.coupons %}
            <div class="coupon-row">
                <div><strong>{{ coupon.benefit_text }}</strong><small>券 #{{ coupon.id }}</small></div>
                <div><span class="coupon-status {{ coupon.status }}">{{ coupon.status_label }}</span></div>
                <div><small>取得時間</small><br>{{ coupon.issued_at_text }}</div>
                <div><small>到期時間</small><br>{{ coupon.expires_at_text }}</div>
                <div>
                    {% if coupon.reserved_order_id %}<small>保留訂單 #{{ coupon.reserved_order_id }}</small>{% endif %}
                    {% if coupon.redeemed_order_id %}<small>使用訂單 #{{ coupon.redeemed_order_id }}</small>{% endif %}
                    {% if coupon.redeemed_at %}<small>使用時間 {{ coupon.redeemed_at_text }}</small>{% endif %}
                </div>
            </div>
            {% endfor %}
        </div>
        {% elif not group.progress %}
        <div class="empty-benefit">這個遊戲目前沒有福利資料。</div>
        {% endif %}
    </section>
    {% else %}
    <div class="empty-benefit">這位客戶目前沒有跨單累積進度或福利券。</div>
    {% endfor %}
</div>
{% endblock %}
'''


TEST_CONTENT = '''import sqlite3
from pathlib import Path

from web.app.services.admin_customer_loyalty import (
    enrich_customer_rows,
    load_customer_loyalty_detail,
)


def _db(tmp_path: Path) -> Path:
    path = tmp_path / "loyalty-admin.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE customer_loyalty_progress (
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
        """)
        conn.execute("""
            CREATE TABLE customer_benefit_coupons (
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
        """)
        conn.execute("""
            INSERT INTO customer_loyalty_progress VALUES
            ('123', 'valorant|valorant_entertain_ng', 'valorant_entertain_ng', 'VALORANT｜娛樂陪｜雙陪', 'hourly', 2, 6, 10, 'extra_hours', 0.5, '2026-10-11T10:00:00+08:00'),
            ('123', 'lol|lol_entertain_ng', 'lol_entertain_ng', 'LOL｜娛樂陪', 'hourly', 1, 4, 10, 'extra_hours', 0.5, '2026-10-11T11:00:00+08:00')
        """)
        conn.execute("""
            INSERT INTO customer_benefit_coupons (
                customer_discord_id, scope_key, rule_key, rule_label, pricing_type,
                player_count, benefit_kind, benefit_units, status, source,
                issued_at, expires_at, reserved_order_id, redeemed_order_id, redeemed_at
            ) VALUES
            ('123', 'valorant|valorant_entertain_ng', 'valorant_entertain_ng', 'VALORANT｜娛樂陪｜雙陪', 'hourly', 2, 'extra_hours', 0.5, 'active', 'loyalty', '2026-10-11T10:00:00+08:00', '2027-01-09T10:00:00+08:00', NULL, NULL, NULL),
            ('123', 'lol|lol_entertain_ng', 'lol_entertain_ng', 'LOL｜娛樂陪', 'hourly', 1, 'extra_hours', 0.5, 'redeemed', 'loyalty', '2026-10-11T09:00:00+08:00', '2027-01-09T09:00:00+08:00', NULL, 88, '2026-10-11T12:00:00+08:00')
        """)
    return path


def test_admin_loyalty_detail_shows_real_coupon_status_and_keeps_games_separate(tmp_path: Path):
    data = load_customer_loyalty_detail(_db(tmp_path), "123")

    assert len(data["groups"]) == 2
    assert {group["scope_key"] for group in data["groups"]} == {
        "valorant|valorant_entertain_ng",
        "lol|lol_entertain_ng",
    }
    assert data["coupon_counts"]["active"] == 1
    assert data["coupon_counts"]["redeemed"] == 1
    assert data["active_coupons"][0]["status_label"] == "可使用"
    assert "折抵 30 分鐘額度" in data["active_coupons"][0]["title"]
    assert "雙陪" not in data["active_coupons"][0]["title"]
    assert all("位" not in row["title"] for row in data["progress"])


def test_customer_list_enrichment_contains_coupon_preview_and_progress(tmp_path: Path):
    rows = enrich_customer_rows(
        _db(tmp_path),
        [{"customer_discord_id": "123", "customer_display_name": "老闆A"}],
    )

    assert rows[0]["loyalty_has_anything"] is True
    assert len(rows[0]["loyalty_progress"]) == 2
    assert len(rows[0]["loyalty_active_coupons"]) == 1
    assert rows[0]["loyalty_coupon_counts"]["redeemed"] == 1
'''


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


SERVICE_PATH.write_text(SERVICE_CONTENT, encoding="utf-8")
DETAIL_TEMPLATE_PATH.write_text(DETAIL_TEMPLATE_CONTENT, encoding="utf-8")
TEST_PATH.write_text(TEST_CONTENT, encoding="utf-8")

replace_once(
    ROUTER_PATH,
    'from web.app.services.admin_customer_loyalty import enrich_customer_rows\n',
    'from web.app.services.admin_customer_loyalty import (\n    enrich_customer_rows,\n    load_customer_loyalty_detail,\n)\n',
)

replace_once(
    ROUTER_PATH,
    '''@router.get("/admin/customer-center")\nasync def customer_center(request: Request, q: str = ""):\n    return await _render(request, center="customers", q=q)\n\n\n@router.get("/admin/customer-center/vip")\n''',
    '''@router.get("/admin/customer-center")\nasync def customer_center(request: Request, q: str = ""):\n    return await _render(request, center="customers", q=q)\n\n\n@router.get("/admin/customer-center/{customer_id}/benefits")\nasync def customer_benefits_detail(request: Request, customer_id: str):\n    user = _current_admin(request)\n    if user is None:\n        return RedirectResponse("/no-access", status_code=303)\n\n    customer_id = str(customer_id or "").strip()\n    if not customer_id:\n        return RedirectResponse("/admin/customer-center", status_code=303)\n\n    loyalty = await run_in_threadpool(\n        lambda: load_customer_loyalty_detail(WEB_DB, customer_id)\n    )\n\n    display_name = customer_id\n    if WEB_DB.exists():\n        try:\n            with _connect(WEB_DB) as conn:\n                if _table_exists(conn, "web_orders"):\n                    row = conn.execute(\n                        """\n                        SELECT MAX(\n                            COALESCE(\n                                NULLIF(customer_display_name, ''),\n                                customer_discord_id\n                            )\n                        ) AS customer_display_name\n                        FROM web_orders\n                        WHERE customer_discord_id = ?\n                        """,\n                        (customer_id,),\n                    ).fetchone()\n                    if row is not None and row["customer_display_name"]:\n                        display_name = str(row["customer_display_name"])\n        except sqlite3.Error:\n            pass\n\n    return templates.TemplateResponse(\n        request=request,\n        name="admin_customer_benefits.html",\n        context={\n            "title": f"{display_name}・福利明細",\n            "user": user,\n            "customer": {\n                "id": customer_id,\n                "display_name": display_name,\n            },\n            "loyalty": loyalty,\n            "is_manager": bool(user.get("is_manager")),\n        },\n    )\n\n\n@router.get("/admin/customer-center/vip")\n''',
)

replace_once(
    CENTER_TEMPLATE_PATH,
    '''                            {% else %}\n                            <div class="loyalty-detail-item"><small>目前沒有未完成的累積進度。</small></div>\n                            {% endfor %}\n                            <small class="loyalty-coupon-history">已兌換 {{ row.loyalty_coupon_counts.redeemed or 0 }} ｜ 已過期 {{ row.loyalty_coupon_counts.expired or 0 }}</small>\n''',
    '''                            {% else %}\n                            <div class="loyalty-detail-item"><small>目前沒有未完成的累積進度。</small></div>\n                            {% endfor %}\n                            {% for coupon in row.loyalty_active_coupons[:3] %}\n                            <div class="loyalty-detail-item">\n                                <strong>{{ coupon.title }}</strong>\n                                <small>{{ coupon.status_label }} ｜ 到期 {{ coupon.expires_at_text }}</small>\n                            </div>\n                            {% endfor %}\n                            <small class="loyalty-coupon-history">已兌換 {{ row.loyalty_coupon_counts.redeemed or 0 }} ｜ 已過期 {{ row.loyalty_coupon_counts.expired or 0 }}</small>\n''',
)

replace_once(
    CENTER_TEMPLATE_PATH,
    '''                <div class="center-actions">\n                    <a class="button secondary" href="/admin/search/customer/{{ row.customer_discord_id }}?return_to=/admin/customer-center">客戶資料</a>\n''',
    '''                <div class="center-actions">\n                    <a class="button secondary" href="/admin/customer-center/{{ row.customer_discord_id }}/benefits">福利明細</a>\n                    <a class="button secondary" href="/admin/search/customer/{{ row.customer_discord_id }}?return_to=/admin/customer-center">客戶資料</a>\n''',
)
