import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_site_manifest_installs_the_whole_website():
    manifest = json.loads(
        (ROOT / "web" / "app" / "static" / "site-app-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["id"] == "/"
    assert manifest["start_url"].startswith("/")
    assert not manifest["start_url"].startswith("/employee")
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["prefer_related_applications"] is False
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"}.issubset(sizes)
    shortcut_urls = {item["url"] for item in manifest["shortcuts"]}
    assert "/order" in shortcut_urls
    assert "/me" in shortcut_urls
    assert "/employee" in shortcut_urls
    assert "/dispatch" in shortcut_urls


def test_site_layout_links_pwa_assets_globally_not_only_employee_pages():
    source = (ROOT / "web" / "app" / "templates" / "site_layout.html").read_text(
        encoding="utf-8"
    )
    assert "/static/site-app-manifest.json" in source
    assert "/static/css/site_pwa.css" in source
    assert "/static/js/site_pwa.js" in source
    assert "viewport-fit=cover" in source
    assert 'apple-mobile-web-app-capable" content="yes"' in source
    assert 'apple-mobile-web-app-title" content="魔丸娛樂"' in source
    assert "{% if employee_app_shell %}\n    <link rel=\"manifest\"" not in source


def test_backoffice_layout_exposes_the_same_site_pwa_when_opened_directly():
    source = (ROOT / "web" / "app" / "templates" / "admin_layout.html").read_text(
        encoding="utf-8"
    )
    assert "/static/site-app-manifest.json" in source
    assert "/static/css/site_pwa.css" in source
    assert "/static/js/site_pwa.js" in source
    assert "viewport-fit=cover" in source
    assert 'apple-mobile-web-app-capable" content="yes"' in source
    assert 'apple-mobile-web-app-title" content="魔丸娛樂"' in source


def test_site_install_script_supports_android_prompt_and_ios_instruction():
    source = (
        ROOT / "web" / "app" / "static" / "js" / "site_pwa.js"
    ).read_text(encoding="utf-8")
    assert "beforeinstallprompt" in source
    assert "deferredPrompt.prompt()" in source
    assert "安裝魔丸 App" in source
    assert "加入主畫面" in source
    assert "打開為網頁 App" in source


def test_site_pwa_css_uses_safe_areas_and_mobile_touch_targets():
    source = (
        ROOT / "web" / "app" / "static" / "css" / "site_pwa.css"
    ).read_text(encoding="utf-8")
    assert "safe-area-inset-bottom" in source
    assert "min-height:44px" in source
    assert "@media(display-mode:standalone)" in source


def test_employee_mobile_css_remains_for_employee_specific_layout_repairs():
    source = (
        ROOT / "web" / "app" / "static" / "css" / "pages" / "employee_mobile_pwa.css"
    ).read_text(encoding="utf-8")
    assert "employee-workspace-site" in source
    assert "font-size:16px" in source
