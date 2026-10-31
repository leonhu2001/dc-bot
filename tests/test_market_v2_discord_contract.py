from __future__ import annotations

from pathlib import Path

import discord

from views.market_v2 import (
    MarketV2NotificationCenterView,
    MarketV2OverviewView,
    build_market_alerts_embed,
)


ROOT = Path(__file__).resolve().parents[1]


def _labels(view: discord.ui.View) -> set[str]:
    return {
        str(getattr(child, "label", "") or "")
        for child in view.children
        if getattr(child, "label", None)
    }


def test_market_v2_public_panels_expose_favorites_and_settings():
    overview = _labels(MarketV2OverviewView())
    notifications = _labels(MarketV2NotificationCenterView())

    assert {"查詢行情", "智慧排行", "我的收藏", "完整行情"} <= overview
    assert {"收藏管理", "價格提醒", "我的提醒", "通知設定"} <= notifications
    assert "暫停全部" not in notifications


def test_market_v2_notification_copy_mentions_15_minute_favorite_warning():
    embed = build_market_alerts_embed()
    assert embed.title == "🔔 我的市場通知"
    values = "\n".join(str(field.value) for field in embed.fields)
    assert "15 分鐘" in values
    assert "可信度 ≥ 65%" in values


def test_market_v2_runtime_filters_discord_items_and_starts_restock_worker():
    source = (ROOT / "views" / "market_v2.py").read_text(encoding="utf-8")
    runtime = (ROOT / "services" / "market" / "discord_runtime.py").read_text(encoding="utf-8")
    restock_runtime = (ROOT / "services" / "market" / "restock_runtime.py").read_text(encoding="utf-8")

    assert "market_item_enabled" in source
    assert "legacy._latest_items = _scoped_latest_items" in source
    assert "ensure_market_restock_runtime_started" in runtime
    assert "_RESTOCK_LEAD_MINUTES = 15" in restock_runtime
    assert "_RESTOCK_MIN_CONFIDENCE = 65" in restock_runtime
    assert "依歷史價格型態推估，非官方補貨時間" in restock_runtime
