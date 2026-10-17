from __future__ import annotations

import discord

from services.logging_service import send_order_log
from services.rewards import format_t_amount
from services.wallet_service import adjust_wallet_balance


def adjust_customer_wallet_balance(
    *,
    customer_id,
    amount: int,
    tx_type: str,
    operator=None,
    order_channel_id=None,
    order_no=None,
    note: str | None = None,
    allow_negative: bool = False,
) -> dict:
    """Discord-facing adapter around the canonical wallet transaction service."""
    operator_id = getattr(operator, "id", None)
    operator_name = (
        getattr(operator, "display_name", None)
        or getattr(operator, "name", None)
        or (str(operator_id) if operator_id is not None else None)
    )
    normalized_type = str(tx_type or "adjustment").strip() or "adjustment"
    return adjust_wallet_balance(
        customer_id=customer_id,
        amount=amount,
        tx_type=normalized_type,
        operator_discord_id=operator_id,
        operator_display_name=operator_name,
        order_channel_id=order_channel_id,
        order_no=order_no,
        note=note,
        allow_negative=allow_negative,
    )


async def send_wallet_log(
    guild: discord.Guild | None,
    *,
    title: str,
    customer: discord.Member,
    operator: discord.Member | discord.User,
    tx: dict,
) -> None:
    try:
        await send_order_log(
            guild,
            title=title,
            fields=[
                ("顧客", customer.mention, True),
                ("操作人員", getattr(operator, "mention", str(getattr(operator, "id", "未知"))), True),
                ("異動金額", format_t_amount(int(tx["amount"])), True),
                ("原餘額", format_t_amount(int(tx["balance_before"])), True),
                ("新餘額", format_t_amount(int(tx["balance_after"])), True),
                ("備註", str(tx.get("note") or "未填寫"), False),
            ],
            color=discord.Color.gold(),
        )
    except Exception as exc:
        print(f"錢包日誌送出失敗：{exc}")
