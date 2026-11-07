from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import discord

from services.market.restock_delivery import MarketRestockRepository
from services.market.restock_prediction import get_cached_item_restock_predictions


MARKET_GAME_KEY = "delta_force"
MARKET_GAME_SLUG = "delta-force"
MARKET_SITE_BASE_URL = "https://mowanentertainment.com"
_RESTOCK_LEAD_MINUTES = 15
_RESTOCK_MIN_CONFIDENCE = 65

def _source_data_fresh(latest_items, *, now: datetime | None = None) -> bool:
    """Never send forecast DMs based on stale upstream market prices."""
    timestamps = [
        item.source_updated_at
        for item in latest_items
        if getattr(item, "source_updated_at", None) is not None
    ]
    if not timestamps:
        return False
    latest = max(
        at.replace(tzinfo=timezone.utc)
        if at.tzinfo is None else at.astimezone(timezone.utc)
        for at in timestamps
    )
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    try:
        allowed_age = max(900, int(os.getenv("MARKET_STALE_SECONDS", "2700")))
    except (TypeError, ValueError):
        allowed_age = 2700
    return max(0, (clock - latest).total_seconds()) <= allowed_age



def _market_item_url(item_key: str) -> str:
    from urllib.parse import quote

    return (
        f"{MARKET_SITE_BASE_URL}/games/{MARKET_GAME_SLUG}/market/items/"
        f"{quote(str(item_key or ''), safe='')}"
    )


def _market_notifications_url() -> str:
    return f"{MARKET_SITE_BASE_URL}/games/{MARKET_GAME_SLUG}/notifications"


async def market_restock_delivery_loop(bot: discord.Client) -> None:
    await bot.wait_until_ready()
    restock_repository: MarketRestockRepository | None = None

    while not bot.is_closed():
        try:
            from services.market.discord_runtime import get_discord_market_services

            services = get_discord_market_services()
            if services is None:
                await asyncio.sleep(30)
                continue

            if restock_repository is None:
                restock_repository = MarketRestockRepository(services.market)
                await asyncio.to_thread(restock_repository.create_all)

            source_items = await asyncio.to_thread(
                services.market.list_latest, MARKET_GAME_KEY, limit=1
            )
            if not _source_data_fresh(source_items):
                # Cached forecasts must not fire while upstream data is old.
                await asyncio.sleep(30)
                continue

            predictions = await asyncio.to_thread(
                get_cached_item_restock_predictions,
                services.market,
                MARKET_GAME_KEY,
            )
            await asyncio.to_thread(
                restock_repository.sync_predictions,
                MARKET_GAME_KEY,
                predictions,
            )
            due = await asyncio.to_thread(
                restock_repository.list_due_deliveries,
                MARKET_GAME_KEY,
                lead_minutes=_RESTOCK_LEAD_MINUTES,
                min_confidence=_RESTOCK_MIN_CONFIDENCE,
                limit=100,
            )
            latest_items = (
                await asyncio.to_thread(
                    services.market.list_latest,
                    MARKET_GAME_KEY,
                    limit=500,
                )
                if due
                else ()
            )
            latest_by_key = {
                str(item.source_item_id): item
                for item in latest_items
            }

            for event in due:
                try:
                    enabled = await asyncio.to_thread(
                        services.discord.dm_enabled,
                        event.discord_user_id,
                    )
                    if not enabled:
                        continue

                    try:
                        user_id = int(event.discord_user_id)
                    except (TypeError, ValueError):
                        await asyncio.to_thread(
                            restock_repository.mark_unavailable,
                            event.forecast_id,
                            event.discord_user_id,
                            "invalid discord user id",
                        )
                        continue

                    user = bot.get_user(user_id)
                    if user is None:
                        try:
                            user = await bot.fetch_user(user_id)
                        except (discord.NotFound, discord.Forbidden):
                            await asyncio.to_thread(
                                restock_repository.mark_unavailable,
                                event.forecast_id,
                                event.discord_user_id,
                                "discord user unavailable",
                            )
                            continue

                    item = latest_by_key.get(event.item_key)
                    if item is None:
                        item = await asyncio.to_thread(
                            services.market.get_item,
                            event.game_key,
                            event.item_key,
                        )
                    item_name = str(getattr(item, "name", "") or event.item_key)
                    current_price = getattr(item, "current_price", None)
                    predicted_ts = int(event.predicted_at.timestamp())

                    embed = discord.Embed(
                        title="📦 個別商品預估降價提醒",
                        description=f"**{item_name}**",
                        color=discord.Color.from_rgb(111, 66, 193),
                    )
                    embed.add_field(
                        name="預估降價時段",
                        value=f"<t:{predicted_ts}:t> · <t:{predicted_ts}:R>",
                        inline=False,
                    )
                    if current_price is not None:
                        embed.add_field(
                            name="目前價格",
                            value=f"${int(current_price):,}",
                            inline=True,
                        )
                    embed.add_field(
                        name="預測可信度",
                        value=f"{event.confidence}% · {event.event_count} 次樣本",
                        inline=True,
                    )
                    if event.jitter_minutes > 0:
                        embed.add_field(
                            name="歷史時間誤差",
                            value=f"約 ±{event.jitter_minutes} 分鐘",
                            inline=True,
                        )
                    embed.set_footer(text="依此商品自己的歷史價格推估；非官方補貨時間或保證")

                    view = discord.ui.View(timeout=None)
                    view.add_item(
                        discord.ui.Button(
                            label="查看行情",
                            emoji="📈",
                            style=discord.ButtonStyle.link,
                            url=_market_item_url(event.item_key),
                        )
                    )
                    view.add_item(
                        discord.ui.Button(
                            label="管理收藏",
                            emoji="⭐",
                            style=discord.ButtonStyle.link,
                            url=_market_notifications_url(),
                        )
                    )

                    try:
                        await user.send(embed=embed, view=view)
                    except (discord.Forbidden, discord.NotFound):
                        await asyncio.to_thread(
                            restock_repository.mark_unavailable,
                            event.forecast_id,
                            event.discord_user_id,
                            "discord dm blocked or unavailable",
                        )
                        continue
                    except discord.HTTPException as exc:
                        await asyncio.to_thread(
                            restock_repository.mark_retry,
                            event.forecast_id,
                            event.discord_user_id,
                            reason=f"HTTP {getattr(exc, 'status', 0) or 0}",
                        )
                        continue

                    await asyncio.to_thread(
                        restock_repository.mark_sent,
                        event.forecast_id,
                        event.discord_user_id,
                    )
                except Exception as exc:
                    try:
                        await asyncio.to_thread(
                            restock_repository.mark_retry,
                            event.forecast_id,
                            event.discord_user_id,
                            reason=type(exc).__name__,
                        )
                    except Exception:
                        pass
                    print(
                        f"[market-restock] delivery failed forecast={event.forecast_id}: "
                        f"{type(exc).__name__}",
                        flush=True,
                    )
        except Exception as exc:
            print(
                f"[market-restock] loop failed: {type(exc).__name__}",
                flush=True,
            )

        await asyncio.sleep(60)


def ensure_market_restock_runtime_started(bot: discord.Client) -> None:
    if getattr(bot, "_market_restock_runtime_started", False):
        return
    bot._market_restock_runtime_started = True
    bot.loop.create_task(market_restock_delivery_loop(bot))
    print("[market-restock] forecast DM runtime started", flush=True)
