from __future__ import annotations

import asyncio

import discord

from services.market.restock_prediction import get_cached_item_restock_predictions
from services.market.scope import market_item_enabled
from views import market as legacy


_PURPLE = discord.Color.from_rgb(111, 66, 193)


async def _scoped_latest_items():
    services = legacy.get_discord_market_services()
    if services is None:
        return ()
    items = await asyncio.to_thread(
        services.market.list_latest,
        legacy.MARKET_GAME_KEY,
        limit=500,
    )
    return tuple(
        item
        for item in items
        if market_item_enabled(legacy.MARKET_GAME_KEY, getattr(item, "tier", None))
    )


def _prediction_text(snapshot) -> str:
    event = getattr(snapshot, "market_event", None)
    if event is None:
        return "模型學習中"
    if event.predicted_window:
        confidence = (
            f" · 可信度 {event.predicted_confidence}%"
            if event.predicted_confidence is not None
            else ""
        )
        return f"**{event.predicted_window}**{confidence}"
    return f"模型學習中 · 同步大跌樣本 {event.historical_event_count}/3"


def build_market_overview_embed(snapshot) -> discord.Embed:
    if snapshot is None:
        return discord.Embed(
            title="📊 三角洲台服｜交易所雷達",
            description="🔴 行情暫不可用",
            color=discord.Color.red(),
        )

    status_text = {
        "ready": "🟢 行情正常",
        "stale": "🟠 行情延遲",
        "source_error": "🔴 行情暫不可用",
        "no_data": "⚪ 尚無行情",
        "source_pending": "⚪ 行情準備中",
    }.get(snapshot.status, "⚪ 行情狀態未知")

    description = f"{status_text}　•　4級以上 {len(snapshot.items)} 種"
    if snapshot.updated_at is not None:
        description += f"\n最後更新 <t:{int(snapshot.updated_at.timestamp())}:R>"

    embed = discord.Embed(
        title="📊 三角洲台服｜交易所雷達",
        description=description,
        color=_PURPLE if snapshot.status == "ready" else discord.Color.orange(),
    )
    embed.add_field(
        name="📦 補貨雷達",
        value=_prediction_text(snapshot),
        inline=False,
    )

    opportunity = snapshot.recommended_item
    if opportunity is not None:
        embed.add_field(
            name="💎 7D 低價機會",
            value=(
                f"**{opportunity.name}**　{legacy._money(opportunity.current_price)}\n"
                f"{opportunity.recommendation_label or ''}"
            ).strip(),
            inline=False,
        )
    else:
        mature = any(item.avg_7d is not None for item in snapshot.items)
        embed.add_field(
            name="💎 7D 低價機會",
            value="目前無明顯低價" if mature else "7D 資料累積中",
            inline=False,
        )

    embed.add_field(
        name="🔥 24H 漲幅",
        value=(
            "\n".join(
                f"**{item.name}**　{legacy._pct(item.change_24h_pct)}"
                for item in snapshot.gainers[:2]
            )
            or "累積中"
        ),
        inline=True,
    )
    embed.add_field(
        name="📉 24H 跌幅",
        value=(
            "\n".join(
                f"**{item.name}**　{legacy._pct(item.change_24h_pct)}"
                for item in snapshot.losers[:2]
            )
            or "累積中"
        ),
        inline=True,
    )
    embed.set_footer(text="補貨時間依歷史價格型態推估")
    return embed


def build_market_alerts_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🔔 我的市場通知",
        description="收藏與價格提醒都會透過 Discord 私訊送達。",
        color=_PURPLE,
    )
    embed.add_field(
        name="⭐ 收藏補貨提醒",
        value="預估補貨前 **15 分鐘** 私訊\n至少 3 次樣本・可信度 ≥ 65%",
        inline=True,
    )
    embed.add_field(
        name="💰 價格提醒",
        value="低於 / 高於指定價格時私訊",
        inline=True,
    )
    return embed


async def _prediction_map():
    services = legacy.get_discord_market_services()
    if services is None:
        return {}
    rows = await asyncio.to_thread(
        get_cached_item_restock_predictions,
        services.market,
        legacy.MARKET_GAME_KEY,
    )
    return {row.item_key: row for row in rows}


async def _build_item_embed(item) -> discord.Embed:
    embed = legacy._item_result_embed(item)
    predictions = await _prediction_map()
    prediction = predictions.get(item.item_key)
    if prediction is not None:
        embed.add_field(
            name="📦 預估補貨",
            value=(
                f"<t:{int(prediction.predicted_at.timestamp())}:t> · "
                f"{prediction.confidence}% · {prediction.event_count} 次樣本"
            ),
            inline=False,
        )
    return embed


class MarketFavoriteToggleButton(discord.ui.Button):
    def __init__(self, item, watched: bool):
        self.item = item
        self.watched = bool(watched)
        super().__init__(
            label="取消收藏" if self.watched else "收藏",
            emoji="★" if self.watched else "⭐",
            style=discord.ButtonStyle.secondary if self.watched else discord.ButtonStyle.success,
        )

    async def callback(self, interaction: discord.Interaction):
        services = legacy.get_discord_market_services()
        if services is None:
            await interaction.response.send_message("行情服務暫時不可用。", ephemeral=True)
            return
        target = not self.watched
        await asyncio.to_thread(
            services.personalization.set_watched,
            str(interaction.user.id),
            legacy.MARKET_GAME_KEY,
            self.item.item_key,
            watched=target,
        )
        embed = await _build_item_embed(self.item)
        await interaction.response.edit_message(
            embed=embed,
            view=MarketV2ItemResultView(self.item, watched=target),
        )


class MarketV2ItemResultView(discord.ui.View):
    def __init__(self, item, *, watched: bool):
        super().__init__(timeout=180)
        self.item = item
        self.add_item(
            discord.ui.Button(
                label="查看走勢",
                emoji="📈",
                style=discord.ButtonStyle.link,
                url=legacy.market_item_url(item.item_key),
            )
        )
        self.add_item(MarketFavoriteToggleButton(item, watched))

    @discord.ui.button(label="設價格提醒", emoji="🔔", style=discord.ButtonStyle.primary)
    async def set_alert(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=legacy._item_result_embed(self.item),
            view=legacy.MarketAlertConditionView(self.item),
        )


class MarketV2ItemSelect(legacy.MarketItemSelect):
    async def callback(self, interaction: discord.Interaction):
        item_key = self.values[0]
        snapshot = await legacy._snapshot()
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
                embed=legacy._item_result_embed(item),
                view=legacy.MarketAlertConditionView(item),
            )
            return

        services = legacy.get_discord_market_services()
        watched = False
        if services is not None:
            watched = await asyncio.to_thread(
                services.personalization.is_watched,
                str(interaction.user.id),
                legacy.MARKET_GAME_KEY,
                item.item_key,
            )
        await interaction.response.edit_message(
            content=None,
            embed=await _build_item_embed(item),
            view=MarketV2ItemResultView(item, watched=watched),
        )


class MarketFavoriteSelect(discord.ui.Select):
    def __init__(self, items, predictions):
        self.items = {item.item_key: item for item in items}
        self.predictions = predictions
        options = []
        for item in items[:25]:
            prediction = predictions.get(item.item_key)
            description = f"{legacy._money(item.current_price)}"
            if prediction is not None:
                description += f" · 補貨 {prediction.confidence}%"
            options.append(
                discord.SelectOption(
                    label=str(item.name)[:100],
                    value=str(item.item_key)[:100],
                    description=description[:100],
                    emoji="⭐",
                )
            )
        super().__init__(
            placeholder="選擇收藏的子彈",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        item = self.items.get(self.values[0])
        if item is None:
            await interaction.response.edit_message(content="找不到這個品項。", embed=None, view=None)
            return
        await interaction.response.edit_message(
            content=None,
            embed=await _build_item_embed(item),
            view=MarketV2ItemResultView(item, watched=True),
        )


class MarketFavoriteListView(discord.ui.View):
    def __init__(self, items, predictions):
        super().__init__(timeout=180)
        self.add_item(MarketFavoriteSelect(items, predictions))


async def _send_watchlist(interaction: discord.Interaction) -> None:
    services = legacy.get_discord_market_services()
    if services is None:
        await interaction.response.send_message("行情服務暫時不可用。", ephemeral=True)
        return
    user_id = str(interaction.user.id)
    watched = await asyncio.to_thread(
        services.personalization.list_watchlist,
        user_id,
        legacy.MARKET_GAME_KEY,
    )
    watched_keys = {row.item_key for row in watched}
    snapshot = await legacy._snapshot()
    if snapshot is None:
        await interaction.response.send_message("行情服務暫時不可用。", ephemeral=True)
        return
    items = tuple(item for item in snapshot.items if item.item_key in watched_keys)
    if not items:
        await interaction.response.send_message(
            "你還沒有收藏 4級以上子彈。從「查詢行情」選擇子彈後即可收藏。",
            ephemeral=True,
        )
        return
    predictions = await _prediction_map()
    embed = discord.Embed(
        title="⭐ 我的收藏",
        description=f"共 {len(items)} 種 · 有可信預測時會在補貨前 15 分鐘私訊",
        color=_PURPLE,
    )
    await interaction.response.send_message(
        embed=embed,
        view=MarketFavoriteListView(items, predictions),
        ephemeral=True,
    )


class MarketV2OverviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="完整行情",
                emoji="🌐",
                style=discord.ButtonStyle.link,
                url=legacy.market_page_url(),
            )
        )

    @discord.ui.button(
        label="查詢行情",
        emoji="🔎",
        style=discord.ButtonStyle.primary,
        custom_id="mowan_market_query_v1",
    )
    async def query_market(self, interaction: discord.Interaction, _button: discord.ui.Button):
        items = await _scoped_latest_items()
        if not items:
            await interaction.response.send_message("目前沒有可查詢的行情。", ephemeral=True)
            return
        await interaction.response.send_message(
            "選擇口徑",
            view=legacy.MarketCategorySelectView(items, mode="query"),
            ephemeral=True,
        )

    @discord.ui.button(
        label="智慧排行",
        emoji="🔥",
        style=discord.ButtonStyle.secondary,
        custom_id="mowan_market_rankings_v1",
    )
    async def rankings(self, interaction: discord.Interaction, _button: discord.ui.Button):
        snapshot = await legacy._snapshot()
        if snapshot is None:
            await interaction.response.send_message("行情服務暫時不可用。", ephemeral=True)
            return
        embed = discord.Embed(title="🔥 智慧排行", color=_PURPLE)
        embed.add_field(
            name="24H 漲幅",
            value=(
                "\n".join(f"{item.name}　{legacy._pct(item.change_24h_pct)}" for item in snapshot.gainers[:3])
                or "累積中"
            ),
            inline=True,
        )
        embed.add_field(
            name="24H 跌幅",
            value=(
                "\n".join(f"{item.name}　{legacy._pct(item.change_24h_pct)}" for item in snapshot.losers[:3])
                or "累積中"
            ),
            inline=True,
        )
        embed.add_field(name="📦 補貨雷達", value=_prediction_text(snapshot), inline=False)
        if snapshot.recommended_item is not None:
            item = snapshot.recommended_item
            embed.add_field(
                name="💎 7D 低價機會",
                value=f"{item.name} · {legacy._money(item.current_price)} · {item.recommendation_label}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="我的收藏",
        emoji="⭐",
        style=discord.ButtonStyle.success,
        custom_id="mowan_market_watchlist_v2",
    )
    async def favorites(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await _send_watchlist(interaction)


class MarketV2DmToggleButton(discord.ui.Button):
    def __init__(self, enabled: bool):
        self.enabled = bool(enabled)
        super().__init__(
            label="關閉 Discord 私訊" if self.enabled else "開啟 Discord 私訊",
            emoji="🔕" if self.enabled else "🔔",
            style=discord.ButtonStyle.danger if self.enabled else discord.ButtonStyle.success,
        )

    async def callback(self, interaction: discord.Interaction):
        services = legacy.get_discord_market_services()
        if services is None:
            await interaction.response.edit_message(content="行情服務暫時不可用。", embed=None, view=None)
            return
        target = not self.enabled
        if target:
            try:
                await interaction.user.send("✅ 三角洲市場通知已開啟。")
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                await interaction.response.edit_message(
                    content="無法私訊你，請先開放此伺服器成員私訊。",
                    embed=None,
                    view=MarketV2NotificationSettingsView(False),
                )
                return
        await asyncio.to_thread(
            services.discord.set_dm_enabled,
            str(interaction.user.id),
            target,
        )
        await _edit_notification_settings(interaction, target)


class MarketPauseAllPriceAlertsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="暫停全部價格提醒", emoji="⏸️", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        services = legacy.get_discord_market_services()
        if services is None:
            await interaction.response.send_message("行情服務暫時不可用。", ephemeral=True)
            return
        user_id = str(interaction.user.id)
        alerts = await asyncio.to_thread(
            services.personalization.list_alerts,
            user_id,
            legacy.MARKET_GAME_KEY,
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
            f"已暫停 {len(enabled)} 個價格提醒。收藏補貨提醒不受影響。",
            ephemeral=True,
        )


class MarketV2NotificationSettingsView(discord.ui.View):
    def __init__(self, enabled: bool):
        super().__init__(timeout=180)
        self.add_item(MarketV2DmToggleButton(enabled))
        self.add_item(MarketPauseAllPriceAlertsButton())


def _notification_settings_embed(enabled: bool) -> discord.Embed:
    embed = discord.Embed(title="⚙️ 通知設定", color=_PURPLE)
    embed.add_field(
        name="Discord 私訊",
        value="✅ 已開啟" if enabled else "🔕 已關閉",
        inline=True,
    )
    embed.add_field(
        name="涵蓋通知",
        value="⭐ 收藏補貨預警\n💰 價格達標提醒",
        inline=True,
    )
    return embed


async def _edit_notification_settings(interaction: discord.Interaction, enabled: bool) -> None:
    await interaction.response.edit_message(
        content=None,
        embed=_notification_settings_embed(enabled),
        view=MarketV2NotificationSettingsView(enabled),
    )


class MarketV2NotificationCenterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="收藏管理",
        emoji="⭐",
        style=discord.ButtonStyle.success,
        custom_id="mowan_market_watchlist_manage_v2",
    )
    async def favorites(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await _send_watchlist(interaction)

    @discord.ui.button(
        label="價格提醒",
        emoji="➕",
        style=discord.ButtonStyle.primary,
        custom_id="mowan_market_alert_add_v1",
    )
    async def add_alert(self, interaction: discord.Interaction, _button: discord.ui.Button):
        items = await _scoped_latest_items()
        if not items:
            await interaction.response.send_message("目前沒有可設定的行情。", ephemeral=True)
            return
        await interaction.response.send_message(
            "選擇口徑",
            view=legacy.MarketCategorySelectView(items, mode="alert"),
            ephemeral=True,
        )

    @discord.ui.button(
        label="我的提醒",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="mowan_market_alert_list_v1",
    )
    async def my_alerts(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await legacy._send_alert_list(interaction)

    @discord.ui.button(
        label="通知設定",
        emoji="⚙️",
        style=discord.ButtonStyle.secondary,
        custom_id="mowan_market_dm_toggle_v1",
    )
    async def settings(self, interaction: discord.Interaction, _button: discord.ui.Button):
        services = await legacy._services_or_reply(interaction)
        if services is None:
            return
        enabled = await asyncio.to_thread(
            services.discord.dm_enabled,
            str(interaction.user.id),
        )
        await interaction.response.send_message(
            embed=_notification_settings_embed(enabled),
            view=MarketV2NotificationSettingsView(enabled),
            ephemeral=True,
        )


async def _scoped_alert_list_payload(user_id: str):
    services = legacy.get_discord_market_services()
    if services is None:
        return (), {}
    alerts = await asyncio.to_thread(
        services.personalization.list_alerts,
        user_id,
        legacy.MARKET_GAME_KEY,
    )
    items = await _scoped_latest_items()
    item_map = {str(item.source_item_id): item for item in items}
    alerts = tuple(alert for alert in alerts if alert.item_key in item_map)
    names = {key: str(item.name) for key, item in item_map.items()}
    return alerts, names


def install_market_v2_overrides(bot: discord.Client) -> None:
    if getattr(bot, "_market_v2_overrides_installed", False):
        return

    legacy._latest_items = _scoped_latest_items
    legacy.build_market_overview_embed = build_market_overview_embed
    legacy.build_market_alerts_embed = build_market_alerts_embed
    legacy.MarketOverviewView = MarketV2OverviewView
    legacy.MarketNotificationCenterView = MarketV2NotificationCenterView
    legacy.MarketItemSelect = MarketV2ItemSelect
    legacy.MarketItemResultView = MarketV2ItemResultView
    legacy._alert_list_payload = _scoped_alert_list_payload

    bot.add_view(MarketV2OverviewView())
    bot.add_view(MarketV2NotificationCenterView())
    bot._market_v2_overrides_installed = True
    print("[market-v2] Discord panel overrides installed", flush=True)
