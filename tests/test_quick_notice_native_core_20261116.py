from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from services import quick_order_v2 as quick
from services import quick_order_ticket_policy_20261028 as policy


ROOT = Path(__file__).resolve().parents[1]


class _FakeMember:
    def __init__(self, member_id: int):
        self.id = member_id


class _Response:
    def __init__(self):
        self.messages = []

    async def send_message(self, content=None, *, embed=None, view=None, ephemeral=False):
        self.messages.append({
            "content": content,
            "embed": embed,
            "view": view,
            "ephemeral": ephemeral,
        })


def _interaction(member_id: int = 42):
    return SimpleNamespace(user=_FakeMember(member_id), response=_Response())


def _button(view, label):
    return next(item for item in view.children if item.label == label)


def test_canonical_quick_entry_requires_read_notice_before_creating_ticket(monkeypatch):
    monkeypatch.setattr(policy.discord, "Member", _FakeMember)
    created = []

    async def create_ticket(interaction, *, category, item_group, source_channel_id):
        created.append((category, item_group, source_channel_id))
        return SimpleNamespace(id=999)

    monkeypatch.setattr(quick, "_create_ticket", create_ticket)

    async def exercise():
        start = _interaction()
        await quick._send_confirmation(
            start,
            category="farm",
            item_group="AW代撞",
            source_channel_id=112,
        )
        assert len(created) == 0
        assert len(start.response.messages) == 1
        message = start.response.messages[0]
        assert message["ephemeral"] is True
        assert message["embed"].title == "📖 下單須知確認"
        view = message["view"]
        assert isinstance(view, policy.QuickOrderNoticeConfirmView)

        await _button(view, "尚未閱讀").callback(_interaction())
        assert created == []

        await _button(view, "已閱讀下單須知，建立票口").callback(_interaction())
        assert created == [("farm", "AW代撞", 112)]
        assert view.opened_ticket is True

        again = _interaction()
        await _button(view, "已閱讀下單須知，建立票口").callback(again)
        assert len(created) == 1
        assert "已經建立過票口" in again.response.messages[-1]["content"]

    asyncio.run(exercise())


def test_failed_ticket_creation_allows_retry_without_duplicate_on_success(monkeypatch):
    attempts = []

    async def create_ticket(*args, **kwargs):
        attempts.append(1)
        return None if len(attempts) == 1 else SimpleNamespace(id=200)

    view = policy.QuickOrderNoticeConfirmView(
        customer_id=42, category="farm", item_group="AW代撞",
        source_channel_id=112, quick_module=SimpleNamespace(_create_ticket=create_ticket),
    )
    button = _button(view, "已閱讀下單須知，建立票口")

    async def exercise():
        await button.callback(_interaction())
        assert view.opened_ticket is False
        assert button.disabled is False
        await button.callback(_interaction())
        assert view.opened_ticket is True
        await button.callback(_interaction())
        assert len(attempts) == 2

    asyncio.run(exercise())


def test_quick_notice_gate_is_core_owned_not_rebound_at_startup():
    startup = (ROOT / "services/__init__.py").read_text(encoding="utf-8")
    core = (ROOT / "services/quick_order_v2.py").read_text(encoding="utf-8")
    policy_source = (
        ROOT / "services/quick_order_ticket_policy_20261028.py"
    ).read_text(encoding="utf-8")

    assert "install_quick_order_ticket_policy_20261028" not in startup
    assert "quick._send_confirmation =" not in policy_source
    assert "from services.quick_order_ticket_policy_20261028 import _send_notice_confirmation" in core
    assert "await _send_notice_confirmation(" in core
    assert "opened_ticket" in policy_source
