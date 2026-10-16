from types import SimpleNamespace

from services import staff_topup


class _FakeLoop:
    def __init__(self):
        self.tasks = []

    def create_task(self, value):
        self.tasks.append(value)
        return value


class _FakeGuild:
    def __init__(self, member):
        self.member = member

    def get_member(self, customer_id):
        if int(customer_id) == int(self.member.id):
            return self.member
        return None


class _FakeBot:
    def __init__(self, guild):
        self.guilds = [guild]
        self.loop = _FakeLoop()


def test_credit_staff_topup_credits_principal_bonus_and_preserves_points(monkeypatch):
    member = SimpleNamespace(id=42, display_name="老闆A")
    guild = _FakeGuild(member)
    bot = _FakeBot(guild)
    operator = SimpleNamespace(id=99, display_name="客服A")
    data = {
        "total_spent": 5900,
        "manual_purchase_keys": [],
    }
    wallet_calls = []
    completed = {}
    saved = []
    role_sync = object()

    monkeypatch.setattr(
        staff_topup,
        "create_topup_order",
        lambda **kwargs: {
            "id": 7,
            "topup_no": "TOPUP-TEST-0007",
            **kwargs,
        },
    )
    monkeypatch.setattr(
        staff_topup.rewards,
        "get_customer_reward_data",
        lambda customer_id: data,
    )
    monkeypatch.setattr(
        staff_topup,
        "repair_vip_progress_data",
        lambda target: target,
    )
    monkeypatch.setattr(
        staff_topup.rewards,
        "get_current_reward_points",
        lambda target: 40,
    )
    monkeypatch.setattr(
        staff_topup,
        "calculate_member_topup_preview",
        lambda target, amount: {
            "vip_total_before": 5900,
            "vip_total_after": 6100,
            "vip_level_before": "銀級魔丸",
            "vip_level_after": "金級魔丸",
            "rebate_percent": 2,
            "rebate_amount": 4,
            "credited_amount": 204,
        },
    )

    def fake_adjust_wallet_balance(**kwargs):
        wallet_calls.append(dict(kwargs))
        return {"id": len(wallet_calls), **kwargs}

    monkeypatch.setattr(
        staff_topup,
        "adjust_wallet_balance",
        fake_adjust_wallet_balance,
    )
    monkeypatch.setattr(
        staff_topup.rewards,
        "calculate_reward_points",
        lambda total_spent: 50,
    )
    monkeypatch.setattr(
        staff_topup.rewards,
        "sync_vip_level_to_cumulative_if_higher",
        lambda target: None,
    )
    monkeypatch.setattr(
        staff_topup.rewards,
        "get_effective_member_level",
        lambda target: {"name": "金級魔丸", "threshold": 6000},
    )
    monkeypatch.setattr(
        staff_topup.rewards,
        "ensure_reward_member_benefits",
        lambda target_guild, target_member, target_data: role_sync,
    )
    monkeypatch.setattr(
        staff_topup.rewards,
        "_SAVE_BOT_DATA",
        lambda: saved.append(True),
    )

    def fake_mark_topup_completed(topup_id, **kwargs):
        completed["topup_id"] = topup_id
        completed.update(kwargs)

    monkeypatch.setattr(
        staff_topup,
        "mark_topup_completed",
        fake_mark_topup_completed,
    )

    result = staff_topup.credit_staff_topup(
        bot,
        customer_id=42,
        amount=200,
        operator=operator,
        note="街口儲值",
    )

    assert result["id"] == 1
    assert wallet_calls == [
        {
            "customer_id": 42,
            "amount": 200,
            "tx_type": "topup",
            "operator_discord_id": 99,
            "operator_display_name": "客服A",
            "order_no": "TOPUP-TEST-0007",
            "note": "街口儲值",
        },
        {
            "customer_id": 42,
            "amount": 4,
            "tx_type": "topup_bonus",
            "operator_discord_id": 99,
            "operator_display_name": "客服A",
            "order_no": "TOPUP-TEST-0007",
            "note": "金級魔丸 儲值回饋 2%",
        },
    ]
    assert data["total_spent"] == 6100
    assert data["manual_purchase_keys"] == ["topup:TOPUP-TEST-0007"]
    assert data["points"] == 40
    assert data["point_adjustment"] == -10
    assert saved == [True]
    assert completed["topup_id"] == 7
    assert completed["wallet_transaction_id"] == 1
    assert completed["bonus_transaction_id"] == 2
    assert completed["preview"]["vip_level_after"] == "金級魔丸"
    assert completed["preview"]["vip_total_after"] == 6100
    assert bot.loop.tasks == [role_sync]


def test_credit_staff_topup_without_rebate_writes_only_principal(monkeypatch):
    bot = _FakeBot(_FakeGuild(SimpleNamespace(id=7, display_name="老闆B")))
    data = {"total_spent": 0, "manual_purchase_keys": []}
    wallet_calls = []
    completed = {}

    monkeypatch.setattr(
        staff_topup,
        "create_topup_order",
        lambda **kwargs: {"id": 1, "topup_no": "TOPUP-TEST-0001"},
    )
    monkeypatch.setattr(
        staff_topup.rewards,
        "get_customer_reward_data",
        lambda customer_id: data,
    )
    monkeypatch.setattr(staff_topup, "repair_vip_progress_data", lambda target: target)
    monkeypatch.setattr(staff_topup.rewards, "get_current_reward_points", lambda target: 3)
    monkeypatch.setattr(
        staff_topup,
        "calculate_member_topup_preview",
        lambda target, amount: {
            "vip_total_before": 0,
            "vip_total_after": 100,
            "vip_level_before": "一般會員",
            "vip_level_after": "一般會員",
            "rebate_percent": 0,
            "rebate_amount": 0,
            "credited_amount": 100,
        },
    )

    def fake_adjust_wallet_balance(**kwargs):
        wallet_calls.append(dict(kwargs))
        return {"id": 11, **kwargs}

    monkeypatch.setattr(staff_topup, "adjust_wallet_balance", fake_adjust_wallet_balance)
    monkeypatch.setattr(staff_topup.rewards, "calculate_reward_points", lambda total: 3)
    monkeypatch.setattr(
        staff_topup.rewards,
        "sync_vip_level_to_cumulative_if_higher",
        lambda target: None,
    )
    monkeypatch.setattr(
        staff_topup.rewards,
        "get_effective_member_level",
        lambda target: {"name": "一般會員", "threshold": 0},
    )
    monkeypatch.setattr(staff_topup.rewards, "_SAVE_BOT_DATA", None)
    monkeypatch.setattr(
        staff_topup.rewards,
        "ensure_reward_member_benefits",
        lambda *args: object(),
    )
    monkeypatch.setattr(
        staff_topup,
        "mark_topup_completed",
        lambda topup_id, **kwargs: completed.update(topup_id=topup_id, **kwargs),
    )

    staff_topup.credit_staff_topup(
        bot,
        customer_id=7,
        amount=100,
        operator=SimpleNamespace(id=8, name="客服B"),
    )

    assert len(wallet_calls) == 1
    assert wallet_calls[0]["tx_type"] == "topup"
    assert wallet_calls[0]["note"] == "客服儲值"
    assert completed["bonus_transaction_id"] is None
    assert data["points"] == 3
