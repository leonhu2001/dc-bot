from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dispatch_alert_script_is_loaded_once():
    dispatch_template = (
        ROOT / "web" / "app" / "templates" / "dispatch.html"
    ).read_text(encoding="utf-8")
    layout_template = (
        ROOT / "web" / "app" / "templates" / "layout.html"
    ).read_text(encoding="utf-8")

    assert "dispatch_alerts.js" not in dispatch_template
    assert layout_template.count("dispatch_alerts.js") == 1
