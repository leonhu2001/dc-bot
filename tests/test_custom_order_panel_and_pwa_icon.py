import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_existing_custom_order_panel_clears_stale_message_content():
    source = (ROOT / "services" / "custom_order_quick_entry.py").read_text(encoding="utf-8")

    expected = (
        "await target.edit(\n"
        "                content=None,\n"
        "                embed=build_custom_order_entry_embed(),\n"
        "                view=CustomOrderQuickEntryView(),\n"
        "            )"
    )
    assert expected in source


def test_custom_order_submit_keeps_private_confirmation():
    source = (ROOT / "services" / "custom_order_quick_entry.py").read_text(encoding="utf-8")

    expected = (
        "await interaction.edit_original_response(\n"
        "        content=f\"自訂單需求已送出：{ticket.mention}\\n"
        "請到私人客服中心確認自助下單規格並等待客服報價。\"\n"
        "    )\n"
        "    return ticket"
    )
    assert expected in source


def test_custom_order_entry_panel_is_concise_and_hides_internal_marker():
    source = (ROOT / "services" / "custom_order_quick_entry.py").read_text(encoding="utf-8")

    assert "先選擇 **1～4 位陪玩**，再填寫遊戲／服務、玩法／規則、方案／目標與其他需求。" in source
    assert "客服確認內容與價格後再正式送單。" in source
    assert "此專屬頻道可直接提出自訂單需求。" not in source
    assert "建議先準備" not in source
    assert "embed.set_footer(text=CUSTOM_ORDER_PANEL_MARKER)" not in source


def test_windows_shortcut_and_installed_app_use_site_logo():
    manifest_path = ROOT / "web" / "app" / "static" / "site-app-manifest.json"
    layout_path = ROOT / "web" / "app" / "templates" / "site_layout.html"
    app_icon_path = ROOT / "web" / "app" / "static" / "img" / "site-app-icon.svg"
    pwa_script_path = ROOT / "web" / "app" / "static" / "js" / "site_pwa.js"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    layout = layout_path.read_text(encoding="utf-8")
    app_icon = app_icon_path.read_text(encoding="utf-8")
    pwa_script = pwa_script_path.read_text(encoding="utf-8")

    icons = manifest.get("icons") or []
    assert icons
    assert {icon.get("sizes") for icon in icons} == {"192x192", "512x512"}
    assert all(str(icon.get("src") or "").startswith("/static/img/site-app-icon.svg") for icon in icons)
    assert all(icon.get("type") == "image/svg+xml" for icon in icons)
    assert "data:image/png;base64," in app_icon
    assert 'aria-label="魔丸娛樂"' in app_icon
    assert 'rel="icon" type="image/gif" href="/static/img/server_logo.gif?v=20261025-2"' in layout
    assert 'rel="shortcut icon" type="image/gif" href="/static/img/server_logo.gif?v=20261025-2"' in layout
    assert 'rel="apple-touch-icon" href="/static/img/site-app-icon.svg?v=20261025-3"' in layout
    assert 'href="/static/site-app-manifest.json?v=20261025-3"' in layout
    assert 'src="/static/js/site_pwa.js?v=20261025-3"' in layout
    assert "button.classList.add('is-visible');\n\n    window.addEventListener('beforeinstallprompt'" in pwa_script
    assert "employee-app-icon.svg" not in manifest_path.read_text(encoding="utf-8")
