from types import SimpleNamespace

from services import legacy_topup_bridge


class _FakeTree:
    def __init__(self, *, global_command=None, guild_command=None):
        self.global_command = global_command
        self.guild_command = guild_command

    def get_command(self, name, *, guild=None):
        if name != "wallet_add":
            return None
        if guild is None:
            return self.global_command
        return self.guild_command


class _FakeBot:
    def __init__(self, tree, *, guilds=None):
        self.tree = tree
        self.guilds = list(guilds or [])


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


def test_bridge_targets_registered_guild_wallet_add_globals_only():
    calls = []

    def original_adjust(**kwargs):
        calls.append(dict(kwargs))
        return {"id": 123, "amount": kwargs.get("amount")}

    target_globals = _callback_namespace(original_adjust)
    command = SimpleNamespace(callback=target_globals["wallet_add"])
    guild = SimpleNamespace()
    bot = _FakeBot(
        _FakeTree(guild_command=command),
        guilds=[guild],
    )

    legacy_topup_bridge.install_legacy_wallet_add_bridge(bot)

    bridged = target_globals["adjust_customer_wallet_balance"]
    assert bridged is not original_adjust
    assert target_globals[legacy_topup_bridge._BRIDGE_INSTALLED_GLOBAL] is True

    result = bridged(
        customer_id=42,
        amount=50,
        tx_type="adjustment",
        note="test",
    )

    assert result == {"id": 123, "amount": 50}
    assert calls == [
        {
            "customer_id": 42,
            "amount": 50,
            "tx_type": "adjustment",
            "note": "test",
        }
    ]


def test_bridge_supports_global_wallet_add_after_future_command_migration():
    def original_adjust(**kwargs):
        return kwargs

    target_globals = _callback_namespace(original_adjust)
    command = SimpleNamespace(callback=target_globals["wallet_add"])
    bot = _FakeBot(_FakeTree(global_command=command))

    legacy_topup_bridge.install_legacy_wallet_add_bridge(bot)

    assert target_globals["adjust_customer_wallet_balance"] is not original_adjust
    assert target_globals[legacy_topup_bridge._BRIDGE_INSTALLED_GLOBAL] is True


def test_bridge_fails_closed_without_registered_wallet_add_command():
    decoy_calls = []

    def decoy_adjust(**kwargs):
        decoy_calls.append(dict(kwargs))
        return kwargs

    decoy_globals = _callback_namespace(decoy_adjust)
    bot = _FakeBot(_FakeTree(), guilds=[SimpleNamespace()])

    legacy_topup_bridge.install_legacy_wallet_add_bridge(bot)

    assert decoy_globals["adjust_customer_wallet_balance"] is decoy_adjust
    assert legacy_topup_bridge._BRIDGE_INSTALLED_GLOBAL not in decoy_globals
    assert decoy_calls == []


def test_bridge_install_is_idempotent_for_same_wallet_add_namespace():
    def original_adjust(**kwargs):
        return kwargs

    target_globals = _callback_namespace(original_adjust)
    command = SimpleNamespace(callback=target_globals["wallet_add"])
    bot = _FakeBot(_FakeTree(global_command=command))

    legacy_topup_bridge.install_legacy_wallet_add_bridge(bot)
    first_wrapper = target_globals["adjust_customer_wallet_balance"]

    legacy_topup_bridge.install_legacy_wallet_add_bridge(bot)
    second_wrapper = target_globals["adjust_customer_wallet_balance"]

    assert second_wrapper is first_wrapper


def test_bridge_no_longer_imports_sys_for_module_scanning():
    assert not hasattr(legacy_topup_bridge, "sys")
