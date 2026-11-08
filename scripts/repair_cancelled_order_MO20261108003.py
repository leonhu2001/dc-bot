#!/usr/bin/env python3
"""One-time, owner-authorized cleanup of the accidentally approved cancelled order.

Run under the accompanying maintenance shell (which stops Bot and Web).
Default invocation is READ ONLY. --apply requires stopped services and backups.
No wallet / banking ledger is ever deleted. A private backup and audit marker
remain to keep the removal accountable and prevent a second VIP deduction.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORDER_NO = "MO20261108003"
CUSTOMER_ID = "519543572194656316"
TICKET_ID = "1568952422544711726"
SIBLING_ORDER_NO = "MO20261108006"
ORDER_PRICE = 3750
EXPECTED_VIP_BEFORE = 6750
EXPECTED_VIP_AFTER = 3000
REPAIR_KEY = "20261108:owner-authorized-purge-MO20261108003-v1"

# These are order-scoped children, never general money/ledger tables.
ORDER_CHILD_TABLES = frozenset({
    "roulette_draw_history", "roulette_redraw_grants", "roulette_redraw_credits",
    "roulette_ready_notifications", "roulette_draws", "order_acceptance_claims",
    "order_acceptance_meta", "order_cancellations", "order_state_history",
    "order_assignments", "worker_payouts", "worker_payout_overrides",
    "customer_service_payouts", "sync_events", "web_order_submission_meta",
    "order_reports", "order_report_reminders", "order_report_reviews",
    "order_review_messages", "order_financial_snapshots", "loyalty_order_events",
    "order_settlement_history", "order_credentials", "order_credential_logs",
})
PROTECTED_LEDGER_TABLES = frozenset({
    "wallet_transactions", "customer_wallets", "admin_audit_logs",
    "one_time_data_repairs", "payment_reviews", "topup_orders",
    "customer_benefit_coupons",
})


def _fail(message: str) -> None:
    raise RuntimeError(f"安全檢查未通過：{message}")


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _tables(conn: sqlite3.Connection, schema: str) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            f"SELECT name FROM {schema}.sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> set[str]:
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*", table):
        _fail(f"invalid SQL table name {table!r}")
    return {
        str(row[1])
        for row in conn.execute(f'PRAGMA {schema}.table_info("{table}")')
    }


def _row(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> dict | None:
    found = conn.execute(sql, args).fetchone()
    return dict(found) if found is not None else None


def _json_dict(text: object) -> dict:
    try:
        result = json.loads(text or "{}")
    except (ValueError, TypeError):
        _fail("VIP / 訂單 JSON 格式錯誤，不能直接修改")
    if not isinstance(result, dict):
        _fail("VIP / 訂單 JSON 不是物件，不能直接修改")
    return result


def _level(total: int) -> tuple[int, str]:
    from core.vip_levels import BASE_MEMBER_LEVELS

    index = 0
    for i, item in enumerate(BASE_MEMBER_LEVELS):
        if total >= int(item["threshold"]):
            index = i
    return index, str(BASE_MEMBER_LEVELS[index]["name"])


def inspect_target(conn: sqlite3.Connection) -> dict:
    web_tables = _tables(conn, "main")
    bot_tables = _tables(conn, "bot")
    if not {"web_orders", "payment_reviews"}.issubset(web_tables):
        _fail("網站資料庫缺少 web_orders 或 payment_reviews")
    if not {"customers", "orders"}.issubset(bot_tables):
        _fail("機器人資料庫缺少 customers 或 orders")

    if not {
        "customer_id", "total_spent", "points", "completed_orders",
        "data_json", "level",
    }.issubset(_columns(conn, "bot", "customers")):
        _fail("機器人會員表結構不符合預期")
    if not {"channel_id", "data_json"}.issubset(_columns(conn, "bot", "orders")):
        _fail("機器人訂單表缺少 channel_id / data_json")

    order = _row(
        conn,
        "SELECT * FROM web_orders WHERE bot_order_no = ?",
        (ORDER_NO,),
    )
    marker = _row(
        conn,
        "SELECT note FROM one_time_data_repairs WHERE repair_key = ?",
        (REPAIR_KEY,),
    ) if "one_time_data_repairs" in web_tables else None
    customer = _row(
        conn, "SELECT * FROM bot.customers WHERE CAST(customer_id AS TEXT) = ?",
        (CUSTOMER_ID,),
    )
    if customer is None:
        _fail(f"找不到指定會員 {CUSTOMER_ID}")

    current_vip = _int(customer["total_spent"])
    if marker:
        if order is not None or current_vip != EXPECTED_VIP_AFTER:
            _fail("修復標記已存在，但訂單 / VIP 尚未符合預期，需人工核對")
        return {
            "state": "already_applied",
            "order_no": ORDER_NO,
            "vip_now": current_vip,
        }

    if order is None:
        _fail("指定網站訂單不存在，且沒有修復標記；不可盲目扣 VIP")
    if str(order.get("customer_discord_id") or "") != CUSTOMER_ID:
        _fail("訂單會員 ID 不符，停止")
    if str(order.get("ticket_channel_id") or "") != TICKET_ID:
        _fail("訂單票口 ID 不符，停止")
    if str(order.get("status") or "").lower() not in {"cancelled", "canceled"}:
        _fail("訂單目前不是已取消狀態，停止")
    if _int(order.get("amount")) != ORDER_PRICE:
        _fail("原始訂單金額不是 3,750T，停止")
    if str(order.get("payment_method") or "").strip() not in {"轉帳", "銀行轉帳"}:
        _fail("這不是預期的轉帳單，禁止誤刪其他付款方式")

    # Confirm the 3000T order stays untouched. Do not infer its VIP credits
    # from its status; only use it as a strong identity/matching guard.
    sibling = _row(
        conn,
        "SELECT bot_order_no, customer_discord_id, amount "
        "FROM web_orders WHERE bot_order_no = ?",
        (SIBLING_ORDER_NO,),
    )
    if (
        sibling is None
        or str(sibling["customer_discord_id"]) != CUSTOMER_ID
        or _int(sibling["amount"]) != EXPECTED_VIP_AFTER
    ):
        _fail("另一張 3,000T 訂單不符合截圖，停止")

    if current_vip not in {EXPECTED_VIP_BEFORE, EXPECTED_VIP_AFTER}:
        _fail(
            f"目前 VIP 為 {current_vip}T，不是 6750/3000T。"
            "可能已有其他消費，不能用舊截圖覆寫"
        )
    customer_data = _json_dict(customer.get("data_json"))
    if bool(customer_data.get("vip_progress_reset_active")):
        _fail("會員有 VIP 重置/降級紀錄，需要先確認基準")
    if current_vip == EXPECTED_VIP_BEFORE and _int(customer.get("completed_orders")) < 1:
        _fail("會員完成單數為 0，但仍有錯誤 VIP 入帳，需人工核對")

    order_id = _int(order["id"])
    reviews = [
        dict(r) for r in conn.execute(
            "SELECT * FROM payment_reviews "
            "WHERE source_type = 'order' AND CAST(source_id AS TEXT) = ?",
            (str(order_id),),
        )
    ]
    for review in reviews:
        if str(review.get("customer_discord_id")) != CUSTOMER_ID:
            _fail("關聯付款審核屬於其他會員")
        if str(review.get("ticket_channel_id") or "") not in {"", TICKET_ID}:
            _fail("關聯付款審核票口不符")

    bot_order = _row(
        conn, "SELECT * FROM bot.orders WHERE CAST(channel_id AS TEXT) = ?",
        (TICKET_ID,),
    )
    if bot_order:
        order_data = _json_dict(bot_order.get("data_json"))
        if order_data.get("order_no") not in (None, "", ORDER_NO):
            _fail("機器人票口已被其他訂單占用")
        if order_data.get("customer_id") not in (None, "", int(CUSTOMER_ID), CUSTOMER_ID):
            _fail("機器人票口會員不一致")
        if order_data.get("web_order_id") not in (None, "", order_id, str(order_id)):
            _fail("機器人票口網站訂單 ID 不符")

    # Guard against reversing real wallet transactions while deleting a
    # mistakenly-approved transfer review. No wallet balance is modified.
    if "wallet_transactions" in bot_tables:
        cols = _columns(conn, "bot", "wallet_transactions")
        checks = []
        args: list[str] = []
        if "order_no" in cols:
            checks.append("CAST(order_no AS TEXT) = ?")
            args.append(ORDER_NO)
        if "order_channel_id" in cols:
            checks.append("CAST(order_channel_id AS TEXT) = ?")
            args.append(TICKET_ID)
        if checks and conn.execute(
            "SELECT 1 FROM bot.wallet_transactions WHERE "
            + " OR ".join(checks) + " LIMIT 1",
            args,
        ).fetchone():
            _fail("偵測到實際錢包流水，不能用轉帳誤審清理流程")

    # Every order_id reference must be either an explicitly approved child or
    # protected ledger/audit. Unknown references fail closed instead of leaving
    # dangling business data, and can be reviewed before changing this script.
    children: dict[str, int] = {}
    for table in web_tables:
        if table in {"web_orders", "sqlite_sequence"}:
            continue
        columns = _columns(conn, "main", table)
        if "order_id" not in columns:
            continue
        count = _int(conn.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE order_id = ?',
            (order_id,),
        ).fetchone()[0])
        if count and table not in ORDER_CHILD_TABLES:
            _fail(f"未列入安全清單的關聯資料表 {table} 有 {count} 筆，不能直接刪除")
        if count:
            children[table] = count

    if "customer_benefit_coupons" in web_tables:
        cols = _columns(conn, "main", "customer_benefit_coupons")
        for column in ("reserved_order_id", "redeemed_order_id"):
            if column in cols and conn.execute(
                f'SELECT 1 FROM customer_benefit_coupons WHERE "{column}" = ? LIMIT 1',
                (order_id,),
            ).fetchone():
                _fail("訂單仍關聯已保留/使用的福利券，須先復原福利，不能直接刪")

    point_adjustment = _int(customer.get("points")) - (current_vip // 100)
    new_points = max(0, EXPECTED_VIP_AFTER // 100 + point_adjustment)
    new_count = _int(customer.get("completed_orders")) - (
        1 if current_vip == EXPECTED_VIP_BEFORE else 0
    )

    return {
        "state": "ready",
        "order_id": order_id,
        "order_no": ORDER_NO,
        "customer": CUSTOMER_ID,
        "ticket": TICKET_ID,
        "vip_before": current_vip,
        "vip_after": EXPECTED_VIP_AFTER,
        "points_before": _int(customer.get("points")),
        "points_after": new_points,
        "completed_before": _int(customer.get("completed_orders")),
        "completed_after": new_count,
        "child_rows": children,
        "reviews": [str(r.get("review_no") or r.get("id")) for r in reviews],
        "bot_order_exists": bot_order is not None,
        "existing_customer": customer_data,
    }


def apply_target(conn: sqlite3.Connection, plan: dict) -> dict:
    if plan["state"] != "ready":
        return plan

    import json as _json

    order_id = plan["order_id"]
    customer_data = dict(plan["existing_customer"])
    level_index, level_name = _level(plan["vip_after"])
    customer_data.update({
        "total_spent": plan["vip_after"],
        "points": plan["points_after"],
        "point_adjustment": plan["points_before"] - plan["vip_before"] // 100,
        "order_count": plan["completed_after"],
        "vip_level_index": level_index,
        "vip_progress_base_total_spent": None,
        "vip_progress_reset_active": False,
    })
    conn.execute(
        "UPDATE bot.customers SET "
        "total_spent=?, points=?, completed_orders=?, level=?, "
        "data_json=?, updated_at=? WHERE CAST(customer_id AS TEXT)=?",
        (
            plan["vip_after"], plan["points_after"], plan["completed_after"],
            level_name, _json.dumps(customer_data, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            CUSTOMER_ID,
        ),
    )

    # Bot-side historic order is deleted only for this exact ticket.
    conn.execute(
        "DELETE FROM bot.orders WHERE CAST(channel_id AS TEXT) = ?",
        (TICKET_ID,),
    )

    # Remove stale Discord claim-state for this order, if any. Claim matching
    # is strict on dispatch id and customer/ticket reference.
    claims = _tables(conn, "bot")
    if "claims" in claims:
        cols = _columns(conn, "bot", "claims")
        if {"dispatch_message_id", "source_channel_id"}.issubset(cols):
            conn.execute(
                "DELETE FROM bot.claims WHERE CAST(source_channel_id AS TEXT)=?",
                (TICKET_ID,),
            )

    for table in plan["child_rows"]:
        conn.execute(
            f'DELETE FROM "{table}" WHERE order_id = ?',
            (order_id,),
        )
    conn.execute(
        "DELETE FROM payment_reviews WHERE source_type='order' "
        "AND CAST(source_id AS TEXT) = ?",
        (str(order_id),),
    )
    conn.execute(
        "DELETE FROM web_orders WHERE id = ? AND bot_order_no = ?",
        (order_id, ORDER_NO),
    )

    # Auditable, idempotent repair marker, deliberately NOT included in the
    # normal customer order or payment listing.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS one_time_data_repairs ("
        "repair_key TEXT PRIMARY KEY, applied_at TEXT NOT NULL, note TEXT)"
    )
    note = {k: v for k, v in plan.items() if k != "existing_customer"}
    conn.execute(
        "INSERT INTO one_time_data_repairs "
        "(repair_key, applied_at, note) VALUES (?, ?, ?)",
        (
            REPAIR_KEY,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            _json.dumps(note, ensure_ascii=False),
        ),
    )

    check = _row(
        conn, "SELECT total_spent, points FROM bot.customers "
        "WHERE CAST(customer_id AS TEXT)=?", (CUSTOMER_ID,),
    )
    if not check or _int(check["total_spent"]) != EXPECTED_VIP_AFTER:
        _fail("會員更新後未達 3,000T，交易回滾")
    if conn.execute(
        "SELECT 1 FROM web_orders WHERE bot_order_no=?", (ORDER_NO,)
    ).fetchone():
        _fail("指定網站訂單仍存在，交易回滾")

    return {
        "state": "applied", "order_no": ORDER_NO,
        "vip_before": plan["vip_before"], "vip_after": plan["vip_after"],
        "points_before": plan["points_before"], "points_after": plan["points_after"],
        "completed_before": plan["completed_before"],
        "completed_after": plan["completed_after"],
        "payment_reviews_deleted": len(plan["reviews"]),
        "web_children_deleted": sum(plan["child_rows"].values()),
    }


def backup_databases(root: Path) -> Path:
    folder = root / "_archive" / (
        "owner_order_purge_MO20261108003_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    folder.mkdir(parents=True, exist_ok=False)
    for filename in ("web_dashboard.db", "bot.db"):
        source = sqlite3.connect(str(root / filename))
        try:
            dest = sqlite3.connect(str(folder / filename))
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()
    return folder


def execute(*, root: Path, apply: bool = False) -> dict:
    web_path, bot_path = root / "web_dashboard.db", root / "bot.db"
    if not web_path.is_file() or not bot_path.is_file():
        _fail("網站或機器人資料庫不存在")
    if apply and os.environ.get("MW_ORDER_REPAIR_MAINTENANCE") != "1":
        _fail("必須透過停機維護腳本執行，避免 Bot 記憶體把 VIP 寫回")
    if apply and not os.access(root / "_archive", os.W_OK):
        # _archive may be absent on fresh test environments.
        (root / "_archive").mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(web_path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("ATTACH DATABASE ? AS bot", (str(bot_path),))
        if apply:
            conn.execute("BEGIN IMMEDIATE")
        plan = inspect_target(conn)
        public_plan = {k: v for k, v in plan.items() if k != "existing_customer"}
        if not apply or plan["state"] != "ready":
            if apply:
                conn.rollback()
            return public_plan
        # Snapshot while services are stopped, before any write.
        backup = backup_databases(root)
        output = apply_target(conn, plan)
        conn.commit()
        output["backup"] = str(backup)
        return output
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        summary = execute(root=args.root.resolve(), apply=args.apply)
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
