import asyncio

from services import vip_review_runtime


def test_reconcile_only_syncs_records_with_active_vip_reset(monkeypatch):
    rows = [
        ("1001", {"vip_progress_reset_active": True}),
        ("1002", {"vip_progress_reset_active": False}),
        ("1003", {"vip_progress_reset_active": True}),
    ]
    calls = []

    monkeypatch.setattr(
        vip_review_runtime.rewards,
        "iter_customer_reward_items",
        lambda: rows,
    )

    async def fake_sync(bot, customer_id, data):
        calls.append((customer_id, data))

    monkeypatch.setattr(vip_review_runtime, "_sync_member_benefits", fake_sync)

    synced = asyncio.run(
        vip_review_runtime._reconcile_existing_reset_vip_roles(object())
    )

    assert synced == 2
    assert [customer_id for customer_id, _ in calls] == [1001, 1003]


def test_reconcile_waits_until_reward_data_is_loaded(monkeypatch):
    monkeypatch.setattr(
        vip_review_runtime.rewards,
        "iter_customer_reward_items",
        lambda: [],
    )

    result = asyncio.run(
        vip_review_runtime._reconcile_existing_reset_vip_roles(object())
    )

    assert result is None
