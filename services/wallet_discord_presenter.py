from __future__ import annotations

import discord

from services.rewards import (
    build_member_info_embed,
    format_customer_notes_for_staff,
    format_t_amount,
    get_customer_reward_data,
)
from services.wallet_service import get_wallet_balance, get_wallet_transactions


def wallet_transaction_type_label(tx_type: str) -> str:
    mapping = {
        "topup": "儲值",
        "payment": "訂單扣款",
        "tip_payment": "雞腿扣款",
        "refund": "退款",
        "adjustment": "修正",
    }
    return mapping.get(str(tx_type or "").strip(), str(tx_type or "未知"))


def build_customer_info_with_wallet_embed(
    member: discord.Member,
    *,
    show_staff_notes: bool = True,
) -> discord.Embed:
    data = get_customer_reward_data(member.id)
    embed = build_member_info_embed(member, data, show_points=True)

    wallet_balance = get_wallet_balance(member.id)
    embed.add_field(
        name="錢包餘額",
        value=format_t_amount(wallet_balance),
        inline=True,
    )

    if show_staff_notes:
        note_text = format_customer_notes_for_staff(member.id)
        if note_text:
            embed.add_field(
                name="客服備註",
                value=note_text[:1024],
                inline=False,
            )

    return embed


def wallet_transaction_history(customer_id, limit: int = 10) -> list[dict]:
    return get_wallet_transactions(customer_id, limit=limit)


def build_wallet_history_embed(
    customer: discord.Member | discord.User,
    *,
    limit: int = 10,
    staff_view: bool = False,
) -> discord.Embed:
    balance = get_wallet_balance(customer.id)
    transactions = wallet_transaction_history(customer.id, limit=limit)

    embed = discord.Embed(
        title=(
            "錢包流水｜"
            f"{getattr(customer, 'display_name', getattr(customer, 'name', customer.id))}"
        ),
        color=discord.Color.gold(),
    )

    embed.add_field(
        name="顧客",
        value=getattr(customer, "mention", f"<@{customer.id}>"),
        inline=True,
    )
    embed.add_field(name="目前餘額", value=format_t_amount(balance), inline=True)

    if not transactions:
        embed.add_field(name="最近流水", value="目前沒有錢包流水。", inline=False)
        return embed

    blocks: list[str] = []

    for index, tx in enumerate(transactions, start=1):
        amount = int(tx.get("amount") or 0)
        sign = "+" if amount > 0 else "-"
        tx_type = wallet_transaction_type_label(str(tx.get("type") or ""))
        before = int(tx.get("balance_before") or 0)
        after = int(tx.get("balance_after") or 0)
        created_at = str(tx.get("created_at") or "未紀錄時間")
        order_no = str(tx.get("order_no") or "").strip()
        note = str(tx.get("note") or "").strip()
        operator_id = str(tx.get("operator_discord_id") or "").strip()
        operator_name = str(tx.get("operator_display_name") or "").strip()

        if len(note) > 300:
            note = note[:297] + "…"

        block = [
            f"**{index}. {tx_type}｜{sign}{format_t_amount(abs(amount))}**",
            f"{format_t_amount(before)} → {format_t_amount(after)}",
        ]

        if order_no:
            block.append(f"訂單：`{order_no}`")

        if staff_view and operator_id:
            block.append(f"操作人：<@{operator_id}>")
        elif staff_view and operator_name:
            block.append(f"操作人：{operator_name}")

        if note:
            block.append(f"備註：{note}")

        block.append(f"時間：{created_at}")
        blocks.append("\n".join(block))

    chunks: list[str] = []
    current = ""

    for block in blocks:
        if len(block) > 1000:
            block = block[:997] + "…"

        candidate = block if not current else current + "\n\n" + block
        if len(candidate) <= 1000:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = block

    if current:
        chunks.append(current)

    for page, chunk in enumerate(chunks, start=1):
        field_name = f"最近 {len(transactions)} 筆流水"
        if len(chunks) > 1:
            field_name += f"（{page}/{len(chunks)}）"
        embed.add_field(name=field_name, value=chunk, inline=False)

    return embed
