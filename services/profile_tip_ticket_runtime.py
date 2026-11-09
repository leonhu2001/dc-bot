"""Private profile chicken-leg tickets backed by the existing tip ledger."""
from __future__ import annotations

from collections.abc import Callable, Awaitable

import discord

from views.profile_tip_ticket import WorkerTipProfileStartView
from views.staff_profiles import get_staff_profile

_CUSTOMER_CATEGORY_ID: int | None = None
_CUSTOMER_ROLE_ID: int | None = None
_CREATE_CHANNEL: Callable[..., Awaitable] | None = None
_SAFE_CHANNEL_NAME: Callable | None = None


def configure_profile_tip_ticket_runtime(
    *, customer_category_id: int, customer_role_id: int,
    create_channel: Callable[..., Awaitable],
    safe_channel_name: Callable,
) -> None:
    global _CUSTOMER_CATEGORY_ID, _CUSTOMER_ROLE_ID
    global _CREATE_CHANNEL, _SAFE_CHANNEL_NAME
    _CUSTOMER_CATEGORY_ID = int(customer_category_id)
    _CUSTOMER_ROLE_ID = int(customer_role_id)
    _CREATE_CHANNEL = create_channel
    _SAFE_CHANNEL_NAME = safe_channel_name


def _tip_topic_parts(topic: str | None) -> dict[str, str]:
    return {
        entry.split("=", 1)[0]: entry.split("=", 1)[1]
        for entry in str(topic or "").split(";") if "=" in entry
    }


async def create_staff_profile_tip_ticket(
    *, interaction: discord.Interaction, staff_id: str
) -> None:
    guild = interaction.guild
    member = interaction.user
    if guild is None or not isinstance(member, discord.Member):
        raise ValueError("這個功能只能在伺服器內使用。")
    if _CREATE_CHANNEL is None or _SAFE_CHANNEL_NAME is None:
        raise ValueError("名片雞腿票口尚未初始化，請通知客服。")

    try:
        target_id = int(str(staff_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("指定成員 ID 無效。") from exc
    if member.id == target_id:
        raise ValueError("不能透過自己的名片給自己加雞腿。")
    profile = get_staff_profile(target_id)
    if profile is None:
        raise ValueError("找不到這位陪玩的個人牆。")

    target = guild.get_member(target_id)
    if target is None:
        try:
            target = await guild.fetch_member(target_id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            target = None
    if target is None:
        raise ValueError("指定陪玩目前不在伺服器，無法建立雞腿票口。")

    role = guild.get_role(_CUSTOMER_ROLE_ID)
    if role is None:
        raise ValueError("找不到客服身分組，請通知管理員。")

    # Reuse an existing private ticket for the same customer and worker.
    for channel in guild.text_channels:
        if channel.category_id != _CUSTOMER_CATEGORY_ID:
            continue
        topic = _tip_topic_parts(channel.topic)
        if (
            topic.get("tip_customer_id") == str(member.id)
            and topic.get("tip_staff_id") == str(target_id)
            and channel.permissions_for(member).view_channel
        ):
            await interaction.response.send_message(
                f"你已經有這位陪玩的雞腿票口：{channel.mention}",
                ephemeral=True,
            )
            return

    await _CREATE_CHANNEL(
        interaction=interaction,
        category_id=_CUSTOMER_CATEGORY_ID,
        channel_name=_SAFE_CHANNEL_NAME("雞腿", member),
        allowed_roles=[role],
        intro_message=(
            "🍗 **陪玩名片加雞腿專用票口**\n"
            f"老闆：{member.mention}\n"
            f"指定陪玩：{target.mention}\n\n"
            "請按下方「輸入雞腿金額」，選擇我的錢包、國泰轉帳或街口。\n"
            "雞腿全額給指定陪玩；國泰／街口需貼付款截圖，"
            "客服審核入帳後才列入薪資。\n"
            "這裡只處理雞腿，不會建立遊戲訂單。"
        ),
        view=WorkerTipProfileStartView(
            customer_id=member.id,
            target={"staff_id": str(target_id), "display_name": target.display_name},
        ),
        topic=f"tip_customer_id={member.id};tip_staff_id={target_id}",
        mention_roles_in_intro=False,
        order_log_status="名片加雞腿",
    )


def register_existing_profile_tip_views(
    bot: discord.Client, *, customer_category_id: int,
) -> int:
    registered = 0
    seen: set[tuple[str, str]] = set()
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.category_id != int(customer_category_id):
                continue
            topic = _tip_topic_parts(channel.topic)
            customer_id = topic.get("tip_customer_id", "")
            worker_id = topic.get("tip_staff_id", "")
            if not customer_id.isdigit() or not worker_id.isdigit():
                continue
            pair = customer_id, worker_id
            if pair in seen:
                continue
            seen.add(pair)
            profile = get_staff_profile(worker_id)
            name = str(profile.get("display_name") or worker_id) if profile else worker_id
            try:
                bot.add_view(WorkerTipProfileStartView(
                    customer_id=int(customer_id),
                    target={"staff_id": worker_id, "display_name": name},
                ))
                registered += 1
            except ValueError:
                pass
    return registered
