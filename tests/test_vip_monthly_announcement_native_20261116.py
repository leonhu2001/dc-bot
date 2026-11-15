from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from services import vip_review_runtime as runtime
from services import vip_monthly_announcement_policy as policy


ROOT = Path(__file__).resolve().parents[1]


class FakeChannel:
    def __init__(self):
        self.sent = []
        self.id = 1482083972031840257

    async def send(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(id=1)


def test_current_month_announcement_is_native_and_uses_live_entitlements(monkeypatch):
    channel = FakeChannel()
    requested = []
    marked = []
    monkeypatch.setattr(policy, "_NOVEMBER_RECONCILED", True)
    monkeypatch.setattr(runtime, "sync_current_month_vip_benefits", lambda: {
        "issued_count": 1,
        "month_key": "2026-12",
        "eligible_customer_count": 2,
        "announcement_needed": True,
    })

    async def get_channel(bot):
        requested.append(bot)
        return channel

    monkeypatch.setattr(runtime, "_get_monthly_announcement_channel", get_channel)
    monkeypatch.setattr(runtime, "mark_month_announcement_sent", marked.append)
    bot = SimpleNamespace(user=SimpleNamespace(id=888))

    asyncio.run(runtime._sync_monthly_benefits_and_announce(bot))
    assert requested == [bot]
    assert len(channel.sent) == 1
    payload = channel.sent[0]
    assert payload["embed"].title == "👑 2026 年 12 月 VIP 每月福利已刷新"
    assert "200T" in str(payload["embed"].to_dict())
    assert "500T" in str(payload["embed"].to_dict())
    assert payload["allowed_mentions"].everyone is False
    assert payload["allowed_mentions"].users is False
    assert payload["allowed_mentions"].roles is False
    assert marked == ["2026-12"]


def test_no_monthly_announcement_when_month_is_already_recorded(monkeypatch):
    channel = FakeChannel()
    monkeypatch.setattr(policy, "_NOVEMBER_RECONCILED", True)
    monkeypatch.setattr(runtime, "sync_current_month_vip_benefits", lambda: {
        "issued_count": 0,
        "month_key": "2026-12",
        "eligible_customer_count": 2,
        "announcement_needed": False,
    })

    async def get_channel(bot):
        return channel

    monkeypatch.setattr(runtime, "_get_monthly_announcement_channel", get_channel)
    monkeypatch.setattr(runtime, "mark_month_announcement_sent", lambda key: (_ for _ in ()).throw(AssertionError("unexpected announcement mark")))
    asyncio.run(runtime._sync_monthly_benefits_and_announce(SimpleNamespace()))
    assert channel.sent == []


def test_failed_november_reconciliation_does_not_block_future_monthly_post(monkeypatch):
    channel = FakeChannel()
    errors = []
    monkeypatch.setattr(policy, "_NOVEMBER_RECONCILED", False)
    monkeypatch.setattr(runtime, "sync_current_month_vip_benefits", lambda: {
        "issued_count": 0,
        "month_key": "2026-12",
        "eligible_customer_count": 2,
        "announcement_needed": True,
    })

    async def get_channel(bot):
        return channel

    async def fail_reconciliation(bot, found_channel):
        errors.append((bot, found_channel))
        raise RuntimeError("old message not found")

    marked = []
    monkeypatch.setattr(runtime, "_get_monthly_announcement_channel", get_channel)
    monkeypatch.setattr(policy, "_reconcile_november_2026_message", fail_reconciliation)
    monkeypatch.setattr(runtime, "mark_month_announcement_sent", marked.append)
    bot = SimpleNamespace(user=SimpleNamespace(id=1))

    asyncio.run(runtime._sync_monthly_benefits_and_announce(bot))
    assert len(errors) == 1
    assert len(channel.sent) == 1
    assert marked == ["2026-12"]


def test_vip_monthly_announcement_has_no_runtime_function_rebinding():
    startup = (ROOT / "services/__init__.py").read_text(encoding="utf-8")
    policy_source = (ROOT / "services/vip_monthly_announcement_policy.py").read_text(encoding="utf-8")
    runtime_source = (ROOT / "services/vip_review_runtime.py").read_text(encoding="utf-8")
    assert "install_vip_monthly_announcement_policy" not in startup
    assert "runtime._sync_monthly_benefits_and_announce =" not in policy_source
    assert "announcement._reconcile_november_2026_message" in runtime_source
    assert "announcement.build_vip_monthly_announcement_embed(month)" in runtime_source
