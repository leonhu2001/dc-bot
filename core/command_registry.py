from __future__ import annotations

import discord
from discord import app_commands


async def clear_stale_remote_global_commands(tree: app_commands.CommandTree) -> None:
    """Delete historical remote global commands without altering the local tree.

    This bot publishes Slash commands to one guild. Older deployments also wrote
    global English commands, so a guild-only sync cannot remove them. The cleanup
    runs at startup before the guild copy/sync and restores every local command
    object immediately after the empty global sync.
    """

    try:
        remote_global_commands = await tree.fetch_commands()
    except discord.HTTPException as exc:
        print(
            "[commands] unable to inspect stale global commands; "
            f"guild sync will continue: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return

    if not remote_global_commands:
        return

    local_global_commands = list(tree.get_commands())
    tree.clear_commands(guild=None)

    try:
        await tree.sync()
    except discord.HTTPException as exc:
        print(
            "[commands] unable to clear stale global commands; "
            f"guild sync will continue: {type(exc).__name__}: {exc}",
            flush=True,
        )
    else:
        print(
            "[commands] cleared stale global commands: "
            f"{len(remote_global_commands)}",
            flush=True,
        )
    finally:
        for command in local_global_commands:
            tree.add_command(command)
