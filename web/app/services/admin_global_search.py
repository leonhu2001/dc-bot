from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


ORDER_STATUS_LABELS = {
    "pending_cs_dispatch": "待客服確認",
    "waiting_acceptance": "等待接單",
    "accepted_pending_pay": "等待付款",
    "active": "進行中",
    "stored": "存單",
    "closed": "已結單",
    "cancelled": "已取消",
    "canceled": "已取消",
}

PAYMENT_STATUS_LABELS = {
    "pending_review": "待審核",
    "approved_pending_apply": "已核准／套用中",
    "applied": "已完成",
    "rejected": "已駁回",
    "apply_error": "套用異常",
}

TOPUP_STATUS_LABELS = {
    "pending_payment": "等待付款",
    "pending_review": "待審核",
    "approved_pending_credit": "已核准／待入帳",
    "crediting": "入帳中",
    "completed": "已完成",
    "rejected": "已駁回",
    "cancelled": "已取消",
}

SUPPORT_STATUS_LABELS = {
    "open": "等待客服接手",
    "claimed": "客服處理中",
    "resolved": "已完成",
    "cancelled": "已結束",
}


def _repo_root(root: str | Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    return Path(__file__).resolve().parents[3]


def _web_db(root: str | Path | None = None) -> Path:
    return _repo_root(root) / "web_dashboard.db"


def _bot_db(root: str | Path | None = None) -> Path:
    return _repo_root(root) / "bot.db"


def _connect_readonly(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    conn = sqlite3.connect(
        f"file:{path}?mode=ro",
        uri=True,
        timeout=15,
    )
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        ).fetchone()
        is not None
    )


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return int(default)


def _fmt_amount(value: Any) -> str:
    return f"{_safe_int(value):,}T"


def _fmt_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    return text.replace("T", " ")[:19]


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _append_match(
    bucket: dict[str, dict[str, Any]],
    customer_id: Any,
    *,
    name: Any = None,
    reason: str,
    score: int,
) -> None:
    customer_id = str(customer_id or "").strip()
    if not customer_id:
        return

    entry = bucket.setdefault(
        customer_id,
        {
            "customer_discord_id": customer_id,
            "customer_display_name": "",
            "score": 0,
            "matches": [],
        },
    )

    display_name = str(name or "").strip()
    if display_name and (
        not entry["customer_display_name"]
        or entry["customer_display_name"].startswith("老闆 ")
    ):
        entry["customer_display_name"] = display_name

    entry["score"] = max(int(entry["score"]), int(score))
    if reason not in entry["matches"]:
        entry["matches"].append(reason)


def search_admin_customers(
    query: str,
    *,
    root: str | Path | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    q = str(query or "").strip()
    if not q:
        return {"query": "", "results": [], "count": 0}

    q_lower = q.lower()
    like = f"%{q}%"
    matches: dict[str, dict[str, Any]] = {}

    web = _connect_readonly(_web_db(root))
    if web is not None:
        try:
            if _table_exists(web, "web_users"):
                rows = web.execute(
                    """
                    SELECT discord_id, username, global_name
                    FROM web_users
                    WHERE CAST(discord_id AS TEXT) LIKE ?
                       OR COALESCE(username, '') LIKE ?
                       OR COALESCE(global_name, '') LIKE ?
                    LIMIT 100
                    """,
                    (like, like, like),
                ).fetchall()
                for row in rows:
                    cid = str(row["discord_id"] or "")
                    name = _first_nonempty(row["global_name"], row["username"])
                    exact_id = cid == q
                    exact_name = name.lower() == q_lower if name else False
                    _append_match(
                        matches,
                        cid,
                        name=name,
                        reason="Discord ID 完全符合" if exact_id else (
                            "暱稱完全符合" if exact_name else "Discord 帳號 / 暱稱符合"
                        ),
                        score=100 if exact_id else (95 if exact_name else 72),
                    )

            if _table_exists(web, "web_orders"):
                cols = _columns(web, "web_orders")
                name_col = (
                    "customer_display_name"
                    if "customer_display_name" in cols
                    else "customer_discord_id"
                )
                rows = web.execute(
                    f"""
                    SELECT id, bot_order_no, ticket_channel_id,
                           customer_discord_id, {name_col} AS customer_name
                    FROM web_orders
                    WHERE CAST(id AS TEXT) LIKE ?
                       OR COALESCE(bot_order_no, '') LIKE ?
                       OR COALESCE(ticket_channel_id, '') LIKE ?
                       OR COALESCE(customer_discord_id, '') LIKE ?
                       OR COALESCE({name_col}, '') LIKE ?
                    ORDER BY id DESC
                    LIMIT 150
                    """,
                    (like, like, like, like, like),
                ).fetchall()
                for row in rows:
                    cid = row["customer_discord_id"]
                    order_no = _first_nonempty(row["bot_order_no"], f"WEB-{row['id']}")
                    exact = q in {
                        str(row["id"] or ""),
                        str(row["bot_order_no"] or ""),
                        str(row["ticket_channel_id"] or ""),
                        f"WEB-{row['id']}",
                    }
                    reason = (
                        f"訂單 / Ticket 完全符合：{order_no}"
                        if exact
                        else f"訂單資料符合：{order_no}"
                    )
                    _append_match(
                        matches,
                        cid,
                        name=row["customer_name"],
                        reason=reason,
                        score=98 if exact else 76,
                    )

            if _table_exists(web, "payment_reviews"):
                rows = web.execute(
                    """
                    SELECT id, review_no, source_id, ticket_channel_id,
                           customer_discord_id, customer_display_name
                    FROM payment_reviews
                    WHERE COALESCE(review_no, '') LIKE ?
                       OR COALESCE(source_id, '') LIKE ?
                       OR COALESCE(ticket_channel_id, '') LIKE ?
                       OR COALESCE(customer_discord_id, '') LIKE ?
                       OR COALESCE(customer_display_name, '') LIKE ?
                    ORDER BY id DESC
                    LIMIT 100
                    """,
                    (like, like, like, like, like),
                ).fetchall()
                for row in rows:
                    exact = q in {
                        str(row["review_no"] or ""),
                        str(row["ticket_channel_id"] or ""),
                    }
                    _append_match(
                        matches,
                        row["customer_discord_id"],
                        name=row["customer_display_name"],
                        reason=f"付款單符合：{row['review_no'] or row['id']}",
                        score=99 if exact else 78,
                    )

            if _table_exists(web, "order_reviews"):
                rows = web.execute(
                    """
                    SELECT id, receipt_id, ticket_channel_id,
                           customer_discord_id, customer_display_name
                    FROM order_reviews
                    WHERE COALESCE(receipt_id, '') LIKE ?
                       OR COALESCE(ticket_channel_id, '') LIKE ?
                       OR COALESCE(customer_discord_id, '') LIKE ?
                       OR COALESCE(customer_display_name, '') LIKE ?
                    ORDER BY id DESC
                    LIMIT 100
                    """,
                    (like, like, like, like),
                ).fetchall()
                for row in rows:
                    _append_match(
                        matches,
                        row["customer_discord_id"],
                        name=row["customer_display_name"],
                        reason=f"評價紀錄符合：#{row['id']}",
                        score=72,
                    )

            if _table_exists(web, "support_calls"):
                rows = web.execute(
                    """
                    SELECT id, ticket_channel_id, customer_discord_id,
                           customer_display_name
                    FROM support_calls
                    WHERE COALESCE(ticket_channel_id, '') LIKE ?
                       OR COALESCE(customer_discord_id, '') LIKE ?
                       OR COALESCE(customer_display_name, '') LIKE ?
                    ORDER BY id DESC
                    LIMIT 100
                    """,
                    (like, like, like),
                ).fetchall()
                for row in rows:
                    exact = str(row["ticket_channel_id"] or "") == q
                    _append_match(
                        matches,
                        row["customer_discord_id"],
                        name=row["customer_display_name"],
                        reason=f"客服鈴 / Ticket 符合：#{row['id']}",
                        score=96 if exact else 74,
                    )

            if _table_exists(web, "ticket_archives"):
                rows = web.execute(
                    """
                    SELECT id, ticket_channel_id, ticket_channel_name, order_no,
                           customer_discord_id, customer_display_name
                    FROM ticket_archives
                    WHERE COALESCE(ticket_channel_id, '') LIKE ?
                       OR COALESCE(ticket_channel_name, '') LIKE ?
                       OR COALESCE(order_no, '') LIKE ?
                       OR COALESCE(customer_discord_id, '') LIKE ?
                       OR COALESCE(customer_display_name, '') LIKE ?
                    ORDER BY id DESC
                    LIMIT 100
                    """,
                    (like, like, like, like, like),
                ).fetchall()
                for row in rows:
                    exact = q in {
                        str(row["ticket_channel_id"] or ""),
                        str(row["order_no"] or ""),
                    }
                    _append_match(
                        matches,
                        row["customer_discord_id"],
                        name=row["customer_display_name"],
                        reason=f"票口紀錄符合：{row['ticket_channel_name'] or row['ticket_channel_id']}",
                        score=98 if exact else 75,
                    )
        finally:
            web.close()

    bot = _connect_readonly(_bot_db(root))
    if bot is not None:
        try:
            if _table_exists(bot, "customer_wallets"):
                rows = bot.execute(
                    """
                    SELECT customer_discord_id
                    FROM customer_wallets
                    WHERE COALESCE(customer_discord_id, '') LIKE ?
                    LIMIT 100
                    """,
                    (like,),
                ).fetchall()
                for row in rows:
                    cid = str(row["customer_discord_id"] or "")
                    _append_match(
                        matches,
                        cid,
                        reason="錢包 Discord ID 符合",
                        score=100 if cid == q else 70,
                    )

            if _table_exists(bot, "wallet_transactions"):
                rows = bot.execute(
                    """
                    SELECT id, customer_discord_id, order_no, order_channel_id
                    FROM wallet_transactions
                    WHERE COALESCE(customer_discord_id, '') LIKE ?
                       OR COALESCE(order_no, '') LIKE ?
                       OR COALESCE(order_channel_id, '') LIKE ?
                       OR COALESCE(note, '') LIKE ?
                    ORDER BY id DESC
                    LIMIT 100
                    """,
                    (like, like, like, like),
                ).fetchall()
                for row in rows:
                    exact = q in {
                        str(row["order_no"] or ""),
                        str(row["order_channel_id"] or ""),
                    }
                    _append_match(
                        matches,
                        row["customer_discord_id"],
                        reason=f"錢包流水符合：#{row['id']}",
                        score=96 if exact else 68,
                    )

            if _table_exists(bot, "topup_orders"):
                rows = bot.execute(
                    """
                    SELECT id, topup_no, customer_discord_id, customer_display_name
                    FROM topup_orders
                    WHERE COALESCE(topup_no, '') LIKE ?
                       OR COALESCE(customer_discord_id, '') LIKE ?
                       OR COALESCE(customer_display_name, '') LIKE ?
                       OR COALESCE(payment_reference, '') LIKE ?
                       OR COALESCE(bank_last5, '') LIKE ?
                    ORDER BY id DESC
                    LIMIT 100
                    """,
                    (like, like, like, like, like),
                ).fetchall()
                for row in rows:
                    exact = str(row["topup_no"] or "") == q
                    _append_match(
                        matches,
                        row["customer_discord_id"],
                        name=row["customer_display_name"],
                        reason=f"儲值單符合：{row['topup_no'] or row['id']}",
                        score=99 if exact else 77,
                    )

            if _table_exists(bot, "customers"):
                cols = _columns(bot, "customers")
                id_col = "customer_id" if "customer_id" in cols else (
                    "user_id" if "user_id" in cols else None
                )
                if id_col:
                    rows = bot.execute(
                        f"""
                        SELECT {id_col} AS customer_id
                        FROM customers
                        WHERE CAST({id_col} AS TEXT) LIKE ?
                        LIMIT 100
                        """,
                        (like,),
                    ).fetchall()
                    for row in rows:
                        cid = str(row["customer_id"] or "")
                        _append_match(
                            matches,
                            cid,
                            reason="VIP / 會員資料符合",
                            score=100 if cid == q else 66,
                        )
        finally:
            bot.close()

    results = sorted(
        matches.values(),
        key=lambda item: (-int(item["score"]), item["customer_display_name"], item["customer_discord_id"]),
    )[: max(1, min(int(limit or 50), 100))]

    for item in results:
        if not item["customer_display_name"]:
            cid = item["customer_discord_id"]
            item["customer_display_name"] = f"老闆 {cid[-4:]}" if cid else "未知顧客"

    return {
        "query": q,
        "results": results,
        "count": len(results),
    }


def _customer_identity(
    web: sqlite3.Connection | None,
    customer_id: str,
) -> dict[str, Any]:
    identity = {
        "discord_id": customer_id,
        "display_name": f"老闆 {customer_id[-4:]}" if customer_id else "未知顧客",
        "username": "",
        "global_name": "",
        "last_login_at": None,
    }

    if web is not None and _table_exists(web, "web_users"):
        row = web.execute(
            """
            SELECT discord_id, username, global_name, last_login_at
            FROM web_users
            WHERE CAST(discord_id AS TEXT) = ?
            LIMIT 1
            """,
            (customer_id,),
        ).fetchone()
        if row is not None:
            identity["username"] = str(row["username"] or "")
            identity["global_name"] = str(row["global_name"] or "")
            identity["last_login_at"] = _fmt_time(row["last_login_at"])
            identity["display_name"] = _first_nonempty(
                row["global_name"],
                row["username"],
                identity["display_name"],
            )

    if web is not None and _table_exists(web, "web_orders"):
        row = web.execute(
            """
            SELECT customer_display_name
            FROM web_orders
            WHERE CAST(customer_discord_id AS TEXT) = ?
              AND COALESCE(customer_display_name, '') != ''
            ORDER BY id DESC
            LIMIT 1
            """,
            (customer_id,),
        ).fetchone()
        if row is not None and row["customer_display_name"]:
            identity["display_name"] = str(row["customer_display_name"])

    return identity


def _wallet_bundle(
    bot: sqlite3.Connection | None,
    customer_id: str,
) -> dict[str, Any]:
    result = {
        "balance": 0,
        "balance_text": "0T",
        "updated_at": "-",
        "transactions": [],
    }
    if bot is None:
        return result

    if _table_exists(bot, "customer_wallets"):
        row = bot.execute(
            """
            SELECT balance, updated_at
            FROM customer_wallets
            WHERE CAST(customer_discord_id AS TEXT) = ?
            LIMIT 1
            """,
            (customer_id,),
        ).fetchone()
        if row is not None:
            result["balance"] = _safe_int(row["balance"])
            result["balance_text"] = _fmt_amount(row["balance"])
            result["updated_at"] = _fmt_time(row["updated_at"])

    if _table_exists(bot, "wallet_transactions"):
        rows = bot.execute(
            """
            SELECT *
            FROM wallet_transactions
            WHERE CAST(customer_discord_id AS TEXT) = ?
            ORDER BY id DESC
            LIMIT 30
            """,
            (customer_id,),
        ).fetchall()
        for row in rows:
            item = dict(row)
            item["amount_text"] = (
                f"+{_fmt_amount(item.get('amount'))}"
                if _safe_int(item.get("amount")) > 0
                else f"-{_fmt_amount(abs(_safe_int(item.get('amount'))))}"
            )
            item["created_at_text"] = _fmt_time(item.get("created_at"))
            result["transactions"].append(item)

    return result


def _vip_bundle(
    bot: sqlite3.Connection | None,
    customer_id: str,
) -> dict[str, Any]:
    result = {
        "level": "普通魔丸",
        "total_spent": 0,
        "total_spent_text": "0T",
        "points": 0,
        "completed_orders": 0,
        "last_order_at": "-",
        "found": False,
    }
    if bot is None or not _table_exists(bot, "customers"):
        return result

    cols = _columns(bot, "customers")
    id_col = "customer_id" if "customer_id" in cols else (
        "user_id" if "user_id" in cols else None
    )
    if not id_col:
        return result

    row = bot.execute(
        f"SELECT * FROM customers WHERE CAST({id_col} AS TEXT) = ? LIMIT 1",
        (customer_id,),
    ).fetchone()
    if row is None:
        return result

    data = dict(row)
    extra: dict[str, Any] = {}
    try:
        parsed = json.loads(str(data.get("data_json") or "{}"))
        if isinstance(parsed, dict):
            extra = parsed
    except Exception:
        extra = {}

    total_spent = _safe_int(data.get("total_spent", extra.get("total_spent")))
    points = _safe_int(data.get("points", extra.get("points")))
    completed = _safe_int(
        data.get(
            "completed_orders",
            extra.get("order_count", extra.get("completed_orders")),
        )
    )
    result.update(
        {
            "found": True,
            "level": _first_nonempty(data.get("level"), extra.get("level"), "普通魔丸"),
            "total_spent": total_spent,
            "total_spent_text": _fmt_amount(total_spent),
            "points": points,
            "completed_orders": completed,
            "last_order_at": _fmt_time(
                data.get("last_order_at", extra.get("last_order_at"))
            ),
        }
    )
    return result


def build_customer_360(
    customer_discord_id: str | int,
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    customer_id = str(customer_discord_id or "").strip()
    web = _connect_readonly(_web_db(root))
    bot = _connect_readonly(_bot_db(root))

    try:
        identity = _customer_identity(web, customer_id)
        wallet = _wallet_bundle(bot, customer_id)
        vip = _vip_bundle(bot, customer_id)

        orders: list[dict[str, Any]] = []
        payments: list[dict[str, Any]] = []
        topups: list[dict[str, Any]] = []
        reviews: list[dict[str, Any]] = []
        support_calls: list[dict[str, Any]] = []
        tickets: list[dict[str, Any]] = []

        if web is not None and _table_exists(web, "web_orders"):
            rows = web.execute(
                """
                SELECT *
                FROM web_orders
                WHERE CAST(customer_discord_id AS TEXT) = ?
                ORDER BY id DESC
                LIMIT 100
                """,
                (customer_id,),
            ).fetchall()
            for row in rows:
                item = dict(row)
                status = str(item.get("status") or "")
                item["status_label"] = ORDER_STATUS_LABELS.get(status, status or "未知")
                item["order_no"] = _first_nonempty(
                    item.get("bot_order_no"),
                    f"WEB-{item.get('id')}",
                )
                amount = item.get("customer_pay_amount")
                if amount is None:
                    amount = item.get("amount")
                item["amount_text"] = _fmt_amount(amount)
                item["created_at_text"] = _fmt_time(item.get("created_at"))
                orders.append(item)

        if web is not None and _table_exists(web, "payment_reviews"):
            rows = web.execute(
                """
                SELECT *
                FROM payment_reviews
                WHERE CAST(customer_discord_id AS TEXT) = ?
                ORDER BY id DESC
                LIMIT 50
                """,
                (customer_id,),
            ).fetchall()
            for row in rows:
                item = dict(row)
                status = str(item.get("status") or "")
                item["status_label"] = PAYMENT_STATUS_LABELS.get(status, status or "未知")
                item["amount_text"] = _fmt_amount(item.get("amount"))
                item["created_at_text"] = _fmt_time(item.get("created_at"))
                payments.append(item)

        if bot is not None and _table_exists(bot, "topup_orders"):
            rows = bot.execute(
                """
                SELECT *
                FROM topup_orders
                WHERE CAST(customer_discord_id AS TEXT) = ?
                ORDER BY id DESC
                LIMIT 50
                """,
                (customer_id,),
            ).fetchall()
            for row in rows:
                item = dict(row)
                status = str(item.get("status") or "")
                item["status_label"] = TOPUP_STATUS_LABELS.get(status, status or "未知")
                item["amount_text"] = _fmt_amount(item.get("amount"))
                item["credited_amount_text"] = _fmt_amount(item.get("credited_amount"))
                item["created_at_text"] = _fmt_time(item.get("created_at"))
                topups.append(item)

        if web is not None and _table_exists(web, "order_reviews"):
            rows = web.execute(
                """
                SELECT *
                FROM order_reviews
                WHERE CAST(customer_discord_id AS TEXT) = ?
                ORDER BY id DESC
                LIMIT 50
                """,
                (customer_id,),
            ).fetchall()
            for row in rows:
                item = dict(row)
                item["created_at_text"] = _fmt_time(item.get("created_at"))
                reviews.append(item)

        if web is not None and _table_exists(web, "support_calls"):
            rows = web.execute(
                """
                SELECT *
                FROM support_calls
                WHERE CAST(customer_discord_id AS TEXT) = ?
                ORDER BY id DESC
                LIMIT 50
                """,
                (customer_id,),
            ).fetchall()
            for row in rows:
                item = dict(row)
                status = str(item.get("status") or "")
                item["status_label"] = SUPPORT_STATUS_LABELS.get(status, status or "未知")
                item["called_at_text"] = _fmt_time(item.get("called_at"))
                support_calls.append(item)

        if web is not None and _table_exists(web, "ticket_archives"):
            rows = web.execute(
                """
                SELECT *
                FROM ticket_archives
                WHERE CAST(customer_discord_id AS TEXT) = ?
                ORDER BY id DESC
                LIMIT 50
                """,
                (customer_id,),
            ).fetchall()
            for row in rows:
                item = dict(row)
                item["closed_at_text"] = _fmt_time(item.get("closed_at"))
                tickets.append(item)

        return {
            "customer_id": customer_id,
            "identity": identity,
            "wallet": wallet,
            "vip": vip,
            "orders": orders,
            "payments": payments,
            "topups": topups,
            "reviews": reviews,
            "support_calls": support_calls,
            "tickets": tickets,
            "counts": {
                "orders": len(orders),
                "payments": len(payments),
                "topups": len(topups),
                "reviews": len(reviews),
                "support_calls": len(support_calls),
                "tickets": len(tickets),
                "wallet_transactions": len(wallet["transactions"]),
            },
        }
    finally:
        if web is not None:
            web.close()
        if bot is not None:
            bot.close()
