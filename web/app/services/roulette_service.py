from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from services.order_rule_store import (
    create_custom_order_rule,
    ensure_order_rule_store,
    get_custom_rule_definition,
)
from services.order_rules import invalidate_rule_override_cache
from web.app.config import config


ROULETTE_RULE_KEY = "fun_russian_roulette"
ROULETTE_RULES_VERSION = "roulette-v1-2026-10-12"
ROULETTE_ITEM_LABEL = "俄羅斯輪盤"
DRAW_ALLOWED_STATUSES = {"active", "stored"}

RED_NUMBERS = {
    1, 3, 5, 7, 9,
    12, 14, 16, 18, 19,
    21, 23, 25, 27, 30,
    32, 34, 36,
}

SAFE_SELECTION_LABELS = {
    "red": "紅色",
    "black": "黑色",
    "odd": "單數",
    "even": "雙數",
    "low": "1–18",
    "high": "19–36",
}

DISCORD_API_BASE = "https://discord.com/api/v10"


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[3] / "web_dashboard.db"


def _connect(db_file: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(db_file), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _format_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y/%m/%d %H:%M:%S")
    except (TypeError, ValueError):
        return text.replace("T", " ")[:19]


def ensure_roulette_draw_tables(db_file: str | Path | None = None) -> None:
    path = _db_path(db_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS roulette_draws (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL UNIQUE,
                customer_discord_id TEXT NOT NULL,
                rules_version TEXT NOT NULL,
                mode TEXT NOT NULL,
                selection_json TEXT NOT NULL,
                selection_label TEXT NOT NULL,
                landed_number INTEGER NOT NULL,
                hit INTEGER NOT NULL,
                guarantee_million INTEGER NOT NULL,
                is_jackpot INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                notification_status TEXT NOT NULL DEFAULT 'pending',
                notification_message_id TEXT,
                notified_at TEXT,
                notification_error TEXT
            );

            CREATE UNIQUE INDEX IF NOT EXISTS ux_roulette_draws_order
            ON roulette_draws(order_id);
            """
        )
        conn.commit()


def _bootstrap_order_rule() -> None:
    ensure_order_rule_store()
    if get_custom_rule_definition(ROULETTE_RULE_KEY) is not None:
        return

    payload = {
        "label": ROULETTE_ITEM_LABEL,
        "pricing_type": "fixed",
        "price": 1200,
        "unit_label": "單",
        "allowed_roles": [
            "top_protector",
            "female_protector",
            "male_protector",
        ],
        "required_staff_count": 2,
        "min_quantity": 1,
        "max_quantity": 1,
        "allow_specify": False,
        "catalog_group_label": ROULETTE_ITEM_LABEL,
        "vip_discount_allowed": False,
        "point_benefits_allowed": False,
        "loyalty_benefits_enabled": False,
        "required_game_roles": ["delta_desktop"],
        "note": (
            "付款完成後於官網抽取一次保底；結果產生後永久鎖定，"
            "以網站紀錄為準。"
        ),
        "intro": (
            "完成付款後可進行一次保底輪盤。未命中保底 1,200 萬；"
            "最高為單押 0 命中 JACKPOT 7,000 萬。"
        ),
    }

    try:
        create_custom_order_rule(
            rule_key=ROULETTE_RULE_KEY,
            category="delta_desktop_fun",
            payload=payload,
            actor_discord_id="system",
            actor_display_name="Mowan Roulette Bootstrap",
        )
    except ValueError as exc:
        if "已存在" not in str(exc):
            raise

    invalidate_rule_override_cache()


def ensure_roulette_feature() -> None:
    ensure_roulette_draw_tables()
    _bootstrap_order_rule()


def _number(value: Any) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("下注位置不正確，請重新選擇。") from exc
    if not 0 <= result <= 36:
        raise ValueError("下注號碼必須介於 0 到 36。")
    return result


def six_line_numbers(anchor: int) -> list[int]:
    anchor = _number(anchor)
    if anchor == 0:
        raise ValueError("六線下注不能使用 0。")
    column = (anchor + 2) // 3
    start_column = min(11, max(1, column))
    return [
        (x - 1) * 3 + row
        for x in (start_column, start_column + 1)
        for row in (1, 2, 3)
    ]


def corner_numbers(anchor: int) -> list[int]:
    anchor = _number(anchor)
    if anchor == 0:
        raise ValueError("四角下注不能使用 0。")
    column = (anchor + 2) // 3
    start_column = min(11, max(1, column))
    row = (anchor - 1) % 3 + 1
    start_row = 2 if row == 3 else 1
    return [
        (x - 1) * 3 + y
        for y in (start_row, start_row + 1)
        for x in (start_column, start_column + 1)
    ]


def normalize_bet(mode: str, selection: Any) -> dict[str, Any]:
    mode_value = str(mode or "").strip().lower()

    if mode_value == "safe":
        key = str(selection or "").strip().lower()
        if key not in SAFE_SELECTION_LABELS:
            raise ValueError("穩健下注位置不正確，請重新選擇。")
        return {
            "mode": "safe",
            "selection": key,
            "selection_label": SAFE_SELECTION_LABELS[key],
            "covered_numbers": [],
        }

    if mode_value == "single":
        number = _number(selection)
        return {
            "mode": "single",
            "selection": number,
            "selection_label": (
                "單押 0｜JACKPOT"
                if number == 0
                else f"單押 {number} 號"
            ),
            "covered_numbers": [number],
        }

    if mode_value == "six":
        anchor = _number(selection)
        covered = six_line_numbers(anchor)
        return {
            "mode": "six",
            "selection": anchor,
            "selection_label": "六線｜" + "・".join(str(n) for n in covered),
            "covered_numbers": covered,
        }

    if mode_value == "corner":
        anchor = _number(selection)
        covered = corner_numbers(anchor)
        return {
            "mode": "corner",
            "selection": anchor,
            "selection_label": "四角｜" + "・".join(str(n) for n in covered),
            "covered_numbers": covered,
        }

    raise ValueError("未知的下注方式。")


def _safe_hit(key: str, landed_number: int) -> bool:
    if landed_number == 0:
        return False
    if key == "red":
        return landed_number in RED_NUMBERS
    if key == "black":
        return landed_number not in RED_NUMBERS
    if key == "odd":
        return landed_number % 2 == 1
    if key == "even":
        return landed_number % 2 == 0
    if key == "low":
        return 1 <= landed_number <= 18
    if key == "high":
        return 19 <= landed_number <= 36
    return False


def resolve_roulette_result(
    mode: str,
    selection: Any,
    landed_number: int,
) -> dict[str, Any]:
    landed = _number(landed_number)
    bet = normalize_bet(mode, selection)
    mode_value = bet["mode"]

    if mode_value == "safe":
        hit = _safe_hit(str(bet["selection"]), landed)
    else:
        hit = landed in set(int(n) for n in bet["covered_numbers"])

    if not hit:
        guarantee = 1200
    elif mode_value == "safe":
        guarantee = 1500
    elif mode_value == "six":
        guarantee = 2000
    elif mode_value == "corner":
        guarantee = 2500
    elif int(bet["selection"]) == 0:
        guarantee = 7000
    else:
        guarantee = 6000

    is_jackpot = bool(
        hit
        and mode_value == "single"
        and int(bet["selection"]) == 0
        and landed == 0
    )

    return {
        **bet,
        "number": landed,
        "hit": bool(hit),
        "prize": int(guarantee),
        "is_jackpot": is_jackpot,
    }


def _load_order(
    conn: sqlite3.Connection,
    order_id: int,
    customer_discord_id: str | int,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT *
        FROM web_orders
        WHERE id = ?
          AND CAST(customer_discord_id AS TEXT) = ?
        LIMIT 1
        """,
        (int(order_id), str(customer_discord_id)),
    ).fetchone()
    return dict(row) if row is not None else None


def _is_roulette_order(order: dict[str, Any]) -> bool:
    rule_key = str(order.get("order_rule_key") or "").strip()
    if rule_key == ROULETTE_RULE_KEY:
        return True
    return ROULETTE_ITEM_LABEL in str(order.get("item") or "")


def _public_order(order: dict[str, Any]) -> dict[str, Any]:
    order_id = int(order.get("id") or 0)
    order_no = str(order.get("bot_order_no") or f"WEB-{order_id}")
    return {
        "id": order_id,
        "order_no": order_no,
        "item": str(order.get("item") or ROULETTE_ITEM_LABEL),
        "status": str(order.get("status") or "").strip().lower(),
        "ticket_channel_id": str(order.get("ticket_channel_id") or "").strip(),
    }


def _draw_from_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    try:
        selection_data = json.loads(str(data.get("selection_json") or "{}"))
    except (TypeError, ValueError):
        selection_data = {}

    covered = selection_data.get("covered_numbers")
    if not isinstance(covered, list):
        covered = []

    return {
        "id": int(data.get("id") or 0),
        "order_id": int(data.get("order_id") or 0),
        "mode": str(data.get("mode") or ""),
        "selection": selection_data.get("selection"),
        "selection_label": str(data.get("selection_label") or ""),
        "covered_numbers": [int(n) for n in covered if str(n).lstrip("-").isdigit()],
        "number": int(data.get("landed_number") or 0),
        "hit": bool(data.get("hit")),
        "prize": int(data.get("guarantee_million") or 1200),
        "is_jackpot": bool(data.get("is_jackpot")),
        "drawn_at": _format_time(data.get("created_at")),
        "notification_status": str(data.get("notification_status") or ""),
    }


def get_roulette_context(
    customer_discord_id: str | int,
    order_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_roulette_draw_tables(db_file)
    with _connect(db_file) as conn:
        order = _load_order(conn, order_id, customer_discord_id)
        if order is None:
            raise LookupError("找不到這張訂單。")
        if not _is_roulette_order(order):
            raise ValueError("這張訂單沒有保底輪盤。")

        draw_row = conn.execute(
            "SELECT * FROM roulette_draws WHERE order_id = ? LIMIT 1",
            (int(order_id),),
        ).fetchone()

    status = str(order.get("status") or "").strip().lower()
    draw = _draw_from_row(draw_row) if draw_row is not None else None

    if draw is not None:
        can_draw = False
        reason = "本單結果已鎖定。"
    elif status in DRAW_ALLOWED_STATUSES:
        can_draw = True
        reason = ""
    elif status in {"pending_cs_dispatch", "waiting_acceptance", "accepted_pending_pay"}:
        can_draw = False
        reason = "付款完成後即可進行一次保底輪盤。"
    elif status in {"closed", "cancelled", "canceled"}:
        can_draw = False
        reason = "此訂單已結束，未產生的輪盤結果不再開放抽取。"
    else:
        can_draw = False
        reason = "目前訂單狀態尚未開放抽取。"

    return {
        "order": _public_order(order),
        "draw": draw,
        "can_draw": can_draw,
        "reason": reason,
    }


def _notification_embed(order: dict[str, Any], draw: dict[str, Any]) -> dict[str, Any]:
    jackpot = bool(draw.get("is_jackpot"))
    title = "🎰 JACKPOT！俄羅斯輪盤結果" if jackpot else "🎲 俄羅斯輪盤｜保底結果"
    description = (
        "單押 0 命中，觸發特殊大獎。"
        if jackpot
        else "老闆已完成本單保底輪盤，結果已永久鎖定。"
    )
    return {
        "title": title,
        "description": description,
        "color": 0xE0BA64 if not jackpot else 0x45B96B,
        "fields": [
            {
                "name": "訂單",
                "value": str(order.get("bot_order_no") or f"WEB-{order.get('id')}"),
                "inline": True,
            },
            {
                "name": "下注",
                "value": str(draw.get("selection_label") or "未紀錄")[:1024],
                "inline": True,
            },
            {
                "name": "落點",
                "value": f"{int(draw.get('number') or 0)} 號",
                "inline": True,
            },
            {
                "name": "最終保底",
                "value": f"**{int(draw.get('prize') or 1200):,} 萬**",
                "inline": False,
            },
        ],
        "footer": {
            "text": f"MW Roulette · order {int(order.get('id') or 0)}"
        },
    }


def _send_discord_notification(order: dict[str, Any], draw: dict[str, Any]) -> str:
    ticket_channel_id = str(order.get("ticket_channel_id") or "").strip()
    if not ticket_channel_id:
        raise RuntimeError("訂單尚未綁定 Discord 票口。")

    token = str(config.DISCORD_BOT_TOKEN or "").strip()
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is not configured")

    customer_id = str(order.get("customer_discord_id") or "").strip()
    content = f"<@{customer_id}> 保底輪盤已完成。" if customer_id else "保底輪盤已完成。"

    response = requests.post(
        f"{DISCORD_API_BASE}/channels/{ticket_channel_id}/messages",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
        },
        json={
            "content": content,
            "embeds": [_notification_embed(order, draw)],
            "allowed_mentions": {
                "parse": [],
                "users": [customer_id] if customer_id else [],
            },
        },
        timeout=15,
    )
    if response.status_code not in {200, 201}:
        raise RuntimeError(f"Discord notification HTTP {response.status_code}")

    return str(response.json().get("id") or "").strip()


def _mark_notification(
    order_id: int,
    *,
    status: str,
    message_id: str = "",
    error: str = "",
    db_file: str | Path | None = None,
) -> None:
    with _connect(db_file) as conn:
        conn.execute(
            """
            UPDATE roulette_draws
            SET notification_status = ?,
                notification_message_id = ?,
                notified_at = CASE WHEN ? = 'sent' THEN ? ELSE notified_at END,
                notification_error = ?
            WHERE order_id = ?
            """,
            (
                str(status),
                str(message_id or ""),
                str(status),
                _now_iso(),
                str(error or "")[:1000],
                int(order_id),
            ),
        )
        conn.commit()


def draw_roulette(
    customer_discord_id: str | int,
    order_id: int,
    *,
    mode: str,
    selection: Any,
    db_file: str | Path | None = None,
    notify: bool = True,
) -> dict[str, Any]:
    ensure_roulette_draw_tables(db_file)
    bet = normalize_bet(mode, selection)
    order: dict[str, Any]
    result: dict[str, Any]
    existing = False

    with _connect(db_file) as conn:
        conn.execute("BEGIN IMMEDIATE")
        order = _load_order(conn, order_id, customer_discord_id) or {}
        if not order:
            conn.rollback()
            raise LookupError("找不到這張訂單。")
        if not _is_roulette_order(order):
            conn.rollback()
            raise ValueError("這張訂單沒有保底輪盤。")

        existing_row = conn.execute(
            "SELECT * FROM roulette_draws WHERE order_id = ? LIMIT 1",
            (int(order_id),),
        ).fetchone()
        if existing_row is not None:
            result = _draw_from_row(existing_row)
            existing = True
            conn.commit()
        else:
            status = str(order.get("status") or "").strip().lower()
            if status not in DRAW_ALLOWED_STATUSES:
                conn.rollback()
                if status in {"pending_cs_dispatch", "waiting_acceptance", "accepted_pending_pay"}:
                    raise PermissionError("付款完成後才會開放保底輪盤。")
                raise PermissionError("這張訂單目前不能進行保底輪盤。")

            landed_number = secrets.randbelow(37)
            resolved = resolve_roulette_result(
                str(bet["mode"]),
                bet["selection"],
                landed_number,
            )
            created_at = _now_iso()
            selection_json = json.dumps(
                {
                    "selection": resolved["selection"],
                    "covered_numbers": resolved["covered_numbers"],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )

            cursor = conn.execute(
                """
                INSERT INTO roulette_draws (
                    order_id,
                    customer_discord_id,
                    rules_version,
                    mode,
                    selection_json,
                    selection_label,
                    landed_number,
                    hit,
                    guarantee_million,
                    is_jackpot,
                    created_at,
                    notification_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    int(order_id),
                    str(customer_discord_id),
                    ROULETTE_RULES_VERSION,
                    str(resolved["mode"]),
                    selection_json,
                    str(resolved["selection_label"]),
                    int(resolved["number"]),
                    1 if resolved["hit"] else 0,
                    int(resolved["prize"]),
                    1 if resolved["is_jackpot"] else 0,
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM roulette_draws WHERE id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
            conn.commit()
            if row is None:
                raise RuntimeError("輪盤結果寫入失敗。")
            result = _draw_from_row(row)

    if notify and not existing:
        try:
            message_id = _send_discord_notification(order, result)
        except Exception as exc:
            _mark_notification(
                order_id,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                db_file=db_file,
            )
        else:
            _mark_notification(
                order_id,
                status="sent",
                message_id=message_id,
                db_file=db_file,
            )
            result["notification_status"] = "sent"

    result["already_drawn"] = bool(existing)
    return result
