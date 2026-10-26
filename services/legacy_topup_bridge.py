from __future__ import annotations

from typing import Any, Callable

import discord

from services.member_portal_runtime_20261026 import install_member_portal_20261026
from services.staff_topup import credit_staff_topup


_BRIDGE_INSTALLED_GLOBAL = "_legacy_wallet_add_bridge_installed"


def _wallet_add_callback(bot: discord.Client) -> Callable[..., Any] | None:
    """Return the callback for this Bot's registered /wallet_add command.

    The compatibility bridge exists only for the legacy command that still lives
    in bot.py. Resolve that exact command instead of scanning sys.modules and
    guessing a module by unrelated global names.
    """

    tree = getattr(bot, "tree", None)
    get_command = getattr(tree, "get_command", None)
    if not callable(get_command):
        return None

    # Keep global lookup for tests/future command migration. The production
    # command is currently guild-scoped, so also inspect the Bot's known guilds.
    try:
        command = get_command("wallet_add")
    except (TypeError, ValueError):
        command = None

    callback = getattr(command, "callback", None)
    if callable(callback):
        return callback

    for guild in list(getattr(bot, "guilds", []) or []):
        try:
            command = get_command("wallet_add", guild=guild)
        except (TypeError, ValueError):
            continue

        callback = getattr(command, "callback", None)
        if callable(callback):
            return callback

    return None


def _wallet_add_globals(bot: discord.Client) -> dict[str, Any] | None:
    callback = _wallet_add_callback(bot)
    namespace = getattr(callback, "__globals__", None)
    return namespace if isinstance(namespace, dict) else None


def install_legacy_wallet_add_bridge(bot: discord.Client) -> None:
    # The top-up runtime is guaranteed to start on every production boot, so it
    # is also the safest place to keep the customer member portal persistent and
    # synchronized without requiring a one-off /setup command after deployment.
    install_member_portal_20261026(bot)

    target_globals = _wallet_add_globals(bot)
    if target_globals is None or bool(target_globals.get(_BRIDGE_INSTALLED_GLOBAL)):
        return

    original_adjust = target_globals.get("adjust_customer_wallet_balance")
    if not callable(original_adjust):
        return

    def bridged_adjust_customer_wallet_balance(**kwargs):
        tx_type = str(kwargs.get("tx_type") or "adjustment").strip()
        if tx_type != "topup":
            return original_adjust(**kwargs)

        return credit_staff_topup(
            bot,
            customer_id=int(str(kwargs.get("customer_id"))),
            amount=int(kwargs.get("amount") or 0),
            operator=kwargs.get("operator"),
            note=str(kwargs.get("note") or "客服儲值").strip(),
        )

    target_globals["adjust_customer_wallet_balance"] = bridged_adjust_customer_wallet_balance
    target_globals[_BRIDGE_INSTALLED_GLOBAL] = True
    print("[topup] legacy /wallet_add bridge installed", flush=True)
