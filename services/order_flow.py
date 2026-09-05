from __future__ import annotations

import discord

from services.rewards import format_t_amount


def get_payment_method_info(method: str | None) -> str | None:
    return {
        "轉帳": (
            "銀行轉帳-國泰\n"
            "代碼：013\n"
            "帳號：135700021419"
        ),
        "街口": (
            "街口支付\n"
            "代碼：396\n"
            "帳號：900884222"
        ),
    }.get(str(method or ""))


def build_payment_method_embed(
    *,
    customer_id: int,
    category_label: str,
    item: str,
    quantity: int,
    payment_method: str | None = None,
    companion_preference: str | None = None,
    amount: int | None = None,
    submitted: bool = False,
    dispatch_url: str | None = None,
) -> discord.Embed:
    payment_info = get_payment_method_info(payment_method)
    amount_text = format_t_amount(amount) if amount else "待客服填寫"
    description = (
        f"下單用戶：<@{customer_id}>\n\n"
        f"訂單類別：{category_label}\n"
        f"訂單項目：{item}\n"
        f"數量：{quantity} 單\n"
        f"訂單總價：{amount_text}\n"
        f"付款方式：{payment_method or '尚未選擇'}\n"
    )

    if submitted and dispatch_url:
        description += "\n✅ 已送出派單，此付款面板已鎖定，請勿重複操作。\n"
        description += f"派單訊息：{dispatch_url}"
    elif amount and payment_info:
        description += "\n請闆闆確認總價與付款資訊，選擇付款方式後按「送出」。"
    else:
        description += "\n請選擇付款方式，完成後按「送出」。"

    embed = discord.Embed(
        title="付款方式",
        description=description,
        color=discord.Color.green() if submitted else discord.Color.gold(),
    )

    if companion_preference is not None:
        embed.add_field(name="指定選項", value=companion_preference, inline=False)

    if amount and payment_info:
        embed.add_field(name="付款資訊", value=f"```text\n{payment_info}\n```", inline=False)

    return embed
