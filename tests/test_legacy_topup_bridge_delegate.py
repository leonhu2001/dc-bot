from types import SimpleNamespace

from services import legacy_topup_bridge


class _FakeTree:
    def __init__(self, command):
        self.command = command

    def get_command(self, name, *, guild=None):
        if name != "wallet_add":
            return None
        return self.command


class _FakeBot:
    def __init__(self, command):
        self.tree = _FakeTree(command)
        self.guilds = []


def _callback_namespace(original_adjust):
    namespace = {
        "adjust_customer_wallet_balance": original_adjust,
    }
    exec(
        "def wallet_add():\n"
        "    return adjust_customer_wallet_balance\n",
        namespace,
    )
    return namespace


def test_topup_calls_staff_topup_service_instead_of_original_adjust(monkeypatch):
    original_calls = []
    service_calls = []

    def original_adjust(**kwargs):
        original_calls.append(dict(kwargs))
        return {"id": 1}

    target_globals = _callback_namespace(original_adjust)
    command = SimpleNamespace(callback=target_globals["wallet_add"])
    bot = _FakeBot(command)

    def fake_credit_staff_topup(target_bot, **kwargs):
        service_calls.append((target_bot, dict(kwargs)))
        return {"id": 88, "type": "topup"}

    monkeypatch.setattr(
        legacy_topup_bridge,
        "credit_staff_topup",
        fake_credit_staff_topup,
    )

    legacy_topup_bridge.install_legacy_wallet_add_bridge(bot)
    bridged = target_globals["adjust_customer_wallet_balance"]

    result = bridged(
        customer_id=42,
        amount=500,
        tx_type="topup",
        operator=SimpleNamespace(id=9),
        note="客服確認",
    )

    assert result == {"id": 88, "type": "topup"}
    assert original_calls == []
    assert len(service_calls) == 1
    assert service_calls[0][0] is bot
    assert service_calls[0][1]["customer_id"] == 42
    assert service_calls[0][1]["amount"] == 500
    assert service_calls[0][1]["note"] == "客服確認"


def test_non_topup_still_delegates_to_original_adjust(monkeypatch):
    original_calls = []

    def original_adjust(**kwargs):
        original_calls.append(dict(kwargs))
        return {"id": 2, "type": kwargs["tx_type"]}

    target_globals = _callback_namespace(original_adjust)
    command = SimpleNamespace(callback=target_globals["wallet_add"])
    bot = _FakeBot(command)

    monkeypatch.setattr(
        legacy_topup_bridge,
        "credit_staff_topup",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("staff topup service should not be called")
        ),
    )

    legacy_topup_bridge.install_legacy_wallet_add_bridge(bot)
    bridged = target_globals["adjust_customer_wallet_balance"]

    result = bridged(
        customer_id=42,
        amount=-50,
        tx_type="adjustment",
        operator=SimpleNamespace(id=9),
        note="修正",
    )

    assert result == {"id": 2, "type": "adjustment"}
    assert original_calls == [
        {
            "customer_id": 42,
            "amount": -50,
            "tx_type": "adjustment",
            "operator": SimpleNamespace(id=9),
            "note": "修正",
        }
    ]
