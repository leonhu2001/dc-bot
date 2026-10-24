import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_employee_manifest_is_installable_contract():
    manifest = json.loads(
        (ROOT / "web" / "app" / "static" / "employee-app-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["id"] == "/employee"
    assert manifest["start_url"].startswith("/employee")
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["prefer_related_applications"] is False
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"}.issubset(sizes)


def test_employee_layout_links_mobile_app_assets_only_for_employee_shell():
    source = (ROOT / "web" / "app" / "templates" / "site_layout.html").read_text(
        encoding="utf-8"
    )
    assert "employee_app_shell" in source
    assert "page_name|default('') == 'employee'" in source
    assert "/static/employee-app-manifest.json" in source
    assert "/static/css/pages/employee_mobile_pwa.css" in source
    assert "/static/js/pages/employee_pwa.js" in source
    assert "viewport-fit=cover" in source
    assert 'apple-mobile-web-app-capable" content="yes"' in source


def test_employee_install_script_supports_android_prompt_and_ios_instruction():
    source = (
        ROOT / "web" / "app" / "static" / "js" / "pages" / "employee_pwa.js"
    ).read_text(encoding="utf-8")
    assert "beforeinstallprompt" in source
    assert "deferredPrompt.prompt()" in source
    assert "加入主畫面" in source
    assert "打開為網頁 App" in source


def test_employee_mobile_css_prevents_ios_form_zoom_and_uses_safe_areas():
    source = (
        ROOT / "web" / "app" / "static" / "css" / "pages" / "employee_mobile_pwa.css"
    ).read_text(encoding="utf-8")
    assert "font-size:16px" in source
    assert "safe-area-inset-bottom" in source
    assert "@media(display-mode:standalone)" in source
