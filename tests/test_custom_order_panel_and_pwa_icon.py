import json
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def _ico_sizes(path: Path) -> set[int]:
    data = path.read_bytes()
    reserved, icon_type, count = struct.unpack("<HHH", data[:6])
    assert reserved == 0
    assert icon_type == 1
    sizes = set()
    for index in range(count):
        offset = 6 + index * 16
        width = data[offset] or 256
        height = data[offset + 1] or 256
        assert width == height
        sizes.add(width)
    return sizes


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
    icon_192_path = ROOT / "web" / "app" / "static" / "img" / "site-app-icon-192.png"
    icon_512_path = ROOT / "web" / "app" / "static" / "img" / "site-app-icon-512.png"
    favicon_32_path = ROOT / "web" / "app" / "static" / "img" / "favicon-32.png"
    favicon_48_path = ROOT / "web" / "app" / "static" / "img" / "favicon-48.png"
    favicon_64_path = ROOT / "web" / "app" / "static" / "img" / "favicon-64.png"
    favicon_ico_path = ROOT / "web" / "app" / "static" / "img" / "favicon.ico"
    pwa_script_path = ROOT / "web" / "app" / "static" / "js" / "site_pwa.js"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    layout = layout_path.read_text(encoding="utf-8")
    pwa_script = pwa_script_path.read_text(encoding="utf-8")

    icons = manifest.get("icons") or []
    assert icons
    by_size = {icon.get("sizes"): icon for icon in icons}
    assert set(by_size) == {"192x192", "512x512"}
    assert by_size["192x192"].get("src") == "/static/img/site-app-icon-192.png?v=20261025-4"
    assert by_size["512x512"].get("src") == "/static/img/site-app-icon-512.png?v=20261025-4"
    assert all(icon.get("type") == "image/png" for icon in icons)
    assert _png_size(icon_192_path) == (192, 192)
    assert _png_size(icon_512_path) == (512, 512)

    assert _png_size(favicon_32_path) == (32, 32)
    assert _png_size(favicon_48_path) == (48, 48)
    assert _png_size(favicon_64_path) == (64, 64)
    assert _ico_sizes(favicon_ico_path) == {16, 32, 48, 64, 128, 256}

    assert 'rel="icon" href="/static/img/favicon.ico?v=20261025-5" sizes="any"' in layout
    assert 'rel="icon" type="image/png" sizes="32x32" href="/static/img/favicon-32.png?v=20261025-5"' in layout
    assert 'rel="icon" type="image/png" sizes="48x48" href="/static/img/favicon-48.png?v=20261025-5"' in layout
    assert 'rel="icon" type="image/png" sizes="64x64" href="/static/img/favicon-64.png?v=20261025-5"' in layout
    assert 'rel="shortcut icon" href="/static/img/favicon.ico?v=20261025-5"' in layout
    assert 'rel="apple-touch-icon" href="/static/img/site-app-icon-512.png?v=20261025-4"' in layout
    assert 'href="/static/site-app-manifest.json?v=20261025-4"' in layout
    assert 'src="/static/js/site_pwa.js?v=20261025-3"' in layout
    assert "button.classList.add('is-visible');\n\n    window.addEventListener('beforeinstallprompt'" in pwa_script
    assert "employee-app-icon.svg" not in manifest_path.read_text(encoding="utf-8")
    assert "site-app-icon.svg" not in manifest_path.read_text(encoding="utf-8")
