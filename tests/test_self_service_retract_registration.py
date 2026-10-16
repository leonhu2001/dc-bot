from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_retract_dispatch_view_is_registered_persistently() -> None:
    bot_source = (ROOT / "bot.py").read_text(encoding="utf-8")
    assert "SelfServiceDispatchedView," in bot_source
    assert "bot.add_view(SelfServiceDispatchedView())" in bot_source


def test_successful_self_service_submit_keeps_retract_control() -> None:
    source = (
        ROOT / "services" / "self_service_ui_runtime.py"
    ).read_text(encoding="utf-8")
    assert "view=SelfServiceDispatchedView()" in source
    assert "await panel_message.edit(" in source
