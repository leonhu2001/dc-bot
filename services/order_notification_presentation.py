from __future__ import annotations

import discord


def cancellation_reason_label(reason_code: str | None, options) -> str:
    mapping = {str(code): str(label) for code, label in (options or ())}
    code = str(reason_code or "").strip()
    return mapping.get(code, code or "未填寫")


def build_cancelled_order_notice(reason_label: str | None) -> str:
    reason = str(reason_label or "未填寫").strip() or "未填寫"
    return (
        "⛔ **已取消｜訂單已停止**\n"
        f"原因：{reason}\n"
        "派單訊息將同步移除；票口 3 秒後關閉。"
    )


def worker_change_marker(order_id: int, event_id: int) -> str:
    return f"WEB-{int(order_id)}｜人員異動｜EVENT-{int(event_id)}"


def build_worker_change_embed(
    *,
    order_id: int,
    event_id: int,
    action: str,
    worker_mention: str,
) -> discord.Embed:
    normalized_action = str(action or "").strip().lower()
    is_added = normalized_action in {"added", "add", "claimed", "admin_added_worker"}
    title = "🔄 人員異動｜已加入服務人員" if is_added else "🔄 人員異動｜已移除服務人員"
    description = (
        f"訂單：**WEB-{int(order_id)}**\n"
        f"人員：{str(worker_mention or '未紀錄')}\n"
        "派單卡與票口權限已同步更新。"
    )
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.blue() if is_added else discord.Color.orange(),
    )
    embed.set_footer(text=worker_change_marker(order_id, event_id))
    return embed


def build_payment_approved_notice(
    *,
    customer_id: int,
    payment_method: str | None,
    amount: int,
) -> str:
    return (
        f"<@{int(customer_id)}> ✅ **付款完成｜訂單已成立**\n"
        f"付款方式：**{str(payment_method or '未紀錄')}**｜金額：**{int(amount or 0):,}T**\n"
        "客服已確認收款，訂單已進入進行中。"
    )


def build_payment_rejected_notice(
    *,
    customer_id: int,
    reason: str | None,
) -> str:
    reason_text = str(reason or "客服未確認到款項").strip() or "客服未確認到款項"
    return (
        f"<@{int(customer_id)}> ⚠️ **付款異常｜審核未通過**\n"
        f"原因：{reason_text}\n\n"
        "請確認付款資訊／付款截圖後，再從付款面板重新送出審核。"
    )


def build_payment_apply_error_notice(
    *,
    customer_id: int | None,
    error_text: str | None,
) -> str:
    mention = f"<@{int(customer_id)}> " if customer_id else ""
    detail = str(error_text or "付款結果同步失敗").strip() or "付款結果同步失敗"
    return (
        f"{mention}⚠️ **付款異常｜需要客服處理**\n"
        "付款審核結果已收到，但訂單狀態同步失敗。\n"
        f"系統訊息：{detail}\n"
        "請客服確認後台訂單狀態；確認前請勿重複套用付款。"
    )
