#!/usr/bin/env python3
"""Audit and safely reverse VIP rewards from internal wash/AW orders.

Default: READ-ONLY preview. --apply requires Bot/Web stopped and performs
a point-in-time SQLite backup, then a single, guarded transaction. Business
order amounts, salaries, wallet balances, and top-up transactions are intact.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.vip_levels import BASE_MEMBER_LEVELS, has_active_vip_progress_reset
from services.internal_non_vip_policy import INTERNAL_NO_VIP_REASON, is_internal_non_vip_order

SERVICE_NAMES = ("dc-bot.service", "dc-bot-dashboard.service")
TAIPEI = ZoneInfo("Asia/Taipei")
MARKER = "internal_non_vip_history_repaired_at"


def _number(value, field: str) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"缺少有效數字：{field}")
    result = int(value)
    if result < 0:
        raise ValueError(f"不可為負數：{field}")
    return result


def _json_object(raw: object, identity: str) -> dict:
    try:
        data = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON 無法解析：{identity}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"JSON 不是物件：{identity}")
    return data


def _level(total: int) -> tuple[int, str]:
    result = (0, BASE_MEMBER_LEVELS[0]["name"])
    for i, level in enumerate(BASE_MEMBER_LEVELS):
        if total >= int(level["threshold"]):
            result = (i, str(level["name"]))
        else:
            break
    return result


def build_plan(orders: list[dict], customers: list[dict]) -> dict:
    """Pure audit plan: rejects unverifiable amounts, mismatched IDs and balances."""
    customer_map = {int(row["customer_id"]): dict(row) for row in customers}
    candidates: list[dict] = []
    groups: dict[int, dict] = defaultdict(lambda: {"vip": 0, "wallet": 0, "orders": 0})
    blockers: list[str] = []
    scanned = 0

    for row in orders:
        channel = str(row["channel_id"])
        order = _json_object(row["data_json"], f"orders:{channel}")
        if row.get("category") is not None:
            order["category"] = row["category"]
        if not is_internal_non_vip_order(order):
            continue
        scanned += 1
        if order.get(MARKER):
            continue

        counted = order.get("reward_counted") is True
        excluded = order.get("reward_excluded") is True
        reward_raw = order.get("reward_amount")
        wallet_counted = order.get("wallet_points_counted") is True
        wallet_raw = order.get("wallet_point_amount", 0)

        # Do not invent VIP charges from a sale price; only recorded reward ledger.
        if counted and not excluded and reward_raw is None:
            blockers.append(f"票口 {channel} 已標記入帳，但缺少 reward_amount")
            continue
        if reward_raw is not None:
            try:
                recorded_vip = _number(reward_raw, f"{channel}.reward_amount")
            except (ValueError, TypeError):
                blockers.append(f"票口 {channel} 的 VIP 入帳金額不明")
                continue
        else:
            recorded_vip = 0
        if recorded_vip and not counted:
            blockers.append(f"票口 {channel} 有 VIP 金額，但未標記 reward_counted")
            continue
        if recorded_vip and order.get("reward_cancel_reconciled"):
            blockers.append(f"票口 {channel} 已取消對帳卻仍有正數 VIP 記錄")
            continue

        vip = recorded_vip if counted and not excluded else 0
        try:
            wallet = _number(wallet_raw, f"{channel}.wallet_point_amount") if wallet_counted else 0
        except (ValueError, TypeError):
            blockers.append(f"票口 {channel} 的錢包點數入帳金額不明")
            continue
        if not vip and not wallet:
            continue

        raw_user = row.get("customer_id") or order.get("customer_id")
        try:
            customer_id = _number(raw_user, f"{channel}.customer_id")
            if not customer_id:
                raise ValueError("missing")
        except (ValueError, TypeError):
            blockers.append(f"票口 {channel} 缺少會員 ID")
            continue
        if order.get("customer_id") not in (None, "", str(customer_id), customer_id):
            blockers.append(f"票口 {channel} 的訂單會員與資料表不一致")
            continue
        if customer_id not in customer_map:
            blockers.append(f"票口 {channel} 找不到會員 {customer_id}")
            continue

        groups[customer_id]["vip"] += vip
        groups[customer_id]["wallet"] += wallet
        groups[customer_id]["orders"] += 1
        candidates.append({
            "channel": channel, "customer": customer_id,
            "vip": vip, "wallet": wallet,
            "order_no": str(order.get("order_no") or ""),
            "rule_key": str(order.get("order_rule_key") or ""),
            "old_json": row["data_json"], "data": order,
        })

    changes: list[dict] = []
    for customer_id, amounts in sorted(groups.items()):
        row = customer_map[customer_id]
        customer_data = _json_object(row["data_json"], f"customers:{customer_id}")
        try:
            old_total = _number(row["total_spent"], "customers.total_spent")
            old_points = _number(row["points"], "customers.points")
            vip = amounts["vip"]
            wallet = amounts["wallet"]
            old_wallet = _number(
                customer_data.get("wallet_point_spend_total", 0),
                "customers.wallet_point_spend_total",
            )
        except (ValueError, TypeError) as exc:
            blockers.append(f"會員 {customer_id} 的累積數字異常：{exc}")
            continue
        if vip > old_total or wallet > old_wallet:
            blockers.append(
                f"會員 {customer_id} 入帳扣回超過目前累積："
                f"VIP={vip}/{old_total}, wallet={wallet}/{old_wallet}"
            )
            continue

        new_total = old_total - vip
        new_wallet = old_wallet - wallet
        point_delta = (
            new_total // 100 - old_total // 100
            + new_wallet // 100 - old_wallet // 100
        )
        new_points = max(0, old_points + point_delta)
        new_level_index, new_level_name = _level(new_total)
        old_level_index, old_level_name = _level(old_total)
        if has_active_vip_progress_reset(customer_data):
            # Manual VIP resets have an independent progress baseline. Do not
            # overwrite it, but ensure the monetary source is still corrected.
            stored_index = customer_data.get("vip_level_index")
            if stored_index is not None:
                try:
                    new_level_index = int(stored_index)
                    new_level_name = str(BASE_MEMBER_LEVELS[new_level_index]["name"])
                except (ValueError, TypeError, IndexError):
                    blockers.append(f"會員 {customer_id} 的手動 VIP 等級異常")
                    continue

        customer_data["total_spent"] = new_total
        customer_data["wallet_point_spend_total"] = new_wallet
        customer_data["point_adjustment"] = new_points - new_total // 100
        customer_data["points"] = new_points
        if not has_active_vip_progress_reset(customer_data):
            customer_data["vip_level_index"] = new_level_index
            customer_data["vip_progress_base_total_spent"] = None
            customer_data["vip_progress_reset_active"] = False
        if new_level_name != row.get("level"):
            customer_data["vip_internal_exclusion_role_sync_pending"] = True
        changes.append({
            "customer": customer_id, "vip": vip, "wallet": wallet,
            "count": amounts["orders"],
            "before": old_total, "after": new_total,
            "before_points": old_points, "after_points": new_points,
            "level_before": row.get("level") or old_level_name,
            "level_after": new_level_name,
            "old_customer": row, "new_data": customer_data,
        })

    return {
        "scanned": scanned,
        "candidates": candidates,
        "changes": changes,
        "blockers": blockers,
    }


def read_plan(conn: sqlite3.Connection) -> dict:
    conn.row_factory = sqlite3.Row
    # Require canonical normalized tables. Old/unknown schemas are manual-review only.
    for table, columns in (
        ("orders", {"channel_id", "category", "customer_id", "data_json"}),
        ("customers", {"customer_id", "total_spent", "points", "level", "data_json"}),
    ):
        actual = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not columns.issubset(actual):
            raise RuntimeError(f"資料庫表結構不符合預期：{table} missing {sorted(columns - actual)}")
    orders = [
        dict(row) for row in conn.execute(
            "SELECT channel_id, category, customer_id, data_json FROM orders"
        )
    ]
    customers = [
        dict(row) for row in conn.execute(
            "SELECT customer_id, total_spent, points, level, data_json FROM customers"
        )
    ]
    return build_plan(orders, customers)


def _services_stopped() -> bool:
    for name in SERVICE_NAMES:
        try:
            result = subprocess.run(["systemctl", "is-active", "--quiet", name], check=False)
        except OSError:
            return False
        if result.returncode == 0:
            return False
    return True


def _backup(db_path: Path) -> Path:
    stamp = datetime.now(TAIPEI).strftime("%Y%m%d_%H%M%S")
    folder = db_path.parent / "_archive" / f"staff_internal_vip_{stamp}"
    folder.mkdir(parents=True, exist_ok=False)
    backup = folder / "bot.db"
    with sqlite3.connect(db_path) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    return backup


def repair(db_path: Path, *, apply: bool = False) -> dict:
    if not db_path.is_file():
        raise FileNotFoundError(f"找不到 bot.db: {db_path}")
    with sqlite3.connect(db_path, timeout=30) as conn:
        plan = read_plan(conn)
    print(f"內部單掃描 {plan['scanned']} 筆；待更正 {len(plan['candidates'])} 筆；"
          f"受影響會員 {len(plan['changes'])} 位")
    for change in plan["changes"]:
        print(
            f"會員 {change['customer']} | 訂單 {change['count']} | "
            f"VIP -{change['vip']}T ({change['before']} -> {change['after']}) | "
            f"點數 {change['before_points']} -> {change['after_points']} | "
            f"VIP {change['level_before']} -> {change['level_after']} | "
            f"錢包點數消費額 -{change['wallet']}T"
        )
    for item in plan["candidates"]:
        print(
            f"  訂單 {item['order_no'] or item['channel']} | "
            f"rule={item['rule_key'] or 'legacy category'} | "
            f"VIP -{item['vip']}T | wallet point spending -{item['wallet']}T"
        )
    for error in plan["blockers"]:
        print("需人工核對，不可自動扣回：", error)
    if not apply:
        print("DRY-RUN：未修改資料。需核對明細後再使用 --apply。")
        return plan
    if plan["blockers"]:
        raise RuntimeError("存在無法驗證的舊訂單，為避免誤扣，整批未執行")
    if not _services_stopped():
        raise RuntimeError("Bot/Web 服務未確認全部停止，不可修改上線資料庫")
    if not plan["candidates"]:
        print("沒有尚未修正的內部單；不需修改。")
        return plan

    backup = _backup(db_path)
    print(f"完成 SQLite 線上安全備份：{backup}")
    timestamp = datetime.now(TAIPEI).isoformat(timespec="seconds")
    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.execute("BEGIN IMMEDIATE")
        # Fail closed on any concurrent or between-preview change.
        current = read_plan(conn)
        original_ids = [(x["channel"], x["vip"], x["wallet"]) for x in plan["candidates"]]
        current_ids = [(x["channel"], x["vip"], x["wallet"]) for x in current["candidates"]]
        if current_ids != original_ids or current["blockers"]:
            raise RuntimeError("資料在預覽後已變更，取消扣回")
        for item in plan["candidates"]:
            data = dict(item["data"])
            data[MARKER] = timestamp
            data["vip_internal_exclusion_reversed_amount"] = item["vip"]
            data["vip_internal_exclusion_reversed_wallet_amount"] = item["wallet"]
            data["reward_excluded"] = True
            data["reward_amount"] = 0
            data["reward_excluded_reason"] = INTERNAL_NO_VIP_REASON
            if item["wallet"]:
                data["wallet_point_amount"] = 0
                data["wallet_points_awarded"] = 0
            cur = conn.execute(
                "UPDATE orders SET data_json=? WHERE channel_id=? AND data_json=?",
                (json.dumps(data, ensure_ascii=False), item["channel"], item["old_json"]),
            )
            if cur.rowcount != 1:
                raise RuntimeError(f"票口 {item['channel']} 資料已更動")
        for change in plan["changes"]:
            old = change["old_customer"]
            cur = conn.execute(
                "UPDATE customers SET total_spent=?, points=?, level=?, data_json=? "
                "WHERE customer_id=? AND total_spent=? AND points=? AND data_json=?",
                (
                    change["after"], change["after_points"], change["level_after"],
                    json.dumps(change["new_data"], ensure_ascii=False),
                    change["customer"], old["total_spent"], old["points"], old["data_json"],
                ),
            )
            if cur.rowcount != 1:
                raise RuntimeError(f"會員 {change['customer']} 資料已更動")
        conn.commit()
    print(f"APPLIED：已修正 {len(plan['candidates'])} 筆內部單；備份 {backup}")
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "bot.db")
    parser.add_argument("--apply", action="store_true", help="Requires Bot and Web stopped")
    args = parser.parse_args()
    try:
        repair(args.db.resolve(), apply=args.apply)
        return 0
    except (RuntimeError, ValueError, FileNotFoundError, sqlite3.DatabaseError) as exc:
        print(f"FAIL：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
