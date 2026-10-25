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


def test_installed_web_app_uses_site_logo_instead_of_employee_icon():
    manifest_path = ROOT / "web" / "app" / "static" / "site-app-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    icons = manifest.get("icons") or []
    assert icons
    assert all(icon.get("src") == "/static/img/favicon.png" for icon in icons)
    assert "employee-app-icon.svg" not in manifest_path.read_text(encoding="utf-8")
