from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from services import custom_order_quick_entry as custom


ROOT = Path(__file__).resolve().parents[1]


def test_custom_order_handler_is_registered_before_ready_or_optional_extensions():
    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    hook_start = source.index("async def _bot_setup_hook() -> None:")
    hook_end = source.index("bot.setup_hook = _bot_setup_hook", hook_start)
    hook = source[hook_start:hook_end]
    assert "from services.custom_order_quick_entry import install_custom_order_quick_entry" in hook
    assert "install_custom_order_quick_entry(bot)" in hook
    assert hook.index("install_custom_order_quick_entry(bot)") < hook.index(
        "install_quick_order_v2(bot)"
    )
    assert source.index("bot.setup_hook = _bot_setup_hook") < source.index(
        "async def on_ready():"
    )


def test_existing_button_callback_is_usable_and_registration_is_idempotent(monkeypatch):
    async def no_op(_bot):
        return None

    monkeypatch.setattr(custom, "ensure_custom_order_quick_panel", no_op)
    monkeypatch.setattr(custom, "repair_existing_custom_order_ticket_controls", no_op)

    class FakeBot:
        def __init__(self):
            self.loop = asyncio.get_running_loop()
            self.registered_views = []
        def add_view(self, view):
            self.registered_views.append(view)

    class FakeMember:
        id = 1234

    monkeypatch.setattr(custom.discord, "Member", FakeMember)

    async def run():
        bot = FakeBot()
        custom.install_custom_order_quick_entry(bot)
        custom.install_custom_order_quick_entry(bot)
        assert len(bot.registered_views) == 1
        view = bot.registered_views[0]
        assert isinstance(view, custom.CustomOrderQuickEntryView)
        assert view.timeout is None
        button = next(item for item in view.children if item.custom_id == "custom_order_quick_entry:open")
        interaction = SimpleNamespace(
            user=FakeMember(),
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        await button.callback(interaction)
        response = interaction.response.send_message
        assert response.await_count == 1
        assert response.await_args.kwargs["ephemeral"] is True
        assert isinstance(
            response.await_args.kwargs["view"],
            custom.CustomOrderCompanionCountView,
        )
        await asyncio.sleep(0)

    asyncio.run(run())


def test_component_failures_acknowledge_user_and_log_stage(monkeypatch, capsys):
    class Response:
        def __init__(self, done=False):
            self.done = done
            self.send_message = AsyncMock()
        def is_done(self):
            return self.done

    async def run(done):
        view = custom.CustomOrderQuickEntryView()
        response = Response(done=done)
        followup = SimpleNamespace(send=AsyncMock())
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=3333),
            channel_id=4444,
            response=response,
            followup=followup,
        )
        await view.on_error(interaction, RuntimeError("mock error"), view.children[0])
        if done:
            followup.send.assert_awaited_once()
        else:
            response.send_message.assert_awaited_once()
        return interaction

    asyncio.run(run(False))
    asyncio.run(run(True))
    assert "button failed" in capsys.readouterr().out
