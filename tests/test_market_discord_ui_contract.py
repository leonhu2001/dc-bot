from pathlib import Path
from types import SimpleNamespace

from views.market import (
    MARKET_PANEL_CHANNEL_ID,
    MarketDmSettingsView,
    MarketNotificationCenterView,
    MarketOverviewView,
    _build_dm_settings_embed,
    _message_component_custom_ids,
    build_market_alerts_embed,
    build_market_overview_embed,
)


ROOT = Path(__file__).resolve().parents[1]


def test_market_panels_target_requested_channel_and_are_persistent():
    assert MARKET_PANEL_CHANNEL_ID == 1566004926209990776

    overview = MarketOverviewView()
    notifications = MarketNotificationCenterView()

    assert overview.timeout is None
    assert notifications.timeout is None
    assert overview.is_persistent() is True
    assert notifications.is_persistent() is True

    overview_custom_ids = {
        child.custom_id
        for child in overview.children
        if getattr(child, "custom_id", None)
    }
    notification_custom_ids = {
        child.custom_id
        for child in notifications.children
        if getattr(child, "custom_id", None)
    }

    assert {
        "mowan_market_query_v1",
        "mowan_market_rankings_v1",
    } <= overview_custom_ids
    assert {
        "mowan_market_alert_add_v1",
        "mowan_market_alert_list_v1",
        "mowan_market_dm_toggle_v1",
        "mowan_market_alert_pause_all_v1",
    } <= notification_custom_ids


def test_market_panel_internal_markers_are_hidden_from_users():
    overview = build_market_overview_embed(None)
    notifications = build_market_alerts_embed()

    assert getattr(overview.footer, "text", None) is None
    assert getattr(notifications.footer, "text", None) is None
    assert notifications.description is None

    fields = {field.name: field.value for field in notifications.fields}
    assert fields == {
        "提醒條件": "📉 低於指定價格\n📈 高於指定價格",
        "通知方式": "💬 Discord 私訊",
    }

    message = SimpleNamespace(
        components=[
            SimpleNamespace(
                children=[SimpleNamespace(custom_id="mowan_market_query_v1")]
            )
        ]
    )
    assert _message_component_custom_ids(message) == {"mowan_market_query_v1"}

    source = (ROOT / "views" / "market.py").read_text(encoding="utf-8")
    assert "embed.set_footer(text=MARKET_OVERVIEW_MARKER)" not in source
    assert "embed.set_footer(text=MARKET_ALERTS_MARKER)" not in source
    assert "marker == LEGACY_MARKET_OVERVIEW_MARKER" in source
    assert "marker == LEGACY_MARKET_ALERTS_MARKER" in source


def test_discord_dm_settings_show_private_status_before_toggling():
    enabled_embed = _build_dm_settings_embed(True)
    disabled_embed = _build_dm_settings_embed(False)
    enabled_view = MarketDmSettingsView(True)
    disabled_view = MarketDmSettingsView(False)

    assert enabled_embed.description == "目前狀態：✅ 已開啟"
    assert disabled_embed.description == "目前狀態：🔕 已關閉"
    assert enabled_view.timeout == 180
    assert disabled_view.timeout == 180
    assert enabled_view.children[0].label == "關閉通知"
    assert disabled_view.children[0].label == "開啟通知"

    source = (ROOT / "views" / "market.py").read_text(encoding="utf-8")
    assert "view=MarketDmSettingsView(enabled)" in source
    assert "target = not self.enabled" in source


def test_setup_cog_installs_market_discord_runtime():
    text = (ROOT / "cogs" / "setup_commands.py").read_text(encoding="utf-8")

    assert "from views.market import install_market_discord" in text
    assert "install_market_discord(bot)" in text


def test_market_and_notifications_are_marked_live_with_short_copy():
    registry = (ROOT / "services" / "game_registry.py").read_text(encoding="utf-8")
    market = (ROOT / "web" / "app" / "templates" / "game_market.html").read_text(
        encoding="utf-8"
    )
    notifications = (
        ROOT / "web" / "app" / "templates" / "game_notifications.html"
    ).read_text(encoding="utf-8")

    assert registry.count('"status": "已上線"') >= 2
    assert "後續將加入" not in registry
    assert "下一階段" not in registry

    assert "只使用我們自己的歷史資料" not in market
    assert "不採用第三方推薦分數" not in market
    assert "不會用未驗證價格填版面" not in market

    assert "推播採每台瀏覽器獨立訂閱" not in notifications
    assert "暫時性失敗會保留待送事件" not in notifications
    assert "失效 endpoint" not in notifications
    assert "管理關注、價格提醒與推播。" in notifications
