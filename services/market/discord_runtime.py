from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import discord
from dotenv import dotenv_values

from services.market.discord_delivery import MarketDiscordRepository
from services.market.notification_test import split_notification_condition
from services.market.personalization import MarketPersonalizationRepository
from services.market.storage import MarketRepository


MARKET_GAME_KEY = "delta_force"
MARKET_GAME_SLUG = "delta-force"
MARKET_SITE_BASE_URL = "https://mowanentertainment.com"


@dataclass(frozen=True)
class DiscordMarketServices:
    market: MarketRepository
    personalization: MarketPersonalizationRepository
    discord: MarketDiscordRepository


def _market_database_url() -> str:
    direct = str(os.getenv("MARKET_DATABASE_URL") or "").strip()
    if direct:
        return direct

    app_dir = Path(os.getenv("APP_DIR") or Path(__file__).resolve().parents[2])
    candidates = (
        Path(
            os.getenv("MARKET_DISCORD_ENV_FILE")
            or app_dir / "data" / "market_discord.env"
        ),
        app_dir / "web" / ".env",
    )
    for path in candidates:
        if not path.exists():
            continue
        try:
            values = dotenv_values(path)
        except Exception:
            continue
        value = str(values.get("MARKET_DATABASE_URL") or "").strip()
        if value:
            return value
    return ""


@lru_cache(maxsize=1)
def get_discord_market_services() -> DiscordMarketServices | None:
    database_url = _market_database_url()
    if not database_url:
        return None

    market = MarketRepository(database_url)
    market.create_all()

    personalization = MarketPersonalizationRepository(market)
    personalization.create_all()

    discord_repository = MarketDiscordRepository(market)
    discord_repository.create_all()

    return DiscordMarketServices(
        market=market,
        personalization=personalization,
        discord=discord_repository,
    )


def reset_discord_market_services_cache() -> None:
    get_discord_market_services.cache_clear()


def market_item_url(item_key: str) -> str:
    return (
        f"{MARKET_SITE_BASE_URL}/games/{MARKET_GAME_SLUG}/market/items/"
        f"{quote(str(item_key or ''), safe='')}"
    )


def market_page_url() -> str:
    return f"{MARKET_SITE_BASE_URL}/games/{MARKET_GAME_SLUG}/market"


def market_notifications_url() -> str:
    return f"{MARKET_SITE_BASE_URL}/games/{MARKET_GAME_SLUG}/notifications"


def _alert_is_active(
    personalization: MarketPersonalizationRepository,
    *,
    discord_user_id: str,
    game_key: str,
    alert_id: int,
) -> bool:
    alerts = personalization.list_alerts(discord_user_id, game_key)
    return any(alert.id == int(alert_id) and alert.enabled for alert in alerts)


async def market_discord_delivery_loop(bot: discord.Client) -> None:
    await bot.wait_until_ready()

    while not bot.is_closed():
        services = get_discord_market_services()
        if services is None:
            await asyncio.sleep(30)
            continue

        try:
            events = await asyncio.to_thread(
                services.discord.list_pending_events,
                limit=50,
            )
        except Exception as exc:
            print(
                f"[market-discord] pending lookup failed: {type(exc).__name__}",
                flush=True,
            )
            await asyncio.sleep(30)
            continue

        for event in events:
            try:
                enabled, enabled_at = await asyncio.to_thread(
                    services.discord.dm_state,
                    event.discord_user_id,
                )
                if not enabled:
                    await asyncio.to_thread(
                        services.discord.mark_skipped,
                        event.outbox_id,
                        "discord dm disabled",
                    )
                    continue
                if enabled_at is not None and event.triggered_at < enabled_at:
                    await asyncio.to_thread(
                        services.discord.mark_skipped,
                        event.outbox_id,
                        "trigger predates discord dm opt-in",
                    )
                    continue

                alert_active = await asyncio.to_thread(
                    _alert_is_active,
                    services.personalization,
                    discord_user_id=event.discord_user_id,
                    game_key=event.game_key,
                    alert_id=event.alert_id,
                )
                if not alert_active:
                    await asyncio.to_thread(
                        services.discord.mark_skipped,
                        event.outbox_id,
                        "alert paused or deleted before discord delivery",
                    )
                    continue

                try:
                    user_id = int(event.discord_user_id)
                except (TypeError, ValueError):
                    await asyncio.to_thread(
                        services.discord.mark_unavailable,
                        event.outbox_id,
                        "invalid discord user id",
                    )
                    continue

                user = bot.get_user(user_id)
                if user is None:
                    try:
                        user = await bot.fetch_user(user_id)
                    except (discord.NotFound, discord.Forbidden):
                        await asyncio.to_thread(
                            services.discord.mark_unavailable,
                            event.outbox_id,
                            "discord user unavailable",
                        )
                        continue

                item = await asyncio.to_thread(
                    services.market.get_item,
                    event.game_key,
                    event.item_key,
                )
                item_name = str(getattr(item, "name", "") or event.item_key)
                base_condition, is_test = split_notification_condition(
                    event.condition_type
                )
                symbol = "≤" if base_condition == "below" else "≥"
                color = (
                    discord.Color.blurple()
                    if is_test
                    else (
                        discord.Color.green()
                        if base_condition == "below"
                        else discord.Color.orange()
                    )
                )
                embed = discord.Embed(
                    title="🧪 價格通知測試" if is_test else "🔔 價格提醒",
                    description=f"**{item_name}** · ${event.current_price:,}",
                    color=color,
                )
                embed.add_field(
                    name="條件" if not is_test else "提醒設定",
                    value=f"{symbol} ${event.target_price:,}",
                    inline=True,
                )
                embed.add_field(
                    name="觸發時間" if not is_test else "測試時間",
                    value=f"<t:{int(event.triggered_at.timestamp())}:R>",
                    inline=True,
                )

                view = discord.ui.View(timeout=None)
                view.add_item(
                    discord.ui.Button(
                        label="查看行情",
                        style=discord.ButtonStyle.link,
                        url=market_item_url(event.item_key),
                    )
                )
                view.add_item(
                    discord.ui.Button(
                        label="管理提醒",
                        style=discord.ButtonStyle.link,
                        url=market_notifications_url(),
                    )
                )

                try:
                    await user.send(embed=embed, view=view)
                except (discord.Forbidden, discord.NotFound):
                    await asyncio.to_thread(
                        services.discord.mark_unavailable,
                        event.outbox_id,
                        "discord dm blocked or unavailable",
                    )
                    continue
                except discord.HTTPException as exc:
                    await asyncio.to_thread(
                        services.discord.mark_retry,
                        event.outbox_id,
                        reason=f"HTTP {getattr(exc, 'status', 0) or 0}",
                    )
                    continue

                await asyncio.to_thread(
                    services.discord.mark_sent,
                    event.outbox_id,
                )
            except Exception as exc:
                try:
                    await asyncio.to_thread(
                        services.discord.mark_retry,
                        event.outbox_id,
                        reason=type(exc).__name__,
                    )
                except Exception:
                    pass
                print(
                    f"[market-discord] delivery failed outbox={event.outbox_id}: "
                    f"{type(exc).__name__}",
                    flush=True,
                )

        await asyncio.sleep(15)


def ensure_market_discord_delivery_started(bot: discord.Client) -> None:
    if getattr(bot, "_market_discord_delivery_started", False):
        return
    bot._market_discord_delivery_started = True
    bot.loop.create_task(market_discord_delivery_loop(bot))
    print("[market-discord] DM dispatcher started", flush=True)
