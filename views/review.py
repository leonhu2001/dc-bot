import asyncio

import discord


_REVIEW_CHANNEL_ID: int | None = None


def configure_review_views(*, review_channel_id: int) -> None:
    global _REVIEW_CHANNEL_ID
    _REVIEW_CHANNEL_ID = review_channel_id


def get_review_channel_id() -> int:
    if _REVIEW_CHANNEL_ID is None:
        raise RuntimeError("Review views are not configured: REVIEW_CHANNEL_ID is missing")
    return _REVIEW_CHANNEL_ID


def rating_to_stars(rating_text: str) -> tuple[int | None, str | None]:
    try:
        rating = int(rating_text.strip())
    except ValueError:
        return None, None

    if rating < 1 or rating > 5:
        return None, None

    stars = "⭐" * rating
    return rating, stars


def is_anonymous_answer(text: str) -> bool:
    answer = text.strip().lower()
    return answer in {"是", "匿名", "要", "yes", "y", "true", "1"}


def is_review_media_attachment(attachment: discord.Attachment) -> bool:
    if attachment.content_type:
        return (
            attachment.content_type.startswith("image/")
            or attachment.content_type.startswith("video/")
        )

    media_exts = (
        ".png", ".jpg", ".jpeg", ".gif", ".webp",
        ".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"
    )
    return attachment.filename.lower().endswith(media_exts)


def chunk_list(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


# ========= 評價暫存資料 =========

REVIEW_DRAFTS = {}


# ========= 評價 Modal / 按鈕 =========

class ReviewSubmitView(discord.ui.View):
    def __init__(self, customer_id: int, channel_id: int):
        super().__init__(timeout=86400)
        self.customer_id = customer_id
        self.channel_id = channel_id

    @discord.ui.button(
        label="送出好評",
        style=discord.ButtonStyle.success
    )
    async def submit_review(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "只有這張票口的點單顧客可以送出評論。",
                ephemeral=True
            )
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "這個功能只能在伺服器內使用。",
                ephemeral=True
            )
            return

        channel = interaction.channel

        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "無法確認目前票口頻道。",
                ephemeral=True
            )
            return

        draft = REVIEW_DRAFTS.get(self.channel_id)

        if draft is None:
            await interaction.response.send_message(
                "找不到暫存的好評資料，請重新按「留下好評」。",
                ephemeral=True
            )
            return

        review_channel = guild.get_channel(get_review_channel_id())

        if review_channel is None or not isinstance(review_channel, discord.TextChannel):
            await interaction.response.send_message(
                "找不到評價頻道，請確認 REVIEW_CHANNEL_ID 是否正確。",
                ephemeral=True
            )
            return

        if draft.get("submitting"):
            await interaction.response.send_message(
                "好評正在送出中，請不要重複按按鈕。",
                ephemeral=True
            )
            return

        draft["submitting"] = True
        REVIEW_DRAFTS[self.channel_id] = draft

        await interaction.response.defer(ephemeral=True)

        button.disabled = True
        button.label = "送出中..."
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass

        try:
            media_attachments = []

            async for message in channel.history(
                after=draft["started_at"],
                oldest_first=True,
                limit=None
            ):
                if message.author.id != self.customer_id:
                    continue

                for attachment in message.attachments:
                    if is_review_media_attachment(attachment):
                        media_attachments.append(attachment)

            embed = discord.Embed(
                color=discord.Color.gold()
            )

            is_anonymous = draft.get("is_anonymous", False)
            review_customer_text = "匿名闆闆" if is_anonymous else interaction.user.mention

            embed.add_field(
                name="客戶",
                value=review_customer_text,
                inline=True
            )

            embed.add_field(
                name="評分",
                value=draft["stars"],
                inline=True
            )

            embed.add_field(
                name="評價內容",
                value=draft["content"],
                inline=False
            )

            embed.add_field(
                name="圖片 / 影片數量",
                value=f"{len(media_attachments)} 個附件",
                inline=True
            )

            files = []
            failed_attachment_count = 0

            for attachment in media_attachments:
                try:
                    file = await attachment.to_file()
                    files.append(file)
                except discord.HTTPException:
                    failed_attachment_count += 1
                except Exception:
                    failed_attachment_count += 1

            if failed_attachment_count:
                embed.add_field(
                    name="附件提醒",
                    value=(
                        f"有 {failed_attachment_count} 個附件未成功轉發，"
                        "可能是 Discord 檔案大小或格式限制。"
                    ),
                    inline=False
                )

            if files:
                first_batch = True

                for file_batch in chunk_list(files, 10):
                    if first_batch:
                        await review_channel.send(
                            embed=embed,
                            files=file_batch,
                            allowed_mentions=discord.AllowedMentions(
                                users=not is_anonymous,
                                roles=False,
                                everyone=False
                            )
                        )
                        first_batch = False
                    else:
                        await review_channel.send(
                            content=(
                                "匿名闆闆 的好評附件續傳"
                                if is_anonymous
                                else f"{interaction.user.mention} 的好評附件續傳"
                            ),
                            files=file_batch,
                            allowed_mentions=discord.AllowedMentions(
                                users=not is_anonymous,
                                roles=False,
                                everyone=False
                            )
                        )
            else:
                await review_channel.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(
                        users=not is_anonymous,
                        roles=False,
                        everyone=False
                    )
                )

        except discord.HTTPException as e:
            draft["submitting"] = False
            REVIEW_DRAFTS[self.channel_id] = draft
            button.disabled = False
            button.label = "送出好評"
            try:
                await interaction.message.edit(view=self)
            except discord.HTTPException:
                pass
            await interaction.followup.send(
                f"好評送出失敗，請稍後再試或請客服協助。錯誤：{e}",
                ephemeral=True
            )
            return
        except Exception as e:
            draft["submitting"] = False
            REVIEW_DRAFTS[self.channel_id] = draft
            button.disabled = False
            button.label = "送出好評"
            try:
                await interaction.message.edit(view=self)
            except discord.HTTPException:
                pass
            await interaction.followup.send(
                f"好評送出失敗，請稍後再試或請客服協助。錯誤：{e}",
                ephemeral=True
            )
            return

        REVIEW_DRAFTS.pop(self.channel_id, None)

        button.disabled = True
        button.label = "已送出"
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass

        await interaction.followup.send(
            "好評已送出，感謝闆闆支持！票口將在 3 秒後關閉。",
            ephemeral=True
        )

        await channel.send(
            f"{interaction.user.mention} 已完成評論，感謝闆闆支持！\n"
            f"票口將在 3 秒後關閉。"
        )

        await asyncio.sleep(3)

        await channel.delete(reason=f"Review completed by {interaction.user}")


class ReviewModal(discord.ui.Modal, title="留下好評"):
    rating = discord.ui.TextInput(
        label="評分",
        placeholder="請輸入 1~5",
        required=True,
        max_length=1
    )

    content = discord.ui.TextInput(
        label="評價內容",
        placeholder="請輸入你的評價內容",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000
    )

    anonymous = discord.ui.TextInput(
        label="是否匿名",
        placeholder="輸入：是 / 否",
        required=True,
        max_length=10
    )

    def __init__(self, customer_id: int):
        super().__init__()
        self.customer_id = customer_id

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有這張票口的點單顧客可以留下評論。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        rating_number, stars = rating_to_stars(self.rating.value)

        if rating_number is None or stars is None:
            await interaction.response.send_message("評分請輸入 1~5 的數字。", ephemeral=True)
            return

        REVIEW_DRAFTS[interaction.channel.id] = {
            "customer_id": self.customer_id,
            "rating_number": rating_number,
            "stars": stars,
            "content": self.content.value,
            "is_anonymous": is_anonymous_answer(self.anonymous.value),
            "started_at": interaction.created_at,
        }

        await interaction.response.send_message(
            "好評文字已填寫完成。\n\n"
            "如果有圖片或影片，請直接傳到這個票口頻道。\n"
            "圖片 / 影片可以傳很多個，也可以分很多則訊息傳。\n\n"
            "全部傳完後，請按下方的「送出好評」。",
            view=ReviewSubmitView(
                customer_id=self.customer_id,
                channel_id=interaction.channel.id
            ),
            ephemeral=False
        )


class LeaveReviewButton(discord.ui.Button):
    def __init__(self, customer_id: int):
        super().__init__(
            label="留下好評",
            style=discord.ButtonStyle.success,
            custom_id="review_leave_button",
            row=0,
        )
        self.customer_id = customer_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有這張票口的點單顧客可以留下評論。", ephemeral=True)
            return

        await interaction.response.send_modal(
            ReviewModal(customer_id=self.customer_id)
        )


class SkipReviewCloseTicketButton(discord.ui.Button):
    def __init__(self, customer_id: int):
        super().__init__(
            label="不寄送好評",
            style=discord.ButtonStyle.danger,
            custom_id="review_skip_close_ticket_button",
            row=1,
        )
        self.customer_id = customer_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message("只有這張票口的點單顧客可以關閉票口。", ephemeral=True)
            return

        channel = interaction.channel

        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        view = self.view
        if isinstance(view, discord.ui.View):
            for child in view.children:
                child.disabled = True

            try:
                await interaction.message.edit(view=view)
            except discord.HTTPException:
                pass

        await interaction.response.send_message(
            "已選擇不寄送好評，票口將在 3 秒後關閉。",
            ephemeral=True
        )

        await channel.send(
            f"{interaction.user.mention} 選擇不寄送好評，票口將在 3 秒後關閉。",
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)
        )

        await asyncio.sleep(3)

        await channel.delete(reason=f"Review skipped by {interaction.user}")


class ReviewButtonView(discord.ui.View):
    def __init__(self, customer_id: int):
        super().__init__(timeout=86400)
        self.customer_id = customer_id
        self.add_item(LeaveReviewButton(customer_id))
        self.add_item(SkipReviewCloseTicketButton(customer_id))
