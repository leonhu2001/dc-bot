from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import requests

from web.app.services import roulette_service


def _connect(db_file: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(roulette_service._db_path(db_file), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_redraw_tables(db_file: str | Path | None = None) -> None:
    roulette_service.ensure_roulette_draw_tables(db_file)
    with _connect(db_file) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS roulette_redraw_credits (
                order_id INTEGER PRIMARY KEY,
                remaining INTEGER NOT NULL DEFAULT 0,
                total_granted INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS roulette_redraw_grants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                count INTEGER NOT NULL,
                reason TEXT NOT NULL,
                granted_by_discord_id TEXT,
                granted_by_display_name TEXT,
                created_at TEXT NOT NULL,
                notification_status TEXT NOT NULL DEFAULT 'pending',
                notification_message_id TEXT,
                notification_error TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_roulette_redraw_grants_order
            ON roulette_redraw_grants(order_id, id DESC);

            CREATE TABLE IF NOT EXISTS roulette_draw_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                source_draw_id INTEGER NOT NULL UNIQUE,
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
                notification_status TEXT,
                notification_message_id TEXT,
                notified_at TEXT,
                notification_error TEXT,
                archived_at TEXT NOT NULL,
                archived_reason TEXT NOT NULL DEFAULT 'redraw'
            );

            CREATE INDEX IF NOT EXISTS idx_roulette_draw_history_order
            ON roulette_draw_history(order_id, id DESC);
            """
        )
        conn.commit()


def _load_order(
    conn: sqlite3.Connection,
    order_id: int,
    customer_discord_id: str | int | None = None,
) -> dict[str, Any] | None:
    if customer_discord_id is None:
        row = conn.execute(
            "SELECT * FROM web_orders WHERE id = ? LIMIT 1",
            (int(order_id),),
        ).fetchone()
    else:
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


def _validate_roulette_order(order: dict[str, Any]) -> None:
    if not roulette_service._is_roulette_order(order):
        raise ValueError("這張訂單不是俄羅斯輪盤趣味單。")


def _credits_row(
    conn: sqlite3.Connection,
    order_id: int,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT order_id, remaining, total_granted, updated_at
        FROM roulette_redraw_credits
        WHERE order_id = ?
        LIMIT 1
        """,
        (int(order_id),),
    ).fetchone()
    if row is None:
        return {
            "order_id": int(order_id),
            "remaining": 0,
            "total_granted": 0,
            "updated_at": "",
        }
    return dict(row)


def _history_draw(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    draw = roulette_service._draw_from_row(row)
    data = dict(row)
    draw["archived_at"] = roulette_service._format_time(data.get("archived_at"))
    draw["archived_reason"] = str(data.get("archived_reason") or "")
    draw["source_draw_id"] = int(data.get("source_draw_id") or 0)
    return draw


def get_redraw_state(
    order_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_redraw_tables(db_file)
    with _connect(db_file) as conn:
        order = _load_order(conn, int(order_id))
        if order is None:
            raise LookupError("找不到這張訂單。")
        _validate_roulette_order(order)

        current = conn.execute(
            "SELECT * FROM roulette_draws WHERE order_id = ? LIMIT 1",
            (int(order_id),),
        ).fetchone()
        history_rows = conn.execute(
            """
            SELECT *
            FROM roulette_draw_history
            WHERE order_id = ?
            ORDER BY id DESC
            """,
            (int(order_id),),
        ).fetchall()
        grant_rows = conn.execute(
            """
            SELECT *
            FROM roulette_redraw_grants
            WHERE order_id = ?
            ORDER BY id DESC
            """,
            (int(order_id),),
        ).fetchall()
        credits = _credits_row(conn, int(order_id))

    final_draw = (
        roulette_service._draw_from_row(current)
        if current is not None
        else None
    )
    history = [_history_draw(row) for row in history_rows]
    grants = [dict(row) for row in grant_rows]

    return {
        "order": roulette_service._public_order(order),
        "final_draw": final_draw,
        "history": history,
        "grants": grants,
        "remaining": max(0, int(credits.get("remaining") or 0)),
        "total_granted": max(0, int(credits.get("total_granted") or 0)),
        "attempt_count": len(history) + (1 if final_draw is not None else 0),
    }


def _send_grant_notification(
    order: dict[str, Any],
    *,
    count: int,
    remaining: int,
) -> str:
    ticket_channel_id = str(order.get("ticket_channel_id") or "").strip()
    if not ticket_channel_id:
        raise RuntimeError("訂單尚未綁定 Discord 票口。")

    customer_id = str(order.get("customer_discord_id") or "").strip()
    order_id = int(order.get("id") or 0)
    order_no = str(order.get("bot_order_no") or f"WEB-{order_id}")
    url = roulette_service._roulette_url(order_id)

    response = requests.post(
        f"{roulette_service.DISCORD_API_BASE}/channels/{ticket_channel_id}/messages",
        headers=roulette_service._discord_headers(),
        json={
            "content": (
                f"<@{customer_id}> 🎰 **客服已補發輪盤抽取次數**"
                if customer_id
                else "🎰 **客服已補發輪盤抽取次數**"
            ),
            "embeds": [
                {
                    "title": "輪盤補發完成",
                    "description": (
                        f"客服已補發 **{int(count)} 次**輪盤抽取。\n"
                        f"目前剩餘可補抽：**{int(remaining)} 次**。\n\n"
                        "補抽完成後，**最新一次結果會成為本單最終保底**；"
                        "舊結果會保留在客服後台紀錄中。"
                    ),
                    "color": 0xE0BA64,
                    "fields": [
                        {
                            "name": "訂單",
                            "value": order_no,
                            "inline": True,
                        },
                        {
                            "name": "剩餘次數",
                            "value": f"{int(remaining)} 次",
                            "inline": True,
                        },
                    ],
                }
            ],
            "components": [
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 2,
                            "style": 5,
                            "label": "前往輪盤補抽",
                            "emoji": {"name": "🎰"},
                            "url": url,
                        }
                    ],
                }
            ],
            "allowed_mentions": {
                "parse": [],
                "users": [customer_id] if customer_id else [],
            },
        },
        timeout=15,
    )
    if response.status_code not in {200, 201}:
        raise RuntimeError(
            f"Discord redraw notification HTTP {response.status_code}: "
            f"{str(response.text or '')[:300]}"
        )
    return str(response.json().get("id") or "").strip()


def grant_redraw(
    order_id: int,
    *,
    count: int,
    reason: str,
    admin_user: dict[str, Any],
    db_file: str | Path | None = None,
    notify: bool = True,
) -> dict[str, Any]:
    ensure_redraw_tables(db_file)

    count = int(count or 0)
    if count < 1 or count > 10:
        raise ValueError("補發次數必須介於 1～10 次。")

    reason = str(reason or "").strip()
    if not reason:
        raise ValueError("請填寫補發原因。")
    if len(reason) > 500:
        raise ValueError("補發原因最多 500 字。")

    with _connect(db_file) as conn:
        conn.execute("BEGIN IMMEDIATE")
        order = _load_order(conn, int(order_id))
        if order is None:
            conn.rollback()
            raise LookupError("找不到這張訂單。")
        _validate_roulette_order(order)

        status = str(order.get("status") or "").strip().lower()
        if status not in roulette_service.DRAW_ALLOWED_STATUSES:
            conn.rollback()
            raise ValueError("只有進行中或存單中的輪盤訂單可以補發抽取次數。")

        now = roulette_service._now_iso()
        conn.execute(
            """
            INSERT INTO roulette_redraw_credits (
                order_id, remaining, total_granted, updated_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(order_id)
            DO UPDATE SET
                remaining = roulette_redraw_credits.remaining + excluded.remaining,
                total_granted = roulette_redraw_credits.total_granted + excluded.total_granted,
                updated_at = excluded.updated_at
            """,
            (int(order_id), count, count, now),
        )

        display_name = str(
            admin_user.get("global_name")
            or admin_user.get("username")
            or admin_user.get("name")
            or admin_user.get("id")
            or ""
        ).strip()
        cursor = conn.execute(
            """
            INSERT INTO roulette_redraw_grants (
                order_id,
                count,
                reason,
                granted_by_discord_id,
                granted_by_display_name,
                created_at,
                notification_status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                int(order_id),
                count,
                reason,
                str(admin_user.get("id") or ""),
                display_name,
                now,
            ),
        )
        grant_id = int(cursor.lastrowid)
        credits = _credits_row(conn, int(order_id))
        conn.commit()

    notification_status = "skipped"
    notification_error = ""
    notification_message_id = ""

    if notify:
        try:
            notification_message_id = _send_grant_notification(
                order,
                count=count,
                remaining=int(credits["remaining"]),
            )
        except Exception as exc:
            notification_status = "failed"
            notification_error = f"{type(exc).__name__}: {exc}"[:1000]
        else:
            notification_status = "sent"

        with _connect(db_file) as conn:
            conn.execute(
                """
                UPDATE roulette_redraw_grants
                SET notification_status = ?,
                    notification_message_id = ?,
                    notification_error = ?
                WHERE id = ?
                """,
                (
                    notification_status,
                    notification_message_id,
                    notification_error,
                    grant_id,
                ),
            )
            conn.commit()

    return {
        "order_id": int(order_id),
        "count": count,
        "remaining": int(credits["remaining"]),
        "grant_id": grant_id,
        "notification_status": notification_status,
        "notification_error": notification_error,
    }


def prepare_redraw_if_credited(
    customer_discord_id: str | int,
    order_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    """Archive the current result and consume one credited redraw if available.

    The actual new random draw is still produced by roulette_service.draw_roulette
    after this function commits. Keeping this preparation separate lets the
    existing server-side randomness and Discord result notification remain the
    single canonical draw implementation.
    """
    ensure_redraw_tables(db_file)

    with _connect(db_file) as conn:
        conn.execute("BEGIN IMMEDIATE")
        order = _load_order(
            conn,
            int(order_id),
            customer_discord_id=customer_discord_id,
        )
        if order is None:
            conn.rollback()
            raise LookupError("找不到這張訂單。")
        _validate_roulette_order(order)

        status = str(order.get("status") or "").strip().lower()
        if status not in roulette_service.DRAW_ALLOWED_STATUSES:
            conn.rollback()
            raise PermissionError("這張訂單目前不能進行保底輪盤。")

        current = conn.execute(
            "SELECT * FROM roulette_draws WHERE order_id = ? LIMIT 1",
            (int(order_id),),
        ).fetchone()
        credits = _credits_row(conn, int(order_id))
        remaining = max(0, int(credits.get("remaining") or 0))

        if current is None or remaining <= 0:
            conn.commit()
            return {
                "prepared": False,
                "remaining": remaining,
            }

        conn.execute(
            """
            INSERT OR IGNORE INTO roulette_draw_history (
                order_id,
                source_draw_id,
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
                notification_status,
                notification_message_id,
                notified_at,
                notification_error,
                archived_at,
                archived_reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'redraw')
            """,
            (
                int(current["order_id"]),
                int(current["id"]),
                str(current["customer_discord_id"]),
                str(current["rules_version"]),
                str(current["mode"]),
                str(current["selection_json"]),
                str(current["selection_label"]),
                int(current["landed_number"]),
                int(current["hit"]),
                int(current["guarantee_million"]),
                int(current["is_jackpot"]),
                str(current["created_at"]),
                str(current["notification_status"] or ""),
                str(current["notification_message_id"] or ""),
                str(current["notified_at"] or ""),
                str(current["notification_error"] or ""),
                roulette_service._now_iso(),
            ),
        )
        conn.execute(
            "DELETE FROM roulette_draws WHERE order_id = ?",
            (int(order_id),),
        )
        conn.execute(
            """
            UPDATE roulette_redraw_credits
            SET remaining = CASE
                    WHEN remaining > 0 THEN remaining - 1
                    ELSE 0
                END,
                updated_at = ?
            WHERE order_id = ?
            """,
            (roulette_service._now_iso(), int(order_id)),
        )
        remaining_after = max(0, remaining - 1)
        conn.commit()

    return {
        "prepared": True,
        "remaining": remaining_after,
    }


def list_admin_roulette_orders(
    *,
    db_file: str | Path | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    ensure_redraw_tables(db_file)
    safe_limit = max(1, min(int(limit or 100), 250))

    with _connect(db_file) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM web_orders
            WHERE order_rule_key IN (?, ?)
               OR item LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                roulette_service.ROULETTE_RULE_KEY,
                roulette_service.LEGACY_ROULETTE_RULE_KEY,
                f"%{roulette_service.ROULETTE_ITEM_LABEL}%",
                safe_limit,
            ),
        ).fetchall()

    output: list[dict[str, Any]] = []
    for row in rows:
        order = dict(row)
        state = get_redraw_state(int(order["id"]), db_file=db_file)
        final_draw = state["final_draw"]
        output.append(
            {
                "id": int(order["id"]),
                "order_no": str(
                    order.get("bot_order_no") or f"WEB-{order['id']}"
                ),
                "customer_name": str(
                    order.get("customer_display_name")
                    or order.get("customer_username")
                    or order.get("customer_discord_id")
                    or "未紀錄"
                ),
                "customer_discord_id": str(
                    order.get("customer_discord_id") or ""
                ),
                "status": str(order.get("status") or "").strip().lower(),
                "ticket_channel_id": str(
                    order.get("ticket_channel_id") or ""
                ),
                "final_draw": final_draw,
                "remaining": state["remaining"],
                "total_granted": state["total_granted"],
                "attempt_count": state["attempt_count"],
                "history": state["history"],
                "grants": state["grants"],
            }
        )
    return output
