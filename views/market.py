from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import discord

from services.market.discord_runtime import (
    MARKET_GAME_KEY,
    ensure_market_discord_delivery_started,
    get_discord_market_services,
    market_item_url,
    market_page_url,
)
from services.market.public_snapshot import MarketItemSummary, get_public_market_snapshot


MARKET_PANEL_CHANNEL_ID = 1566004926209990776
MARKET_OVERVIEW_MARKER = "MOWAN_MARKET_OVERVIEW_V1"
MARKET_ALERTS_MARKER = "MOWAN_MARKET_ALERTS_V1"
MARKET_STALE_SECONDS = 2700


def _money(value: int | float | None) -> str:
    if value is None:
        return "—"
    return f"${int(round(value)):,}"


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    prefix = "+" if value > 0 else ""
    return f"{prefix}{value:.1f}%"


def _item_map(items) -> dict[str, object]:
    return {str(item.source_item_id): item for item in items}


async def _services_or_reply(interaction: discord.Interaction):
    services = get_discord_market_services()
    if services is not None:
        return services
    await interaction.response.send_message("行情服務暫時不可用。", ephemeral=True)
    return None


async def _latest_items():
    services = get_discord_market_services()
    if services is None:
        return ()
    return await asyncio.to_thread(services.market.list_latest, MARKET_GAME_KEY, limit=500)


async def _snapshot():
    services = get_discord_market_services()
    if services is None:
        return None
    return await asyncio.to_thread(
        get_public_market_snapshot,
        MARKET_GAME_KEY,
        repository=services.market,
    )


def build_market_overview_embed(snapshot) -> discord.Embed:
    if snapshot is None:
        embed = discord.Embed(
            title="📈 三角洲台服交易所",
            description="🔴 行情暫不可用",
            color=discord.Color.red(),
        )
        embed.set_footer(text=MARKET_OVERVIEW_MARKER)
        return embed

    status_text = {
        "ready": "🟢 行情正常",
        "stale": "🟠 行情延遲",
        "source_error": "🔴 行情暫不可用",
        "no_data": "⚪ 尚無行情",
        "source_pending": "⚪ 行情準備中",
    }.get(snapshot.status, "⚪ 行情狀態未知")

    lines = [f"{status_text} · {len(snapshot.items)} 品項"]
    if snapshot.updated_at is not None:
        lines.append(f"更新 <t:{int(snapshot.updated_at.timestamp())}:R>")

    embed = discord.Embed(
        title="📈 三角洲台服交易所",
        description="\n".join(lines),
        color=discord.Color.green() if snapshot.status == "ready" else discord.Color.orange(),
    )

    if snapshot.gainers:
        embed.add_field(
            name="🔥 24H 漲幅",
            value="\n".join(
                f"**{item.name}**  {_pct(item.change_24h_pct)}"
                for item in snapshot.gainers[:3]
            ),
            inline=True,
        )
    else:
        embed.add_field(name="🔥 24H 漲幅", value="累積中", inline=True)

    if snapshot.losers:
        embed.add_field(
            name="📉 24H 跌幅",
            value="\n".join(
                f"**{item.name}**  {_pct(item.change_24h_pct)}"
                for item in snapshot.losers[:3]
            ),
            inline=True,
        )
    else:
        embed.add_field(name="📉 24H 跌幅", value="累積中", inline=True)

    opportunity = snapshot.recommended_item
    if opportunity is not None:
        embed.add_field(
            name="💰 7D 價格機會",
            value=(
                f"**{opportunity.name}** · {_money(opportunity.current_price)}\n"
                f"{opportunity.recommendation_label or ''}"
            ).strip(),
            inline=False,
        )
    else:
        mature = any(item.avg_7d is not None for item in snapshot.items)
        embed.add_field(
            name="💰 7D 價格機會",
            value="目前無明顯低價" if mature else "7D 累積中",
            inline=False,
        )

    embed.set_footer(text=MARKET_OVERVIEW_MARKER)
    return embed


def build_market_alerts_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🔔 價格通知中心",
        description="價格達標時以 Discord 私訊通知。",
        color=discord.Color.blurple(),
    )
    embed.set_footer(text=MARKET_ALERTS_MARKER)
    return embed


def _item_result_embed(item: MarketItemSummary) -> discord.Embed:
    embed = discord.Embed(
        title=item.name,
        description=f"**{_money(item.current_price)}**",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="24H", value=_pct(item.change_24h_pct), inline=True)
    embed.add_field(name="7D 均價", value=_money(item.avg_7d), inline=True)
    if item.vs_7d_avg_pct is None:
        value_text = "—"
    elif item.vs_7d_avg_pct < 0:
        value_text = f"低 {abs(item.vs_7d_avg_pct):.1f}%"
    elif item.vs_7d_avg_pct > 0:
        value_text = f"高 {item.vs_7d_avg_pct:.1f}%"
    else:
        value_text = "接近均價"
    embed.add_field(name="7D 對比", value=value_text, inline=True)
    return embed


def _alert_detail_embed(alert, item) -> discord.Embed:
    name = str(getattr(item, "name", "") or alert.item_key)
    current = getattr(item, "current_price", None)
    symbol = "≤" if alert.condition_type == "below" else "≥"
    embed = discord.Embed(
        title=name,
        description=f"{symbol} **{_money(alert.target_price)}**",
        color=discord.Color.green() if alert.enabled else discord.Color.dark_grey(),
    )
    embed.add_field(name="目前", value=_money(current), inline=True)
    embed.add_field(name="狀態", value="啟用中" if alert.enabled else "已暫停", inline=True)
    if alert.last_triggered_at is not None:
        embed.add_field(
            name="最近觸發",
            value=f"<t:{int(alert.last_triggered_at.timestamp())}:R>",
            inline=True,
        )
    return embed


class MarketOverviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="完整行情",
                emoji="🌐",
                style=discord.ButtonStyle.link,
                url=market_page_url(),
            )
        )

    @discord.ui.button(
        label="查詢行情",
        emoji="🔎",
        style=discord.ButtonStyle.primary,
        custom_id="mowan_market_query_v1",
    )
    async def query_market(self, interaction: discord.Interaction, _button: discord.ui.Button):
        items = await _latest_items()
        if not items:
            await interaction.response.send_message("目前沒有可查詢的行情。", ephemeral=True)
            return
        await interaction.response.send_message(
            "選擇口徑",
            view=MarketCategorySelectView(items, mode="query"),
            ephemeral=True,
        )

    @discord.ui.button(
        label="市場排行",
        emoji="🔥",
        style=discord.ButtonStyle.secondary,
        custom_id="mowan_market_rankings_v1",
    )
    async def rankings(self, interaction: discord.Interaction, _button: discord.ui.Button):
        snapshot = await _snapshot()
        if snapshot is None:
            await interaction.response.send_message("行情服務暫時不可用。", ephemeral=True)
            return
        embed = discord.Embed(title="🔥 市場排行", color=discord.Color.orange())
        embed.add_field(
            name="24H 漲幅",
            value=(
                "\n".join(f"{item.name}  {_pct(item.change_24h_pct)}" for item in snapshot.gainers[:3])
                or "累積中"
            ),
            inline=True,
        )
        embed.add_field(
            name="24H 跌幅",
            value=(
                "\n".join(f"{item.name}  {_pct(item.change_24h_pct)}" for item in snapshot.losers[:3])
                or "累積中"
            ),
            inline=True,
        )
        if snapshot.recommended_item is not None:
            item = snapshot.recommended_item
            embed.add_field(
                name="7D 價格機會",
                value=f"{item.name} · {_money(item.current_price)} · {item.recommendation_label}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class MarketNotificationCenterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="新增提醒",
        emoji="➕",
        style=discord.ButtonStyle.success,
        custom_id="mowan_market_alert_add_v1",
    )
    async def add_alert(self, interaction: discord.Interaction, _button: discord.ui.Button):
        items = await _latest_items()
        if not items:
            await interaction.response.send_message("目前沒有可設定的行情。", ephemeral=True)
            return
        await interaction.response.send_message(
            "選擇口徑",
            view=MarketCategorySelectView(items, mode="alert"),
            ephemeral=True,
        )

    @discord.ui.button(
        label="我的提醒",
        emoji="📋",
        style=discord.ButtonStyle.primary,
        custom_id="mowan_market_alert_list_v1",
    )
    async def my_alerts(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await _send_alert_list(interaction)

    @discord.ui.button(
        label="Discord通知",
        emoji="🔔",
        style=discord.ButtonStyle.secondary,
        custom_id="mowan_market_dm_toggle_v1",
    )
    async def toggle_dm(self, interaction: discord.Interaction, _button: discord.ui.Button):
        services = await _services_or_reply(interaction)
        if services is None:
            return
        user_id = str(interaction.user.id)
        enabled = await asyncio.to_thread(services.discord.dm_enabled, user_id)
        target = not enabled

        if target:
            try:
                await interaction.user.send("✅ 三角洲價格通知已開啟。")
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                await interaction.response.send_message(
                    "無法私訊你，請先開放此伺服器成員私訊。",
                    ephemeral=True,
                )
                return

        await asyncio.to_thread(services.discord.set_dm_enabled, user_id, target)
        await interaction.response.send_message(
            f"Discord 私訊通知：{'已開啟' if target else '已關閉'}",
            ephemeral=True,
        )

    @discord.ui.button(
        label="暫停全部",
        emoji="⏸️",
        style=discord.ButtonStyle.secondary,
        custom_id="mowan_market_alert_pause_all_v1",
    )
    async def pause_all(self, interaction: discord.Interaction, _button: discord.ui.Button):
        services = await _services_or_reply(interaction)
        if services is None:
            return
        user_id = str(interaction.user.id)
        alerts = await asyncio.to_thread(
            services.personalization.list_alerts,
            user_id,
            MARKET_GAME_KEY,
        )
        enabled = [alert for alert in alerts if alert.enabled]
        for alert in enabled:
            await asyncio.to_thread(
                services.personalization.set_alert_enabled,
                user_id,
                alert.id,
                enabled=False,
            )
        await interaction.response.send_message(
            f"已暫停 {len(enabled)} 個提醒。",
            ephemeral=True,
        )


class MarketCategorySelect(discord.ui.Select):
    def __init__(self, items, *, mode: str):
        self.items = tuple(items)
        self.mode = mode
        categories = sorted({str(item.category or "其他") for item in self.items})
        options = [
            discord.SelectOption(label=category[:100], value=category[:100])
            for category in categories[:25]
        ]
        super().__init__(
            placeholder="選擇口徑",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        filtered = tuple(
            item for item in self.items if str(item.category or "其他") == selected
        )
        if not filtered:
            await interaction.response.edit_message(content="沒有可用品項。", view=None)
            return
        await interaction.response.edit_message(
            content="選擇子彈",
            view=MarketItemSelectView(filtered, mode=self.mode),
        )


class MarketCategorySelectView(discord.ui.View):
    def __init__(self, items, *, mode: str):
        super().__init__(timeout=180)
        self.add_item(MarketCategorySelect(items, mode=mode))


class MarketItemSelect(discord.ui.Select):
    def __init__(self, items, *, mode: str):
        self.items = tuple(items)
        self.mode = mode
        options = []
        for item in self.items[:25]:
            tier = f"{item.tier}級 · " if item.tier else ""
            options.append(
                discord.SelectOption(
                    label=str(item.name)[:100],
                    value=str(item.source_item_id)[:100],
                    description=f"{tier}${item.current_price:,}"[:100],
                )
            )
        super().__init__(
            placeholder="選擇子彈",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        item_key = self.values[0]
        snapshot = await _snapshot()
        if snapshot is None:
            await interaction.response.edit_message(content="行情服務暫時不可用。", view=None)
            return
        item = next((row for row in snapshot.items if row.item_key == item_key), None)
        if item is None:
            await interaction.response.edit_message(content="找不到這個品項。", view=None)
            return

        if self.mode == "alert":
            await interaction.response.edit_message(
                content=None,
                embed=_item_result_embed(item),
                view=MarketAlertConditionView(item),
            )
            return

        await interaction.response.edit_message(
            content=None,
            embed=_item_result_embed(item),
            view=MarketItemResultView(item),
        )


class MarketItemSelectView(discord.ui.View):
    def __init__(self, items, *, mode: str):
        super().__init__(timeout=180)
        self.add_item(MarketItemSelect(items, mode=mode))


class MarketItemResultView(discord.ui.View):
    def __init__(self, item: MarketItemSummary):
        super().__init__(timeout=180)
        self.item = item
        self.add_item(
            discord.ui.Button(
                label="查看走勢",
                style=discord.ButtonStyle.link,
                url=market_item_url(item.item_key),
            )
        )

    @discord.ui.button(label="設提醒", emoji="🔔", style=discord.ButtonStyle.success)
    async def set_alert(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=_item_result_embed(self.item),
            view=MarketAlertConditionView(self.item),
        )


class MarketAlertConditionView(discord.ui.View):
    def __init__(self, item: MarketItemSummary):
        super().__init__(timeout=180)
        self.item = item
        self.add_item(
            discord.ui.Button(
                label="查看走勢",
                style=discord.ButtonStyle.link,
                url=market_item_url(item.item_key),
            )
        )

    @discord.ui.button(label="低於或等於", style=discord.ButtonStyle.success)
    async def below(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(
            MarketTargetPriceModal(self.item, condition_type="below")
        )

    @discord.ui.button(label="高於或等於", style=discord.ButtonStyle.danger)
    async def above(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(
            MarketTargetPriceModal(self.item, condition_type="above")
        )


class MarketTargetPriceModal(discord.ui.Modal, title="設定價格提醒"):
    target_price = discord.ui.TextInput(
        label="目標價格",
        placeholder="例如 5000",
        required=True,
        max_length=12,
    )

    def __init__(self, item: MarketItemSummary, *, condition_type: str):
        super().__init__()
        self.item = item
        self.condition_type = condition_type

    async def on_submit(self, interaction: discord.Interaction):
        clean = str(self.target_price.value or "").replace(",", "").replace("$", "").strip()
        if not clean.isdigit():
            await interaction.response.send_message("請輸入有效價格。", ephemeral=True)
            return
        price = int(clean)
        if price <= 0 or price > 2_147_483_647:
            await interaction.response.send_message("請輸入有效價格。", ephemeral=True)
            return

        services = get_discord_market_services()
        if services is None:
            await interaction.response.send_message("行情服務暫時不可用。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        alerts = await asyncio.to_thread(
            services.personalization.list_alerts,
            user_id,
            MARKET_GAME_KEY,
        )
        if len(alerts) >= 50:
            await interaction.followup.send("每個遊戲最多 50 個提醒。", ephemeral=True)
            return

        alert = await asyncio.to_thread(
            services.personalization.create_alert,
            user_id,
            MARKET_GAME_KEY,
            self.item.item_key,
            condition_type=self.condition_type,
            target_price=price,
        )
        await asyncio.to_thread(
            services.personalization.set_watched,
            user_id,
            MARKET_GAME_KEY,
            self.item.item_key,
            watched=True,
        )

        dm_enabled = await asyncio.to_thread(services.discord.dm_enabled, user_id)
        dm_note = ""
        if not dm_enabled:
            try:
                await interaction.user.send("✅ 三角洲價格通知已開啟。")
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                dm_note = "\nDiscord 私訊目前未開啟。"
            else:
                await asyncio.to_thread(services.discord.set_dm_enabled, user_id, True)

        symbol = "≤" if alert.condition_type == "below" else "≥"
        await interaction.followup.send(
            f"✅ {self.item.name} {symbol} {_money(alert.target_price)}{dm_note}",
            ephemeral=True,
        )


class MarketAlertSelect(discord.ui.Select):
    def __init__(self, alerts, names: dict[str, str]):
        self.alerts = tuple(alerts)
        self.names = names
        options = []
        for alert in self.alerts[:25]:
            symbol = "≤" if alert.condition_type == "below" else "≥"
            name = names.get(alert.item_key, alert.item_key)
            options.append(
                discord.SelectOption(
                    label=str(name)[:100],
                    value=str(alert.id),
                    description=(
                        f"{symbol} ${alert.target_price:,} · "
                        f"{'啟用中' if alert.enabled else '已暫停'}"
                    )[:100],
                )
            )
        super().__init__(
            placeholder="選擇提醒",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        services = get_discord_market_services()
        if services is None:
            await interaction.response.edit_message(content="行情服務暫時不可用。", embed=None, view=None)
            return
        alert_id = int(self.values[0])
        user_id = str(interaction.user.id)
        alerts = await asyncio.to_thread(
            services.personalization.list_alerts,
            user_id,
            MARKET_GAME_KEY,
        )
        alert = next((row for row in alerts if row.id == alert_id), None)
        if alert is None:
            await interaction.response.edit_message(content="提醒不存在。", embed=None, view=None)
            return
        items = await asyncio.to_thread(services.market.list_latest, MARKET_GAME_KEY, limit=500)
        item = _item_map(items).get(alert.item_key)
        await interaction.response.edit_message(
            content=None,
            embed=_alert_detail_embed(alert, item),
            view=MarketAlertManageView(alert.id),
        )


class MarketAlertsListView(discord.ui.View):
    def __init__(self, alerts, names: dict[str, str]):
        super().__init__(timeout=180)
        self.add_item(MarketAlertSelect(alerts, names))


class MarketAlertManageView(discord.ui.View):
    def __init__(self, alert_id: int):
        super().__init__(timeout=180)
        self.alert_id = int(alert_id)

    @discord.ui.button(label="暫停 / 啟用", style=discord.ButtonStyle.secondary)
    async def toggle(self, interaction: discord.Interaction, _button: discord.ui.Button):
        services = get_discord_market_services()
        if services is None:
            await interaction.response.edit_message(content="行情服務暫時不可用。", embed=None, view=None)
            return
        user_id = str(interaction.user.id)
        alerts = await asyncio.to_thread(
            services.personalization.list_alerts,
            user_id,
            MARKET_GAME_KEY,
        )
        alert = next((row for row in alerts if row.id == self.alert_id), None)
        if alert is None:
            await interaction.response.edit_message(content="提醒不存在。", embed=None, view=None)
            return
        await asyncio.to_thread(
            services.personalization.set_alert_enabled,
            user_id,
            alert.id,
            enabled=not alert.enabled,
        )
        alerts = await asyncio.to_thread(
            services.personalization.list_alerts,
            user_id,
            MARKET_GAME_KEY,
        )
        alert = next(row for row in alerts if row.id == self.alert_id)
        items = await asyncio.to_thread(services.market.list_latest, MARKET_GAME_KEY, limit=500)
        item = _item_map(items).get(alert.item_key)
        await interaction.response.edit_message(
            embed=_alert_detail_embed(alert, item),
            view=MarketAlertManageView(alert.id),
        )

    @discord.ui.button(label="刪除", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, _button: discord.ui.Button):
        services = get_discord_market_services()
        if services is None:
            await interaction.response.edit_message(content="行情服務暫時不可用。", embed=None, view=None)
            return
        deleted = await asyncio.to_thread(
            services.personalization.delete_alert,
            str(interaction.user.id),
            self.alert_id,
        )
        await interaction.response.edit_message(
            content="提醒已刪除。" if deleted else "提醒不存在。",
            embed=None,
            view=None,
        )

    @discord.ui.button(label="返回列表", style=discord.ButtonStyle.primary)
    async def back(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await _edit_alert_list(interaction)


async def _alert_list_payload(user_id: str):
    services = get_discord_market_services()
    if services is None:
        return (), {}
    alerts = await asyncio.to_thread(
        services.personalization.list_alerts,
        user_id,
        MARKET_GAME_KEY,
    )
    items = await asyncio.to_thread(services.market.list_latest, MARKET_GAME_KEY, limit=500)
    names = {str(item.source_item_id): str(item.name) for item in items}
    return alerts, names


async def _send_alert_list(interaction: discord.Interaction) -> None:
    alerts, names = await _alert_list_payload(str(interaction.user.id))
    if not alerts:
        await interaction.response.send_message("你還沒有價格提醒。", ephemeral=True)
        return
    embed = discord.Embed(
        title="📋 我的提醒",
        description=f"共 {len(alerts)} 個",
        color=discord.Color.blurple(),
    )
    await interaction.response.send_message(
        embed=embed,
        view=MarketAlertsListView(alerts, names),
        ephemeral=True,
    )


async def _edit_alert_list(interaction: discord.Interaction) -> None:
    alerts, names = await _alert_list_payload(str(interaction.user.id))
    if not alerts:
        await interaction.response.edit_message(content="你還沒有價格提醒。", embed=None, view=None)
        return
    embed = discord.Embed(
        title="📋 我的提醒",
        description=f"共 {len(alerts)} 個",
        color=discord.Color.blurple(),
    )
    await interaction.response.edit_message(
        content=None,
        embed=embed,
        view=MarketAlertsListView(alerts, names),
    )


async def _market_channel(bot: discord.Client) -> discord.TextChannel | None:
    channel = bot.get_channel(MARKET_PANEL_CHANNEL_ID)
    if isinstance(channel, discord.TextChannel):
        return channel
    try:
        fetched = await bot.fetch_channel(MARKET_PANEL_CHANNEL_ID)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None
    return fetched if isinstance(fetched, discord.TextChannel) else None


async def sync_market_panels(bot: discord.Client, snapshot=None) -> bool:
    channel = await _market_channel(bot)
    if channel is None or bot.user is None:
        print("[market-discord] target channel unavailable", flush=True)
        return False

    if snapshot is None:
        snapshot = await _snapshot()

    overview_message = None
    alerts_message = None
    try:
        async for message in channel.history(limit=100, oldest_first=False):
            if message.author.id != bot.user.id or not message.embeds:
                continue
            marker = str(getattr(message.embeds[0].footer, "text", "") or "")
            if marker == MARKET_OVERVIEW_MARKER and overview_message is None:
                overview_message = message
            elif marker == MARKET_ALERTS_MARKER and alerts_message is None:
                alerts_message = message
            if overview_message is not None and alerts_message is not None:
                break
    except (discord.Forbidden, discord.HTTPException) as exc:
        print(f"[market-discord] panel scan failed: {type(exc).__name__}", flush=True)
        return False

    try:
        overview_embed = build_market_overview_embed(snapshot)
        if overview_message is None:
            overview_message = await channel.send(
                embed=overview_embed,
                view=MarketOverviewView(),
            )
        else:
            await overview_message.edit(
                embed=overview_embed,
                view=MarketOverviewView(),
            )

        alerts_embed = build_market_alerts_embed()
        if alerts_message is None:
            alerts_message = await channel.send(
                embed=alerts_embed,
                view=MarketNotificationCenterView(),
            )
        else:
            await alerts_message.edit(
                embed=alerts_embed,
                view=MarketNotificationCenterView(),
            )
    except (discord.Forbidden, discord.HTTPException) as exc:
        print(f"[market-discord] panel sync failed: {type(exc).__name__}", flush=True)
        return False

    print(
        f"[market-discord] panels synced channel={channel.id} "
        f"overview={overview_message.id} alerts={alerts_message.id}",
        flush=True,
    )
    return True


async def market_panel_refresh_loop(bot: discord.Client) -> None:
    await bot.wait_until_ready()
    services = get_discord_market_services()
    if services is None:
        print("[market-discord] Market DB unavailable; panel refresh disabled", flush=True)
        return

    last_source_at = None
    rendered_stale = False

    while not bot.is_closed():
        try:
            latest = await asyncio.to_thread(
                services.market.list_latest,
                MARKET_GAME_KEY,
                limit=500,
            )
            current_source_at = (
                max(item.source_updated_at for item in latest)
                if latest
                else None
            )
            now = datetime.now(timezone.utc)
            is_stale = bool(
                current_source_at
                and (now - current_source_at).total_seconds() > MARKET_STALE_SECONDS
            )
            if (
                last_source_at is None
                or current_source_at != last_source_at
                or is_stale != rendered_stale
            ):
                snapshot = await _snapshot()
                await sync_market_panels(bot, snapshot=snapshot)
                last_source_at = current_source_at
                rendered_stale = is_stale
        except Exception as exc:
            print(
                f"[market-discord] panel refresh failed: {type(exc).__name__}",
                flush=True,
            )
        await asyncio.sleep(60)


def install_market_discord(bot: discord.Client) -> None:
    if not getattr(bot, "_market_panel_views_registered", False):
        bot.add_view(MarketOverviewView())
        bot.add_view(MarketNotificationCenterView())
        bot._market_panel_views_registered = True

    ensure_market_discord_delivery_started(bot)

    if not getattr(bot, "_market_panel_refresh_started", False):
        bot._market_panel_refresh_started = True
        bot.loop.create_task(market_panel_refresh_loop(bot))
        print("[market-discord] panel refresh started", flush=True)
