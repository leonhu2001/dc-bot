"""One Discord dispatch-card presentation, independent of source channel.

All updates should render the same order/payment state and preserve product,
financial, assignment, anonymity, and routing fields from the source embed.
No payment transition, permission decision, or database mutation belongs here.
"""
from __future__ import annotations

import discord

STATUS_FIELD = "訂單狀態"
PAYMENT_FIELD = "付款狀態"
TITLE = "魔丸娛樂｜接單面板"
DESCRIPTION = "接單、付款、存單與結單狀態以此面板為準。"

# Prior producers appended additional status blocks instead of replacing them.
_OBSOLETE = frozenset({"狀態", "目前階段", STATUS_FIELD, PAYMENT_FIELD})
_FIRST = (
    "接單進度", "護航需求", "顧客", "票口", "訂單",
    "服務內容", "實際服務", "服務福利", "目前接單", "指定",
    "客服備註", "存單資訊", "存單備註", "恢復紀錄",
    "接單規則", "網站下單資訊", "接單需求", "可接職位",
    "陪玩人數", "點數福利",
)


def display_status(status: str) -> tuple[str, discord.Color]:
    status = str(status or "").strip().lower()
    if status in {"active", "paid"}:
        return "🟢 服務進行中", discord.Color.green()
    if status == "accepted_pending_pay":
        return "🟡 接單完成｜等待付款", discord.Color.gold()
    if status == "waiting_acceptance":
        return "🟡 等待接單", discord.Color.gold()
    if status == "stored":
        return "🔵 已存單｜暫停服務", discord.Color.blue()
    if status in {"closed", "completed", "done"}:
        return "✅ 已結單", discord.Color.green()
    if status in {"cancelled", "canceled"}:
        return "⛔ 已取消", discord.Color.red()
    if status == "pending_cs_dispatch":
        return "🟡 待客服確認", discord.Color.gold()
    return "⚪ 狀態待確認", discord.Color.light_grey()


def display_payment(
    status: str, *, zero_amount: bool = False, paid_confirmed: bool = False,
) -> str:
    status = str(status or "").strip().lower()
    if status in {"active", "paid"}:
        return "免付款（0T）" if zero_amount else "已付款"
    if status == "accepted_pending_pay":
        return "等待付款"
    if status in {"waiting_acceptance", "pending_cs_dispatch", "draft"}:
        return "尚未付款"
    if status in {"stored", "closed", "completed", "done"}:
        if paid_confirmed:
            return "免付款（0T）" if zero_amount else "已付款"
        return "請依原付款紀錄確認"
    if status in {"cancelled", "canceled"}:
        return "請依退款／付款紀錄確認"
    return "付款狀態待確認"


# Discord accepts at most 25 fields. On exceptionally dense custom orders,
# combine financial detail before that limit is reached: never silently drop
# discount/payout values from the tail of the source Embed.
_FINANCIAL = frozenset({
    "客服報價", "商品原價", "百分比折扣", "固定折扣", "點數折價",
    "指定費", "顧客應付", "顧客實付", "打手分潤基準", "加急費",
    "掛名狀態", "店家抽成前差額", "客服分潤", "店家實留",
    "VIP 月券", "活動加贈", "訂單福利備註",
})


def _compact_financials(
    entries: list[tuple[str, str, bool]],
) -> list[tuple[str, str, bool]]:
    financial = [
        (name, value) for name, value, _ in entries if name in _FINANCIAL
    ]
    if not financial:
        return entries
    sections: list[str] = []
    section = ""
    for name, value in financial:
        line = f"**{name}**：{value}"
        if section and len(section) + len(line) + 1 > 1000:
            sections.append(section)
            section = ""
        section = f"{section}\n{line}" if section else line
    if section:
        sections.append(section)
    remaining = [
        entry for entry in entries if entry[0] not in _FINANCIAL
    ]
    for index, text in enumerate(sections, 1):
        remaining.append((
            "金額明細" if len(sections) == 1 else f"金額明細 {index}/{len(sections)}",
            text[:1024],
            False,
        ))
    return remaining


def unify_dispatch_embed(
    embed: discord.Embed,
    *,
    status: str,
    zero_amount: bool = False,
    paid_confirmed: bool = False,
) -> discord.Embed:
    """Idempotently replace stale status/payment fields and order all others.

    Reusing an existing embed (refresh, store, restore) is safe: there can
    never be more than one order status or payment status. Existing custom,
    quoted, point-benefit and loyalty fields are kept as-is.
    """
    phase, color = display_status(status)
    payment = display_payment(
        status, zero_amount=zero_amount, paid_confirmed=paid_confirmed
    )
    entries: list[tuple[str, str, bool]] = []
    seen: set[str] = set()
    for field in embed.fields:
        name = str(field.name)
        if name in _OBSOLETE or name in seen:
            continue
        seen.add(name)
        entries.append((name, str(field.value)[:1024], bool(field.inline)))

    ordered = sorted(
        enumerate(entries),
        key=lambda item: (
            _FIRST.index(item[1][0]) if item[1][0] in _FIRST else len(_FIRST),
            item[0],
        ),
    )
    ordered_fields = [entry for _index, entry in ordered]
    if len(ordered_fields) > 23:
        ordered_fields = _compact_financials(ordered_fields)
    embed.title = TITLE
    embed.description = DESCRIPTION
    embed.color = color
    embed.clear_fields()
    embed.add_field(name=STATUS_FIELD, value=phase, inline=True)
    embed.add_field(name=PAYMENT_FIELD, value=payment, inline=True)
    for name, value, inline in ordered_fields[:23]:
        embed.add_field(name=name, value=value, inline=inline)
    return embed


def dispatch_creation_placeholder(
    *, order_id: int, customer_mention: str, category: str, item: str,
) -> discord.Embed:
    """Site-order interim message also uses the final dispatch-card geometry."""
    embed = discord.Embed(color=discord.Color.gold())
    embed.add_field(name="顧客", value=customer_mention or "未紀錄", inline=True)
    embed.add_field(name="訂單", value=f"{category}｜{item}"[:1024], inline=False)
    embed.add_field(
        name="目前接單", value="正在建立正式接單面板", inline=False
    )
    unify_dispatch_embed(embed, status="waiting_acceptance")
    # Used by the existing retry/idempotency lookup; never change its marker.
    embed.set_footer(text=f"WEB-{int(order_id)}｜網站訂單")
    return embed
