from __future__ import annotations

from typing import Any, Callable

import discord

from services.order_credential_revocation import (
    revoke_order_credential_messages as _revoke_order_credential_messages,
)


CREDENTIAL_OWNER_USER_ID: int
GUILD_ID: int
SELF_SERVICE_ORDER_SELECTIONS: dict
_to_int: Callable[..., int]
bot: Any
fetch_member_safely: Callable[..., Any]
get_taipei_now_iso: Callable[..., str]
remember_order_data: Callable[..., Any]
save_bot_data: Callable[..., Any]


def configure_order_credentials(
    *,
    credential_owner_user_id: int,
    guild_id: int,
    self_service_order_selections: dict,
    to_int: Callable[..., int],
    bot_instance: Any,
    fetch_member: Callable[..., Any],
    taipei_now_iso: Callable[..., str],
    remember_data: Callable[..., Any],
    save_data: Callable[..., Any],
) -> None:
    global CREDENTIAL_OWNER_USER_ID
    global GUILD_ID
    global SELF_SERVICE_ORDER_SELECTIONS
    global _to_int
    global bot
    global fetch_member_safely
    global get_taipei_now_iso
    global remember_order_data
    global save_bot_data

    CREDENTIAL_OWNER_USER_ID = int(credential_owner_user_id or 0)
    GUILD_ID = int(guild_id or 0)
    SELF_SERVICE_ORDER_SELECTIONS = self_service_order_selections
    _to_int = to_int
    bot = bot_instance
    fetch_member_safely = fetch_member
    get_taipei_now_iso = taipei_now_iso
    remember_order_data = remember_data
    save_bot_data = save_data


def _order_requires_credentials(data: dict | None) -> bool:
    if not isinstance(data, dict):
        return False

    rule_key = str(data.get("order_rule_key") or "").strip().lower()
    category = str(data.get("category") or "").strip().lower()
    return rule_key.startswith("farm_") or category == "farm"


async def _credential_user_for_id(
    guild: discord.Guild | None,
    user_id: int,
) -> discord.Member | discord.User | None:
    if guild is not None:
        member = guild.get_member(int(user_id))
        if member is not None:
            return member

        try:
            member = await fetch_member_safely(guild, int(user_id))
        except Exception:
            member = None

        if member is not None:
            return member

    user = bot.get_user(int(user_id))
    if user is not None:
        return user

    try:
        return await bot.fetch_user(int(user_id))
    except Exception:
        return None


def _credential_display_name(
    guild: discord.Guild | None,
    user: discord.Member | discord.User | None,
    user_id: int | str,
) -> str:
    try:
        numeric_id = int(user_id)
    except (TypeError, ValueError):
        numeric_id = 0

    if guild is not None and numeric_id:
        member = guild.get_member(numeric_id)
        if member is not None:
            return str(member.display_name)

    if user is not None:
        return str(
            getattr(user, "display_name", None)
            or getattr(user, "global_name", None)
            or getattr(user, "name", None)
            or user_id
        )

    return str(user_id)


async def _resolve_credential_owner(
    guild: discord.Guild | None,
) -> discord.Member | discord.User | None:
    if int(CREDENTIAL_OWNER_USER_ID or 0) > 0:
        return await _credential_user_for_id(guild, int(CREDENTIAL_OWNER_USER_ID))

    try:
        app_info = await bot.application_info()
    except Exception:
        app_info = None

    owner = getattr(app_info, "owner", None) if app_info is not None else None
    if owner is not None:
        owner_id = _to_int(getattr(owner, "id", None))
        if owner_id is not None:
            resolved = await _credential_user_for_id(guild, owner_id)
            return resolved or owner

    team = getattr(app_info, "team", None) if app_info is not None else None
    team_owner_id = _to_int(getattr(team, "owner_id", None)) if team is not None else None
    if team_owner_id is not None:
        return await _credential_user_for_id(guild, team_owner_id)

    return None


async def revoke_order_credential_messages(
    order_id: int,
    *,
    reason: str,
    ticket_channel: discord.TextChannel | None = None,
    notify_customer: bool = True,
) -> dict:
    return await _revoke_order_credential_messages(
        order_id,
        reason=reason,
        ticket_channel=ticket_channel,
        notify_customer=notify_customer,
        to_int=_to_int,
        resolve_user=_credential_user_for_id,
        fallback_guild=bot.get_guild(GUILD_ID),
        taipei_now_iso=get_taipei_now_iso,
    )


async def ensure_order_credential_request(
    *,
    channel: discord.TextChannel,
    customer_id: int,
    data: dict,
) -> discord.Message | None:
    if not _order_requires_credentials(data):
        return None

    existing_message_id = _to_int(data.get("credential_request_message_id"))

    if existing_message_id is not None:
        try:
            existing_message = await channel.fetch_message(existing_message_id)
            await existing_message.edit(view=OrderCredentialEntryView())
            return existing_message
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    embed = discord.Embed(
        title="🔐 代肝／代解登入資料",
        description=(
            "此訂單需要登入您的遊戲帳號。\n\n"
            "帳號與密碼**不會寫入魔丸娛樂資料庫**，只會在您送出時由機器人"
            "直接私訊給目前接單人員與店長。\n"
            "結單或取消後，機器人會自動撤回這些帳密私訊；"
            "系統只保留不含帳密內容的授權／撤回紀錄。"
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="誰會取得帳密？",
        value="目前實際接單人員與店長。送出後會明確列出姓名。",
        inline=False,
    )
    embed.add_field(
        name="安全提醒",
        value="服務完成後仍建議更換密碼；若接單人員異動，請重新提交登入資料。",
        inline=False,
    )

    message = await channel.send(
        content=f"<@{customer_id}> 請填寫本單登入資料。",
        embed=embed,
        view=OrderCredentialEntryView(),
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False,
        ),
    )

    data["credential_request_message_id"] = message.id
    data["credential_request_created_at"] = get_taipei_now_iso()
    remember_order_data(channel.id, data)
    save_bot_data()
    return message


class OrderCredentialModal(discord.ui.Modal, title="代肝／代解登入資料"):
    account = discord.ui.TextInput(
        label="登入帳號",
        placeholder="請輸入此訂單使用的遊戲登入帳號",
        required=True,
        max_length=200,
    )
    password = discord.ui.TextInput(
        label="登入密碼",
        placeholder="請輸入此訂單使用的登入密碼",
        required=True,
        max_length=200,
    )
    login_note = discord.ui.TextInput(
        label="登入方式／備註（選填）",
        placeholder="例如 Steam、Garena、Google 登入，或其他登入注意事項",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, order_channel_id: int):
        super().__init__()
        self.order_channel_id = int(order_channel_id)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("無法確認此訂單票口。", ephemeral=True)
            return

        channel = interaction.channel
        data = SELF_SERVICE_ORDER_SELECTIONS.get(self.order_channel_id)

        if not isinstance(data, dict):
            await interaction.response.send_message("找不到這張訂單資料，請通知客服。", ephemeral=True)
            return

        customer_id = _to_int(data.get("customer_id"))
        if customer_id is None or int(interaction.user.id) != customer_id:
            await interaction.response.send_message("只有此訂單的老闆可以提交登入資料。", ephemeral=True)
            return

        if str(data.get("status") or "").lower() != "active":
            await interaction.response.send_message("訂單尚未付款成立，或目前已不在進行中。", ephemeral=True)
            return

        if not _order_requires_credentials(data):
            await interaction.response.send_message("這張訂單不需要提交登入資料。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        from services.order_credentials import (
            get_active_worker_ids,
            get_order_context,
            get_order_id_by_ticket_channel,
            record_delivery,
        )

        order_id = _to_int(data.get("web_order_id"))
        if order_id is None:
            order_id = get_order_id_by_ticket_channel(self.order_channel_id)

        if order_id is None:
            await interaction.followup.send("找不到網站訂單資料，請通知客服。", ephemeral=True)
            return

        context = get_order_context(order_id) or {}
        if str(context.get("status") or "").lower() != "active":
            await interaction.followup.send("這張訂單目前不是進行中狀態。", ephemeral=True)
            return

        worker_ids = get_active_worker_ids(order_id)
        if not worker_ids:
            await interaction.followup.send("目前找不到正式接單人員，請通知客服確認接單狀態。", ephemeral=True)
            return

        owner_user = await _resolve_credential_owner(interaction.guild)
        owner_id = _to_int(getattr(owner_user, "id", None))

        if owner_user is None or owner_id is None:
            await interaction.followup.send(
                "目前無法確認店長 Discord 帳號，登入資料尚未送出，請通知客服。",
                ephemeral=True,
            )
            return

        # 重新提交時，先撤回上一輪私訊；帳密內容本身沒有資料庫副本。
        await revoke_order_credential_messages(
            order_id,
            reason="resubmitted",
            ticket_channel=channel,
            notify_customer=False,
        )

        recipients: list[tuple[int, str, discord.Member | discord.User]] = []
        seen_ids: set[int] = set()

        for worker_id_text in worker_ids:
            worker_id = _to_int(worker_id_text)
            if worker_id is None or worker_id in seen_ids:
                continue
            worker_user = await _credential_user_for_id(interaction.guild, worker_id)
            if worker_user is None:
                await revoke_order_credential_messages(
                    order_id,
                    reason="delivery_failed",
                    ticket_channel=channel,
                    notify_customer=False,
                )
                await interaction.followup.send(
                    f"無法私訊其中一位接單人員（ID {worker_id}），帳密尚未完成交付。請通知客服。",
                    ephemeral=True,
                )
                return
            seen_ids.add(worker_id)
            recipients.append((worker_id, "worker", worker_user))

        if owner_id not in seen_ids:
            seen_ids.add(owner_id)
            recipients.append((owner_id, "owner", owner_user))

        order_no = str(
            data.get("order_no")
            or data.get("receipt_id")
            or context.get("bot_order_no")
            or f"WEB-{order_id}"
        )
        account_value = str(self.account.value or "").strip()
        password_value = str(self.password.value or "")
        note_value = str(self.login_note.value or "").strip()

        delivered_display: list[str] = []

        for recipient_id, recipient_type, recipient in recipients:
            display_name = _credential_display_name(
                interaction.guild,
                recipient,
                recipient_id,
            )
            label = "店長" if recipient_type == "owner" else "接單人員"

            credential_embed = discord.Embed(
                title="🔐 魔丸娛樂｜臨時帳號授權",
                description=(
                    "此登入資料僅限本訂單服務使用。\n"
                    "完成、取消或重新提交後，機器人會嘗試自動撤回本訊息。"
                ),
                color=discord.Color.orange(),
            )
            credential_embed.add_field(name="訂單", value=order_no, inline=False)
            credential_embed.add_field(name="登入帳號", value=account_value[:1024], inline=False)
            credential_embed.add_field(name="登入密碼", value=password_value[:1024], inline=False)
            if note_value:
                credential_embed.add_field(
                    name="登入方式／備註",
                    value=note_value[:1024],
                    inline=False,
                )
            credential_embed.set_footer(text="請勿轉傳、截圖或用於本訂單以外用途")

            try:
                dm_message = await recipient.send(embed=credential_embed)
            except Exception:
                await revoke_order_credential_messages(
                    order_id,
                    reason="delivery_failed",
                    ticket_channel=channel,
                    notify_customer=False,
                )
                await interaction.followup.send(
                    f"無法將登入資料交付給{label}「{display_name}」。"
                    "已撤回本次其他已送出的帳密訊息，請通知客服。",
                    ephemeral=True,
                )
                return

            record_delivery(
                order_id=order_id,
                submitted_by_discord_id=customer_id,
                recipient_discord_id=recipient_id,
                recipient_type=recipient_type,
                recipient_display_name=display_name,
                dm_channel_id=dm_message.channel.id,
                dm_message_id=dm_message.id,
            )
            delivered_display.append(f"・{label}：{display_name}")

        data["web_order_id"] = int(order_id)
        data["credential_last_submitted_at"] = get_taipei_now_iso()
        data["credential_delivery_count"] = len(recipients)
        remember_order_data(self.order_channel_id, data)
        save_bot_data()

        receipt_text = (
            f"🛡️ **帳號資料已安全交付**\n"
            f"訂單：**{order_no}**\n\n"
            "目前取得本次帳號資料的人員：\n"
            + "\n".join(delivered_display)
            + "\n\n除上述人員外，機器人未將帳密送給其他店內成員。"
            "\n帳號與密碼內容未寫入魔丸娛樂資料庫；"
            "結單或取消後機器人會自動撤回這些帳密私訊。"
        )

        customer_notice_sent = False
        try:
            await interaction.user.send(receipt_text)
            customer_notice_sent = True
        except Exception:
            customer_notice_sent = False

        if not customer_notice_sent:
            try:
                await channel.send(
                    f"<@{customer_id}> {receipt_text}",
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
            except Exception:
                pass

        await interaction.followup.send(
            "登入資料已交付完成。\n\n" + "\n".join(delivered_display),
            ephemeral=True,
        )


class OrderCredentialEntryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🔐 填寫／更新帳號資料",
        style=discord.ButtonStyle.primary,
        custom_id="order_credentials:submit",
    )
    async def submit_credentials(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("請在原訂單票口操作。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.get(interaction.channel.id)
        if not isinstance(data, dict):
            await interaction.response.send_message("找不到這張訂單資料，請通知客服。", ephemeral=True)
            return

        customer_id = _to_int(data.get("customer_id"))
        if customer_id is None or int(interaction.user.id) != customer_id:
            await interaction.response.send_message("只有此訂單的老闆可以填寫登入資料。", ephemeral=True)
            return

        if str(data.get("status") or "").lower() != "active":
            await interaction.response.send_message("這張訂單目前不是進行中狀態。", ephemeral=True)
            return

        if not _order_requires_credentials(data):
            await interaction.response.send_message("這張訂單不需要登入資料。", ephemeral=True)
            return

        await interaction.response.send_modal(
            OrderCredentialModal(interaction.channel.id)
        )
