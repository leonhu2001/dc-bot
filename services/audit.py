from __future__ import annotations

import discord

from core.time_utils import get_taipei_now
from services.orders import _to_int, get_order_amount_for_maintenance

_ORDER_SELECTIONS: dict[int, dict] = {}
_ORDER_CLAIMS: dict[int, dict] = {}
_CUSTOMER_REWARDS: dict[int, dict] = {}


def configure_audit_service(order_selections: dict, order_claims: dict, customer_rewards: dict) -> None:
    global _ORDER_SELECTIONS, _ORDER_CLAIMS, _CUSTOMER_REWARDS
    _ORDER_SELECTIONS = order_selections
    _ORDER_CLAIMS = order_claims
    _CUSTOMER_REWARDS = customer_rewards



def audit_amount_text(amount) -> str:
    """Format money for /audit_data.

    This function is intentionally local to the audit block and does not depend on
    reward-service helpers, so /audit_data will not break during modularization.
    """
    try:
        value = int(amount or 0)
    except (TypeError, ValueError):
        return f"{amount}T"
    return f"{value:,}T"


def _audit_order_status(data: dict) -> str:
    return str(data.get("status") or ("closed" if data.get("closed") else "active")).lower()


def _audit_order_amount(data: dict) -> int:
    return get_order_amount_for_maintenance(data)


def _audit_closed_orders_by_customer() -> dict[int, dict]:
    totals: dict[int, dict] = {}

    for channel_id, data in _ORDER_SELECTIONS.items():
        if not isinstance(data, dict):
            continue

        if _audit_order_status(data) != "closed" and not data.get("closed"):
            continue

        customer_id = _to_int(data.get("customer_id"))
        if customer_id is None:
            continue

        bucket = totals.setdefault(
            customer_id,
            {
                "amount": 0,
                "quantity": 0,
                "orders": 0,
                "channel_ids": [],
            }
        )
        bucket["amount"] += _audit_order_amount(data)
        bucket["quantity"] += _to_int(data.get("quantity"), 1) or 1
        bucket["orders"] += 1
        bucket["channel_ids"].append(channel_id)

    return totals


def build_audit_data_report(limit: int = 10) -> tuple[discord.Embed, str]:
    safe_limit = max(1, min(int(limit or 10), 25))
    closed_totals = _audit_closed_orders_by_customer()

    customer_mismatches = []
    checked_customer_ids = set(_CUSTOMER_REWARDS.keys()) | set(closed_totals.keys())

    for customer_id in sorted(checked_customer_ids):
        customer_data = _CUSTOMER_REWARDS.get(customer_id, {})
        if not isinstance(customer_data, dict):
            customer_data = {}

        customer_total = int(customer_data.get("total_spent", 0) or 0)
        customer_order_count = int(customer_data.get("order_count", 0) or 0)
        order_bucket = closed_totals.get(customer_id, {"amount": 0, "quantity": 0, "orders": 0})
        closed_amount = int(order_bucket.get("amount", 0) or 0)
        closed_quantity = int(order_bucket.get("quantity", 0) or 0)

        amount_diff = customer_total - closed_amount
        count_diff = customer_order_count - closed_quantity

        if amount_diff != 0 or count_diff != 0:
            customer_mismatches.append({
                "customer_id": customer_id,
                "customer_total": customer_total,
                "closed_amount": closed_amount,
                "amount_diff": amount_diff,
                "customer_order_count": customer_order_count,
                "closed_quantity": closed_quantity,
                "count_diff": count_diff,
            })

    closed_zero_orders = []
    missing_customer_orders = []
    stored_orders = []
    active_orders = []
    reward_not_counted_closed = []
    duplicate_order_nos: dict[str, list[int]] = {}
    duplicate_dispatch_ids: dict[int, list[int]] = {}
    orphan_claims = []

    known_order_channels = set(_ORDER_SELECTIONS.keys())

    for channel_id, data in _ORDER_SELECTIONS.items():
        if not isinstance(data, dict):
            continue

        status = _audit_order_status(data)
        amount = _audit_order_amount(data)
        order_no = str(data.get("order_no") or data.get("receipt_id") or "").strip()
        dispatch_message_id = _to_int(data.get("dispatch_message_id"))

        if order_no:
            duplicate_order_nos.setdefault(order_no, []).append(int(channel_id))
        if dispatch_message_id is not None:
            duplicate_dispatch_ids.setdefault(dispatch_message_id, []).append(int(channel_id))

        if status == "closed" or data.get("closed"):
            if amount <= 0:
                closed_zero_orders.append((channel_id, data))
            if not data.get("reward_counted"):
                reward_not_counted_closed.append((channel_id, data))

        if _to_int(data.get("customer_id")) is None:
            missing_customer_orders.append((channel_id, data))

        if status == "stored":
            stored_orders.append((channel_id, data))
        elif status == "active":
            active_orders.append((channel_id, data))

    for message_id, claim in _ORDER_CLAIMS.items():
        if not isinstance(claim, dict):
            continue
        source_channel_id = _to_int(claim.get("source_channel_id"))
        if source_channel_id is None or source_channel_id not in known_order_channels:
            orphan_claims.append((message_id, claim))

    duplicated_order_nos = {k: v for k, v in duplicate_order_nos.items() if len(v) > 1}
    duplicated_dispatch_ids = {k: v for k, v in duplicate_dispatch_ids.items() if len(v) > 1}

    summary_lines = [
        "資料庫健康檢查完成。",
        f"總訂單暫存：{len(_ORDER_SELECTIONS):,} 筆",
        f"顧客資料：{len(_CUSTOMER_REWARDS):,} 筆",
        f"接單面板 claims：{len(_ORDER_CLAIMS):,} 筆",
        "",
        f"會員 / 已結訂單對帳異常：{len(customer_mismatches):,} 筆",
        f"已結單金額為 0：{len(closed_zero_orders):,} 筆",
        f"缺少 customer_id 訂單：{len(missing_customer_orders):,} 筆",
        f"存單：{len(stored_orders):,} 筆",
        f"進行中訂單：{len(active_orders):,} 筆",
        f"已結但未標記 reward_counted：{len(reward_not_counted_closed):,} 筆",
        f"重複訂單編號：{len(duplicated_order_nos):,} 組",
        f"重複派單訊息 ID：{len(duplicated_dispatch_ids):,} 組",
        f"找不到來源訂單的 claims：{len(orphan_claims):,} 筆",
    ]

    detail_lines = []

    def order_line(channel_id: int, data: dict) -> str:
        order_no = data.get("order_no") or data.get("receipt_id") or "未產生"
        customer_id = data.get("customer_id")
        customer_text = f"<@{customer_id}>" if customer_id else "未紀錄"
        item = data.get("item") or "未紀錄"
        amount = _audit_order_amount(data)
        status = _audit_order_status(data)
        return f"{order_no}｜票口 {channel_id}｜{customer_text}｜{item}｜{audit_amount_text(amount)}｜{status}"

    if customer_mismatches:
        detail_lines.append("\n【會員 / 已結訂單對帳異常】")
        for item in customer_mismatches[:safe_limit]:
            detail_lines.append(
                f"<@{item['customer_id']}>｜會員累積 {audit_amount_text(item['customer_total'])} / "
                f"已結訂單 {audit_amount_text(item['closed_amount'])} / 差額 {audit_amount_text(item['amount_diff'])}｜"
                f"會員單數 {item['customer_order_count']} / 已結數量 {item['closed_quantity']} / 差 {item['count_diff']}"
            )
        if len(customer_mismatches) > safe_limit:
            detail_lines.append(f"…還有 {len(customer_mismatches) - safe_limit} 筆")

    for title, rows in [
        ("已結單金額為 0", closed_zero_orders),
        ("缺少 customer_id 訂單", missing_customer_orders),
        ("存單", stored_orders),
        ("已結但未標記 reward_counted", reward_not_counted_closed),
    ]:
        if rows:
            detail_lines.append(f"\n【{title}】")
            for channel_id, data in rows[:safe_limit]:
                detail_lines.append(order_line(channel_id, data))
            if len(rows) > safe_limit:
                detail_lines.append(f"…還有 {len(rows) - safe_limit} 筆")

    if duplicated_order_nos:
        detail_lines.append("\n【重複訂單編號】")
        for order_no, channel_ids in list(duplicated_order_nos.items())[:safe_limit]:
            detail_lines.append(f"{order_no}｜票口：{', '.join(str(cid) for cid in channel_ids)}")

    if duplicated_dispatch_ids:
        detail_lines.append("\n【重複派單訊息 ID】")
        for message_id, channel_ids in list(duplicated_dispatch_ids.items())[:safe_limit]:
            detail_lines.append(f"{message_id}｜票口：{', '.join(str(cid) for cid in channel_ids)}")

    if orphan_claims:
        detail_lines.append("\n【找不到來源訂單的 claims】")
        for message_id, claim in orphan_claims[:safe_limit]:
            detail_lines.append(f"派單訊息 {message_id}｜來源票口：{claim.get('source_channel_id') or '未紀錄'}｜項目：{claim.get('item') or '未紀錄'}")

    full_report = "\n".join(summary_lines + detail_lines)

    has_problem = any([
        customer_mismatches,
        closed_zero_orders,
        missing_customer_orders,
        reward_not_counted_closed,
        duplicated_order_nos,
        duplicated_dispatch_ids,
        orphan_claims,
    ])

    embed = discord.Embed(
        title="資料庫健康檢查",
        description="\n".join(summary_lines),
        color=discord.Color.orange() if has_problem else discord.Color.green(),
        timestamp=get_taipei_now(),
    )
    embed.set_footer(text=f"明細上限：每類 {safe_limit} 筆。完整內容會在訊息或附件中提供。")

    return embed, full_report


